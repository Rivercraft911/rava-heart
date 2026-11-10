#pragma once

#include <cstdint>

namespace heart::board {

// ESP32-C3-WROOM-02 pins, extracted from the ordered HeartArray schematic.
inline constexpr int kLedChain0Gpio = 5;  // U4 channel 2 -> R15 -> D13 DIN
inline constexpr int kLedChain1Gpio = 4;  // U4 channel 1 -> R14 -> D85 DIN
inline constexpr int kI2cSclGpio = 6;
inline constexpr int kI2cSdaGpio = 7;
inline constexpr int kMagDataReadyGpio = 10;
inline constexpr int kImuInt1Gpio = 1;
inline constexpr int kImuInt2Gpio = 3;
// Runtime roles follow the physical placement the board was designed around:
// S2 is the convenient front/bottom mode button, while S3 is the rear auxiliary
// button. GPIO9 remains the ESP32-C3 hardware BOOT strap regardless of its
// runtime role, so do not hold S2 during reset or power-up.
inline constexpr int kModeButtonGpio = 9;        // S2, active low; BOOT strap
inline constexpr int kBrightnessButtonGpio = 0;  // S3, active low

inline constexpr std::uint8_t kLis3mdlAddress = 0x1C;
inline constexpr std::uint8_t kLsm6dsoxAddress = 0x6A;
inline constexpr std::uint8_t kWhoAmIRegister = 0x0F;
inline constexpr std::uint8_t kLis3mdlWhoAmI = 0x3D;
inline constexpr std::uint8_t kLsm6dsoxWhoAmI = 0x6C;

inline constexpr float kFrameRateHz = 60.0F;
inline constexpr std::uint32_t kLedDataRateBitsPerSecond = 800000;
inline constexpr std::uint32_t kLedBitsPerPixel = 24;
// WS2812B-MINI-V6 specifies >280 us; use 300 us for the schedule budget.
inline constexpr std::uint32_t kLedResetBudgetMicroseconds = 300;

// The eFuse is near 3 A. Reserve roughly 0.5 A for the ESP32, regulator
// losses, sensors, and transient/model error instead of leaning on the trip.
inline constexpr float kLedCurrentBudgetMilliAmps = 2500.0F;
inline constexpr float kMilliAmpsPerColorChannel = 12.0F;

// Initial LSM6DSOX-to-front-art coordinate transform. The IMU is mounted on
// B.Cu, so verify these signs during the first-board tilt test. To correct an
// axis, only these four constants need to change; the liquid physics does not.
inline constexpr float kImuBoardXFromSensorX = -1.0F;
inline constexpr float kImuBoardXFromSensorY = 0.0F;
inline constexpr float kImuBoardYFromSensorX = 0.0F;
inline constexpr float kImuBoardYFromSensorY = 1.0F;
inline constexpr float kImuBoardZFromSensorZ = -1.0F;

// U1 is also on B.Cu at 180 degrees. These are deliberately independent from
// the IMU transform so either footprint can be corrected after the first-board
// compass/tilt test without changing any effect code.
inline constexpr float kMagBoardXFromSensorX = 1.0F;
inline constexpr float kMagBoardXFromSensorY = 0.0F;
inline constexpr float kMagBoardYFromSensorX = 0.0F;
inline constexpr float kMagBoardYFromSensorY = 1.0F;
inline constexpr float kMagBoardZFromSensorZ = -1.0F;

}  // namespace heart::board
