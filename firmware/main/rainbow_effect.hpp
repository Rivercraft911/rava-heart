#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <numbers>

#include "heart_types.hpp"

namespace heart {

class RainbowEffect {
 public:
  void render(const RenderContext& context, Frame& frame) const {
    for (std::size_t index = 0; index < frame.size(); ++index) {
      const auto& location = generated::kPixels[index];
      const float dx = location.x - 0.5F;
      const float dy = location.y - 0.5F;
      const float radius = std::hypot(dx, dy);
      const float turns =
          std::atan2(dy, dx) / (2.0F * std::numbers::pi_v<float>);
      const float ripple = std::sin(
          2.0F * std::numbers::pi_v<float> *
          (radius * 2.2F - context.now_seconds * 0.18F));
      const float hue =
          turns + 0.85F * radius - context.now_seconds * 0.10F + 0.08F * ripple;
      const float value =
          0.72F +
          0.28F *
              (0.5F +
               0.5F * std::sin(
                          2.0F * std::numbers::pi_v<float> *
                          (1.7F * radius - 0.24F * context.now_seconds +
                           0.35F * turns)));
      frame[index] = hsv_to_rgb(hue, 1.0F, value);
    }
  }

 private:
  static Rgb8 hsv_to_rgb(float hue, float saturation, float value) {
    hue -= std::floor(hue);
    const float sector = hue * 6.0F;
    const int index = static_cast<int>(std::floor(sector));
    const float fraction = sector - static_cast<float>(index);
    const float p = value * (1.0F - saturation);
    const float q = value * (1.0F - saturation * fraction);
    const float t = value * (1.0F - saturation * (1.0F - fraction));
    const auto color = [=](float red, float green, float blue) {
      return Rgb8{to_channel(red), to_channel(green), to_channel(blue)};
    };
    switch (index % 6) {
      case 0:
        return color(value, t, p);
      case 1:
        return color(q, value, p);
      case 2:
        return color(p, value, t);
      case 3:
        return color(p, q, value);
      case 4:
        return color(t, p, value);
      default:
        return color(value, p, q);
    }
  }

  static std::uint8_t to_channel(float value) {
    return static_cast<std::uint8_t>(
        std::lround(std::clamp(value, 0.0F, 1.0F) * 255.0F));
  }
};

}  // namespace heart
