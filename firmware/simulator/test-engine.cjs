"use strict";

const assert = require("node:assert/strict");
require("./generated/pixel-map.js");
const engine = require("./engine.js");

const pixels = globalThis.HEART_PIXEL_MAP;
const outline = globalThis.HEART_BOARD_OUTLINE;
assert.equal(pixels.length, 144);
assert.ok(outline.length > 100);
assert.equal(pixels.filter((pixel) => pixel.chain === 0).length, 72);
assert.equal(pixels.filter((pixel) => pixel.chain === 1).length, 72);
assert.equal(new Set(pixels.map((pixel) => pixel.reference)).size, 144);
const oneChainWireSeconds =
  (engine.PIXELS_PER_CHAIN * engine.LED_BITS_PER_PIXEL) /
    engine.LED_DATA_RATE_BITS_PER_SECOND +
  engine.LED_RESET_BUDGET_MICROSECONDS / 1_000_000;
assert.ok(oneChainWireSeconds < 1 / engine.FIRMWARE_FRAME_RATE_HZ);
assert.ok(oneChainWireSeconds * 2 < 1 / engine.FIRMWARE_FRAME_RATE_HZ);
for (const chain of [0, 1]) {
  const addresses = pixels
    .filter((pixel) => pixel.chain === chain)
    .map((pixel) => pixel.address);
  assert.deepEqual(addresses, Array.from({ length: 72 }, (_, index) => index));
}

const redSum = (frame) => frame.reduce((sum, color) => sum + color[0], 0);
assert.ok(
  redSum(engine.heartbeatFrame(pixels, 1.15, 60)) >
    redSum(engine.heartbeatFrame(pixels, 0.75, 60)) * 8,
);

function centroid(frame) {
  let x = 0;
  let y = 0;
  let weight = 0;
  frame.forEach((color, index) => {
    x += pixels[index].x * color[0];
    y += pixels[index].y * color[0];
    weight += color[0];
  });
  return { x: x / weight, y: y / weight };
}

const northArrow = centroid(engine.arrowFrame(pixels, 0, 0, 0, true));
const eastArrow = centroid(engine.arrowFrame(pixels, 0, 90, 0, true));
assert.ok(northArrow.y > 0.40);
assert.ok(eastArrow.x > 0.50);
const northFrame = engine.arrowFrame(pixels, 0, 0, 0, true);
const northLit = northFrame
  .map((color, index) => ({ color, pixel: pixels[index] }))
  .filter(({ color }) => color[0] > 24);
assert.ok(northLit.length >= 10);
assert.ok(Math.max(...northLit.map(({ pixel }) => pixel.y)) <= 0.78);

const loveI = engine.loveFrame(pixels, 0.40);
const loveHeart = engine.loveFrame(pixels, 1.40);
const loveU = engine.loveFrame(pixels, 2.55);
const litCount = (frame) => frame.filter((color) => color[0] > 20).length;
assert.ok(litCount(loveI) >= 12 && litCount(loveI) < pixels.length / 2);
assert.equal(litCount(loveHeart), pixels.length);
assert.ok(litCount(loveU) >= 12 && litCount(loveU) < pixels.length / 2);

const liquid = new engine.LiquidSimulation(pixels);
const initialMass = liquid.totalMass();
for (let frame = 0; frame < 360; frame += 1) {
  liquid.update(1 / 60, 0, -1, 1);
}
assert.ok(Math.abs(liquid.totalMass() - initialMass) < 0.001);
assert.ok(liquid.edges.length > pixels.length);
const settled = liquid.frame();
liquid.splash(1, 0, 1);
assert.ok(liquid.kineticEnergy() > 1);
for (let frame = 0; frame < 8; frame += 1) {
  liquid.update(1 / 60, 0, -1, 1);
}
const splashed = liquid.frame();
assert.ok(
  settled.filter((color, index) => color[0] !== splashed[index][0]).length > 20,
);
assert.ok(Math.abs(liquid.totalMass() - initialMass) < 0.001);
const downCenter = liquid.centerOfMass();
for (let frame = 0; frame < 360; frame += 1) {
  liquid.update(1 / 60, 1, 0, 1);
}
assert.ok(liquid.centerOfMass().x > downCenter.x + 0.10);
assert.ok(Math.abs(liquid.totalMass() - initialMass) < 0.001);

const rainbowFirst = engine.rainbowFrame(pixels, 0);
const rainbowLater = engine.rainbowFrame(pixels, 1);
assert.ok(new Set(rainbowFirst.map((color) => color.join(","))).size > 40);
assert.ok(
  rainbowFirst.filter((color, index) => color.join(",") !== rainbowLater[index].join(","))
    .length > 120,
);

const processed = engine.processFrame([[0, 128, 255]], 1, true)[0];
assert.deepEqual(processed, [0, 56, 255]);

console.log("Heart simulator engine tests passed");
