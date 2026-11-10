#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>

#include "heart_types.hpp"

namespace heart {

// A small hydraulic network on the real LED layout. Each neighboring LED pair
// is a channel with inertial flow; cell mass supplies pressure and board tilt
// supplies gravitational head. The model conserves red "water" while retaining
// enough momentum to slosh when the heart rotates.
class LiquidEffect {
 public:
  static_assert(generated::kPixelCount <= 256);

  LiquidEffect() {
    build_edges();
    reset();
  }

  void reset() {
    mass_.fill(0.0F);
    for (auto& edge : edges_) {
      edge.velocity = 0.0F;
    }
    random_state_ = 0xA5C31E27U;
    std::size_t placed = 0;
    while (placed < kFillPixelCount) {
      const std::size_t index = next_random() % mass_.size();
      if (mass_[index] == 0.0F) {
        mass_[index] = 1.0F;
        ++placed;
      }
    }
    down_x_ = 0.0F;
    down_y_ = -1.0F;
    splash_energy_ = 0.0F;
    flow_step_ = 0;
  }

  void update(
      float delta_seconds,
      float down_x,
      float down_y,
      float in_plane_gravity_g) {
    const float dt = std::clamp(delta_seconds, 0.0F, 0.05F);
    const float direction_length = std::hypot(down_x, down_y);
    if (direction_length > 0.04F) {
      const float target_x = down_x / direction_length;
      const float target_y = down_y / direction_length;
      const float blend = 1.0F - std::exp(-8.0F * dt);
      down_x_ += (target_x - down_x_) * blend;
      down_y_ += (target_y - down_y_) * blend;
      const float smoothed_length = std::hypot(down_x_, down_y_);
      if (smoothed_length > 0.001F) {
        down_x_ /= smoothed_length;
        down_y_ /= smoothed_length;
      }
    }

    splash_energy_ *= std::exp(-5.0F * dt);

    const float gravity_strength = std::clamp(in_plane_gravity_g, 0.0F, 1.0F);
    const int substeps = std::max(1, std::min(6, static_cast<int>(
        std::ceil(dt * kSimulationRateHz))));
    const float step_seconds = dt / static_cast<float>(substeps);
    for (int step = 0; step < substeps; ++step) {
      simulate_step(step_seconds, gravity_strength);
    }
  }

  void splash(float impulse_x, float impulse_y, float strength) {
    const float clamped_strength = std::clamp(strength, 0.0F, 1.0F);
    const float direction_length = std::hypot(impulse_x, impulse_y);
    const float direction_x =
        direction_length > 0.02F ? impulse_x / direction_length : 0.0F;
    const float direction_y =
        direction_length > 0.02F ? impulse_y / direction_length : 0.0F;

    // Shake momentum is projected onto every local channel. A small turbulent
    // term breaks symmetry, but the measured IMU impulse remains dominant.
    for (std::size_t index = 0; index < edge_count_; ++index) {
      auto& edge = edges_[index];
      const auto& first = generated::kPixels[edge.first];
      const auto& second = generated::kPixels[edge.second];
      const float edge_x = second.x - first.x;
      const float edge_y = second.y - first.y;
      const float edge_length = std::hypot(edge_x, edge_y);
      const float directed = edge_length > 0.0F
          ? (edge_x * direction_x + edge_y * direction_y) / edge_length
          : 0.0F;
      const float turbulence = random_signed() * 0.30F;
      if (mass_[edge.first] + mass_[edge.second] > 0.02F) {
        edge.velocity = std::clamp(
            edge.velocity +
                (directed + turbulence) * 3.6F * clamped_strength,
            -kMaximumFlowPerSecond,
            kMaximumFlowPerSecond);
      }
    }
    splash_energy_ = clamped_strength;
  }

  void render(Frame& frame) const {
    for (std::size_t index = 0; index < frame.size(); ++index) {
      const float sparkle =
          0.72F + 0.28F * static_cast<float>((index * 73U) % 19U) / 18.0F;
      const float coverage = std::clamp(mass_[index] * 1.30F, 0.0F, 1.0F);
      const float breakup = static_cast<float>(
          (index * 73U) % 31U) / 30.0F;
      const float surface_gate =
          smoothstep(breakup - 0.20F, breakup + 0.20F, coverage);
      const float intensity = std::clamp(
          std::sqrt(coverage) * (0.45F + 0.55F * surface_gate) *
              (1.0F + 0.24F * std::sqrt(splash_energy_) * sparkle),
          0.0F,
          1.0F);
      frame[index] = {to_channel(intensity), 0, 0};
    }
  }

  [[nodiscard]] float total_mass() const {
    float total = 0.0F;
    for (float mass : mass_) {
      total += mass;
    }
    return total;
  }

  [[nodiscard]] float kinetic_energy() const {
    float energy = 0.0F;
    for (std::size_t index = 0; index < edge_count_; ++index) {
      energy += edges_[index].velocity * edges_[index].velocity;
    }
    return energy;
  }

  [[nodiscard]] float center_of_mass_x() const { return center_of_mass(true); }
  [[nodiscard]] float center_of_mass_y() const { return center_of_mass(false); }

