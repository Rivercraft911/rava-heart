#pragma once

#include <cstddef>
#include <cstdint>

#include "driver/i2c_master.h"
#include "esp_err.h"
#include "esp_log.h"

#include "board_config.hpp"
#include "imu_axes.hpp"

namespace heart {

class SensorService {
 public:
  bool initialize() {
    i2c_master_bus_config_t bus_config{};
    bus_config.i2c_port = I2C_NUM_0;
    bus_config.sda_io_num = static_cast<gpio_num_t>(board::kI2cSdaGpio);
    bus_config.scl_io_num = static_cast<gpio_num_t>(board::kI2cSclGpio);
    bus_config.clk_source = I2C_CLK_SRC_DEFAULT;
    bus_config.glitch_ignore_cnt = 7;
    bus_config.flags.enable_internal_pullup = false;  // R12/R13 are 4.7 kOhm.
    if (!check(i2c_new_master_bus(&bus_config, &bus_), "create I2C bus")) {
      return false;
    }

    if (!add_device(board::kLsm6dsoxAddress, &imu_) ||
        !add_device(board::kLis3mdlAddress, &magnetometer_)) {
      return false;
    }

    const bool imu_identity = check_identity(
        imu_, board::kLsm6dsoxWhoAmI, "LSM6DSOX");
    magnetometer_ready_ = check_identity(
        magnetometer_, board::kLis3mdlWhoAmI, "LIS3MDL");
    if (!imu_identity) {
      return false;
    }

    // LSM6DSOX: block-data update, address increment, 104 Hz, +/-2 g.
    const bool imu_configured =
        write_register(imu_, kImuCtrl3C, 0x44) &&
        write_register(imu_, kImuCtrl1Xl, 0x40);

    // LIS3MDL: ultra-high-performance XYZ, 80 Hz, +/-4 gauss, continuous.
    if (magnetometer_ready_) {
      magnetometer_ready_ =
          write_register(magnetometer_, kMagCtrl1, 0x7C) &&
          write_register(magnetometer_, kMagCtrl2, 0x00) &&
          write_register(magnetometer_, kMagCtrl3, 0x00) &&
          write_register(magnetometer_, kMagCtrl4, 0x0C);
    }
    return imu_configured;
  }

  bool read_acceleration(AccelerationSample& sample) {
    if (imu_ == nullptr) {
      return false;
    }
    std::uint8_t bytes[6]{};
    if (!read_registers(imu_, kOutXlA, bytes, sizeof(bytes))) {
      return false;
    }
    sample.sensor_x_g = static_cast<float>(unpack(&bytes[0])) * kGPerLsbAt2G;
    sample.sensor_y_g = static_cast<float>(unpack(&bytes[2])) * kGPerLsbAt2G;
    sample.sensor_z_g = static_cast<float>(unpack(&bytes[4])) * kGPerLsbAt2G;
    sample.valid = true;
    return true;
  }

  bool read_magnetic_field(MagneticSample& sample) {
    if (!magnetometer_ready_) {
      return false;
    }
    std::uint8_t bytes[6]{};
    // LIS3MDL uses the sub-address MSB to enable multi-byte auto increment.
    if (!read_registers(
            magnetometer_, kMagOutXl | 0x80U, bytes, sizeof(bytes))) {
      return false;
    }
    sample.sensor_x_gauss =
        static_cast<float>(unpack(&bytes[0])) * kGaussPerLsbAt4Gauss;
    sample.sensor_y_gauss =
        static_cast<float>(unpack(&bytes[2])) * kGaussPerLsbAt4Gauss;
    sample.sensor_z_gauss =
        static_cast<float>(unpack(&bytes[4])) * kGaussPerLsbAt4Gauss;
    sample.valid = true;
    return true;
  }

  [[nodiscard]] bool magnetometer_ready() const { return magnetometer_ready_; }

 private:
  static constexpr std::uint8_t kImuCtrl1Xl = 0x10;
  static constexpr std::uint8_t kImuCtrl3C = 0x12;
  static constexpr std::uint8_t kOutXlA = 0x28;
  static constexpr std::uint8_t kMagCtrl1 = 0x20;
  static constexpr std::uint8_t kMagCtrl2 = 0x21;
  static constexpr std::uint8_t kMagCtrl3 = 0x22;
  static constexpr std::uint8_t kMagCtrl4 = 0x23;
  static constexpr std::uint8_t kMagOutXl = 0x28;
  static constexpr float kGPerLsbAt2G = 0.000061F;
  static constexpr float kGaussPerLsbAt4Gauss = 1.0F / 6842.0F;

  static std::int16_t unpack(const std::uint8_t* value) {
    return static_cast<std::int16_t>(
        static_cast<std::uint16_t>(value[0]) |
        (static_cast<std::uint16_t>(value[1]) << 8U));
  }

  static bool check(esp_err_t error, const char* operation) {
    if (error == ESP_OK) {
      return true;
    }
    ESP_LOGE("sensors", "%s failed: %s", operation, esp_err_to_name(error));
    return false;
  }

  bool add_device(std::uint8_t address, i2c_master_dev_handle_t* result) {
    i2c_device_config_t config{};
    config.dev_addr_length = I2C_ADDR_BIT_LEN_7;
    config.device_address = address;
    config.scl_speed_hz = 400000;
    return check(i2c_master_bus_add_device(bus_, &config, result), "add I2C device");
  }

  bool check_identity(
      i2c_master_dev_handle_t device,
      std::uint8_t expected,
      const char* name) {
    std::uint8_t actual = 0;
    if (!read_registers(device, board::kWhoAmIRegister, &actual, 1)) {
      ESP_LOGE("sensors", "%s WHO_AM_I read failed", name);
      return false;
    }
    if (actual != expected) {
      ESP_LOGE(
          "sensors", "%s WHO_AM_I=0x%02X, expected 0x%02X", name, actual, expected);
      return false;
    }
    ESP_LOGI("sensors", "%s identity OK (0x%02X)", name, actual);
    return true;
  }

  static bool write_register(
      i2c_master_dev_handle_t device, std::uint8_t address, std::uint8_t value) {
    const std::uint8_t transaction[] = {address, value};
    return check(
        i2c_master_transmit(device, transaction, sizeof(transaction), 100),
        "write sensor register");
  }

  static bool read_registers(
      i2c_master_dev_handle_t device,
      std::uint8_t address,
      std::uint8_t* destination,
      std::size_t length) {
    return check(
        i2c_master_transmit_receive(
            device, &address, 1, destination, length, 100),
        "read sensor register");
  }

  i2c_master_bus_handle_t bus_ = nullptr;
  i2c_master_dev_handle_t imu_ = nullptr;
  i2c_master_dev_handle_t magnetometer_ = nullptr;
  bool magnetometer_ready_ = false;
};

}  // namespace heart
