#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs_flash.h"

#include "pair_protocol.hpp"

namespace heart {

// Zero-configuration first-board transport: both hearts use the same fixed
// Wi-Fi channel and accept only the tiny RAVA packet format/group identifier.
// Broadcast makes the interaction usable before the boards' MAC addresses are
// known. Provisioned encrypted unicast is the intended post-bring-up upgrade.
class PairLink {
 public:
  bool initialize() {
    instance_ = this;
    if (!accept_already_initialized(nvs_flash_init(), "initialize NVS") ||
        !accept_already_initialized(esp_netif_init(), "initialize netif") ||
        !accept_already_initialized(
            esp_event_loop_create_default(), "create event loop")) {
      return false;
    }

    wifi_init_config_t wifi_config = WIFI_INIT_CONFIG_DEFAULT();
    if (!check(esp_wifi_init(&wifi_config), "initialize Wi-Fi") ||
        !check(esp_wifi_set_storage(WIFI_STORAGE_RAM), "set Wi-Fi storage") ||
        !check(esp_wifi_set_mode(WIFI_MODE_STA), "set station mode") ||
        !check(esp_wifi_start(), "start Wi-Fi") ||
        !check(
            esp_wifi_get_mac(WIFI_IF_STA, local_address_.data()),
            "read station MAC") ||
        !check(
            esp_wifi_set_channel(kChannel, WIFI_SECOND_CHAN_NONE),
            "set ESP-NOW channel") ||
        !check(esp_wifi_set_ps(WIFI_PS_NONE), "disable Wi-Fi power save") ||
        !check(esp_now_init(), "initialize ESP-NOW") ||
        !check(esp_now_register_recv_cb(receive_callback), "register receive callback")) {
      return false;
    }

    esp_now_peer_info_t peer{};
    std::memcpy(
        peer.peer_addr, kBroadcastAddress.data(), kBroadcastAddress.size());
    peer.channel = kChannel;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    if (!check(esp_now_add_peer(&peer), "add broadcast peer")) {
      return false;
    }

    next_sequence_ = static_cast<std::uint16_t>(esp_random());
    next_sync_send_seconds_ =
        0.10F + static_cast<float>(esp_random() % 180U) / 1000.0F;
    ready_ = true;
    ESP_LOGI(
        kTag,
        "ESP-NOW pair link ready on channel %u, MAC %02x:%02x:%02x:%02x:%02x:%02x",
        kChannel,
        local_address_[0],
        local_address_[1],
        local_address_[2],
        local_address_[3],
        local_address_[4],
        local_address_[5]);
    return true;
  }

  void queue_love(float now_seconds) {
    if (!ready_) {
      return;
    }
    pending_message_ = {};
    pending_message_.type = pair::MessageType::kLove;
    pending_message_.sequence = ++next_sequence_;
    pending_repeats_ = 3;
    next_send_seconds_ = now_seconds;
  }

  void update(
      float now_seconds,
      float heartbeat_phase_seconds,
      float heartbeat_period_seconds) {
    process_presence(now_seconds);
    if (!ready_) {
      return;
    }

    if (pending_repeats_ > 0 && now_seconds >= next_send_seconds_) {
      send(pending_message_);
      --pending_repeats_;
      next_send_seconds_ = now_seconds + 0.14F;
    }

    if (now_seconds >= next_sync_send_seconds_) {
      pair::Message sync{};
      sync.sequence = ++next_sequence_;
      sync.type = pair::MessageType::kHeartbeatSync;
      sync.beat_period_milliseconds = seconds_to_milliseconds(
          heartbeat_period_seconds, std::numeric_limits<std::uint16_t>::max());
      const float wrapped_phase = std::fmod(
          std::max(0.0F, heartbeat_phase_seconds), heartbeat_period_seconds);
      sync.beat_phase_milliseconds = seconds_to_milliseconds(
          wrapped_phase, sync.beat_period_milliseconds - 1U);
      send(sync);
      next_sync_send_seconds_ = now_seconds + kSyncIntervalSeconds;
    }
  }