 private:
  static constexpr std::size_t kFillPixelCount = 52;
  static constexpr float kNeighborRadius = 0.106F;
  static constexpr std::size_t kMaxEdges = generated::kPixelCount * 5;
  static constexpr float kSimulationRateHz = 120.0F;
  static constexpr float kCellCapacity = 1.0F;
  static constexpr float kPressureScale = 1.15F;
  static constexpr float kGravityHeadScale = 2.8F;
  static constexpr float kFlowAcceleration = 56.0F;
  static constexpr float kFlowDamping = 1.5F;
  static constexpr float kMaximumFlowPerSecond = 4.2F;

  struct FlowEdge {
    std::uint8_t first = 0;
    std::uint8_t second = 0;
    float velocity = 0.0F;  // Positive transfers first -> second.
  };

  void build_edges() {
    edge_count_ = 0;
    for (std::size_t first = 0; first < generated::kPixelCount; ++first) {
      const auto& a = generated::kPixels[first];
      for (std::size_t second = first + 1;
           second < generated::kPixelCount;
           ++second) {
        const auto& b = generated::kPixels[second];
        if (std::hypot(b.x - a.x, b.y - a.y) <= kNeighborRadius &&
            edge_count_ < edges_.size()) {
          edges_[edge_count_++] = {
              static_cast<std::uint8_t>(first),
              static_cast<std::uint8_t>(second),
              0.0F,
          };
        }
      }
    }
  }

  void simulate_step(float dt, float gravity_strength) {
    if (dt <= 0.0F) {
      return;
    }
    const float damping = std::exp(-kFlowDamping * dt);
    for (std::size_t edge_index = 0; edge_index < edge_count_; ++edge_index) {
      auto& edge = edges_[edge_index];
      const std::size_t first = edge.first;
      const std::size_t second = edge.second;
      if (mass_[first] + mass_[second] < 0.001F) {
        edge.velocity *= damping;
        continue;
      }

      const auto& a = generated::kPixels[first];
      const auto& b = generated::kPixels[second];
      const float depth_a = a.x * down_x_ + a.y * down_y_;
      const float depth_b = b.x * down_x_ + b.y * down_y_;
      const float head_a =
          kPressureScale * mass_[first] -
          kGravityHeadScale * gravity_strength * depth_a;
      const float head_b =
          kPressureScale * mass_[second] -
          kGravityHeadScale * gravity_strength * depth_b;
      edge.velocity += (head_a - head_b) * kFlowAcceleration * dt;
      edge.velocity = std::clamp(
          edge.velocity * damping,
          -kMaximumFlowPerSecond,
          kMaximumFlowPerSecond);
    }

    // Applying transfers in a rotating order avoids a permanent geometry bias.
    // Every transfer subtracts and adds the exact same amount.
    const std::size_t start = flow_step_ % std::max<std::size_t>(1, edge_count_);
    for (std::size_t offset = 0; offset < edge_count_; ++offset) {
      auto& edge = edges_[(start + offset) % edge_count_];
      const std::size_t source = edge.velocity >= 0.0F ? edge.first : edge.second;
      const std::size_t destination =
          edge.velocity >= 0.0F ? edge.second : edge.first;
      const float requested = std::abs(edge.velocity) * dt;
      const float available = std::min(
          mass_[source], kCellCapacity - mass_[destination]);
      const float transferred = std::min(requested, std::max(0.0F, available));
      mass_[source] -= transferred;
      mass_[destination] += transferred;
      if (transferred + 0.00001F < requested) {
        // A full/empty cell acts like a soft wall. Kill most normal velocity,
        // but keep a small reflected impulse so the surface can slosh.
        edge.velocity *= -0.12F;
      }
    }
    ++flow_step_;
  }

  std::uint32_t next_random() {
    random_state_ ^= random_state_ << 13U;
    random_state_ ^= random_state_ >> 17U;
    random_state_ ^= random_state_ << 5U;
    return random_state_;
  }

  float random_signed() {
    return static_cast<float>(next_random() & 0xFFFFU) / 32767.5F - 1.0F;
  }

  float center_of_mass(bool x_axis) const {
    const float total = total_mass();
    if (total <= 0.0F) {
      return 0.0F;
    }
    float weighted = 0.0F;
    for (std::size_t index = 0; index < mass_.size(); ++index) {
      const float coordinate =
          x_axis ? generated::kPixels[index].x : generated::kPixels[index].y;
      weighted += coordinate * mass_[index];
    }
    return weighted / total;
  }

  static std::uint8_t to_channel(float value) {
    return static_cast<std::uint8_t>(
        std::lround(std::clamp(value, 0.0F, 1.0F) * 255.0F));
  }

  static float smoothstep(float low, float high, float value) {
    const float t = std::clamp((value - low) / (high - low), 0.0F, 1.0F);
    return t * t * (3.0F - 2.0F * t);
  }

  std::array<float, generated::kPixelCount> mass_{};
  std::array<FlowEdge, kMaxEdges> edges_{};
  std::size_t edge_count_ = 0;
  std::size_t flow_step_ = 0;
  float down_x_ = 0.0F;
  float down_y_ = -1.0F;
  float splash_energy_ = 0.0F;
  std::uint32_t random_state_ = 0xA5C31E27U;
};

}  // namespace heart
