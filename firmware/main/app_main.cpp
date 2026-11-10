#include <array>
#include <cstddef>
#include <cstdint>

#include "driver/gpio.h"
#include "esp_err.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"

#include "board_config.hpp"
#include "button.hpp"
#include "color_pipeline.hpp"
#include "compass.hpp"
#include "gesture_detector.hpp"
#include "heartbeat_effect.hpp"
#include "liquid_effect.hpp"
#include "love_effect.hpp"
#include "pair_link.hpp"
#include "rainbow_effect.hpp"
#include "sensor_service.hpp"
#include "target_arrow_effect.hpp"
#include "target_provider.hpp"

namespace {

constexpr char kTag[] = "rava_heart";
constexpr std::uint32_t kLedRmtResolutionHz = 10U * 1000U * 1000U;
constexpr float kLedChainWireTimeSeconds =
    static_cast<float>(
        heart::generated::kPixelsPerChain * heart::board::kLedBitsPerPixel) /
        static_cast<float>(heart::board::kLedDataRateBitsPerSecond) +
    static_cast<float>(heart::board::kLedResetBudgetMicroseconds) / 1'000'000.0F;
static_assert(
    kLedChainWireTimeSeconds * heart::generated::kChainCount <
    1.0F / heart::board::kFrameRateHz,
    "LED wire time does not fit the configured frame rate");

enum class EffectMode {
  kHeartbeat,
  kLiquid,
  kRainbow,
  kCompassArrow,
};

const char* mode_name(EffectMode mode) {
  switch (mode) {
    case EffectMode::kHeartbeat:
      return "heartbeat";
    case EffectMode::kLiquid:
      return "gravity red";
    case EffectMode::kRainbow:
      return "flowing rainbow";
    case EffectMode::kCompassArrow:
      return "find heart";
  }
  return "unknown";
}

EffectMode next_mode(EffectMode mode) {
  switch (mode) {
    case EffectMode::kHeartbeat:
      return EffectMode::kLiquid;
    case EffectMode::kLiquid:
      return EffectMode::kRainbow;
    case EffectMode::kRainbow:
      return EffectMode::kCompassArrow;
    case EffectMode::kCompassArrow:
      return EffectMode::kHeartbeat;
  }
  return EffectMode::kHeartbeat;
}

led_strip_handle_t configure_strip(int gpio) {
  led_strip_config_t strip_config{};
  strip_config.strip_gpio_num = gpio;
  strip_config.max_leds = heart::generated::kPixelsPerChain;
  strip_config.led_model = LED_MODEL_WS2812;
  strip_config.color_component_format = LED_STRIP_COLOR_COMPONENT_FMT_GRB;
  strip_config.flags.invert_out = false;

  led_strip_rmt_config_t rmt_config{};
  rmt_config.clk_src = RMT_CLK_SRC_DEFAULT;
  rmt_config.resolution_hz = kLedRmtResolutionHz;
  rmt_config.mem_block_symbols = 0;
  rmt_config.flags.with_dma = false;  // ESP32-C3 RMT does not provide LED-strip DMA.

  led_strip_handle_t strip = nullptr;
  ESP_ERROR_CHECK(led_strip_new_rmt_device(&strip_config, &rmt_config, &strip));
  ESP_ERROR_CHECK(led_strip_clear(strip));
  return strip;
}

void configure_buttons() {
  gpio_config_t config{};
  config.pin_bit_mask =
      (1ULL << heart::board::kModeButtonGpio) |
      (1ULL << heart::board::kBrightnessButtonGpio);
  config.mode = GPIO_MODE_INPUT;
  config.pull_up_en = GPIO_PULLUP_ENABLE;
  config.pull_down_en = GPIO_PULLDOWN_DISABLE;
  config.intr_type = GPIO_INTR_DISABLE;
  ESP_ERROR_CHECK(gpio_config(&config));
}

void write_frame(
    const heart::Frame& frame,
    const std::array<led_strip_handle_t, heart::generated::kChainCount>& strips) {
  for (std::size_t chain = 0; chain < strips.size(); ++chain) {
    const std::size_t offset = chain * heart::generated::kPixelsPerChain;
    for (std::size_t pixel = 0;
         pixel < heart::generated::kPixelsPerChain;
         ++pixel) {
      const auto& color = frame[offset + pixel];
      ESP_ERROR_CHECK(
          led_strip_set_pixel(strips[chain], pixel, color.r, color.g, color.b));
    }
    ESP_ERROR_CHECK(led_strip_refresh(strips[chain]));
  }
}

float seconds_since_boot() {
  return static_cast<float>(esp_timer_get_time()) / 1'000'000.0F;
}

}  // namespace

