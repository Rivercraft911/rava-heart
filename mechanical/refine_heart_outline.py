#!/usr/bin/env python3
"""Shorten the USB-C chin and gently round the centre notch of HeartArray.

Only Edge.Cuts graphics are replaced.  Footprints, tracks, zones, nets, and all
other board content are preserved byte-for-byte.
"""

from __future__ import annotations

import argparse
import re
import uuid
from pathlib import Path

from generate_heart_outline import cubic, standard_heart, write_r12_dxf
from place_leds_and_caps import matching_paren


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
BOARD_PATH = PROJECT_DIR / "hardware" / "HeartArray.kicad_pcb"
CANDIDATE_PATH = PROJECT_DIR / "hardware" / "HeartArray_short_chin_candidate.kicad_pcb"
BACKUP_PATH = PROJECT_DIR / "hardware" / "HeartArray_pre_short_chin_20260829.kicad_pcb"
DXF_PATH = SCRIPT_DIR / "heart_matrix_94x88_refined_edgecuts.dxf"

BOARD_ORIGIN = (100.0, 50.0)
BOARD_WIDTH_MM = 94.0
BOTTOM_Y_MM = 88.3


def interpolate(a: tuple[float, float], b: tuple[float, float], count: int):
    return [
        (
            a[0] + (b[0] - a[0]) * index / count,
            a[1] + (b[1] - a[1]) * index / count,
        )
        for index in range(count)
    ]


def cubic_inclusive(p0, p1, p2, p3, count=16):
    points = []
    for index in range(count + 1):
        t = index / count
        u = 1.0 - t
        points.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return points


def refined_outline() -> list[tuple[float, float]]:
    """Return a 94 mm wide, 88 mm tall heart with a short USB-C chin."""
    base = standard_heart(samples=720)
    right_join = base[280]
    left_join = base[440]

    # Work in the original 2..98 mm source system, then normalize to 94 mm.
    source_bottom_y = 2.0 + BOTTOM_Y_MM * 96.0 / 94.0
    source_tab_top_y = source_bottom_y - 1.35
    source = list(base[:281])
    source.extend(
        cubic(
            right_join,
            (60.5, 80.8),
            (57.8, 86.2),
            (57.0, source_tab_top_y),
            30,
        )
    )
    source.extend(
        cubic(
            (57.0, source_tab_top_y),
            (56.95, source_tab_top_y + 0.65),
            (56.6, source_bottom_y),
            (56.0, source_bottom_y),
            14,
        )
    )
    source.extend(interpolate((56.0, source_bottom_y), (44.0, source_bottom_y), 20))
    source.extend(
        cubic(
            (44.0, source_bottom_y),
            (43.4, source_bottom_y),
            (43.05, source_tab_top_y + 0.65),
            (43.0, source_tab_top_y),
            14,
        )
    )
    source.extend(
        cubic(
            (43.0, source_tab_top_y),
            (42.2, 86.2),
            (39.5, 80.8),
            left_join,
            30,
        )
    )
    source.extend(base[440:])

    scaled = [((x - 2.0) * 94.0 / 96.0, (y - 2.0) * 94.0 / 96.0) for x, y in source]

    # Remove the mathematical cusp and replace it with a barely-visible,
    # 0.65 mm-wide U-shaped radius between the lobes.
    core = scaled[18:-17]
    right_cut = core[0]
    left_cut = core[-1]
    bottom = (BOARD_WIDTH_MM / 2.0, 22.20)
    left_arc = cubic_inclusive(
        left_cut,
        (46.82, 20.90),
        (46.75, 22.20),
        bottom,
        14,
    )
    right_arc = cubic_inclusive(
        bottom,
        (47.25, 22.20),
        (47.18, 20.90),
        right_cut,
        14,
    )
    return core + left_arc[1:] + right_arc[1:-1]


def edge_cuts_text(outline: list[tuple[float, float]]) -> str:
    clean: list[tuple[float, float]] = []
    for x, y in outline:
        point = (round(x, 4), round(y, 4))
        if not clean or point != clean[-1]:
            clean.append(point)
    if clean[0] == clean[-1]:
        clean.pop()

    origin_x, origin_y = BOARD_ORIGIN
    blocks = []
    for start, end in zip(clean, clean[1:] + clean[:1]):
        blocks.append(
            "\n".join(
                [
                    "\t(gr_line",
                    f"\t\t(start {origin_x + start[0]:.4f} {origin_y + start[1]:.4f})",
                    f"\t\t(end {origin_x + end[0]:.4f} {origin_y + end[1]:.4f})",
                    "\t\t(stroke (width 0.05) (type solid))",
                    '\t\t(layer "Edge.Cuts")',
                    f'\t\t(uuid "{uuid.uuid4()}")',
                    "\t)",
                ]
            )
        )
    return "\n".join(blocks) + "\n"


def replace_edge_cuts(board: str, outline: list[tuple[float, float]]) -> str:
    removals: list[tuple[int, int]] = []
    for match in re.finditer(r"(?m)^\t(?=\(gr_(?:line|arc|rect|poly))", board):
        start = match.end()
        end = matching_paren(board, start)
        block = board[start:end]
        if '(layer "Edge.Cuts")' in block:
            removals.append((start, end))
    if not removals:
        raise ValueError("No existing Edge.Cuts graphics found")

    rewritten = board
    for start, end in reversed(removals):
        rewritten = rewritten[:start] + rewritten[end:]
    if '(layer "Edge.Cuts")' in rewritten:
        raise ValueError("An unsupported Edge.Cuts item remains after replacement")

    marker = "\n\t(embedded_fonts no)\n)"
    insertion = rewritten.rfind(marker)
    if insertion < 0:
        raise ValueError("Could not locate the end of the KiCad board")
    return rewritten[:insertion] + "\n" + edge_cuts_text(outline) + rewritten[insertion:]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD_PATH)
    parser.add_argument("--output", type=Path, default=CANDIDATE_PATH)
    parser.add_argument("--backup", type=Path, default=BACKUP_PATH)
    parser.add_argument("--apply-main", action="store_true")
    args = parser.parse_args()

    board = args.board.read_text(encoding="utf-8")
    outline = refined_outline()
    rewritten = replace_edge_cuts(board, outline)
    if args.apply_main:
        lock = args.board.with_name(f"~{args.board.name}.lck")
        if lock.exists():
            raise ValueError(f"PCB is currently locked by KiCad: {lock}")
        if not args.backup.exists():
            args.backup.write_text(board, encoding="utf-8")
        args.board.write_text(rewritten, encoding="utf-8")
        destination = args.board
    else:
        args.output.write_text(rewritten, encoding="utf-8")
        destination = args.output
    write_r12_dxf(DXF_PATH, outline)
    print(f"Outline: {BOARD_WIDTH_MM:.1f} mm wide x {BOTTOM_Y_MM:.1f} mm tall")
    print(f"Wrote PCB: {destination}")
    print(f"Wrote DXF: {DXF_PATH}")
    if args.apply_main:
        print(f"Backup: {args.backup}")


if __name__ == "__main__":
    main()
