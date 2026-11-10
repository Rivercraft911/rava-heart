#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <numbers>

#include "imu_axes.hpp"

namespace heart {

struct CompassReading {
  float heading_degrees = 0.0F;
  bool valid = false;
  bool calibration_ready = false;
};

// Learns a diagonal hard/soft-iron correction while the heart is rotated in a
// figure eight. Heading remains available from raw data before calibration is
// complete, then automatically improves once all three axes have enough span.
class CompassEstimator {
 public:
  CompassReading update(
      const AccelerationSample& acceleration,
      const MagneticSample& magnetic) {
    if (!acceleration.valid || !magnetic.valid) {
      return {};
    }

    const Vector3 up = normalized(acceleration_in_board_axes(acceleration));
    const Vector3 raw_magnetic = magnetic_field_in_board_axes(magnetic);
    update_extrema(raw_magnetic);
    const Vector3 corrected_magnetic = calibrated(raw_magnetic);

    // Remove the vertical component of Earth's field. The result is magnetic
    // north expressed in board coordinates, even while the PCB is tilted.
    Vector3 north = subtract(
        corrected_magnetic,
        multiply(up, dot(corrected_magnetic, up)));
    north = normalized(north);
    if (length(up) < 0.5F || length(north) < 0.5F) {
      return {};
    }

    const Vector3 east = normalized(cross(north, up));
    constexpr Vector3 kBoardForward{0.0F, 1.0F, 0.0F};
    const Vector3 forward_horizontal = subtract(
        kBoardForward,
        multiply(up, dot(kBoardForward, up)));
    if (length(forward_horizontal) < 0.10F) {
      return {};
    }

    const float heading = std::atan2(
        dot(east, forward_horizontal),
        dot(north, forward_horizontal));
    return {
        smooth_heading(
            wrap_degrees(heading * 180.0F / std::numbers::pi_v<float>)),
        true,
        calibration_ready(),
    };
  }

  void reset_calibration() {
    initialized_ = false;
    minimum_ = {};
    maximum_ = {};
    heading_filter_initialized_ = false;
    filtered_heading_x_ = 1.0F;
    filtered_heading_y_ = 0.0F;
  }

 private:
  static constexpr float kMinimumCalibrationSpanGauss = 0.20F;
  // Light circular low-pass filtering: enough to settle single-pixel arrow
  // chatter without making a hand-turned heart feel delayed.
  static constexpr float kHeadingFilterAlpha = 0.22F;

  static float length(const Vector3& value) {
    return std::sqrt(dot(value, value));
  }

  static Vector3 normalized(const Vector3& value) {
    const float magnitude = length(value);
    if (magnitude < 0.0001F) {
      return {};
    }
    return multiply(value, 1.0F / magnitude);
  }

  static float dot(const Vector3& a, const Vector3& b) {
    return a.x * b.x + a.y * b.y + a.z * b.z;
  }

  static Vector3 cross(const Vector3& a, const Vector3& b) {
    return {
        a.y * b.z - a.z * b.y,
        a.z * b.x - a.x * b.z,
        a.x * b.y - a.y * b.x,
    };
  }

  static Vector3 subtract(const Vector3& a, const Vector3& b) {
    return {a.x - b.x, a.y - b.y, a.z - b.z};
  }

  static Vector3 multiply(const Vector3& value, float scale) {
    return {value.x * scale, value.y * scale, value.z * scale};
  }

  static float wrap_degrees(float degrees) {
    float wrapped = std::fmod(degrees, 360.0F);
    if (wrapped < 0.0F) {
      wrapped += 360.0F;
    }
    return wrapped;
  }

  float smooth_heading(float heading_degrees) {
    const float radians =
        heading_degrees * std::numbers::pi_v<float> / 180.0F;
    const float sample_x = std::cos(radians);
    const float sample_y = std::sin(radians);
    if (!heading_filter_initialized_) {
      filtered_heading_x_ = sample_x;
      filtered_heading_y_ = sample_y;
      heading_filter_initialized_ = true;
    } else {
      filtered_heading_x_ +=
          (sample_x - filtered_heading_x_) * kHeadingFilterAlpha;
      filtered_heading_y_ +=
          (sample_y - filtered_heading_y_) * kHeadingFilterAlpha;
    }
    return wrap_degrees(
        std::atan2(filtered_heading_y_, filtered_heading_x_) * 180.0F /
        std::numbers::pi_v<float>);
  }

  void update_extrema(const Vector3& value) {
    if (!initialized_) {
      minimum_ = value;
      maximum_ = value;
      initialized_ = true;
      return;
    }
    minimum_.x = std::min(minimum_.x, value.x);
    minimum_.y = std::min(minimum_.y, value.y);
    minimum_.z = std::min(minimum_.z, value.z);
    maximum_.x = std::max(maximum_.x, value.x);
    maximum_.y = std::max(maximum_.y, value.y);
    maximum_.z = std::max(maximum_.z, value.z);
  }

  bool calibration_ready() const {
    return initialized_ &&
        maximum_.x - minimum_.x >= kMinimumCalibrationSpanGauss &&
        maximum_.y - minimum_.y >= kMinimumCalibrationSpanGauss &&
        maximum_.z - minimum_.z >= kMinimumCalibrationSpanGauss;
  }

  Vector3 calibrated(const Vector3& value) const {
    if (!calibration_ready()) {
      return value;
    }
    const Vector3 center{
        (maximum_.x + minimum_.x) * 0.5F,
        (maximum_.y + minimum_.y) * 0.5F,
        (maximum_.z + minimum_.z) * 0.5F,
    };
    const Vector3 half_span{
        (maximum_.x - minimum_.x) * 0.5F,
        (maximum_.y - minimum_.y) * 0.5F,
        (maximum_.z - minimum_.z) * 0.5F,
    };
    const float average_span = (half_span.x + half_span.y + half_span.z) / 3.0F;
    return {
        (value.x - center.x) * average_span / half_span.x,
        (value.y - center.y) * average_span / half_span.y,
        (value.z - center.z) * average_span / half_span.z,
    };
  }

  Vector3 minimum_{};
  Vector3 maximum_{};
  bool initialized_ = false;
  float filtered_heading_x_ = 1.0F;
  float filtered_heading_y_ = 0.0F;
  bool heading_filter_initialized_ = false;
};

}  // namespace heart
