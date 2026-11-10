(function runHeartSimulator() {
  "use strict";

  const pixels = globalThis.HEART_PIXEL_MAP;
  const outline = globalThis.HEART_BOARD_OUTLINE;
  const engine = globalThis.HeartSimEngine;
  if (
    !Array.isArray(pixels) ||
    pixels.length !== 144 ||
    !Array.isArray(outline) ||
    outline.length < 3 ||
    !engine
  ) {
    throw new Error("Generated heart pixel map or simulator engine is missing");
  }

  const root = document.getElementById("heart-simulator");
  const canvas = document.getElementById("heart-canvas");
  const context = canvas.getContext("2d");
  const detail = document.getElementById("pixel-detail");
  const modeSelect = document.getElementById("mode");
  const playButton = document.getElementById("play");
  const brightness = document.getElementById("brightness");
  const gamma = document.getElementById("gamma");
  const addresses = document.getElementById("addresses");
  const ledSize = document.getElementById("led-size");
  const bpm = document.getElementById("bpm");
  const gravityPad = document.getElementById("gravity-pad");
  const gravityKnob = document.getElementById("gravity-knob");
  const gravityVectorLine = document.getElementById("gravity-vector-line");
  const bearing = document.getElementById("bearing");
  const heading = document.getElementById("heading");
  const arrowValid = document.getElementById("arrow-valid");
  const mediaFile = document.getElementById("media-file");
  const mediaFit = document.getElementById("media-fit");
  const mediaScale = document.getElementById("media-scale");
  const mediaX = document.getElementById("media-x");
  const mediaY = document.getElementById("media-y");

  const bounds = outline.reduce(
    (result, pixel) => ({
      minX: Math.min(result.minX, pixel.xMm),
      maxX: Math.max(result.maxX, pixel.xMm),
      minY: Math.min(result.minY, pixel.yMm),
      maxY: Math.max(result.maxY, pixel.yMm),
    }),
    { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity },
  );
  bounds.width = bounds.maxX - bounds.minX;
  bounds.height = bounds.maxY - bounds.minY;

  const mediaCanvas = document.createElement("canvas");
  mediaCanvas.width = 600;
  mediaCanvas.height = Math.round(600 * (bounds.height / bounds.width));
  const mediaContext = mediaCanvas.getContext("2d", { willReadFrequently: true });
  const mediaImage = new Image();
  let mediaUrl = "";
  let mediaReady = false;
  let playing = true;
  let elapsedSeconds = 0;
  let previousTimestamp = performance.now();
  let firmwareFrameAccumulator = 0;
  let screenPixels = [];
  let currentFrame = engine.blackFrame(pixels);
  let gravityVector = { x: 0, y: -1 };
  let loveStartSeconds = 0;
  const liquid = new engine.LiquidSimulation(pixels);

  function setOutput(id, value) {
    document.getElementById(id).value = value;
  }

  function cardinal(degrees) {
    const names = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
    return names[Math.round(Number(degrees) / 45) % names.length];
  }

  function updateLabels() {
    setOutput("brightness-value", `${brightness.value}%`);
    setOutput("size-value", `${ledSize.value}%`);
    setOutput("bpm-value", `${bpm.value} BPM`);
    const signed = (value) => `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}`;
    setOutput(
      "gravity-vector-value",
      `X ${signed(gravityVector.x)} · Y ${signed(gravityVector.y)} g`,
    );
    setOutput("bearing-value", `${bearing.value}° ${cardinal(bearing.value)}`);
    setOutput("heading-value", `${heading.value}° ${cardinal(heading.value)}`);
    setOutput("media-scale-value", `${mediaScale.value}%`);
    setOutput("media-x-value", `${mediaX.value}%`);
    setOutput("media-y-value", `${mediaY.value}%`);
  }

  function updateGravityPad() {
    const xPercent = 50 + gravityVector.x * 50;
    const yPercent = 50 - gravityVector.y * 50;
    gravityKnob.style.left = `${xPercent}%`;
    gravityKnob.style.top = `${yPercent}%`;
    const magnitude = Math.hypot(gravityVector.x, gravityVector.y);
    const screenAngle = Math.atan2(-gravityVector.y, gravityVector.x);
    gravityVectorLine.style.width = `${magnitude * 50}%`;
    gravityVectorLine.style.transform = `rotate(${screenAngle}rad)`;
    gravityPad.setAttribute(
      "aria-valuetext",
      `X ${gravityVector.x.toFixed(2)}, Y ${gravityVector.y.toFixed(2)} g`,
    );
    updateLabels();
  }

  function setGravityFromPointer(event) {
    const rectangle = gravityPad.getBoundingClientRect();
    let x = (event.clientX - (rectangle.left + rectangle.width * 0.5)) /
      (rectangle.width * 0.5);
    let y = -(
      (event.clientY - (rectangle.top + rectangle.height * 0.5)) /
      (rectangle.height * 0.5)
    );
    const magnitude = Math.hypot(x, y);
    if (magnitude > 1) {
      x /= magnitude;
      y /= magnitude;
    }
    gravityVector = { x, y };
    updateGravityPad();
  }

  function updateModePanels() {
    for (const panel of root.querySelectorAll(".mode-panel")) {
      panel.hidden = panel.dataset.mode !== modeSelect.value;
    }
  }

  function resizeCanvas() {
    const rectangle = canvas.getBoundingClientRect();
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.max(1, Math.round(rectangle.width * pixelRatio));
    canvas.height = Math.max(1, Math.round(rectangle.height * pixelRatio));
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  }

  function layoutForCanvas() {
    const rectangle = canvas.getBoundingClientRect();
    const margin = Math.max(42, Math.min(rectangle.width, rectangle.height) * 0.075);
    const boardWidth = bounds.width;
    const boardHeight = bounds.height;
    const scale = Math.min(
      (rectangle.width - margin * 2) / boardWidth,
      (rectangle.height - margin * 2) / boardHeight,
    );
    const left = (rectangle.width - boardWidth * scale) * 0.5;
    const top = (rectangle.height - boardHeight * scale) * 0.5;
    return {
      scale,
      left,
      top,
      mmToScreen(xMm, yMm) {
        return {
          x: left + (xMm - bounds.minX) * scale,
          y: top + (yMm - bounds.minY) * scale,
        };
      },
    };
  }

  function drawBoard(layout) {
    context.beginPath();
    outline.forEach((point, index) => {
      const screen = layout.mmToScreen(point.xMm, point.yMm);
      if (index === 0) context.moveTo(screen.x, screen.y);
      else context.lineTo(screen.x, screen.y);
    });
    context.closePath();
    context.fillStyle = "#241923";
    context.fill();
    context.lineWidth = Math.max(1.5, layout.scale * 0.45);
    context.strokeStyle = "rgba(255, 111, 158, 0.34)";
    context.stroke();
  }

  function sampleMediaFrame() {
    if (!mediaReady) return engine.blackFrame(pixels);
    const width = mediaCanvas.width;
    const height = mediaCanvas.height;
    mediaContext.fillStyle = "#000";
    mediaContext.fillRect(0, 0, width, height);

    const naturalWidth = mediaImage.naturalWidth || 1;
    const naturalHeight = mediaImage.naturalHeight || 1;
    let drawWidth = width;
    let drawHeight = height;
    if (mediaFit.value !== "stretch") {
      const baseScale = mediaFit.value === "contain"
        ? Math.min(width / naturalWidth, height / naturalHeight)
        : Math.max(width / naturalWidth, height / naturalHeight);
      drawWidth = naturalWidth * baseScale;
      drawHeight = naturalHeight * baseScale;
    }
    const userScale = Number(mediaScale.value) / 100;
    drawWidth *= userScale;
    drawHeight *= userScale;
    const drawX =
      (width - drawWidth) * 0.5 + (Number(mediaX.value) / 100) * width * 0.5;
    const drawY =
      (height - drawHeight) * 0.5 + (Number(mediaY.value) / 100) * height * 0.5;
    mediaContext.imageSmoothingEnabled = true;
    mediaContext.imageSmoothingQuality = "high";
    mediaContext.drawImage(mediaImage, drawX, drawY, drawWidth, drawHeight);

    const image = mediaContext.getImageData(0, 0, width, height).data;
    return pixels.map((pixel) => {
      const sampleX = Math.round(((pixel.xMm - bounds.minX) / bounds.width) * (width - 1));
      const sampleY = Math.round(((pixel.yMm - bounds.minY) / bounds.height) * (height - 1));
      let red = 0;
      let green = 0;
      let blue = 0;
      let samples = 0;
      for (let offsetY = -2; offsetY <= 2; offsetY += 1) {
        for (let offsetX = -2; offsetX <= 2; offsetX += 1) {
          const x = Math.max(0, Math.min(width - 1, sampleX + offsetX));
          const y = Math.max(0, Math.min(height - 1, sampleY + offsetY));
          const index = (y * width + x) * 4;
          const alpha = image[index + 3] / 255;
          red += image[index] * alpha;
          green += image[index + 1] * alpha;
          blue += image[index + 2] * alpha;
          samples += 1;
        }
      }
      return [
        Math.round(red / samples),
        Math.round(green / samples),
        Math.round(blue / samples),
      ];
    });
  }

  function advanceFirmwareFrame() {
    elapsedSeconds += 1 / engine.FIRMWARE_FRAME_RATE_HZ;
    if (modeSelect.value === "liquid") {
      liquid.update(
        1 / engine.FIRMWARE_FRAME_RATE_HZ,
        gravityVector.x,
        gravityVector.y,
        Math.hypot(gravityVector.x, gravityVector.y),
      );
    }
  }

  function modeFrame() {
    switch (modeSelect.value) {
      case "heartbeat":
        return engine.heartbeatFrame(pixels, elapsedSeconds, Number(bpm.value));
      case "liquid":
        return liquid.frame();
      case "rainbow":
        return engine.rainbowFrame(pixels, elapsedSeconds);
      case "love": {
        const cycleSeconds = 3.85;
        const loveElapsed =
          ((elapsedSeconds - loveStartSeconds) % cycleSeconds + cycleSeconds) %
          cycleSeconds;
        return engine.loveFrame(pixels, loveElapsed);
      }
      case "arrow":
        return engine.arrowFrame(
          pixels,
          elapsedSeconds,
          Number(bearing.value),
          Number(heading.value),
          arrowValid.checked,
        );
      case "media":
        return sampleMediaFrame();
      default:
        return engine.blackFrame(pixels);
    }
  }

  function drawFrame(frame) {
    const rectangle = canvas.getBoundingClientRect();
    context.clearRect(0, 0, rectangle.width, rectangle.height);
    const layout = layoutForCanvas();
    drawBoard(layout);
    screenPixels = pixels.map((pixel) => layout.mmToScreen(pixel.xMm, pixel.yMm));
    const baseRadius = Math.max(2.6, layout.scale * 1.58);
    const radius = baseRadius * (Number(ledSize.value) / 100);

    for (let index = 0; index < pixels.length; index += 1) {
      const position = screenPixels[index];
      const color = frame[index];
      const lit = color[0] + color[1] + color[2] > 3;
      if (lit) {
        context.shadowBlur = radius * 2.6;
        context.shadowColor = `rgb(${color[0]} ${color[1]} ${color[2]})`;
      } else {
        context.shadowBlur = 0;
      }
      context.beginPath();
      context.arc(position.x, position.y, radius, 0, Math.PI * 2);
      context.fillStyle = `rgb(${color[0]} ${color[1]} ${color[2]})`;
      context.fill();
      context.shadowBlur = 0;
      context.lineWidth = 1;
      context.strokeStyle = lit ? "rgba(255,255,255,0.34)" : "#4b3948";
      context.stroke();

      if (addresses.checked) {
        context.fillStyle = color[0] + color[1] + color[2] > 330 ? "#160d12" : "#fff";
        context.font = `600 ${Math.max(6, radius * 0.54)}px ui-monospace, monospace`;
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText(pixels[index].reference.slice(1), position.x, position.y);
      }
    }
  }

  function render(timestamp) {
    const deltaSeconds = Math.min(0.05, Math.max(0, (timestamp - previousTimestamp) / 1000));
    previousTimestamp = timestamp;
    if (playing) {
      firmwareFrameAccumulator += deltaSeconds;
      const firmwareFrameSeconds = 1 / engine.FIRMWARE_FRAME_RATE_HZ;
      while (firmwareFrameAccumulator >= firmwareFrameSeconds) {
        advanceFirmwareFrame();
        firmwareFrameAccumulator -= firmwareFrameSeconds;
      }
    }
    currentFrame = engine.processFrame(
      modeFrame(),
      Number(brightness.value) / 100,
      gamma.checked,
    );
    drawFrame(currentFrame);
    requestAnimationFrame(render);
  }

  function inspectPointer(event) {
    if (screenPixels.length === 0) return;
    const rectangle = canvas.getBoundingClientRect();
    const x = event.clientX - rectangle.left;
    const y = event.clientY - rectangle.top;
    let nearest = -1;
    let nearestDistance = Infinity;
    for (let index = 0; index < screenPixels.length; index += 1) {
      const distance = Math.hypot(x - screenPixels[index].x, y - screenPixels[index].y);
      if (distance < nearestDistance) {
        nearest = index;
        nearestDistance = distance;
      }
    }
    if (nearestDistance > 24) {
      detail.textContent = "Move over an LED to inspect it";
      return;
    }
    const pixel = pixels[nearest];
    const color = currentFrame[nearest];
    detail.textContent =
      `${pixel.reference} · chain ${pixel.chain} · address ${pixel.address} · ` +
      `RGB ${color[0]}, ${color[1]}, ${color[2]}`;
  }

  function loadMedia(file) {
    if (!file) return;
    if (mediaUrl) URL.revokeObjectURL(mediaUrl);
    mediaUrl = URL.createObjectURL(file);
    mediaReady = false;
    mediaImage.onload = () => {
      mediaReady = true;
      modeSelect.value = "media";
      updateModePanels();
    };
    mediaImage.onerror = () => {
      mediaReady = false;
      detail.textContent = "That image could not be decoded by this browser";
    };
    mediaImage.src = mediaUrl;
  }

  function exportFrame() {
    const payload = {
      mode: modeSelect.value,
      order: "chain 0 address 0..71, then chain 1 address 0..71",
      pixels: pixels.map((pixel, index) => ({
        reference: pixel.reference,
        chain: pixel.chain,
        address: pixel.address,
        rgb: currentFrame[index],
      })),
    };
    const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `rava-heart-${modeSelect.value}-frame.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  modeSelect.addEventListener("change", updateModePanels);
  playButton.addEventListener("click", () => {
    playing = !playing;
    playButton.textContent = playing ? "Pause" : "Play";
  });
  const shakeButton = document.getElementById("shake");
  let shakeLabelTimer = 0;
  shakeButton.addEventListener("click", () => {
    const magnitude = Math.hypot(gravityVector.x, gravityVector.y);
    liquid.splash(
      magnitude > 0.05 ? gravityVector.x : 0,
      magnitude > 0.05 ? gravityVector.y : -1,
      1,
    );
    shakeButton.textContent = "Splash!";
    window.clearTimeout(shakeLabelTimer);
    shakeLabelTimer = window.setTimeout(() => {
      shakeButton.textContent = "Shake / splash";
    }, 240);
  });
  document.getElementById("reset-liquid").addEventListener("click", () => liquid.reset());
  document.getElementById("replay-love").addEventListener("click", () => {
    loveStartSeconds = elapsedSeconds;
  });
  gravityPad.addEventListener("pointerdown", (event) => {
    gravityPad.setPointerCapture(event.pointerId);
    setGravityFromPointer(event);
  });
  gravityPad.addEventListener("pointermove", (event) => {
    if (gravityPad.hasPointerCapture(event.pointerId)) setGravityFromPointer(event);
  });
  gravityPad.addEventListener("pointerup", (event) => {
    if (gravityPad.hasPointerCapture(event.pointerId)) {
      gravityPad.releasePointerCapture(event.pointerId);
    }
  });
  gravityPad.addEventListener("keydown", (event) => {
    const step = event.shiftKey ? 0.10 : 0.04;
    const delta = {
      ArrowLeft: [-step, 0],
      ArrowRight: [step, 0],
      ArrowUp: [0, step],
      ArrowDown: [0, -step],
    }[event.key];
    if (!delta) return;
    event.preventDefault();
    let x = gravityVector.x + delta[0];
    let y = gravityVector.y + delta[1];
    const magnitude = Math.hypot(x, y);
    if (magnitude > 1) {
      x /= magnitude;
      y /= magnitude;
    }
    gravityVector = { x, y };
    updateGravityPad();
  });
  document.getElementById("export-frame").addEventListener("click", exportFrame);
  mediaFile.addEventListener("change", () => loadMedia(mediaFile.files[0]));
  canvas.addEventListener("pointermove", inspectPointer);
  canvas.addEventListener("pointerleave", () => {
    detail.textContent = "Move over an LED to inspect it";
  });
  for (const control of root.querySelectorAll("input, select")) {
    control.addEventListener("input", updateLabels);
  }
  new ResizeObserver(resizeCanvas).observe(canvas);
  window.addEventListener("beforeunload", () => {
    if (mediaUrl) URL.revokeObjectURL(mediaUrl);
  });

  updateLabels();
  updateGravityPad();
  updateModePanels();
  resizeCanvas();
  requestAnimationFrame(render);
})();
