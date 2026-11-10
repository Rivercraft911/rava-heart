#pragma once

namespace heart {

struct ButtonGestureEvents {
  bool short_press = false;
  bool long_press = false;
};

class DebouncedButton {
 public:
  explicit DebouncedButton(float debounce_seconds = 0.025F)
      : debounce_seconds_(debounce_seconds) {}

  bool pressed(float now_seconds, bool raw_pressed) {
    if (raw_pressed != candidate_pressed_) {
      candidate_pressed_ = raw_pressed;
      candidate_since_seconds_ = now_seconds;
    }

    if (candidate_pressed_ != stable_pressed_ &&
        now_seconds - candidate_since_seconds_ >= debounce_seconds_) {
      stable_pressed_ = candidate_pressed_;
      return stable_pressed_;
    }
    return false;
  }

 private:
  float debounce_seconds_;
  float candidate_since_seconds_ = 0.0F;
  bool candidate_pressed_ = false;
  bool stable_pressed_ = false;
};

// Delays the short-press event until release so the same physical button can
// cleanly support both mode changes and a hold gesture.
class ButtonGesture {
 public:
  explicit ButtonGesture(
      float debounce_seconds = 0.025F, float hold_seconds = 0.75F)
      : debounce_seconds_(debounce_seconds), hold_seconds_(hold_seconds) {}

  ButtonGestureEvents update(float now_seconds, bool raw_pressed) {
    ButtonGestureEvents events{};
    if (raw_pressed != candidate_pressed_) {
      candidate_pressed_ = raw_pressed;
      candidate_since_seconds_ = now_seconds;
    }

    if (candidate_pressed_ != stable_pressed_ &&
        now_seconds - candidate_since_seconds_ >= debounce_seconds_) {
      stable_pressed_ = candidate_pressed_;
      if (stable_pressed_) {
        pressed_since_seconds_ = now_seconds;
        long_press_emitted_ = false;
      } else if (!long_press_emitted_) {
        events.short_press = true;
      }
    }

    if (stable_pressed_ && !long_press_emitted_ &&
        now_seconds - pressed_since_seconds_ >= hold_seconds_) {
      long_press_emitted_ = true;
      events.long_press = true;
    }
    return events;
  }

 private:
  float debounce_seconds_;
  float hold_seconds_;
  float candidate_since_seconds_ = 0.0F;
  float pressed_since_seconds_ = 0.0F;
  bool candidate_pressed_ = false;
  bool stable_pressed_ = false;
  bool long_press_emitted_ = false;
};

}  // namespace heart
