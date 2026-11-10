#pragma once

#include <array>
#include <cstdint>

#include "generated/pixel_map.hpp"

namespace heart {

struct Rgb8 {
  std::uint8_t r = 0;
  std::uint8_t g = 0;
  std::uint8_t b = 0;
};

using Frame = std::array<Rgb8, generated::kPixelCount>;

struct MotionState {
  float down_x = 0.0F;
  float down_y = -1.0F;
  float in_plane_gravity_g = 0.0F;
  float heading_degrees = 0.0F;
  bool compass_valid = false;
};

// The heart renderer only needs a bearing. A future phone or paired-heart
// transport can provide it without coupling networking into the effects code.
struct TargetState {
  float bearing_degrees = 0.0F;
  float distance_meters = 0.0F;
  bool valid = false;
};

struct RenderContext {
  float now_seconds = 0.0F;
  MotionState motion{};
  TargetState target{};
};

}  // namespace heart
