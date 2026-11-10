#!/usr/bin/env python3
"""Preview and apply the 144-pixel heart matrix mechanical placement.

The placement is deliberately driven by the saved PCB nets, not by reference
number assumptions.  Each 72-pixel chain follows complete horizontal rows in
a serpentine path.  The paired 100 nF capacitors are matched by repeated-sheet
membership and sit in the open VDD-side lane beside each LED on F.Cu.

Without ``--apply`` the script only writes the SVG preview and placement CSV.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from generate_heart_outline import inside_polygon, svg_path, write_r12_dxf
from generate_rf_heart_options import usb_c_heart
from place_leds_and_caps import (
    Footprint,
    data_rotations,
    discover_chains,
    natural_number,
    parse_footprints,
)


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
BOARD_PATH = PROJECT_DIR / "hardware" / "HeartArray.kicad_pcb"
PREVIEW_PATH = SCRIPT_DIR / "heart_matrix_94mm_preview.svg"
CSV_PATH = SCRIPT_DIR / "heart_matrix_94mm_placement.csv"
DXF_PATH = SCRIPT_DIR / "heart_matrix_94mm_edgecuts.dxf"

BOARD_SIZE_MM = 94.0
BOARD_ORIGIN = (100.0, 50.0)
GRID_X_PITCH_MM = 5.6
GRID_Y_PITCH_MM = 5.2
GRID_Y0_MM = 3.5
HOLE_LED_CLEARANCE_MM = 5.8
CAP_VDD_OFFSET_MM = 2.0
LEDS_PER_CHAIN = 72

# Local board coordinates.  M3 holes use 3.2 mm drills; the exclusion radius
# includes the LED body and useful screw-head/assembly breathing room.
MOUNTING_HOLES = {
    "H1": (11.0, 14.0),
    "H2": (83.0, 14.0),
    "H3": (47.0, 78.0),
}

# HX-TYPE-C-16PIN origin: its front shell edge is +5.25 mm in footprint Y.
USB_ORIGIN = (47.0, BOARD_SIZE_MM - 5.25)
USB_BODY = (42.25, 85.75, 51.75, 94.0)


@dataclass(frozen=True)
class Placement:
    chain_index: int
    chain_step: int
    led_ref: str
    cap_ref: str
    local_x: float
    local_y: float
    rotation: int
    cap_x: float
    cap_y: float
    cap_rotation: int

    @property
    def board_x(self) -> float:
        return BOARD_ORIGIN[0] + self.local_x

    @property
    def board_y(self) -> float:
        return BOARD_ORIGIN[1] + self.local_y

    @property
    def cap_board_x(self) -> float:
        return BOARD_ORIGIN[0] + self.cap_x

    @property
    def cap_board_y(self) -> float:
        return BOARD_ORIGIN[1] + self.cap_y


def normalized_outline() -> list[tuple[float, float]]:
    """Scale the soft USB-C heart to an exact 94 x 94 mm envelope."""
    source = usb_c_heart()
    min_x = min(x for x, _ in source)
    max_x = max(x for x, _ in source)
    min_y = min(y for _, y in source)
    max_y = max(y for _, y in source)
    scaled = [
        (
            (x - min_x) * BOARD_SIZE_MM / (max_x - min_x),
            (y - min_y) * BOARD_SIZE_MM / (max_y - min_y),
        )
        for x, y in source
    ]
    # Replace the heart equation's microscopic centre-notch cusp loop with one
    # clean vertex.  This is a sub-0.15 mm cosmetic change and prevents KiCad
    # from reporting a self-intersecting Edge.Cuts outline.
    return [(BOARD_SIZE_MM / 2, scaled[0][1])] + scaled[5:-5]


def distance_to_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.dist(point, start)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def distance_to_outline(point: tuple[float, float], outline: list[tuple[float, float]]) -> float:
    return min(
        distance_to_segment(point, start, end)
        for start, end in zip(outline, outline[1:] + outline[:1])
    )


def left_half_grid(outline: list[tuple[float, float]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    columns = [
        BOARD_SIZE_MM / 2 - GRID_X_PITCH_MM / 2 - column * GRID_X_PITCH_MM
        for column in range(20)
        if BOARD_SIZE_MM / 2 - GRID_X_PITCH_MM / 2 - column * GRID_X_PITCH_MM > 0
    ]
    for row in range(24):
        y = GRID_Y0_MM + row * GRID_Y_PITCH_MM
        for x in columns:
            point = (x, y)
            if any(math.dist(point, hole) < HOLE_LED_CLEARANCE_MM for hole in MOUNTING_HOLES.values()):
                continue
            # Reserve the centered bottom lane for USB-C and the user's MCU/RF
            # placement.  This is intentionally larger than the connector body.
            if x >= 40.0 and y >= 83.0:
                continue
            # Test the actual V6 pad rectangles expanded by 0.30 mm, not just
            # the 3.5 mm plastic package.
            copper_safe = True
            for pad_x in (-1.637541, 1.637541):
                for pad_y in (-0.890018, 0.890018):
                    for sign_x in (-1, 1):
                        for sign_y in (-1, 1):
                            corner = (
                                x + pad_x + sign_x * (1.545009 / 2.0 + 0.50),
                                y + pad_y + sign_y * (0.997003 / 2.0 + 0.50),
                            )
                            if not inside_polygon(corner, outline):
                                copper_safe = False
            if not copper_safe:
                continue
            points.append((round(x, 4), round(y, 4)))
    if len(points) != LEDS_PER_CHAIN:
        raise ValueError(f"Expected {LEDS_PER_CHAIN} points in left half, found {len(points)}")
    return points


def serpentine_rows(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    rows: dict[float, list[tuple[float, float]]] = defaultdict(list)
    for point in points:
        rows[point[1]].append(point)
    path: list[tuple[float, float]] = []
    for row_index, y in enumerate(sorted(rows)):
        row = sorted(rows[y], key=lambda point: point[0])
        if row_index % 2:
            row.reverse()
        path.extend(row)
    return path


def validate_geometry(outline: list[tuple[float, float]], placements: list[Placement]) -> None:
    """Check body spacing, M3 avoidance, and LED copper-to-edge clearance."""
    for index, first in enumerate(placements):
        for second in placements[index + 1 :]:
            distance = math.dist(
                (first.local_x, first.local_y), (second.local_x, second.local_y)
            )
            if distance < 5.20 - 1e-6:
                raise ValueError(
                    f"{first.led_ref} and {second.led_ref} are only {distance:.3f} mm apart"
                )
        for hole_ref, hole in MOUNTING_HOLES.items():
            distance = math.dist((first.local_x, first.local_y), hole)
            if distance < HOLE_LED_CLEARANCE_MM:
                raise ValueError(
                    f"{first.led_ref} is only {distance:.3f} mm from {hole_ref}"
                )

        # WS2812B-MINI-V6 pad geometry from the imported footprint.  Check the
        # rectangle corners after the board's 0.50 mm edge-clearance expansion.
        for pad_x in (-1.637541, 1.637541):
            for pad_y in (-0.890018, 0.890018):
                for sign_x in (-1, 1):
                    for sign_y in (-1, 1):
                        corner = (
                            first.local_x
                            + pad_x
                            + sign_x * (1.545009 / 2.0 + 0.50),
                            first.local_y
                            + pad_y
                            + sign_y * (0.997003 / 2.0 + 0.50),
                        )
                        if not inside_polygon(corner, outline):
                            raise ValueError(
                                f"{first.led_ref} copper clearance exits Edge.Cuts at {corner}"
                            )


def paired_caps(footprints: list[Footprint], leds: dict[str, Footprint]) -> dict[str, str]:
    """Pair each sheet's twelve LEDs with that sheet's twelve 100 nF caps."""
    leds_by_sheet: dict[str, list[str]] = defaultdict(list)
    caps_by_sheet: dict[str, list[str]] = defaultdict(list)
    for footprint in footprints:
        sheet_match = re.search(r'\(sheetname "([^"]+)"\)', footprint.block)
        if not sheet_match:
            continue
        sheet = sheet_match.group(1)
        if footprint.reference in leds:
            leds_by_sheet[sheet].append(footprint.reference)
        elif footprint.value == "100nF" and footprint.reference.startswith("C"):
            caps_by_sheet[sheet].append(footprint.reference)

    result: dict[str, str] = {}
    for sheet, sheet_leds in leds_by_sheet.items():
        sheet_leds.sort(key=natural_number)
        sheet_caps = sorted(caps_by_sheet[sheet], key=natural_number)
        if len(sheet_leds) != 12 or len(sheet_caps) != 12:
            raise ValueError(
                f"{sheet}: expected 12 LEDs and 12 100 nF caps; "
                f"found {len(sheet_leds)} and {len(sheet_caps)}"
            )
        result.update(zip(sheet_leds, sheet_caps))
    if set(result) != set(leds):
        missing = sorted(set(leds) - set(result), key=natural_number)
        raise ValueError(f"Could not pair capacitors for: {', '.join(missing)}")
    return result


def build_placements(
    chains: list[list[str]], cap_by_led: dict[str, str], outline: list[tuple[float, float]]
) -> list[Placement]:
    if len(chains) != 2 or any(len(chain) != LEDS_PER_CHAIN for chain in chains):
        raise ValueError(f"Expected two 72-LED chains; found {[len(chain) for chain in chains]}")
    left_path = serpentine_rows(left_half_grid(outline))
    right_path = [(BOARD_SIZE_MM - x, y) for x, y in left_path]
    # The saved chain heads are the external DIN nodes.  Reverse the geometric
    # paths so both DINs land beside H3/USB-C and data cascades upward.
    left_path.reverse()
    right_path.reverse()
    placements: list[Placement] = []
    for chain_index, (chain, path) in enumerate(zip(chains, (left_path, right_path)), start=1):
        rotations = data_rotations(path)
        for step, (led_ref, point, rotation) in enumerate(zip(chain, path, rotations), start=1):
            # Keep the capacitor next to the LED's *physical VDD side*.  The
            # rows rotate 180 degrees to keep DOUT->DIN local, so the apparent
            # above/below side alternates while the VDD loop remains short.
            cap_y = point[1] - CAP_VDD_OFFSET_MM if rotation == 0 else point[1] + CAP_VDD_OFFSET_MM
            placements.append(
                Placement(
                    chain_index=chain_index,
                    chain_step=step,
                    led_ref=led_ref,
                    cap_ref=cap_by_led[led_ref],
                    local_x=point[0],
                    local_y=point[1],
                    rotation=rotation,
                    cap_x=point[0],
                    cap_y=cap_y,
                    cap_rotation=rotation,
                )
            )
    return placements


def write_csv(path: Path, placements: list[Placement], leds: dict[str, Footprint]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(
            [
                "chain",
                "chain_step",
                "led_reference",
                "cap_reference",
                "x_mm",
                "y_mm",
                "rotation_deg",
                "cap_x_mm",
                "cap_y_mm",
                "cap_rotation_deg",
                "din_net",
                "dout_net",
            ]
        )
        for item in placements:
            writer.writerow(
                [
                    item.chain_index,
                    item.chain_step,
                    item.led_ref,
                    item.cap_ref,
                    f"{item.board_x:.4f}",
                    f"{item.board_y:.4f}",
                    item.rotation,
                    f"{item.cap_board_x:.4f}",
                    f"{item.cap_board_y:.4f}",
                    item.cap_rotation,
                    leds[item.led_ref].nets_by_function["DIN"],
                    leds[item.led_ref].nets_by_function["DOUT"],
                ]
            )


def write_preview(
    path: Path, outline: list[tuple[float, float]], placements: list[Placement]
) -> None:
    chain_colors = {1: "#fb7185", 2: "#c084fc"}
    by_chain = {
        index: sorted(
            (item for item in placements if item.chain_index == index),
            key=lambda item: item.chain_step,
        )
        for index in (1, 2)
    }
    parts = [
        '<rect x="-9" y="-13" width="112" height="119" rx="3" fill="#111827"/>',
        f'<path d="{svg_path(outline)}" fill="#ec4899" fill-opacity="0.22" '
        'stroke="#f9a8d4" stroke-width="0.55"/>',
    ]
    for chain_index, chain in by_chain.items():
        color = chain_colors[chain_index]
        points = " ".join(f"{item.local_x},{item.local_y}" for item in chain)
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="0.55" stroke-opacity="0.72" stroke-linejoin="round"/>'
        )
        for item in chain:
            parts.append(
                f'<rect x="{item.local_x - 1.75:.3f}" y="{item.local_y - 1.75:.3f}" '
                f'width="3.5" height="3.5" rx="0.42" fill="{color}" fill-opacity="0.93"/>'
            )
            # The gold bar represents the paired front-side 0402 capacitor,
            # positioned on the physical VDD side of the rotated LED.
            parts.append(
                f'<rect x="{item.cap_x - 0.52:.3f}" y="{item.cap_y - 0.18:.3f}" '
                'width="1.04" height="0.36" rx="0.08" fill="#fde68a"/>'
            )
            if item.chain_step == 1 or item.chain_step % 12 == 0 or item.chain_step == 72:
                parts.append(
                    f'<text x="{item.local_x:.3f}" y="{item.local_y + 0.72:.3f}" '
                    'font-family="ui-monospace,monospace" font-size="1.45" text-anchor="middle" '
                    f'fill="#111827">{item.led_ref}</text>'
                )
        first = chain[0]
        last = chain[-1]
        parts.extend(
            [
                f'<circle cx="{first.local_x}" cy="{first.local_y}" r="2.55" '
                'fill="none" stroke="#ffffff" stroke-width="0.55"/>',
                f'<text x="{first.local_x}" y="{first.local_y - 3.3}" '
                'font-family="system-ui,sans-serif" font-size="1.8" text-anchor="middle" '
                f'fill="#ffffff">DIN · {first.led_ref}</text>',
                f'<text x="{last.local_x}" y="{last.local_y + 3.5}" '
                'font-family="system-ui,sans-serif" font-size="1.8" text-anchor="middle" '
                f'fill="#ffffff">{last.led_ref} · DOUT</text>',
            ]
        )

    for reference, (x, y) in MOUNTING_HOLES.items():
        parts.extend(
            [
                f'<circle cx="{x}" cy="{y}" r="3.65" fill="#111827" '
                'stroke="#f8fafc" stroke-width="0.42"/>',
                f'<circle cx="{x}" cy="{y}" r="1.6" fill="#030712" '
                'stroke="#cbd5e1" stroke-width="0.25"/>',
                f'<text x="{x}" y="{y + 0.55}" font-family="system-ui,sans-serif" '
                f'font-size="1.45" text-anchor="middle" fill="#f8fafc">{reference}</text>',
            ]
        )
    x1, y1, x2, y2 = USB_BODY
    parts.extend(
        [
            f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" '
            'rx="0.8" fill="#64748b" stroke="#e2e8f0" stroke-width="0.35"/>',
            '<path d="M42.25,94 L51.75,94" stroke="#f8fafc" stroke-width="0.8"/>',
            '<text x="47" y="90.5" font-family="system-ui,sans-serif" font-size="1.65" '
            'text-anchor="middle" fill="#f8fafc">USB-C</text>',
        ]
    )
    parts.extend(
        [
            '<text x="47" y="-7.7" font-family="system-ui,sans-serif" font-size="4" '
            'font-weight="600" text-anchor="middle" fill="#f8fafc">94 mm heart · 144 pixels</text>',
        '<text x="47" y="-3.4" font-family="system-ui,sans-serif" font-size="2.35" '
            'text-anchor="middle" fill="#cbd5e1">5.6 × 5.2 mm grid · two 72-pixel serpentine chains · three M3 holes</text>',
            '<circle cx="10" cy="99.2" r="1.2" fill="#fb7185"/>',
            '<text x="12.3" y="99.9" font-family="system-ui,sans-serif" font-size="2" '
            'fill="#f8fafc">left chain</text>',
            '<circle cx="34" cy="99.2" r="1.2" fill="#c084fc"/>',
            '<text x="36.3" y="99.9" font-family="system-ui,sans-serif" font-size="2" '
            'fill="#f8fafc">right chain</text>',
            '<rect x="61" y="98.9" width="2" height="0.65" fill="#fde68a"/>',
            '<text x="64" y="99.9" font-family="system-ui,sans-serif" font-size="2" '
            'fill="#f8fafc">front 100 nF · VDD side</text>',
        ]
    )
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="112mm" height="119mm" '
        'viewBox="-9 -13 112 119">\n  '
        + "\n  ".join(parts)
        + "\n</svg>\n",
        encoding="utf-8",
    )


def replace_top_level_at(block: str, x: float, y: float, rotation: int) -> str:
    pattern = re.compile(
        r"(?m)^(\t\t)\(at\s+[-+\d.eE]+\s+[-+\d.eE]+(?:\s+[-+\d.eE]+)?\)"
    )
    replacement = rf"\1(at {x:.4f} {y:.4f} {rotation})"
    rewritten, count = pattern.subn(replacement, block, count=1)
    if count != 1:
        raise ValueError("Could not replace footprint top-level (at ...) field")
    return rewritten


def flip_cap_to_back(block: str) -> str:
    """Flip the symmetric 0402 footprint to B.Cu using KiCad layer tokens."""
    if re.search(r'(?m)^\t\t\(layer "B\.Cu"\)', block):
        return block
    if not re.search(r'(?m)^\t\t\(layer "F\.Cu"\)', block):
        raise ValueError("Paired capacitor footprint is not on F.Cu or B.Cu")
    layer_pairs = (
        ('"F.Cu"', '"B.Cu"'),
        ('"F.Paste"', '"B.Paste"'),
        ('"F.Mask"', '"B.Mask"'),
        ('"F.SilkS"', '"B.SilkS"'),
        ('"F.Fab"', '"B.Fab"'),
        ('"F.CrtYd"', '"B.CrtYd"'),
    )
    for front, back in layer_pairs:
        block = block.replace(front, back)
    return block


def upgrade_hole_to_m3(block: str) -> str:
    """Change the existing connected M2 DIN965 pad footprint to M3 DIN965."""
    replacements = (
        (
            'MountingHole:MountingHole_2.2mm_M2_DIN965_Pad',
            'MountingHole:MountingHole_3.2mm_M3_DIN965_Pad',
        ),
        ('Mounting Hole 2.2mm, M2', 'Mounting Hole 3.2mm, M3'),
        ('mountinghole M2 DIN965', 'mountinghole M3 DIN965'),
        ('(at 0 -2.85 0)', '(at 0 -3.75 0)'),
        ('(at 0 2.85 0)', '(at 0 3.75 0)'),
        ('(end 1.9 0)', '(end 2.8 0)'),
        ('(end 2.15 0)', '(end 3.05 0)'),
        ('(size 3.8 3.8)', '(size 5.6 5.6)'),
        ('(drill 2.2)', '(drill 3.2)'),
    )
    for old, new in replacements:
        if old not in block:
            raise ValueError(f"Expected M2 mounting-hole token missing: {old}")
        block = block.replace(old, new, 1)
    return block


def edge_cuts_text(outline: list[tuple[float, float]]) -> str:
    origin_x, origin_y = BOARD_ORIGIN
    # The Bézier helpers intentionally repeat join points.  Quantize and drop
    # duplicates so KiCad never receives zero-length Edge.Cuts segments.
    clean_outline: list[tuple[float, float]] = []
    for x, y in outline:
        point = (round(x, 4), round(y, 4))
        if not clean_outline or point != clean_outline[-1]:
            clean_outline.append(point)
    if len(clean_outline) > 1 and clean_outline[0] == clean_outline[-1]:
        clean_outline.pop()
    lines = []
    for start, end in zip(clean_outline, clean_outline[1:] + clean_outline[:1]):
        lines.append(
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
    return "\n".join(lines) + "\n"


def apply_to_board(
    board: str,
    footprints: list[Footprint],
    placements: list[Placement],
    outline: list[tuple[float, float]],
) -> str:
    if '(layer "Edge.Cuts")' in board:
        raise ValueError("Input already contains Edge.Cuts; refusing to duplicate the outline")

    placement_by_led = {item.led_ref: item for item in placements}
    placement_by_cap = {item.cap_ref: item for item in placements}
    replacements: dict[str, str] = {}
    for footprint in footprints:
        reference = footprint.reference
        block = footprint.block
        if reference in placement_by_led:
            item = placement_by_led[reference]
            block = replace_top_level_at(block, item.board_x, item.board_y, item.rotation)
            replacements[reference] = block
        elif reference in placement_by_cap:
            item = placement_by_cap[reference]
            block = replace_top_level_at(
                block, item.cap_board_x, item.cap_board_y, item.cap_rotation
            )
            replacements[reference] = block
        elif reference in MOUNTING_HOLES:
            local_x, local_y = MOUNTING_HOLES[reference]
            block = replace_top_level_at(
                block, BOARD_ORIGIN[0] + local_x, BOARD_ORIGIN[1] + local_y, 0
            )
            block = upgrade_hole_to_m3(block)
            replacements[reference] = block
        elif reference == "J1":
            block = replace_top_level_at(
                block,
                BOARD_ORIGIN[0] + USB_ORIGIN[0],
                BOARD_ORIGIN[1] + USB_ORIGIN[1],
                0,
            )
            replacements[reference] = block

    expected = 144 + 144 + 3 + 1
    if len(replacements) != expected:
        raise ValueError(f"Expected {expected} footprint rewrites; built {len(replacements)}")

    rewritten = board
    targets = [footprint for footprint in footprints if footprint.reference in replacements]
    for footprint in sorted(targets, key=lambda item: item.start, reverse=True):
        rewritten = (
            rewritten[: footprint.start]
            + replacements[footprint.reference]
            + rewritten[footprint.end :]
        )

    final_marker = "\n\t(embedded_fonts no)\n)"
    insertion = rewritten.rfind(final_marker)
    if insertion < 0:
        raise ValueError("Could not locate end of KiCad board for Edge.Cuts insertion")
    return rewritten[:insertion] + "\n" + edge_cuts_text(outline) + rewritten[insertion:]


def validate_applied_board(rewritten: str, placements: list[Placement]) -> None:
    footprints = {item.reference: item for item in parse_footprints(rewritten)}
    for item in placements:
        led = footprints[item.led_ref]
        cap = footprints[item.cap_ref]
        if not (
            math.isclose(led.x, item.board_x, abs_tol=5e-5)
            and math.isclose(led.y, item.board_y, abs_tol=5e-5)
            and math.isclose(led.rotation % 360, item.rotation % 360, abs_tol=1e-6)
        ):
            raise ValueError(f"Applied LED placement mismatch for {item.led_ref}")
        if not (
            math.isclose(cap.x, item.cap_board_x, abs_tol=5e-5)
            and math.isclose(cap.y, item.cap_board_y, abs_tol=5e-5)
            and math.isclose(cap.rotation % 360, item.cap_rotation % 360, abs_tol=1e-6)
            and re.search(r'(?m)^\t\t\(layer "F\.Cu"\)', cap.block)
        ):
            raise ValueError(f"Applied front-side capacitor mismatch for {item.cap_ref}")
    for reference, local_point in MOUNTING_HOLES.items():
        hole = footprints[reference]
        expected_x = BOARD_ORIGIN[0] + local_point[0]
        expected_y = BOARD_ORIGIN[1] + local_point[1]
        if not (
            math.isclose(hole.x, expected_x, abs_tol=5e-5)
            and math.isclose(hole.y, expected_y, abs_tol=5e-5)
            and '(drill 3.2)' in hole.block
            and '(size 5.6 5.6)' in hole.block
        ):
            raise ValueError(f"Applied M3 hole mismatch for {reference}")
    usb = footprints["J1"]
    if not (
        math.isclose(usb.x, BOARD_ORIGIN[0] + USB_ORIGIN[0], abs_tol=5e-5)
        and math.isclose(usb.y, BOARD_ORIGIN[1] + USB_ORIGIN[1], abs_tol=5e-5)
    ):
        raise ValueError("Applied USB-C placement mismatch")
    edge_count = len(re.findall(r'\(layer "Edge\.Cuts"\)', rewritten))
    if edge_count < 100:
        raise ValueError(f"Expected a detailed closed Edge.Cuts outline, found {edge_count} segments")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=BOARD_PATH)
    parser.add_argument("--preview", type=Path, default=PREVIEW_PATH)
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--dxf", type=Path, default=DXF_PATH)
    parser.add_argument(
        "--backup",
        type=Path,
        default=BOARD_PATH.with_name("HeartArray_pre_matrix_20260829.kicad_pcb"),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the reviewed placement, M3 holes, USB location, and Edge.Cuts to --board.",
    )
    args = parser.parse_args()

    board = args.board.read_text(encoding="utf-8")
    footprints = parse_footprints(board)
    leds = {
        footprint.reference: footprint
        for footprint in footprints
        if footprint.value == "WS2812B-MINI-V6" and footprint.reference.startswith("D")
    }
    chains = discover_chains(leds)
    cap_by_led = paired_caps(footprints, leds)
    outline = normalized_outline()
    placements = build_placements(chains, cap_by_led, outline)
    validate_geometry(outline, placements)

    write_preview(args.preview, outline, placements)
    write_csv(args.csv, placements, leds)
    write_r12_dxf(args.dxf, outline)

    if args.apply:
        rewritten = apply_to_board(board, footprints, placements, outline)
        validate_applied_board(rewritten, placements)
        if not args.backup.exists():
            args.backup.write_text(board, encoding="utf-8")
        args.board.write_text(rewritten, encoding="utf-8")

    print(f"Generated {len(placements)} LED placements on a {BOARD_SIZE_MM:.0f} mm heart")
    print(f"Chain 1: {chains[0][0]} -> {chains[0][-1]}")
    print(f"Chain 2: {chains[1][0]} -> {chains[1][-1]}")
    print(f"Preview: {args.preview}")
    print(f"Placement CSV: {args.csv}")
    print(f"Edge.Cuts DXF: {args.dxf}")
    if args.apply:
        print(f"Updated PCB: {args.board}")
        print(f"Original PCB backup: {args.backup}")


if __name__ == "__main__":
    main()
