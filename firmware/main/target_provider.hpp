#pragma once

#include <algorithm>
#include <cmath>
#include <numbers>

#include "heart_types.hpp"

namespace heart {

struct GeographicPosition {
  double latitude_degrees = 0.0;
  double longitude_degrees = 0.0;
  bool valid = false;
};

inline TargetState target_from_positions(
    const GeographicPosition& local,
    const GeographicPosition& remote) {
  if (!local.valid || !remote.valid) {
    return {};
  }

  constexpr double kEarthRadiusMeters = 6'371'000.0;
  const auto radians = [](double degrees) {
    return degrees * std::numbers::pi / 180.0;
  };
  const double latitude_a = radians(local.latitude_degrees);
  const double latitude_b = radians(remote.latitude_degrees);
  const double delta_latitude = latitude_b - latitude_a;
  const double delta_longitude =
      radians(remote.longitude_degrees - local.longitude_degrees);

  const double bearing_y = std::sin(delta_longitude) * std::cos(latitude_b);
  const double bearing_x =
      std::cos(latitude_a) * std::sin(latitude_b) -
      std::sin(latitude_a) * std::cos(latitude_b) * std::cos(delta_longitude);
  double bearing_degrees =
      std::atan2(bearing_y, bearing_x) * 180.0 / std::numbers::pi;
  if (bearing_degrees < 0.0) {
    bearing_degrees += 360.0;
  }

  const double haversine =
      std::sin(delta_latitude * 0.5) * std::sin(delta_latitude * 0.5) +
      std::cos(latitude_a) * std::cos(latitude_b) *
          std::sin(delta_longitude * 0.5) * std::sin(delta_longitude * 0.5);
  const double distance =
      2.0 * kEarthRadiusMeters *
      std::asin(std::sqrt(std::clamp(haversine, 0.0, 1.0)));
  return {
      static_cast<float>(bearing_degrees),
      static_cast<float>(distance),
      true,
  };
}

class TargetProvider {
 public:
  void set_positions(
      const GeographicPosition& local,
      const GeographicPosition& remote) {
    target_ = target_from_positions(local, remote);
  }

  // Useful for USB bench tests and for a transport that already computes the
  // true bearing on a phone or paired device.
  void set_bearing(float bearing_degrees) {
    target_ = {wrap_degrees(bearing_degrees), 0.0F, true};
  }

  void clear() { target_ = {}; }

  [[nodiscard]] const TargetState& target() const { return target_; }

 private:
  static float wrap_degrees(float degrees) {
    float wrapped = std::fmod(degrees, 360.0F);
    return wrapped < 0.0F ? wrapped + 360.0F : wrapped;
  }

  TargetState target_{};
};

}  // namespace heart