  [[nodiscard]] bool consume_love() {
    return received_love_count_.exchange(0U, std::memory_order_acq_rel) > 0U;
  }

  // Returns a latency-adjusted phase only when a nearby lower-MAC heart is
  // available. With two identical boards this deterministically makes one the
  // clock leader and prevents them from repeatedly correcting each other.
  [[nodiscard]] bool consume_heartbeat_sync(
      float now_seconds,
      float expected_period_seconds,
      float& phase_seconds) {
    const std::uint32_t generation =
        received_sync_generation_.load(std::memory_order_acquire);
    if (!nearby_ || generation == consumed_sync_generation_) {
      return false;
    }
    consumed_sync_generation_ = generation;

    const std::uint16_t period_ms =
        received_sync_period_milliseconds_.load(std::memory_order_relaxed);
    const std::uint16_t phase_ms =
        received_sync_phase_milliseconds_.load(std::memory_order_relaxed);
    if (period_ms == 0U ||
        std::abs(static_cast<float>(period_ms) / 1000.0F -
                 expected_period_seconds) > 0.06F) {
      return false;
    }

    const std::uint32_t received_ms =
        received_sync_time_milliseconds_.load(std::memory_order_relaxed);
    const std::uint32_t now_ms = static_cast<std::uint32_t>(
        std::max(0.0F, now_seconds) * 1000.0F);
    const std::uint32_t age_ms = now_ms - received_ms;
    if (age_ms > 1000U) {
      return false;
    }
    phase_seconds = static_cast<float>((phase_ms + age_ms) % period_ms) / 1000.0F;
    if (!sync_reported_) {
      ESP_LOGI(kTag, "Following nearby lower-MAC heartbeat clock");
      sync_reported_ = true;
    }
    return true;
  }

  [[nodiscard]] bool nearby() const { return nearby_; }

  [[nodiscard]] float smoothed_rssi_dbm() const { return smoothed_rssi_dbm_; }

  [[nodiscard]] bool ready() const { return ready_; }

