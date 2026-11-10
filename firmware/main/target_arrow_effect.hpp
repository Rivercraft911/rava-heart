#pragma once

#include <algorithm>
#include <cmath>
#include <numbers>

#include "heart_types.hpp"

namespace heart {

class TargetArrowEffect {
 public:
  // Offset between the PCB's visual top (+Y) and the calibrated compass
  // heading when the heart is held upright. Tune after the first assembled test.
  explicit TargetArrowEffect(float board_forward_offset_degrees = 0.0F)
      : board_forward_offset_degrees_(board_forward_offset_degrees) {}

  void render(const RenderContext& context, Frame& frame) const {
    frame.fill({});
    if (!context.target.valid || !context.motion.compass_valid) {
      render_waiting_indicator(context.now_seconds, frame);
      return;
    }

    const float relative_degrees = wrap_degrees(
        context.target.bearing_degrees - context.motion.heading_degrees -
        board_forward_offset_degrees_);
    const float angle = relative_degrees * std::numbers::pi_v<float> / 180.0F;
    const float direction_x = std::sin(angle);
    const float direction_y = std::cos(angle);
    constexpr float kCenterX = 0.5F;
    // Keep the glyph centered in every ordinary direction. Only an almost
    // due-north arrow shifts down so its tip lands below the heart notch.
    const float north_bias = std::pow(std::max(0.0F, direction_y), 96.0F);
    const float center_y = 0.48F - 0.155F * north_bias;
    constexpr float tip_along = 0.39F;
    constexpr float head_length = 0.20F;
    const float head_start = tip_along - head_length;
    constexpr float tail_along = -0.24F;

    for (std::size_t index = 0; index < frame.size(); ++index) {
      const auto& location = generated::kPixels[index];
      const float dx = location.x - kCenterX;
      const float dy = location.y - center_y;
      const float along = dx * direction_x + dy * direction_y;
      const float across = std::abs(dx * direction_y - dy * direction_x);

      const float shaft = soft_inside(across, 0.052F) *
                          soft_range(
                              along, tail_along, head_start + 0.035F, 0.050F);
      const float head_progress =
          std::clamp((tip_along - along) / head_length, 0.0F, 1.0F);
      const float head_width = 0.060F + head_progress * 0.155F;
      const float head = soft_inside(across, head_width) *
                         soft_range(along, head_start, tip_along, 0.050F);
      const float intensity = std::clamp(std::max(shaft, head), 0.0F, 1.0F);
      frame[index] = {
          to_channel(intensity),
          to_channel(intensity * 0.055F),
          to_channel(intensity * 0.020F),
      };
    }
  }

 private:
  static float wrap_degrees(float degrees) {
    float wrapped = std::fmod(degrees + 180.0F, 360.0F);
    if (wrapped < 0.0F) {
      wrapped += 360.0F;
    }
    return wrapped - 180.0F;
  }

  static float smoothstep(float edge0, float edge1, float value) {
    if (edge0 == edge1) {
      return value < edge0 ? 0.0F : 1.0F;
    }
    const float t = std::clamp((value - edge0) / (edge1 - edge0), 0.0F, 1.0F);
    return t * t * (3.0F - 2.0F * t);
  }

  static float soft_inside(float value, float half_width) {
    return 1.0F - smoothstep(half_width, half_width + 0.065F, value);
  }

  static float soft_range(float value, float low, float high, float feather) {
    return smoothstep(low - feather, low, value) *
           (1.0F - smoothstep(high, high + feather, value));
  }

  static std::uint8_t to_channel(float value) {
    return static_cast<std::uint8_t>(
        std::lround(std::clamp(value, 0.0F, 1.0F) * 255.0F));
  }

  static void render_waiting_indicator(float now_seconds, Frame& frame) {
    const float pulse = 0.10F + 0.10F * (0.5F + 0.5F * std::sin(now_seconds * 3.0F));
    for (std::size_t index = 0; index < frame.size(); ++index) {
      const auto& location = generated::kPixels[index];
      const float dx = location.x - 0.5F;
      const float dy = location.y - 0.48F;
      if (dx * dx + dy * dy < 0.010F) {
        frame[index] = {to_channel(pulse), to_channel(pulse * 0.16F), 0};
      }
    }
  }

  float board_forward_offset_degrees_;
};

}  // namespace heart
