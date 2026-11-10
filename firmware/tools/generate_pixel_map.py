#!/usr/bin/env python3
"""Generate the firmware LED map from the ordered KiCad PCB.

The electrical chain order is discovered from each WS2812 DIN/DOUT net.  No
assumption is made that reference numbers increase along a chain.  This keeps
firmware coordinates synchronized with the actual board after PCB edits.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
FIRMWARE_DIR = SCRIPT_DIR.parent
PROJECT_DIR = FIRMWARE_DIR.parent
MECHANICAL_DIR = PROJECT_DIR / "mechanical"
DEFAULT_BOARD = PROJECT_DIR / "hardware" / "HeartArray.kicad_pcb"
DEFAULT_HEADER = FIRMWARE_DIR / "main" / "generated" / "pixel_map.hpp"
DEFAULT_JSON = FIRMWARE_DIR / "generated" / "pixel_map.json"
DEFAULT_SIMULATOR_JS = FIRMWARE_DIR / "simulator" / "generated" / "pixel-map.js"

sys.path.insert(0, str(MECHANICAL_DIR))
from place_leds_and_caps import (  # noqa: E402
    discover_chains,
    matching_paren,
    parse_footprints,
)


def reference_number(reference: str) -> int:
    return int(reference[1:])


def load_map(board_path: Path) -> list[list[dict[str, float | int | str]]]:
    board = board_path.read_text(encoding="utf-8")
    footprints = parse_footprints(board)
    leds = {
        footprint.reference: footprint
        for footprint in footprints
        if footprint.value == "WS2812B-MINI-V6"
    }
    chains = discover_chains(leds)
    if sorted(len(chain) for chain in chains) != [72, 72]:
        raise ValueError(
            f"Expected two 72-pixel chains; discovered {[len(chain) for chain in chains]}"
        )

    all_leds = [leds[reference] for chain in chains for reference in chain]
    min_x = min(led.x for led in all_leds)
    max_x = max(led.x for led in all_leds)
    min_y = min(led.y for led in all_leds)
    max_y = max(led.y for led in all_leds)
    span_x = max_x - min_x
    span_y = max_y - min_y

    result: list[list[dict[str, float | int | str]]] = []
    for chain_index, chain in enumerate(chains):
        entries = []
        for physical_index, reference in enumerate(chain):
            led = leds[reference]
            entries.append(
                {
                    "chain": chain_index,
                    "physical_index": physical_index,
                    "reference": reference,
                    "reference_number": reference_number(reference),
                    "x_mm": round(led.x, 4),
                    "y_mm": round(led.y, 4),
                    "x": round((led.x - min_x) / span_x, 7),
                    # KiCad Y grows downward; firmware Y grows upward.
                    "y": round((max_y - led.y) / span_y, 7),
                    "rotation_deg": round(led.rotation, 4),
                    "din_net": led.nets_by_function["DIN"],
                    "dout_net": led.nets_by_function["DOUT"],
                }
            )
        result.append(entries)
    return result


def load_edge_outline(board_path: Path) -> list[tuple[float, float]]:
    board = board_path.read_text(encoding="utf-8")
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for match in re.finditer(r"(?m)^\t(?=\(gr_line)", board):
        start = match.end()
        end = matching_paren(board, start)
        block = board[start:end]
        if '(layer "Edge.Cuts")' not in block:
            continue
        start_match = re.search(r"\(start\s+([-\d.]+)\s+([-\d.]+)\)", block)
        end_match = re.search(r"\(end\s+([-\d.]+)\s+([-\d.]+)\)", block)
        if start_match and end_match:
            segments.append(
                (
                    (float(start_match.group(1)), float(start_match.group(2))),
                    (float(end_match.group(1)), float(end_match.group(2))),
                )
            )
    if not segments:
        raise ValueError("No line-segment Edge.Cuts outline found")

    def key(point: tuple[float, float]) -> tuple[float, float]:
        return round(point[0], 4), round(point[1], 4)

    unused = list(segments)
    first_start, current = unused.pop(0)
    outline = [first_start]
    while key(current) != key(first_start):
        outline.append(current)
        for index, (candidate_start, candidate_end) in enumerate(unused):
            if key(candidate_start) == key(current):
                current = candidate_end
                unused.pop(index)
                break
            if key(candidate_end) == key(current):
                current = candidate_start
                unused.pop(index)
                break
        else:
            raise ValueError("Edge.Cuts line segments do not form a closed outline")
    if unused:
        raise ValueError("Multiple Edge.Cuts loops are not supported by the simulator")
    return outline


def write_json(
    path: Path,
    chains: list[list[dict[str, float | int | str]]],
    source_board: Path,
    outline: list[tuple[float, float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        source = str(source_board.relative_to(PROJECT_DIR))
    except ValueError:
        source = str(source_board)
    payload = {
        "source": source,
        "coordinate_system": "normalized board space: +X right, +Y up",
        "board_outline_mm": [
            {"x": round(x, 4), "y": round(y, 4)} for x, y in outline
        ],
        "chains": chains,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def write_header(path: Path, chains: list[list[dict[str, float | int | str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = [entry for chain in chains for entry in chain]
    lines = [
        "// Generated by firmware/tools/generate_pixel_map.py. Do not edit by hand.",
        "#pragma once",
        "",
        "#include <array>",
        "#include <cstddef>",
        "#include <cstdint>",
        "",
        "namespace heart::generated {",
        "",
        "struct PixelLocation {",
        "  float x;",
        "  float y;",
        "  std::uint16_t reference_number;",
        "  std::uint8_t chain;",
        "  std::uint8_t physical_index;",
        "};",
        "",
        "inline constexpr std::size_t kChainCount = 2;",
        "inline constexpr std::size_t kPixelsPerChain = 72;",
        "inline constexpr std::size_t kPixelCount = kChainCount * kPixelsPerChain;",
        "",
        "// Entries are ordered exactly as bytes must be transmitted: chain 0, then chain 1.",
        "inline constexpr std::array<PixelLocation, kPixelCount> kPixels = {{",
    ]
    for entry in entries:
        lines.append(
            "  PixelLocation{"
            f"{entry['x']:.7f}F, {entry['y']:.7f}F, "
            f"{entry['reference_number']}, {entry['chain']}, {entry['physical_index']}"
            f"}},  // {entry['reference']}"
        )
    lines.extend(
        [
            "}};",
            "",
            f"inline constexpr std::uint16_t kChain0FirstReference = {chains[0][0]['reference_number']};",
            f"inline constexpr std::uint16_t kChain1FirstReference = {chains[1][0]['reference_number']};",
            "",
            "}  // namespace heart::generated",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_simulator_js(
    path: Path,
    chains: list[list[dict[str, float | int | str]]],
    outline: list[tuple[float, float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pixels = [
        {
            "x": entry["x"],
            "y": entry["y"],
            "xMm": entry["x_mm"],
            "yMm": entry["y_mm"],
            "reference": entry["reference"],
            "chain": entry["chain"],
            "address": entry["physical_index"],
        }
        for chain in chains
        for entry in chain
    ]
    path.write_text(
        "// Generated by firmware/tools/generate_pixel_map.py. Do not edit.\n"
        "globalThis.HEART_PIXEL_MAP = Object.freeze(\n"
        + json.dumps(pixels, separators=(",", ":"))
        + "\n);\n"
        "globalThis.HEART_BOARD_OUTLINE = Object.freeze(\n"
        + json.dumps(
            [{"xMm": round(x, 4), "yMm": round(y, 4)} for x, y in outline],
            separators=(",", ":"),
        )
        + "\n);\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--header", type=Path, default=DEFAULT_HEADER)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--simulator-js", type=Path, default=DEFAULT_SIMULATOR_JS)
    args = parser.parse_args()

    board_path = args.board.resolve()
    chains = load_map(board_path)
    outline = load_edge_outline(board_path)
    write_header(args.header.resolve(), chains)
    write_json(args.json.resolve(), chains, board_path, outline)
    write_simulator_js(args.simulator_js.resolve(), chains, outline)
    print(
        "Generated "
        f"{sum(len(chain) for chain in chains)} pixels: "
        + ", ".join(
            f"chain {index} starts {chain[0]['reference']} and has {len(chain)} pixels"
            for index, chain in enumerate(chains)
        )
    )


if __name__ == "__main__":
    main()
