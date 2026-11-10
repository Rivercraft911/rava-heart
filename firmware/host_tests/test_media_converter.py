#!/usr/bin/env python3

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PIL import Image


FIRMWARE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FIRMWARE_DIR / "tools"))
from convert_media import convert_media  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        still_path = temporary / "still.png"
        Image.new("RGB", (40, 30), (255, 255, 255)).save(still_path)
        still = convert_media(still_path, brightness=0.5, gamma=2.2)
        assert len(still["frames"]) == 1
        assert len(still["frames"][0]["rgb"]) == 144
        assert all(color == [55, 55, 55] for color in still["frames"][0]["rgb"])

        gif_path = temporary / "animation.gif"
        first = Image.new("RGB", (24, 24), (255, 0, 0))
        second = Image.new("RGB", (24, 24), (0, 0, 255))
        first.save(
            gif_path,
            save_all=True,
            append_images=[second],
            duration=[120, 240],
            loop=0,
        )
        animation = convert_media(gif_path, gamma=1.0)
        assert len(animation["frames"]) == 2
        assert animation["frames"][0]["duration_ms"] == 120
        assert animation["frames"][1]["duration_ms"] == 240
        assert all(color == [255, 0, 0] for color in animation["frames"][0]["rgb"])
        assert all(color == [0, 0, 255] for color in animation["frames"][1]["rgb"])

    print("Heart media converter tests passed")


if __name__ == "__main__":
    main()
