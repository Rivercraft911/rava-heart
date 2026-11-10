#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

#include "heart_types.hpp"

namespace heart {

class LoveEffect {
 public:
  static constexpr float kDurationSeconds = 3.35F;

  void trigger(float now_seconds) {
    start_seconds_ = now_seconds;
    active_ = true;
  }

  [[nodiscard]] bool active(float now_seconds) const {
    return active_ && now_seconds - start_seconds_ < kDurationSeconds;
  }

  void render(float now_seconds, Frame& frame) {
    frame.fill({});
    const float elapsed = now_seconds - start_seconds_;
    if (!active_ || elapsed < 0.0F || elapsed >= kDurationSeconds) {
      active_ = false;
      return;
    }

    if (elapsed < 0.82F) {
      const float envelope = phase_envelope(elapsed / 0.82F);
      render_letter_i(envelope, frame);
    } else if (elapsed < 2.02F) {
      const float envelope = phase_envelope((elapsed - 0.82F) / 1.20F);
      render_heart(envelope, frame);
    } else {
      const float envelope = phase_envelope((elapsed - 2.02F) / 1.33F);
      render_letter_u(envelope, frame);
    }
  }

 private:
  static float phase_envelope(float phase) {
    const float fade_in = smoothstep(0.0F, 0.12F, phase);
    const float fade_out = 1.0F - smoothstep(0.82F, 1.0F, phase);
    return fade_in * fade_out;
  }

  static void render_letter_i(float envelope, Frame& frame) {
    constexpr float kOneLedRow = 0.0769231F;
    for (std::size_t index = 0; index < frame.size(); ++index) {
      const auto& pixel = generated::kPixels[index];
      const float dx = std::abs(pixel.x - 0.5F);
      const bool vertical = dx < 0.060F &&
                            pixel.y > 0.25F - kOneLedRow &&
                            pixel.y < 0.72F - kOneLedRow;
      const bool bars = dx < 0.225F &&
                        (std::abs(pixel.y - (0.27F - kOneLedRow)) < 0.060F ||
                         std::abs(pixel.y - (0.70F - kOneLedRow)) < 0.060F);
      if (vertical || bars) {
        frame[index] = color(envelope, 1.0F, 0.25F, 0.58F);
      }
    }
  }

  static void render_heart(float envelope, Frame& frame) {
    const float breathe = 0.91F + 0.09F * envelope;
    for (auto& pixel : frame) {
      pixel = color(envelope * breathe, 1.0F, 0.15F, 0.65F);
    }
  }

  static void render_letter_u(float envelope, Frame& frame) {
    for (std::size_t index = 0; index < frame.size(); ++index) {
      const auto& pixel = generated::kPixels[index];
      const float dx = pixel.x - 0.5F;
      float distance = 1.0F;
      if (pixel.y >= 0.34F && pixel.y <= 0.72F) {
        distance = std::min(std::abs(dx - 0.18F), std::abs(dx + 0.18F));
      }
      if (pixel.y <= 0.38F) {
        distance = std::min(
            distance,
            std::abs(std::hypot(dx, pixel.y - 0.37F) - 0.18F));
      }
      const float mask = 1.0F - smoothstep(0.050F, 0.105F, distance);
      if (mask > 0.01F) {
        frame[index] = color(envelope * mask, 1.0F, 0.30F, 0.78F);
      }
    }
  }

  static float smoothstep(float low, float high, float value) {
    const float t = std::clamp((value - low) / (high - low), 0.0F, 1.0F);
    return t * t * (3.0F - 2.0F * t);
  }

  static Rgb8 color(float intensity, float red, float green, float blue) {
    return {
        to_channel(intensity * red),
        to_channel(intensity * green),
        to_channel(intensity * blue),
    };
  }

  static std::uint8_t to_channel(float value) {
    return static_cast<std::uint8_t>(
        std::lround(std::clamp(value, 0.0F, 1.0F) * 255.0F));
  }

  float start_seconds_ = 0.0F;
  bool active_ = false;
};

}  // namespace heart
