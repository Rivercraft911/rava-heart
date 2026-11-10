#pragma once

#include <algorithm>
#include <cmath>

namespace heart {

struct GestureEvents {
  bool shake = false;
  float impulse_x = 0.0F;
  float impulse_y = 0.0F;
  float strength = 0.0F;
};

class ShakeDetector {
 public:
  GestureEvents update(
      float now_seconds, float accel_x_g, float accel_y_g, float accel_z_g) {
    if (!initialized_) {
      gravity_x_g_ = accel_x_g;
      gravity_y_g_ = accel_y_g;
      gravity_z_g_ = accel_z_g;
      initialized_ = true;
      return {};
    }

    // A low-pass gravity estimate leaves the short, directional acceleration
    // caused by the user's hand. The water receives the opposite (inertial)
    // impulse, which is why a rightward board flick throws it left.
    constexpr float kGravityTracking = 0.08F;
    gravity_x_g_ += (accel_x_g - gravity_x_g_) * kGravityTracking;
    gravity_y_g_ += (accel_y_g - gravity_y_g_) * kGravityTracking;
    gravity_z_g_ += (accel_z_g - gravity_z_g_) * kGravityTracking;
    const float dynamic_x = accel_x_g - gravity_x_g_;
    const float dynamic_y = accel_y_g - gravity_y_g_;
    const float dynamic_z = accel_z_g - gravity_z_g_;
    const float dynamic_magnitude =
        std::sqrt(dynamic_x * dynamic_x + dynamic_y * dynamic_y + dynamic_z * dynamic_z);
    const float magnitude =
        std::sqrt(accel_x_g * accel_x_g + accel_y_g * accel_y_g + accel_z_g * accel_z_g);
    const float impulse = std::max(
        std::abs(magnitude - 1.0F), dynamic_magnitude * 0.62F);
    envelope_ = std::max(impulse, envelope_ * 0.82F);

    GestureEvents events{};
    // A deliberate wrist shake commonly produces only a few tenths of a g of
    // linear acceleration once the 1 g gravity vector is removed. Keep the
    // threshold low enough to catch that motion, while the cooldown prevents
    // one physical shake from becoming a burst of repeated events.
    if (envelope_ > 0.34F && now_seconds - last_shake_seconds_ > 0.65F) {
      events.shake = true;
      events.impulse_x = -dynamic_x;
      events.impulse_y = -dynamic_y;
      events.strength = std::clamp((envelope_ - 0.24F) / 0.90F, 0.25F, 1.0F);
      last_shake_seconds_ = now_seconds;
      envelope_ = 0.0F;
    }
    return events;
  }

 private:
  float envelope_ = 0.0F;
  float last_shake_seconds_ = -10.0F;
  float gravity_x_g_ = 0.0F;
  float gravity_y_g_ = 0.0F;
  float gravity_z_g_ = 0.0F;
  bool initialized_ = false;
};

}  // namespace heart
