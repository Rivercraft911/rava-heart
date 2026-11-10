#pragma once

#include <algorithm>
#include <cmath>

#include "heart_types.hpp"

namespace heart {

class HeartbeatEffect {
 public:
  explicit HeartbeatEffect(float beats_per_minute = 64.0F)
      : beats_per_minute_(beats_per_minute) {}

  void trigger_extra_beat(float now_seconds) { extra_beat_start_ = now_seconds; }

  [[nodiscard]] float period_seconds() const {
    return 60.0F / beats_per_minute_;
  }

  [[nodiscard]] float phase_seconds(float now_seconds) const {
    return positive_mod(now_seconds + phase_offset_seconds_, period_seconds());
  }

  // Lock the repeating beat to a nearby heart without making later radio
  // timing jitter visible. The first beacon snaps into phase; subsequent
  // beacons gently remove only a bounded fraction of the phase error.
  void synchronize(float now_seconds, float remote_phase_seconds) {
    const float period = period_seconds();
    const float local_phase = phase_seconds(now_seconds);
    const float error = positive_mod(
                            remote_phase_seconds - local_phase + period * 0.5F,
                            period) -
                        period * 0.5F;
    if (!has_external_sync_) {
      phase_offset_seconds_ += error;
      has_external_sync_ = true;
      return;
    }
    phase_offset_seconds_ +=
        std::clamp(error * 0.35F, -0.045F, 0.045F);
  }

  void render(const RenderContext& context, Frame& frame) const {
    frame.fill({});
    const float normal_phase = phase_seconds(context.now_seconds);
    float envelope = beat_envelope(normal_phase);

    const float extra_phase = context.now_seconds - extra_beat_start_;
    if (extra_phase >= 0.0F && extra_phase < 0.75F) {
      envelope = std::max(envelope, beat_envelope(extra_phase));
    }

    for (std::size_t index = 0; index < frame.size(); ++index) {
      const auto& location = generated::kPixels[index];
      const float dx = location.x - 0.5F;
      const float dy = location.y - 0.53F;
      const float radius = std::sqrt(dx * dx + dy * dy);
      const float center_lift = std::clamp(1.10F - 0.32F * radius, 0.82F, 1.0F);
      const float glow = std::clamp(0.018F + envelope * center_lift, 0.0F, 1.0F);
      frame[index] = {
          to_channel(glow),
          to_channel(glow * 0.010F),
          to_channel(glow * 0.018F),
      };
    }
  }

 private:
  static float positive_mod(float value, float divisor) {
    const float result = std::fmod(value, divisor);
    return result < 0.0F ? result + divisor : result;
  }

  static float gaussian(float x, float center, float width) {
    const float normalized = (x - center) / width;
    return std::exp(-0.5F * normalized * normalized);
  }

  static float beat_envelope(float phase_seconds) {
    // A deliberately relaxed "lub-dub": the beat rate stays natural while
    // each pulse remains visible long enough to read across the sparse matrix.
    return std::clamp(
        0.98F * gaussian(phase_seconds, 0.150F, 0.088F) +
            0.62F * gaussian(phase_seconds, 0.410F, 0.120F),
        0.0F,
        1.0F);
  }

  static std::uint8_t to_channel(float value) {
    return static_cast<std::uint8_t>(
        std::lround(std::clamp(value, 0.0F, 1.0F) * 255.0F));
  }

  float beats_per_minute_;
  float extra_beat_start_ = -10.0F;
  float phase_offset_seconds_ = 0.0F;
  bool has_external_sync_ = false;
};

}  // namespace heart
