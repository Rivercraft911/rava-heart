# Rava Heart firmware

This is the ESP32-C3 firmware foundation for the 144-pixel HeartArray PCB. It
is intentionally driven by the ordered KiCad board rather than assuming that
LED reference numbers equal their transmission order.

## Current V0

- Two 72-pixel WS2812B-MINI-V6 outputs at 800 kbit/s using Espressif's RMT
  `led_strip` driver.
- Generated physical/electrical LED map with normalized heart coordinates.
- Relaxed double-pulse heartbeat, inertial gravity-driven red liquid, flowing
  rainbow, and Find Heart compass-arrow modes.
- Frame-wide brightness, gamma correction, and a 2.5 A estimated LED budget.
- Debounced S2 mode switch and three brightness levels on S3 at runtime.
- Continuous LSM6DSOX acceleration and tilt-compensated LIS3MDL heading.
- Shake creates an extra heartbeat or injects directional IMU momentum into the
  liquid without teleporting its mass.
- Hold S2 for 0.75 seconds to play I-♥-U locally and broadcast the same overlay
  to the other heart over ESP-NOW.
- Nearby hearts automatically share one heartbeat phase, using filtered radio
  strength with hysteresis for presence and the lower MAC address as the stable
  clock leader.
- Host tests for mapping, rendering, direction math, gestures, and power limiting.

The target build is ESP-IDF 5.4 or newer with `espressif/led_strip` 3.x. The
ESP32-C3 uses RMT without DMA.

Each 72-pixel chain needs 2.16 ms for its 1,728 data bits, plus the specified
reset interval of more than 280 us. Even treating both outputs as sequential
gives about 4.9 ms of wire time, comfortably inside the 16.67 ms frame period.
The RMT 10 MHz setting is its timing resolution; the LED protocol itself remains
800 kbit/s. The simulator advances its firmware effects on this same fixed
60 Hz cadence. The LEDs' internal PWM scan is 2 kHz and is separate from frame
transmission.

## Ordered-board pin map

| Function | ESP32-C3 GPIO | Notes |
|---|---:|---|
| LED chain 0 | 5 | U4/R15, first transmitted pixel D13 |
| LED chain 1 | 4 | U4/R14, first transmitted pixel D85 |
| I2C SCL | 6 | LIS3MDL and LSM6DSOX |
| I2C SDA | 7 | LIS3MDL and LSM6DSOX |
| Magnetometer DRDY | 10 | LIS3MDL DRDY |
| IMU INT1 | 1 | LSM6DSOX INT1 |
| IMU INT2 | 3 | LSM6DSOX INT2 |
| Main mode button S2 | 9 | Front/bottom; active low; also the hardware BOOT strap |
| Brightness button S3 | 0 | Rear button labeled BOOT; active low |
| USB D- / D+ | 18 / 19 | Built-in USB Serial/JTAG |

S1 is connected to EN and is a hardware reset button, not a software input.

## Current controls

- S2 short press and release after boot: cycle Heartbeat / Gravity Red / Flowing Rainbow / Find Heart.
- S2 hold after boot: play and send the I-♥-U message without changing the current mode.
- S3 short press: cycle 28% / 55% / 90% brightness.
- Shake: extra heartbeat in Heartbeat; directional liquid impulse in Gravity Red.

S2 is also the ESP32-C3 boot-strap button, so do not hold it during reset or
power-up. Its runtime mode-button behavior begins after the firmware boots.

Gravity Red conserves a fixed amount of red "liquid" in a hydraulic network
built from the actual PCB LED-neighbor graph. Local edge velocity, pressure,
damping, gravity head, and reflected flow retain enough momentum to slosh when
the heart rotates. Tilting changes projected gravity; when the board lies flat,
in-plane gravity approaches zero while existing motion decays naturally.

The LSM6DSOX and LIS3MDL are on B.Cu, so their axis orientations must be
confirmed on the first board. Axis corrections are isolated in
`main/board_config.hpp`.

## Target-arrow data contract

Find Heart consumes only:

```text
target bearing + target distance + local calibrated heading
```

The provider can later be swapped without changing rendering:

