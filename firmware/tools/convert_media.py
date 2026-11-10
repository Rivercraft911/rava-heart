#!/usr/bin/env python3
"""Sample an image or animated GIF at the HeartArray's real LED locations."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageSequence


FIRMWARE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MAP = FIRMWARE_DIR / "generated" / "pixel_map.json"
SAMPLE_RADIUS = 2
CANVAS_WIDTH = 600


def load_geometry(path: Path) -> tuple[list[dict], dict[str, float]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    pixels = [pixel for chain in payload["chains"] for pixel in chain]
    if len(pixels) != 144:
        raise ValueError(f"Expected 144 pixels, found {len(pixels)}")
    outline = payload["board_outline_mm"]
    bounds = {
        "min_x": min(point["x"] for point in outline),
        "max_x": max(point["x"] for point in outline),
        "min_y": min(point["y"] for point in outline),
        "max_y": max(point["y"] for point in outline),
    }
    bounds["width"] = bounds["max_x"] - bounds["min_x"]
    bounds["height"] = bounds["max_y"] - bounds["min_y"]
    return pixels, bounds


def composite_frame(
    source: Image.Image,
    canvas_size: tuple[int, int],
    fit: str,
    scale: float,
    offset_x: float,
    offset_y: float,
) -> Image.Image:
    source = source.convert("RGBA")
    canvas_width, canvas_height = canvas_size
    if fit == "stretch":
        draw_width, draw_height = canvas_width, canvas_height
    else:
        scale_x = canvas_width / source.width
        scale_y = canvas_height / source.height
        base_scale = min(scale_x, scale_y) if fit == "contain" else max(scale_x, scale_y)
        draw_width = round(source.width * base_scale)
        draw_height = round(source.height * base_scale)
    draw_width = max(1, round(draw_width * scale))
    draw_height = max(1, round(draw_height * scale))
    resized = source.resize((draw_width, draw_height), Image.Resampling.LANCZOS)
    left = round((canvas_width - draw_width) / 2 + offset_x * canvas_width / 2)
    top = round((canvas_height - draw_height) / 2 + offset_y * canvas_height / 2)
    canvas = Image.new("RGBA", canvas_size, (0, 0, 0, 255))
    canvas.paste(resized, (left, top), resized)
    return canvas


def sample_pixels(
    image: Image.Image,
    pixels: list[dict],
    bounds: dict[str, float],
    brightness: float,
    gamma: float,
) -> list[list[int]]:
    source = image.load()
    width, height = image.size
    result = []
    for pixel in pixels:
        center_x = round(
            (pixel["x_mm"] - bounds["min_x"]) / bounds["width"] * (width - 1)
        )
        center_y = round(
            (pixel["y_mm"] - bounds["min_y"]) / bounds["height"] * (height - 1)
        )
        totals = [0.0, 0.0, 0.0]
        samples = 0
        for y_offset in range(-SAMPLE_RADIUS, SAMPLE_RADIUS + 1):
            for x_offset in range(-SAMPLE_RADIUS, SAMPLE_RADIUS + 1):
                x = max(0, min(width - 1, center_x + x_offset))
                y = max(0, min(height - 1, center_y + y_offset))
                red, green, blue, alpha = source[x, y]
                alpha_scale = alpha / 255.0
                totals[0] += red * alpha_scale
                totals[1] += green * alpha_scale
                totals[2] += blue * alpha_scale
                samples += 1
        color = []
        for total in totals:
            normalized = max(0.0, min(1.0, total / samples / 255.0 * brightness))
            color.append(round(math.pow(normalized, gamma) * 255.0))
        result.append(color)
    return result


def convert_media(
    input_path: Path,
    map_path: Path = DEFAULT_MAP,
    fit: str = "cover",
    scale: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    brightness: float = 1.0,
    gamma: float = 2.2,
) -> dict:
    pixels, bounds = load_geometry(map_path)
    canvas_height = round(CANVAS_WIDTH * bounds["height"] / bounds["width"])
    frames = []
    with Image.open(input_path) as media:
        for source_frame in ImageSequence.Iterator(media):
            composited = composite_frame(
                source_frame,
                (CANVAS_WIDTH, canvas_height),
                fit,
                scale,
                offset_x,
                offset_y,
            )
            frames.append(
                {
                    "duration_ms": max(10, int(source_frame.info.get("duration", 100))),
                    "rgb": sample_pixels(
                        composited,
                        pixels,
                        bounds,
                        brightness,
                        gamma,
                    ),
                }
            )
    return {
        "source": input_path.name,
        "pixel_order": "chain 0 address 0..71, then chain 1 address 0..71",
        "pixel_identity": [
            {
                "reference": pixel["reference"],
                "chain": pixel["chain"],
                "address": pixel["physical_index"],
            }
            for pixel in pixels
        ],
        "frames": frames,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--map", type=Path, default=DEFAULT_MAP)
    parser.add_argument("--fit", choices=("cover", "contain", "stretch"), default="cover")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--offset-x", type=float, default=0.0)
    parser.add_argument("--offset-y", type=float, default=0.0)
    parser.add_argument("--brightness", type=float, default=1.0)
    parser.add_argument("--gamma", type=float, default=2.2)
    args = parser.parse_args()
    if args.scale <= 0.0:
        parser.error("--scale must be greater than zero")
    if not 0.0 <= args.brightness <= 1.0:
        parser.error("--brightness must be between 0 and 1")
    if args.gamma <= 0.0:
        parser.error("--gamma must be greater than zero")

    result = convert_media(
        args.input.resolve(),
        args.map.resolve(),
        args.fit,
        args.scale,
        args.offset_x,
        args.offset_y,
        args.brightness,
        args.gamma,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    print(f"Wrote {len(result['frames'])} frame(s) x 144 pixels to {args.output}")


if __name__ == "__main__":
    main()