extern "C" void app_main() {
  ESP_LOGI(
      kTag,
      "Rava heart V0: %zu pixels; chains begin D%u on GPIO%d and D%u on GPIO%d",
      heart::generated::kPixelCount,
      static_cast<unsigned>(heart::generated::kChain0FirstReference),
      heart::board::kLedChain0Gpio,
      static_cast<unsigned>(heart::generated::kChain1FirstReference),
      heart::board::kLedChain1Gpio);

  configure_buttons();
  heart::SensorService sensors;
  const bool imu_ready = sensors.initialize();
  ESP_LOGI(
      kTag,
      "IMU: %s; magnetometer: %s",
      imu_ready ? "ready" : "unavailable (using fixed down)",
      sensors.magnetometer_ready() ? "ready" : "unavailable");

  static_assert(heart::generated::kChainCount == 2);
  const std::array<led_strip_handle_t, heart::generated::kChainCount> strips = {
      configure_strip(heart::board::kLedChain0Gpio),
      configure_strip(heart::board::kLedChain1Gpio),
  };

  heart::HeartbeatEffect heartbeat;
  heart::LoveEffect love;
  heart::RainbowEffect rainbow;
  heart::TargetArrowEffect target_arrow;
  heart::CompassEstimator compass;
  heart::TargetProvider target_provider;
  // Bench-safe default: until phone/peer coordinates arrive, Find Heart points
  // to magnetic north. set_positions() or set_bearing() replaces this directly.
  target_provider.set_bearing(0.0F);
  // Keep the graph, mass field, and framebuffer out of the main task's small
  // stack. These objects live for the entire firmware lifetime anyway.
  static heart::LiquidEffect liquid;
  heart::PairLink pair_link;
  const bool pair_link_ready = pair_link.initialize();
  ESP_LOGI(kTag, "Pair link: %s", pair_link_ready ? "ready" : "unavailable");
  heart::ShakeDetector shake_detector;
  heart::ButtonGesture user_button;
  heart::DebouncedButton alternate_button;
  static heart::Frame frame{};
  EffectMode mode = EffectMode::kHeartbeat;
  constexpr std::array<float, 3> kBrightnessLevels = {0.28F, 0.55F, 0.90F};
  std::size_t brightness_index = 1;
  float previous_seconds = seconds_since_boot();

  TickType_t last_wake = xTaskGetTickCount();
  constexpr auto kFrameMilliseconds = static_cast<std::uint32_t>(
      1000.0F / heart::board::kFrameRateHz + 0.5F);
  constexpr TickType_t kFrameTicks = pdMS_TO_TICKS(kFrameMilliseconds);
  while (true) {
    const bool raw_user_pressed =
        gpio_get_level(static_cast<gpio_num_t>(heart::board::kModeButtonGpio)) == 0;
    const bool raw_alt_pressed =
        gpio_get_level(
            static_cast<gpio_num_t>(heart::board::kBrightnessButtonGpio)) == 0;

    const float now_seconds = seconds_since_boot();
    const float delta_seconds = now_seconds - previous_seconds;
    previous_seconds = now_seconds;
    const heart::ButtonGestureEvents user_events =
        user_button.update(now_seconds, raw_user_pressed);
    const bool alternate_pressed =
        alternate_button.pressed(now_seconds, raw_alt_pressed);

    if (user_events.short_press) {
      mode = next_mode(mode);
      if (mode == EffectMode::kLiquid) {
        liquid.reset();
      }
      ESP_LOGI(kTag, "Mode: %s", mode_name(mode));
    }
    if (user_events.long_press) {
      love.trigger(now_seconds);
      pair_link.queue_love(now_seconds);
      ESP_LOGI(kTag, "I heart you sent");
    }
    pair_link.update(
        now_seconds,
        heartbeat.phase_seconds(now_seconds),
        heartbeat.period_seconds());
    float paired_heartbeat_phase = 0.0F;
    if (pair_link.consume_heartbeat_sync(
            now_seconds,
            heartbeat.period_seconds(),
            paired_heartbeat_phase)) {
      heartbeat.synchronize(now_seconds, paired_heartbeat_phase);
    }
    if (pair_link.consume_love()) {
      love.trigger(now_seconds);
      ESP_LOGI(kTag, "I heart you received");
    }
    if (alternate_pressed) {
      brightness_index = (brightness_index + 1) % kBrightnessLevels.size();
      ESP_LOGI(kTag, "Brightness %.0f%%", kBrightnessLevels[brightness_index] * 100.0F);
    }

    heart::AccelerationSample acceleration{};
    const bool have_sample = imu_ready && sensors.read_acceleration(acceleration);
    heart::MotionState motion = heart::motion_from_acceleration(acceleration);
    if (!have_sample) {
      // Keeps the visual testable if a sensor is absent. Real motion replaces
      // this immediately whenever the LSM6DSOX is available.
      motion.down_y = -1.0F;
      motion.in_plane_gravity_g = 1.0F;
    }
    heart::MagneticSample magnetic{};
    if (have_sample && sensors.read_magnetic_field(magnetic)) {
      const heart::CompassReading reading = compass.update(acceleration, magnetic);
      motion.heading_degrees = reading.heading_degrees;
      motion.compass_valid = reading.valid;
    }
    heart::GestureEvents gesture{};
    if (have_sample) {
      const heart::Vector3 board_acceleration =
          heart::acceleration_in_board_axes(acceleration);
      gesture = shake_detector.update(
          now_seconds,
          board_acceleration.x,
          board_acceleration.y,
          board_acceleration.z);
    }

    if (love.active(now_seconds)) {
      love.render(now_seconds, frame);
    } else if (mode == EffectMode::kHeartbeat) {
      if (gesture.shake) {
        heartbeat.trigger_extra_beat(now_seconds);
      }
      heart::RenderContext context{};
      context.now_seconds = now_seconds;
      heartbeat.render(context, frame);
    } else if (mode == EffectMode::kLiquid) {
      if (gesture.shake) {
        liquid.splash(
            gesture.impulse_x, gesture.impulse_y, gesture.strength);
      }
      liquid.update(
          delta_seconds,
          motion.down_x,
          motion.down_y,
          motion.in_plane_gravity_g);
      liquid.render(frame);
    } else if (mode == EffectMode::kRainbow) {
      heart::RenderContext context{};
      context.now_seconds = now_seconds;
      rainbow.render(context, frame);
    } else {
      heart::RenderContext context{};
      context.now_seconds = now_seconds;
      context.motion = motion;
      context.target = target_provider.target();
      target_arrow.render(context, frame);
    }

    heart::apply_brightness(frame, kBrightnessLevels[brightness_index]);
    heart::apply_gamma(frame);
    const float power_scale = heart::limit_led_current(
        frame,
        heart::board::kLedCurrentBudgetMilliAmps,
        heart::board::kMilliAmpsPerColorChannel);
    if (power_scale < 0.999F) {
      ESP_LOGD(kTag, "Power limiter scale %.3f", power_scale);
    }
    write_frame(frame, strips);
    xTaskDelayUntil(&last_wake, kFrameTicks);
  }
}