- Phone GPS over BLE for actual person-to-person bearing outdoors.
- ESP-NOW for nearby heart messages and synchronized effects.
- A test console command while developing without a phone app.

BLE RSSI may be used for warmer/colder proximity but cannot provide bearing.
The compass determines which way this PCB is facing; it cannot determine where
the other heart is. `TargetProvider` therefore accepts either a ready-made
bearing or two phone/peer geographic positions. Until that transport is wired,
the hardware mode deliberately uses magnetic north as its bench-test target.

The LIS3MDL heading is usable immediately and accumulates a figure-eight
hard/soft-iron calibration while running. Persisting that calibration is a
post-bring-up step because LED-current interference must be measured first.

## Paired-heart link

The first-board link uses ESP-NOW broadcast on Wi-Fi channel 6. A long press is
sent three times, 140 ms apart, and repeated packets are de-duplicated by their
sequence number. Both hearts also send a heartbeat-phase beacon every 450 ms.
Filtered RSSI enters the nearby state at -72 dBm, leaves at -80 dBm, and times
out after 2.5 seconds; the hysteresis prevents edge-of-range chatter. The lower
MAC address is the deterministic beat-clock leader, while the other heart
latency-compensates each beacon and gently corrects residual phase error. Both
hearts must run this firmware and be on the same channel. This zero-configuration
broadcast is group-filtered but not encrypted; replace it with provisioned peer
MAC addresses and encrypted unicast before treating the pairing as private.

## Browser LED lab

Open `simulator/index.html` directly. It uses the exact generated LED positions,
electrical addresses, and PCB `Edge.Cuts`; previews all four firmware modes;
and samples uploaded images or animated GIFs onto the matrix. Its current-frame
export is ordered exactly like the two LED buses.

For reproducible offline conversion of every image/GIF frame:

```sh
python3 firmware/tools/convert_media.py animation.gif \
  --output firmware/generated/animation.json
```

See `simulator/README.md` for controls and tests.

## Development gates

### Before boards arrive

1. Define compass calibration storage after measuring LED magnetic interference.
2. Provision peer MAC addresses/encryption and extend ESP-NOW with target data.

### First board power-up

1. Inspect 5 V and 3.3 V with LEDs dark.
2. Flash over native USB and confirm both sensor identity logs.
3. Run one dim red pixel through each chain and confirm physical map order.
4. Verify S3 and runtime S2 events.
5. Ramp red, rainbow, then white while checking voltage and eFuse behavior.
6. Compare measured USB current with the software estimator and tune the 12 mA
   per-channel model.
7. Collect magnetometer data with LEDs off, red, rainbow, and white before
   deciding whether compass-mode brightness needs special handling.

### Feature milestones

1. **Heartbeat:** tune pulse timing and shake burst on hardware.
2. **Motion:** validate IMU axes and tune liquid feel on hardware.
3. **Direction:** compass calibration and test-controlled target arrow.
4. **Pair:** provision encrypted ESP-NOW peers (heartbeat synchronization works).
5. **Phone:** BLE setup, location-derived bearing, and optional internet relay.

## Regenerate the PCB-derived map

Run this after any LED placement or connectivity change:

```sh
python3 firmware/tools/generate_pixel_map.py
```

It rewrites:

- `firmware/main/generated/pixel_map.hpp`
- `firmware/generated/pixel_map.json`
- `firmware/simulator/generated/pixel-map.js`

The generator fails unless it discovers exactly two complete 72-pixel chains.

## Host tests

These tests do not require ESP-IDF:

```sh
cmake -S firmware/host_tests -B /tmp/rava-heart-host-tests
cmake --build /tmp/rava-heart-host-tests
/tmp/rava-heart-host-tests/heart_core_tests
```

## ESP-IDF build

After installing and exporting ESP-IDF:

```sh
cd firmware
idf.py set-target esp32c3
idf.py build
idf.py -p /dev/cu.usbmodemPORT flash monitor
```

For the first recovery flash, hold S2/BOOT, press and release S1/RESET, then
release S2. Normal USB Serial/JTAG flashing should reset automatically after a
working firmware has been installed.
