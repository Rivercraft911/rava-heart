#pragma once

#include <cmath>

#include "board_config.hpp"
#include "heart_types.hpp"

namespace heart {

struct AccelerationSample {
  float sensor_x_g = 0.0F;
  float sensor_y_g = 0.0F;
  float sensor_z_g = 1.0F;
  bool valid = false;
};

struct MagneticSample {
  float sensor_x_gauss = 0.0F;
  float sensor_y_gauss = 0.0F;
  float sensor_z_gauss = 0.0F;
  bool valid = false;
};

struct Vector3 {
  float x = 0.0F;
  float y = 0.0F;
  float z = 0.0F;
};

inline Vector3 acceleration_in_board_axes(const AccelerationSample& sample) {
  return {
      board::kImuBoardXFromSensorX * sample.sensor_x_g +
          board::kImuBoardXFromSensorY * sample.sensor_y_g,
      board::kImuBoardYFromSensorX * sample.sensor_x_g +
          board::kImuBoardYFromSensorY * sample.sensor_y_g,
      board::kImuBoardZFromSensorZ * sample.sensor_z_g,
  };
}

inline Vector3 magnetic_field_in_board_axes(const MagneticSample& sample) {
  return {
      board::kMagBoardXFromSensorX * sample.sensor_x_gauss +
          board::kMagBoardXFromSensorY * sample.sensor_y_gauss,
      board::kMagBoardYFromSensorX * sample.sensor_x_gauss +
          board::kMagBoardYFromSensorY * sample.sensor_y_gauss,
      board::kMagBoardZFromSensorZ * sample.sensor_z_gauss,
  };
}

inline MotionState motion_from_acceleration(const AccelerationSample& sample) {
  MotionState motion{};
  if (!sample.valid) {
    return motion;
  }

  const Vector3 board_specific_force = acceleration_in_board_axes(sample);

  // A stationary accelerometer measures support force opposite gravity.
  motion.down_x = -board_specific_force.x;
  motion.down_y = -board_specific_force.y;
  motion.in_plane_gravity_g = std::hypot(motion.down_x, motion.down_y);
  return motion;
}

}  // namespace heart
