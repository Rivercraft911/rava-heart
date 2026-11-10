#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>

#include "heart_types.hpp"

namespace heart {

inline std::uint8_t to_byte(float value) {
  const float clamped = std::clamp(value, 0.0F, 1.0F);
  return static_cast<std::uint8_t>(std::lround(clamped * 255.0F));
}

inline void apply_brightness(Frame& frame, float brightness) {
  const float scale = std::clamp(brightness, 0.0F, 1.0F);
  for (auto& pixel : frame) {
    pixel.r = static_cast<std::uint8_t>(std::lround(pixel.r * scale));
    pixel.g = static_cast<std::uint8_t>(std::lround(pixel.g * scale));
    pixel.b = static_cast<std::uint8_t>(std::lround(pixel.b * scale));
  }
}

inline const std::array<std::uint8_t, 256>& gamma_lut() {
  static const std::array<std::uint8_t, 256> lookup = [] {
    std::array<std::uint8_t, 256> result{};
    for (std::size_t index = 0; index < result.size(); ++index) {
      const float normalized = static_cast<float>(index) / 255.0F;
      result[index] = to_byte(std::pow(normalized, 2.2F));
    }
    return result;
  }();
  return lookup;
}

inline void apply_gamma(Frame& frame) {
  const auto& lookup = gamma_lut();
  for (auto& pixel : frame) {
    pixel.r = lookup[pixel.r];
    pixel.g = lookup[pixel.g];
    pixel.b = lookup[pixel.b];
  }
}

inline float estimate_led_current_milliamps(
    const Frame& frame, float milliamps_per_channel) {
  std::uint64_t channel_sum = 0;
  for (const auto& pixel : frame) {
    channel_sum += pixel.r;
    channel_sum += pixel.g;
    channel_sum += pixel.b;
  }
  return static_cast<float>(channel_sum) * milliamps_per_channel / 255.0F;
}

inline float limit_led_current(
    Frame& frame, float budget_milliamps, float milliamps_per_channel) {
  const float estimate = estimate_led_current_milliamps(frame, milliamps_per_channel);
  if (estimate <= budget_milliamps || estimate <= 0.0F) {
    return 1.0F;
  }
  const float scale = budget_milliamps / estimate;
  apply_brightness(frame, scale);
  return scale;
}

}  // namespace heart
