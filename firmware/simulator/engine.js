(function attachHeartSimulatorEngine(root) {
  "use strict";

  const FIRMWARE_FRAME_RATE_HZ = 60;
  const LED_DATA_RATE_BITS_PER_SECOND = 800000;
  const LED_BITS_PER_PIXEL = 24;
  const LED_RESET_BUDGET_MICROSECONDS = 300;
  const PIXELS_PER_CHAIN = 72;
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const byte = (value) => Math.round(clamp(value, 0, 1) * 255);
  const blackFrame = (pixels) => pixels.map(() => [0, 0, 0]);

  function gaussian(value, center, width) {
    const normalized = (value - center) / width;
    return Math.exp(-0.5 * normalized * normalized);
  }

  function heartbeatFrame(pixels, timeSeconds, beatsPerMinute = 64) {
    const period = 60 / beatsPerMinute;
    const phase = ((timeSeconds % period) + period) % period;
    const envelope = clamp(
      0.98 * gaussian(phase, 0.150, 0.088) +
        0.62 * gaussian(phase, 0.410, 0.120),
      0,
      1,
    );
    return pixels.map((pixel) => {
      const radius = Math.hypot(pixel.x - 0.5, pixel.y - 0.53);
      const centerLift = clamp(1.10 - 0.32 * radius, 0.82, 1);
      const glow = clamp(0.018 + envelope * centerLift, 0, 1);
      return [byte(glow), byte(glow * 0.010), byte(glow * 0.018)];
    });
  }

  function smoothstep(edge0, edge1, value) {
    if (edge0 === edge1) return value < edge0 ? 0 : 1;
    const t = clamp((value - edge0) / (edge1 - edge0), 0, 1);
    return t * t * (3 - 2 * t);
  }

  function softInside(value, halfWidth) {
    return 1 - smoothstep(halfWidth, halfWidth + 0.065, value);
  }

  function softRange(value, low, high, feather) {
    return (
      smoothstep(low - feather, low, value) *
      (1 - smoothstep(high, high + feather, value))
    );
  }

  function arrowFrame(
    pixels,
    timeSeconds,
    targetBearingDegrees,
    headingDegrees,
    valid = true,
  ) {
    if (!valid) {
      const pulse = 0.10 + 0.10 * (0.5 + 0.5 * Math.sin(timeSeconds * 3));
      return pixels.map((pixel) => {
        const dx = pixel.x - 0.5;
        const dy = pixel.y - 0.48;
        return dx * dx + dy * dy < 0.010
          ? [byte(pulse), byte(pulse * 0.16), 0]
          : [0, 0, 0];
      });
    }

    const angle = ((targetBearingDegrees - headingDegrees) * Math.PI) / 180;
    const directionX = Math.sin(angle);
    const directionY = Math.cos(angle);
    const centerX = 0.5;
    // Keep the glyph centered for almost every direction. Only a nearly due
    // north arrow slides down enough that its tip lands below the heart notch.
    const northBias = Math.pow(Math.max(0, directionY), 96);
    const centerY = 0.48 - 0.155 * northBias;
    const tipAlong = 0.39;
    const headLength = 0.20;
    const headStart = tipAlong - headLength;
    const tailAlong = -0.24;

    return pixels.map((pixel) => {
      const dx = pixel.x - centerX;
      const dy = pixel.y - centerY;
      const along = dx * directionX + dy * directionY;
      const across = Math.abs(dx * directionY - dy * directionX);
      const shaft =
        softInside(across, 0.052) *
        softRange(along, tailAlong, headStart + 0.035, 0.050);
      const headProgress = clamp((tipAlong - along) / headLength, 0, 1);
      const headWidth = 0.060 + headProgress * 0.155;
      const head =
        softInside(across, headWidth) *
        softRange(along, headStart, tipAlong, 0.050);
      const intensity = clamp(Math.max(shaft, head), 0, 1);
      return [byte(intensity), byte(intensity * 0.055), byte(intensity * 0.020)];
    });
  }

  function hsvToRgb(hue, saturation, value) {
    const wrappedHue = ((hue % 1) + 1) % 1;
    const sector = wrappedHue * 6;
    const index = Math.floor(sector);
    const fraction = sector - index;
    const p = value * (1 - saturation);
    const q = value * (1 - saturation * fraction);
    const t = value * (1 - saturation * (1 - fraction));
    const colors = [
      [value, t, p],
      [q, value, p],
      [p, value, t],
      [p, q, value],
      [t, p, value],
      [value, p, q],
    ];
    return colors[index % 6].map(byte);
  }

  function rainbowFrame(pixels, timeSeconds) {
    return pixels.map((pixel) => {
      const dx = pixel.x - 0.5;
      const dy = pixel.y - 0.5;
      const radius = Math.hypot(dx, dy);
      const turns = Math.atan2(dy, dx) / (Math.PI * 2);
      const ripple = Math.sin(
        Math.PI * 2 * (radius * 2.2 - timeSeconds * 0.18),
      );
      const hue = turns + 0.85 * radius - timeSeconds * 0.10 + 0.08 * ripple;
      const value =
        0.72 +
        0.28 *
          (0.5 +
            0.5 *
              Math.sin(
                Math.PI * 2 *
                  (1.7 * radius - 0.24 * timeSeconds + 0.35 * turns),
              ));
      return hsvToRgb(hue, 1, value);
    });
  }

  function loveFrame(pixels, elapsedSeconds) {
    const frame = blackFrame(pixels);
    const envelope = (phase) =>
      smoothstep(0, 0.12, phase) * (1 - smoothstep(0.82, 1, phase));
    const color = (intensity, red, green, blue) => [
      byte(intensity * red),
      byte(intensity * green),
      byte(intensity * blue),
    ];
    if (elapsedSeconds < 0 || elapsedSeconds >= 3.35) return frame;

    if (elapsedSeconds < 0.82) {
      const amount = envelope(elapsedSeconds / 0.82);
      const oneLedRow = 0.0769231;
      return pixels.map((pixel) => {
        const dx = Math.abs(pixel.x - 0.5);
        const vertical =
          dx < 0.060 &&
          pixel.y > 0.25 - oneLedRow &&
          pixel.y < 0.72 - oneLedRow;
        const bars =
          dx < 0.225 &&
          (Math.abs(pixel.y - (0.27 - oneLedRow)) < 0.060 ||
            Math.abs(pixel.y - (0.70 - oneLedRow)) < 0.060);
        return vertical || bars ? color(amount, 1, 0.25, 0.58) : [0, 0, 0];
      });
    }

    if (elapsedSeconds < 2.02) {
      const amount = envelope((elapsedSeconds - 0.82) / 1.20);
      const breathe = 0.91 + 0.09 * amount;
      return pixels.map(() => color(amount * breathe, 1, 0.15, 0.65));
    }

    const amount = envelope((elapsedSeconds - 2.02) / 1.33);
    return pixels.map((pixel) => {
      const dx = pixel.x - 0.5;
      let distance = 1;
      if (pixel.y >= 0.34 && pixel.y <= 0.72) {
        distance = Math.min(Math.abs(dx - 0.18), Math.abs(dx + 0.18));
      }
      if (pixel.y <= 0.38) {
        distance = Math.min(
          distance,
          Math.abs(Math.hypot(dx, pixel.y - 0.37) - 0.18),
        );
      }
      const mask = 1 - smoothstep(0.050, 0.105, distance);
      return mask > 0.01
        ? color(amount * mask, 1, 0.30, 0.78)
        : [0, 0, 0];
    });
  }

  class LiquidSimulation {
    constructor(pixels) {
      this.pixels = pixels;
      this.edges = [];
      for (let first = 0; first < pixels.length; first += 1) {
        for (let second = first + 1; second < pixels.length; second += 1) {
          if (
            Math.hypot(
              pixels[second].x - pixels[first].x,
              pixels[second].y - pixels[first].y,
            ) <= 0.106
          ) {
            this.edges.push({ first, second, velocity: 0 });
          }
        }
      }
      this.reset();
    }

    reset() {
      this.mass = this.pixels.map(() => 0);
      this.randomState = 0xa5c31e27;
      let placed = 0;
      while (placed < 52) {
        const index = this.nextRandom() % this.mass.length;
        if (this.mass[index] === 0) {
          this.mass[index] = 1;
          placed += 1;
        }
      }
      for (const edge of this.edges) edge.velocity = 0;
      this.downX = 0;
      this.downY = -1;
      this.splashEnergy = 0;
      this.flowStep = 0;
    }

    nextRandom() {
      let value = this.randomState | 0;
      value ^= value << 13;
      value ^= value >>> 17;
      value ^= value << 5;
      this.randomState = value >>> 0;
      return this.randomState;
    }

    randomSigned() {
      return (this.nextRandom() & 0xffff) / 32767.5 - 1;
    }

    splash(impulseX = 0, impulseY = -1, strength = 1) {
      const clampedStrength = clamp(strength, 0, 1);
      const directionLength = Math.hypot(impulseX, impulseY);
      const directionX = directionLength > 0.02 ? impulseX / directionLength : 0;
      const directionY = directionLength > 0.02 ? impulseY / directionLength : 0;
      for (const edge of this.edges) {
        const first = this.pixels[edge.first];
        const second = this.pixels[edge.second];
        const edgeX = second.x - first.x;
        const edgeY = second.y - first.y;
        const edgeLength = Math.hypot(edgeX, edgeY);
        const directed =
          edgeLength > 0
            ? (edgeX * directionX + edgeY * directionY) / edgeLength
            : 0;
        const turbulence = this.randomSigned() * 0.30;
        if (this.mass[edge.first] + this.mass[edge.second] > 0.02) {
          edge.velocity = clamp(
            edge.velocity +
              (directed + turbulence) * 3.6 * clampedStrength,
            -4.2,
            4.2,
          );
        }
      }
      this.splashEnergy = clampedStrength;
    }

    update(deltaSeconds, downX, downY, gravityStrength = 1) {
      const dt = clamp(deltaSeconds, 0, 0.05);
      const directionLength = Math.hypot(downX, downY);
      if (directionLength > 0.04) {
        const targetX = downX / directionLength;
        const targetY = downY / directionLength;
        const blend = 1 - Math.exp(-8 * dt);
        this.downX += (targetX - this.downX) * blend;
        this.downY += (targetY - this.downY) * blend;
        const smoothedLength = Math.hypot(this.downX, this.downY);
        this.downX /= smoothedLength;
        this.downY /= smoothedLength;
      }
      const strength = clamp(gravityStrength, 0, 1);
      this.splashEnergy *= Math.exp(-5 * dt);
      const substeps = Math.max(1, Math.min(6, Math.ceil(dt * 120)));
      const stepSeconds = substeps > 0 ? dt / substeps : 0;
      for (let step = 0; step < substeps; step += 1) {
        this.simulateStep(stepSeconds, strength);
      }
    }

    simulateStep(dt, gravityStrength) {
      if (dt <= 0) return;
      const damping = Math.exp(-1.5 * dt);
      for (const edge of this.edges) {
        const first = edge.first;
        const second = edge.second;
        if (this.mass[first] + this.mass[second] < 0.001) {
          edge.velocity *= damping;
          continue;
        }
        const a = this.pixels[first];
        const b = this.pixels[second];
        const depthA = a.x * this.downX + a.y * this.downY;
        const depthB = b.x * this.downX + b.y * this.downY;
        const headA = this.mass[first] * 1.15 - 2.8 * gravityStrength * depthA;
        const headB = this.mass[second] * 1.15 - 2.8 * gravityStrength * depthB;
        edge.velocity = clamp(
          (edge.velocity + (headA - headB) * 56 * dt) * damping,
          -4.2,
          4.2,
        );
      }

      const start = this.flowStep % Math.max(1, this.edges.length);
      for (let offset = 0; offset < this.edges.length; offset += 1) {
        const edge = this.edges[(start + offset) % this.edges.length];
        const source = edge.velocity >= 0 ? edge.first : edge.second;
        const destination = edge.velocity >= 0 ? edge.second : edge.first;
        const requested = Math.abs(edge.velocity) * dt;
        const available = Math.min(this.mass[source], 1 - this.mass[destination]);
        const transferred = Math.min(requested, Math.max(0, available));
        this.mass[source] -= transferred;
        this.mass[destination] += transferred;
        if (transferred + 0.00001 < requested) {
          edge.velocity *= -0.12;
        }
      }
      this.flowStep += 1;
    }

    frame() {
      return this.mass.map((mass, index) => {
        const sparkle = 0.72 + (0.28 * ((index * 73) % 19)) / 18;
        const coverage = clamp(mass * 1.30, 0, 1);
        const breakup = ((index * 73) % 31) / 30;
        const surfaceGate = smoothstep(breakup - 0.20, breakup + 0.20, coverage);
        const intensity = clamp(
          Math.sqrt(coverage) * (0.45 + 0.55 * surfaceGate) *
            (1 + 0.24 * Math.sqrt(this.splashEnergy) * sparkle),
          0,
          1,
        );
        return [byte(intensity), 0, 0];
      });
    }

    totalMass() {
      return this.mass.reduce((total, mass) => total + mass, 0);
    }

    kineticEnergy() {
      return this.edges.reduce(
        (energy, edge) => energy + edge.velocity * edge.velocity,
        0,
      );
    }

    centerOfMass() {
      const total = this.totalMass();
      return this.mass.reduce(
        (center, mass, index) => ({
          x: center.x + (this.pixels[index].x * mass) / total,
          y: center.y + (this.pixels[index].y * mass) / total,
        }),
        { x: 0, y: 0 },
      );
    }
  }

  function processFrame(frame, brightness = 1, gammaEnabled = true) {
    const scale = clamp(brightness, 0, 1);
    return frame.map((color) =>
      color.map((channel) => {
        const normalized = (channel / 255) * scale;
        return byte(gammaEnabled ? normalized ** 2.2 : normalized);
      }),
    );
  }

  const api = Object.freeze({
    FIRMWARE_FRAME_RATE_HZ,
    LED_BITS_PER_PIXEL,
    LED_DATA_RATE_BITS_PER_SECOND,
    LED_RESET_BUDGET_MICROSECONDS,
    PIXELS_PER_CHAIN,
    arrowFrame,
    blackFrame,
    heartbeatFrame,
    loveFrame,
    LiquidSimulation,
    processFrame,
    rainbowFrame,
  });
  root.HeartSimEngine = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(globalThis);
