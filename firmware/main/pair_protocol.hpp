#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>

namespace heart::pair {

inline constexpr std::uint32_t kMagic = 0x52415641U;  // "RAVA"
inline constexpr std::uint32_t kGroupId = 0x48454152U;  // "HEAR"
inline constexpr std::uint8_t kVersion = 2;

enum class MessageType : std::uint8_t {
  kLove = 1,
  kHeartbeatSync = 2,
};

struct Message {
  std::uint32_t magic = kMagic;
  std::uint32_t group_id = kGroupId;
  std::uint16_t sequence = 0;
  std::uint8_t version = kVersion;
  MessageType type = MessageType::kLove;
  std::uint16_t beat_phase_milliseconds = 0;
  std::uint16_t beat_period_milliseconds = 0;
};

static_assert(sizeof(Message) <= 16);

inline bool decode_message(
    const std::uint8_t* data, std::size_t length, Message& result) {
  if (data == nullptr || length != sizeof(Message)) {
    return false;
  }
  std::memcpy(&result, data, sizeof(result));
  const bool known_type = result.type == MessageType::kLove ||
                          result.type == MessageType::kHeartbeatSync;
  return result.magic == kMagic && result.group_id == kGroupId &&
         result.version == kVersion && known_type;
}

}  // namespace heart::pair
