const fs = require('fs');
const path = require('path');
const sharp = require('sharp');

const input = process.argv[2];
const outputDir = process.argv[3];
const outputStem = process.argv[4] || 'IMG_2507-silkscreen-cutout-70mm';
const previewStem = process.argv[5] || 'IMG_2507-silkscreen-preview-pink.png';
const previewMode = process.argv[6] || 'pink-pcb';

if (!input || !outputDir) {
  throw new Error('usage: node build_silkscreen_cutout.js INPUT_PNG OUTPUT_DIR');
}

const physicalWidthMm = 70;
const pixelMm = 0.2;
const outputWidth = Math.round(physicalWidthMm / pixelMm);

async function findSubjectBounds() {
  const { data, info } = await sharp(input)
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });

  let left = info.width;
  let top = info.height;
  let right = -1;
  let bottom = -1;

  // The generated subject is black line art. The pale checkerboard is above
  // this threshold and is therefore excluded from the crop.
  for (let y = 0; y < info.height; y += 1) {
    for (let x = 0; x < info.width; x += 1) {
      if (data[y * info.width + x] < 160) {
        left = Math.min(left, x);
        top = Math.min(top, y);
        right = Math.max(right, x);
        bottom = Math.max(bottom, y);
      }
    }
  }

  if (right < left || bottom < top) throw new Error('subject was not detected');

  const padding = 10;
  left = Math.max(0, left - padding);
  top = Math.max(0, top - padding);
  right = Math.min(info.width - 1, right + padding);
  bottom = Math.min(info.height - 1, bottom + padding);

  return {
    left,
    top,
    width: right - left + 1,
    height: bottom - top + 1,
  };
}

async function main() {
  fs.mkdirSync(outputDir, { recursive: true });
  const crop = await findSubjectBounds();

  // Materialize the crop before resizing. This avoids libvips reordering the
  // two geometric operations and preserves the subject's exact proportions.
  const cropped = await sharp(input)
    .extract(crop)
    .png()
    .toBuffer();

  const { data, info } = await sharp(cropped)
    .resize({ width: outputWidth, kernel: sharp.kernel.lanczos3 })
    .greyscale()
    .raw()
    .toBuffer({ resolveWithObject: true });

  const width = info.width;
  const height = info.height;
  const work = new Float32Array(width * height);

  for (let i = 0; i < data.length; i += 1) {
    // Guarantee that the pale checkerboard and the white portions of the
    // portrait become empty space. Boost only the remaining dark artwork.
    work[i] = data[i] > 220
      ? 255
      : Math.max(0, Math.min(255, (data[i] - 128) * 1.18 + 128));
  }

  const mask = Buffer.alloc(width * height);
  for (let y = 0; y < height; y += 1) {
    const leftToRight = y % 2 === 0;
    const start = leftToRight ? 0 : width - 1;
    const end = leftToRight ? width : -1;
    const step = leftToRight ? 1 : -1;

    for (let x = start; x !== end; x += step) {
      const i = y * width + x;
      const oldValue = work[i];
      const newValue = oldValue < 128 ? 0 : 255;
      mask[i] = newValue;
      const error = oldValue - newValue;
      const spread = (nx, ny, amount) => {
        if (nx >= 0 && nx < width && ny >= 0 && ny < height) {
          work[ny * width + nx] += error * amount;
        }
      };
      spread(x + step, y, 7 / 16);
      spread(x - step, y + 1, 3 / 16);
      spread(x, y + 1, 5 / 16);
      spread(x + step, y + 1, 1 / 16);
    }
  }

  const base = path.join(outputDir, outputStem);

  // Black opaque means silkscreen ink; all other pixels are genuinely
  // transparent. This file has no rectangular background.
  const rgba = Buffer.alloc(width * height * 4);
  for (let i = 0; i < mask.length; i += 1) {
    const ink = mask[i] === 0;
    rgba[i * 4] = 0;
    rgba[i * 4 + 1] = 0;
    rgba[i * 4 + 2] = 0;
    rgba[i * 4 + 3] = ink ? 255 : 0;
  }

  await sharp(rgba, { raw: { width, height, channels: 4 } })
    .png({ palette: true, colours: 2, dither: 0 })
    .withMetadata({ density: 127 })
    .toFile(`${base}.png`);

  const commands = [];
  for (let y = 0; y < height; y += 1) {
    let x = 0;
    while (x < width) {
      while (x < width && mask[y * width + x] !== 0) x += 1;
      if (x >= width) break;
      const x0 = x;
      while (x < width && mask[y * width + x] === 0) x += 1;
      commands.push(`M${x0} ${y}h${x - x0}v1H${x0}z`);
    }
  }

  const physicalHeightMm = height * pixelMm;
  const svg = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    `<svg xmlns="http://www.w3.org/2000/svg" width="${physicalWidthMm}mm" height="${physicalHeightMm.toFixed(3)}mm" viewBox="0 0 ${width} ${height}">`,
    '  <title>IMG 2507 background-free PCB silkscreen; black shapes are ink</title>',
    `  <path fill="#000000" shape-rendering="crispEdges" d="${commands.join('')}"/>`,
    '</svg>',
    '',
  ].join('\n');
  fs.writeFileSync(`${base}.svg`, svg);

  const previewScale = 4;
  const preview = Buffer.alloc(width * height * 3);
  const maskColor = previewMode === 'white-pcb' ? [246, 246, 242] : [210, 62, 119];
  const inkColor = previewMode === 'white-pcb' ? [20, 20, 18] : [244, 244, 235];
  for (let i = 0; i < mask.length; i += 1) {
    const color = mask[i] === 0 ? inkColor : maskColor;
    preview[i * 3] = color[0];
    preview[i * 3 + 1] = color[1];
    preview[i * 3 + 2] = color[2];
  }
  await sharp(preview, { raw: { width, height, channels: 3 } })
    .resize({ width: width * previewScale, kernel: sharp.kernel.nearest })
    .png()
    .toFile(path.join(outputDir, previewStem));

  console.log(JSON.stringify({
    widthPx: width,
    heightPx: height,
    physicalWidthMm,
    physicalHeightMm: Number(physicalHeightMm.toFixed(3)),
    minimumFeatureMm: pixelMm,
    png: `${base}.png`,
    svg: `${base}.svg`,
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