 private:
  static constexpr char kTag[] = "pair_link";
  static constexpr std::uint8_t kChannel = 6;
  static constexpr std::array<std::uint8_t, 6> kBroadcastAddress = {
      0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
  static constexpr float kSyncIntervalSeconds = 0.45F;
  static constexpr float kPeerTimeoutSeconds = 2.5F;
  static constexpr float kNearbyEnterRssiDbm = -72.0F;
  static constexpr float kNearbyExitRssiDbm = -80.0F;

  static std::uint16_t seconds_to_milliseconds(
      float seconds, std::uint16_t maximum) {
    return static_cast<std::uint16_t>(std::clamp(
        std::lround(std::max(0.0F, seconds) * 1000.0F),
        0L,
        static_cast<long>(maximum)));
  }

  static bool check(esp_err_t error, const char* operation) {
    if (error == ESP_OK) {
      return true;
    }
    ESP_LOGE(kTag, "%s failed: %s", operation, esp_err_to_name(error));
    return false;
  }

  static bool accept_already_initialized(esp_err_t error, const char* operation) {
    if (error == ESP_OK || error == ESP_ERR_INVALID_STATE) {
      return true;
    }
    ESP_LOGE(kTag, "%s failed: %s", operation, esp_err_to_name(error));
    return false;
  }

  void send(const pair::Message& message) const {
    const esp_err_t error = esp_now_send(
        kBroadcastAddress.data(),
        reinterpret_cast<const std::uint8_t*>(&message),
        sizeof(message));
    if (error != ESP_OK) {
      ESP_LOGW(kTag, "ESP-NOW send failed: %s", esp_err_to_name(error));
    }
  }

  void process_presence(float now_seconds) {
    const std::uint32_t generation =
        received_packet_generation_.load(std::memory_order_acquire);
    if (generation != processed_packet_generation_) {
      processed_packet_generation_ = generation;
      last_peer_packet_seconds_ = now_seconds;
      const float latest_rssi = static_cast<float>(
          latest_rssi_dbm_.load(std::memory_order_relaxed));
      if (!have_rssi_) {
        smoothed_rssi_dbm_ = latest_rssi;
        have_rssi_ = true;
      } else {
        smoothed_rssi_dbm_ += 0.24F * (latest_rssi - smoothed_rssi_dbm_);
      }
    }

    const bool was_nearby = nearby_;
    if (nearby_ && now_seconds - last_peer_packet_seconds_ > kPeerTimeoutSeconds) {
      nearby_ = false;
    } else if (have_rssi_) {
      if (!nearby_ && smoothed_rssi_dbm_ >= kNearbyEnterRssiDbm) {
        nearby_ = true;
      } else if (nearby_ && smoothed_rssi_dbm_ < kNearbyExitRssiDbm) {
        nearby_ = false;
      }
    }
    if (nearby_ != was_nearby) {
      ESP_LOGI(
          kTag,
          "Nearby heart %s (RSSI %.1f dBm)",
          nearby_ ? "found" : "lost",
          smoothed_rssi_dbm_);
      if (!nearby_) {
        sync_reported_ = false;
      }
    }
  }

  static void receive_callback(
      const esp_now_recv_info_t* information,
      const std::uint8_t* data,
      int length) {
    if (instance_ == nullptr || information == nullptr ||
        information->src_addr == nullptr || length < 0) {
      return;
    }
    pair::Message message{};
    if (!pair::decode_message(data, static_cast<std::size_t>(length), message)) {
      return;
    }
    if (information->rx_ctrl != nullptr) {
      instance_->latest_rssi_dbm_.store(
          information->rx_ctrl->rssi, std::memory_order_relaxed);
    }
    instance_->received_packet_generation_.fetch_add(
        1U, std::memory_order_release);

    if (message.type == pair::MessageType::kLove) {
      const std::uint16_t previous =
          instance_->last_received_love_sequence_.exchange(
              message.sequence, std::memory_order_acq_rel);
      if (previous != message.sequence) {
        instance_->received_love_count_.fetch_add(
            1U, std::memory_order_release);
      }
      return;
    }

    if (message.type == pair::MessageType::kHeartbeatSync &&
        std::memcmp(
            information->src_addr,
            instance_->local_address_.data(),
            instance_->local_address_.size()) < 0) {
      instance_->received_sync_phase_milliseconds_.store(
          message.beat_phase_milliseconds, std::memory_order_relaxed);
      instance_->received_sync_period_milliseconds_.store(
          message.beat_period_milliseconds, std::memory_order_relaxed);
      instance_->received_sync_time_milliseconds_.store(
          static_cast<std::uint32_t>(esp_timer_get_time() / 1000),
          std::memory_order_relaxed);
      instance_->received_sync_generation_.fetch_add(
          1U, std::memory_order_release);
    }
  }

  inline static PairLink* instance_ = nullptr;
  std::array<std::uint8_t, 6> local_address_{};
  std::atomic<std::uint32_t> received_love_count_{0};
  std::atomic<std::uint16_t> last_received_love_sequence_{
      std::numeric_limits<std::uint16_t>::max()};
  std::atomic<std::int16_t> latest_rssi_dbm_{-127};
  std::atomic<std::uint32_t> received_packet_generation_{0};
  std::atomic<std::uint16_t> received_sync_phase_milliseconds_{0};
  std::atomic<std::uint16_t> received_sync_period_milliseconds_{0};
  std::atomic<std::uint32_t> received_sync_time_milliseconds_{0};
  std::atomic<std::uint32_t> received_sync_generation_{0};
  pair::Message pending_message_{};
  std::uint16_t next_sequence_ = 0;
  std::uint8_t pending_repeats_ = 0;
  std::uint32_t processed_packet_generation_ = 0;
  std::uint32_t consumed_sync_generation_ = 0;
  float next_send_seconds_ = 0.0F;
  float next_sync_send_seconds_ = 0.0F;
  float last_peer_packet_seconds_ = -10.0F;
  float smoothed_rssi_dbm_ = -127.0F;
  bool have_rssi_ = false;
  bool nearby_ = false;
  bool sync_reported_ = false;
  bool ready_ = false;
};

}  // namespace heart
