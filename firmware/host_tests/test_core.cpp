#include <array>
#include <cassert>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <set>

#include "board_config.hpp"
#include "button.hpp"
#include "color_pipeline.hpp"
#include "compass.hpp"
#include "gesture_detector.hpp"
#include "heartbeat_effect.hpp"
#include "imu_axes.hpp"
#include "liquid_effect.hpp"
#include "love_effect.hpp"
#include "pair_protocol.hpp"
#include "rainbow_effect.hpp"
#include "target_arrow_effect.hpp"
#include "target_provider.hpp"

namespace {

std::uint64_t red_sum(const heart::Frame& frame) {
  std::uint64_t total = 0;
  for (const auto& pixel : frame) {
    total += pixel.r;
  }
  return total;
}

void test_generated_map() {
  using namespace heart::generated;
  static_assert(kPixelCount == 144);
  static_assert(kPixelsPerChain == 72);
  static_assert(kChain0FirstReference == 13);
  static_assert(kChain1FirstReference == 85);
  std::set<std::uint16_t> references;
  for (const auto& pixel : kPixels) {
    assert(pixel.x >= 0.0F && pixel.x <= 1.0F);
    assert(pixel.y >= 0.0F && pixel.y <= 1.0F);
    assert(pixel.chain < 2);
    assert(pixel.physical_index < 72);
    references.insert(pixel.reference_number);
  }
  assert(references.size() == 144);
}

void test_power_limiter() {
  heart::Frame frame{};
  frame.fill({255, 255, 255});
  const float raw = heart::estimate_led_current_milliamps(
      frame, heart::board::kMilliAmpsPerColorChannel);
  assert(std::abs(raw - 5184.0F) < 0.1F);
  const float scale = heart::limit_led_current(
      frame,
      heart::board::kLedCurrentBudgetMilliAmps,
      heart::board::kMilliAmpsPerColorChannel);
  assert(scale > 0.47F && scale < 0.49F);
  const float limited = heart::estimate_led_current_milliamps(
      frame, heart::board::kMilliAmpsPerColorChannel);
  assert(limited <= heart::board::kLedCurrentBudgetMilliAmps + 25.0F);
}

void test_gamma_lookup() {
  heart::Frame frame{};
  frame[0] = {0, 128, 255};
  heart::apply_gamma(frame);
  assert(frame[0].r == 0);
  assert(frame[0].g >= 55 && frame[0].g <= 56);
  assert(frame[0].b == 255);
}

void test_heartbeat() {
  heart::HeartbeatEffect effect(60.0F);
  heart::Frame quiet{};
  heart::Frame pulse{};
  heart::RenderContext context{};
  context.now_seconds = 0.75F;
  effect.render(context, quiet);
  context.now_seconds = 1.15F;
  effect.render(context, pulse);
  assert(red_sum(pulse) > red_sum(quiet) * 8);

  // A follower with a different boot-time phase locks to the leader, then
  // applies only gentle corrections to later, slightly noisy beacons.
  heart::HeartbeatEffect follower(60.0F);
  follower.synchronize(10.70F, 0.15F);
  assert(std::abs(follower.phase_seconds(10.70F) - 0.15F) < 0.001F);
  follower.synchronize(11.70F, 0.25F);
  assert(std::abs(follower.phase_seconds(11.70F) - 0.185F) < 0.002F);
}

void test_target_arrow() {
  heart::TargetArrowEffect effect;
  heart::Frame frame{};
  heart::RenderContext context{};
  context.motion.heading_degrees = 0.0F;
  context.motion.compass_valid = true;
  context.target.bearing_degrees = 0.0F;
  context.target.valid = true;
  effect.render(context, frame);

  float weighted_y = 0.0F;
  float weight = 0.0F;
  float highest_bright_pixel = 0.0F;
  std::size_t bright_pixels = 0;
  for (std::size_t index = 0; index < frame.size(); ++index) {
    weighted_y += heart::generated::kPixels[index].y * frame[index].r;
    weight += frame[index].r;
    if (frame[index].r > 24) {
      highest_bright_pixel =
          std::max(highest_bright_pixel, heart::generated::kPixels[index].y);
      ++bright_pixels;
    }
  }
  assert(weight > 0.0F);
  assert(weighted_y / weight > 0.40F);
  assert(bright_pixels >= 10);
  // At 12 o'clock the arrow slides below the empty notch instead of clipping.
  assert(highest_bright_pixel <= 0.78F);
}

void test_love_animation() {
  heart::LoveEffect effect;
  heart::Frame frame{};
  effect.trigger(10.0F);
  assert(effect.active(10.1F));

  effect.render(10.40F, frame);
  std::size_t i_pixels = 0;
  for (const auto& pixel : frame) {
    i_pixels += pixel.r > 20 ? 1U : 0U;
  }
  assert(i_pixels >= 12 && i_pixels < frame.size() / 2);

  effect.render(11.40F, frame);
  assert(std::all_of(frame.begin(), frame.end(), [](const heart::Rgb8& pixel) {
    return pixel.r > 100 && pixel.b > pixel.g;
  }));

  effect.render(12.55F, frame);
  std::size_t u_pixels = 0;
  for (const auto& pixel : frame) {
    u_pixels += pixel.r > 20 ? 1U : 0U;
  }
  assert(u_pixels >= 12 && u_pixels < frame.size() / 2);
  assert(!effect.active(13.36F));
}

void test_pair_protocol() {
  heart::pair::Message sent{};
  sent.sequence = 314;
  heart::pair::Message received{};
  assert(heart::pair::decode_message(
      reinterpret_cast<const std::uint8_t*>(&sent), sizeof(sent), received));
  assert(received.sequence == 314);

  sent.type = heart::pair::MessageType::kHeartbeatSync;
  sent.beat_phase_milliseconds = 412;
  sent.beat_period_milliseconds = 938;
  assert(heart::pair::decode_message(
      reinterpret_cast<const std::uint8_t*>(&sent), sizeof(sent), received));
  assert(received.beat_phase_milliseconds == 412);
  assert(received.beat_period_milliseconds == 938);

  sent.type = static_cast<heart::pair::MessageType>(99);
  assert(!heart::pair::decode_message(
      reinterpret_cast<const std::uint8_t*>(&sent), sizeof(sent), received));
  sent.type = heart::pair::MessageType::kLove;
  sent.magic = 0;
  assert(!heart::pair::decode_message(
      reinterpret_cast<const std::uint8_t*>(&sent), sizeof(sent), received));
}

void test_compass_heading() {
  heart::AccelerationSample acceleration{};
  // Both sensors face B.Cu, so sensor -Z maps to board/front +Z initially.
  acceleration.sensor_z_g = -1.0F;
  acceleration.valid = true;

  heart::MagneticSample north{};
  north.sensor_y_gauss = 0.45F;
  north.sensor_z_gauss = 0.15F;
  north.valid = true;
  heart::CompassEstimator north_compass;
  const heart::CompassReading north_reading =
      north_compass.update(acceleration, north);
  assert(north_reading.valid);
  assert(std::abs(north_reading.heading_degrees) < 0.01F);

  // If magnetic north is to the board's left, the board top faces east.
  heart::MagneticSample east{};
  east.sensor_x_gauss = -0.45F;
  east.sensor_z_gauss = 0.15F;
  east.valid = true;
  heart::CompassEstimator east_compass;
  const heart::CompassReading east_reading =
      east_compass.update(acceleration, east);
  assert(east_reading.valid);
  assert(std::abs(east_reading.heading_degrees - 90.0F) < 0.01F);

  // A new heading is approached instead of jumping there in one frame.
  heart::CompassEstimator filtered_compass;
  filtered_compass.update(acceleration, north);
  const heart::CompassReading filtered_east =
      filtered_compass.update(acceleration, east);
  assert(filtered_east.heading_degrees > 10.0F);
  assert(filtered_east.heading_degrees < 30.0F);
}

void test_target_from_positions() {
  const heart::GeographicPosition san_francisco{37.7749, -122.4194, true};
  const heart::GeographicPosition los_angeles{34.0522, -118.2437, true};
  const heart::TargetState target =
      heart::target_from_positions(san_francisco, los_angeles);
  assert(target.valid);
  assert(target.bearing_degrees > 130.0F && target.bearing_degrees < 145.0F);
  assert(target.distance_meters > 540000.0F && target.distance_meters < 580000.0F);
}

void test_liquid_follows_gravity() {
  heart::LiquidEffect effect;
  const float initial_mass = effect.total_mass();
  const float initial_y = effect.center_of_mass_y();
  for (int frame = 0; frame < 360; ++frame) {
    effect.update(1.0F / 60.0F, 0.0F, -1.0F, 1.0F);
  }
  assert(std::abs(effect.total_mass() - initial_mass) < 0.001F);
  assert(effect.center_of_mass_y() < initial_y - 0.12F);

  heart::Frame settled{};
  heart::Frame splashed{};
  effect.render(settled);
  effect.splash(1.0F, 0.0F, 1.0F);
  assert(effect.kinetic_energy() > 1.0F);
  for (int frame = 0; frame < 8; ++frame) {
    effect.update(1.0F / 60.0F, 0.0F, -1.0F, 1.0F);
  }
  effect.render(splashed);
  std::size_t changed_pixels = 0;
  for (std::size_t index = 0; index < settled.size(); ++index) {
    changed_pixels += settled[index].r != splashed[index].r ? 1U : 0U;
  }
  assert(changed_pixels > 20);
  assert(std::abs(effect.total_mass() - initial_mass) < 0.001F);

  const float left_x = effect.center_of_mass_x();
  for (int frame = 0; frame < 360; ++frame) {
    effect.update(1.0F / 60.0F, 1.0F, 0.0F, 1.0F);
  }
  assert(std::abs(effect.total_mass() - initial_mass) < 0.001F);
  assert(effect.center_of_mass_x() > left_x + 0.12F);

  heart::Frame frame{};
  effect.render(frame);
  bool found_red = false;
  for (const auto& pixel : frame) {
    found_red = found_red || pixel.r > 0;
    assert(pixel.g == 0 && pixel.b == 0);
  }
  assert(found_red);
}

void test_rainbow() {
  heart::RainbowEffect effect;
  heart::RenderContext context{};
  heart::Frame first{};
  heart::Frame later{};
  context.now_seconds = 0.0F;
  effect.render(context, first);
  context.now_seconds = 1.0F;
  effect.render(context, later);

  std::set<std::uint32_t> colors;
  std::size_t changed = 0;
  for (std::size_t index = 0; index < first.size(); ++index) {
    colors.insert(
        (static_cast<std::uint32_t>(first[index].r) << 16U) |
        (static_cast<std::uint32_t>(first[index].g) << 8U) |
        first[index].b);
    changed +=
        first[index].r != later[index].r ||
                first[index].g != later[index].g ||
                first[index].b != later[index].b
            ? 1U
            : 0U;
  }
  assert(colors.size() > 40);
  assert(changed > 120);
}

void test_shake_detector() {
  heart::ShakeDetector detector;
  assert(!detector.update(0.0F, 0.0F, 0.0F, 1.0F).shake);
  assert(!detector.update(0.5F, 0.15F, 0.0F, 0.99F).shake);
  const heart::GestureEvents right_flick =
      detector.update(1.0F, 1.2F, 0.0F, 1.0F);
  assert(right_flick.shake);
  assert(right_flick.impulse_x < -0.5F);
  assert(right_flick.strength >= 0.25F);
  assert(!detector.update(1.1F, -1.2F, 0.0F, 1.0F).shake);
  assert(detector.update(1.7F, -1.2F, 0.0F, 1.0F).shake);
}

void test_button_debounce() {
  heart::DebouncedButton button(0.025F);
  assert(!button.pressed(0.000F, false));
  assert(!button.pressed(0.010F, true));
  assert(!button.pressed(0.020F, false));  // Contact bounce.
  assert(!button.pressed(0.030F, true));
  assert(!button.pressed(0.050F, true));
  assert(button.pressed(0.056F, true));
  assert(!button.pressed(0.070F, false));
  assert(!button.pressed(0.096F, false));  // Releases do not emit presses.
}

void test_button_gestures() {
  heart::ButtonGesture button(0.025F, 0.75F);
  assert(!button.update(0.00F, false).short_press);
  assert(!button.update(0.10F, true).short_press);
  assert(!button.update(0.13F, true).short_press);
  assert(!button.update(0.30F, false).short_press);
  assert(button.update(0.33F, false).short_press);

  assert(!button.update(1.00F, true).long_press);
  assert(!button.update(1.03F, true).long_press);
  const heart::ButtonGestureEvents held = button.update(1.80F, true);
  assert(held.long_press && !held.short_press);
  assert(!button.update(1.90F, false).short_press);
  assert(!button.update(1.93F, false).short_press);
}

void test_imu_axis_mapping() {
  heart::AccelerationSample sample{};
  sample.sensor_x_g = 0.30F;
  sample.sensor_y_g = -0.40F;
  sample.sensor_z_g = 0.866F;
  sample.valid = true;
  const heart::MotionState motion = heart::motion_from_acceleration(sample);
  const float expected_board_x =
      heart::board::kImuBoardXFromSensorX * sample.sensor_x_g +
      heart::board::kImuBoardXFromSensorY * sample.sensor_y_g;
  const float expected_board_y =
      heart::board::kImuBoardYFromSensorX * sample.sensor_x_g +
      heart::board::kImuBoardYFromSensorY * sample.sensor_y_g;
  assert(std::abs(motion.down_x + expected_board_x) < 0.001F);
  assert(std::abs(motion.down_y + expected_board_y) < 0.001F);
  assert(
      std::abs(
          motion.in_plane_gravity_g -
          std::hypot(expected_board_x, expected_board_y)) < 0.001F);
}

}  // namespace

int main() {
  test_generated_map();
  test_power_limiter();
  test_gamma_lookup();
  test_heartbeat();
  test_target_arrow();
  test_love_animation();
  test_pair_protocol();
  test_compass_heading();
  test_target_from_positions();
  test_liquid_follows_gravity();
  test_rainbow();
  test_shake_detector();
  test_button_debounce();
  test_button_gestures();
  test_imu_axis_mapping();
  std::cout << "Heart firmware core tests passed\n";
  return 0;
}
