#!/usr/bin/env python3
"""Stamp local 5 V/GND fan-outs onto the HeartArray LED matrix.

The board's LED data routing is left byte-for-byte intact.  Every generated
power cell independently fans out the WS2812B-MINI-V6 power pads and its
paired 100 nF capacitor pads using four short F.Cu dogbones and four standard
0.60/0.30 mm through-vias.  The two solid inner planes join the same-net pads.

The same template is expressed in LED-local coordinates, so it follows both
0 and 180 degree footprint rotations.  References and pairings are discovered
from the repeated hierarchical sheets; annotation order is not assumed.

By default a separate candidate PCB and CSV report are written.  The input is
never overwritten.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from place_leds_and_caps import Footprint, matching_paren, natural_number, parse_footprints
from place_heart_matrix import paired_caps


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_BOARD = PROJECT_DIR / "hardware" / "HeartArray.kicad_pcb"
DEFAULT_OUTPUT = (
    PROJECT_DIR / "hardware" / "HeartArray_led_power_candidate.kicad_pcb"
)
DEFAULT_REPORT = SCRIPT_DIR / "led_power_autoroute_report.csv"

LED_VALUE = "WS2812B-MINI-V6"
TRACK_WIDTH_MM = 0.25
VIA_DIAMETER_MM = 0.60
VIA_DRILL_MM = 0.30


@dataclass(frozen=True)
class Pad:
    number: str
    net: str
    x: float
    y: float


@dataclass(frozen=True)
class RouteItem:
    kind: str
    role: str
    net: str
    start: tuple[float, float]
    end: tuple[float, float] | None = None


@dataclass(frozen=True)
class CellResult:
    led_ref: str
    cap_ref: str
    rotation: int
    status: str
    led_five_v_via: tuple[float, float] | None
    led_ground_via: tuple[float, float] | None
    cap_five_v_via: tuple[float, float] | None
    cap_ground_via: tuple[float, float] | None
    inserted_segments: int
    inserted_vias: int


def transform(
    origin: tuple[float, float], rotation_deg: float, local: tuple[float, float]
) -> tuple[float, float]:
    angle = math.radians(rotation_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    x, y = local
    return (
        origin[0] + cosine * x - sine * y,
        origin[1] + sine * x + cosine * y,
    )


def clean_point(point: tuple[float, float]) -> tuple[float, float]:
    return (round(point[0], 6), round(point[1], 6))


def point_segment_distance(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    px, py = point
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-18:
        return math.dist(point, start)
    ratio = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    return math.hypot(px - (x1 + ratio * dx), py - (y1 + ratio * dy))


def drc_problem_roles(
    report: str, cell_items: dict[str, list[RouteItem]]
) -> set[tuple[str, str]]:
    """Map KiCad geometry violations back to generated LED fan-out roles.

    The baseline board has no clearance/short/crossing errors.  Coordinates in
    these sections that lie on a generated item therefore identify a cell that
    must be left for manual routing.  A generous 0.40 mm matching radius covers
    KiCad's item anchor reporting as well as exact via centers.
    """
    relevant = {
        "clearance",
        "shorting_items",
        "tracks_crossing",
        "hole_clearance",
        "hole_to_hole",
        "copper_edge_clearance",
        "solder_mask_bridge",
        "holes_co_located",
    }
    result: set[tuple[str, str]] = set()
    for section in re.split(r"(?=^\[[^]]+\]:)", report, flags=re.MULTILINE):
        category_match = re.match(r"\[([^]]+)\]:", section)
        if not category_match or category_match.group(1) not in relevant:
            continue
        coordinates = [
            (float(x), float(y))
            for x, y in re.findall(
                r"@\(([-+\d.]+) mm,\s*([-+\d.]+) mm\)", section
            )
        ]
        for coordinate in coordinates:
            distances: list[tuple[float, str, str]] = []
            for led_ref, items in cell_items.items():
                for item in items:
                    if item.kind == "via":
                        distance = math.dist(coordinate, item.start)
                    else:
                        assert item.end is not None
                        distance = point_segment_distance(coordinate, item.start, item.end)
                    distances.append((distance, led_ref, item.role))
            if distances:
                distance, led_ref, role = min(distances)
                if distance <= 0.40:
                    result.add((led_ref, role))
    return result


def parse_pad_details(footprint: Footprint) -> dict[str, Pad]:
    pads: dict[str, Pad] = {}
    for match in re.finditer(r"(?m)^\t\t(?=\(pad )", footprint.block):
        start = match.end()
        block = footprint.block[start : matching_paren(footprint.block, start)]
        number_match = re.match(r'\(pad "([^"]+)"', block)
        at_match = re.search(
            r"\(at\s+([-+\d.eE]+)\s+([-+\d.eE]+)(?:\s+[-+\d.eE]+)?\)", block
        )
        net_match = re.search(r'\(net "([^"]+)"\)', block)
        if not (number_match and at_match and net_match):
            continue
        local = (float(at_match.group(1)), float(at_match.group(2)))
        x, y = transform((footprint.x, footprint.y), footprint.rotation, local)
        pads[number_match.group(1)] = Pad(
            number=number_match.group(1),
            net=net_match.group(1),
            x=round(x, 6),
            y=round(y, 6),
        )
    return pads


def parse_existing_routes(board: str) -> tuple[set[tuple], set[tuple]]:
    segments: set[tuple] = set()
    vias: set[tuple] = set()
    for match in re.finditer(r"(?m)^\t(?=\(segment)", board):
        start = match.end()
        block = board[start : matching_paren(board, start)]
        start_match = re.search(r"\(start\s+([-+\d.eE]+)\s+([-+\d.eE]+)\)", block)
        end_match = re.search(r"\(end\s+([-+\d.eE]+)\s+([-+\d.eE]+)\)", block)
        layer_match = re.search(r'\(layer "([^"]+)"\)', block)
        net_match = re.search(r'\(net "([^"]+)"\)', block)
        if not (start_match and end_match and layer_match and net_match):
            continue
        point_a = clean_point((float(start_match.group(1)), float(start_match.group(2))))
        point_b = clean_point((float(end_match.group(1)), float(end_match.group(2))))
        endpoints = tuple(sorted((point_a, point_b)))
        segments.add((net_match.group(1), layer_match.group(1), endpoints))
    for match in re.finditer(r"(?m)^\t(?=\(via)", board):
        start = match.end()
        block = board[start : matching_paren(board, start)]
        at_match = re.search(r"\(at\s+([-+\d.eE]+)\s+([-+\d.eE]+)\)", block)
        net_match = re.search(r'\(net "([^"]+)"\)', block)
        if at_match and net_match:
            point = clean_point((float(at_match.group(1)), float(at_match.group(2))))
            vias.add((net_match.group(1), point))
    return segments, vias


def segment_text(net: str, start: tuple[float, float], end: tuple[float, float]) -> str:
    return "\n".join(
        [
            "\t(segment",
            f"\t\t(start {start[0]:.6f} {start[1]:.6f})",
            f"\t\t(end {end[0]:.6f} {end[1]:.6f})",
            f"\t\t(width {TRACK_WIDTH_MM:.2f})",
            '\t\t(layer "F.Cu")',
            f'\t\t(net "{net}")',
            f'\t\t(uuid "{uuid.uuid4()}")',
            "\t)",
        ]
    )


def via_text(net: str, point: tuple[float, float]) -> str:
    return "\n".join(
        [
            "\t(via",
            f"\t\t(at {point[0]:.6f} {point[1]:.6f})",
            f"\t\t(size {VIA_DIAMETER_MM:.2f})",
            f"\t\t(drill {VIA_DRILL_MM:.2f})",
            '\t\t(layers "F.Cu" "B.Cu")',
            f'\t\t(net "{net}")',
            f'\t\t(uuid "{uuid.uuid4()}")',
            "\t)",
        ]
    )


def local_cell_items(led: Footprint, cap: Footprint) -> list[RouteItem]:
    """Build the two-rail template using actual saved pad centers.

    The LED vias sit in the unused center channel between the V6's left and
    right pad columns.  The capacitor vias sit just outside its pads.  This
    avoids via-in-pad solder wicking and, crucially, does not cross the data
    tracks that the user has already completed between cells.
    """
    led_pads = parse_pad_details(led)
    cap_pads = parse_pad_details(cap)
    if not {"1", "3"}.issubset(led_pads) or not {"1", "2"}.issubset(cap_pads):
        raise ValueError(f"Missing expected pads on {led.reference}/{cap.reference}")
    if led_pads["1"].net != "5V" or led_pads["3"].net != "GND":
        raise ValueError(f"Unexpected LED power nets on {led.reference}")
    if cap_pads["1"].net != "5V" or cap_pads["2"].net != "GND":
        raise ValueError(f"Unexpected capacitor power nets on {cap.reference}")

    origin = (led.x, led.y)
    rotation = led.rotation
    # The paired capacitor is always at local (0, -2.0) and rotates with the LED.
    expected_cap = transform(origin, rotation, (0.0, -2.0))
    if math.dist(expected_cap, (cap.x, cap.y)) > 0.02 or not math.isclose(
        cap.rotation % 360, rotation % 360, abs_tol=0.02
    ):
        raise ValueError(
            f"{led.reference}/{cap.reference} no longer matches the generated cell geometry"
        )

    led_vdd_via = clean_point(transform(origin, rotation, (-0.70, -0.890018)))
    led_gnd_via = clean_point(transform(origin, rotation, (0.70, 0.890018)))
    cap_vdd_via = clean_point(transform(origin, rotation, (-1.15, -2.0)))
    cap_gnd_via = clean_point(transform(origin, rotation, (1.15, -2.0)))

    led_vdd = clean_point((led_pads["1"].x, led_pads["1"].y))
    led_gnd = clean_point((led_pads["3"].x, led_pads["3"].y))
    cap_vdd = clean_point((cap_pads["1"].x, cap_pads["1"].y))
    cap_gnd = clean_point((cap_pads["2"].x, cap_pads["2"].y))
    return [
        RouteItem("segment", "led_5v", "5V", led_vdd, led_vdd_via),
        RouteItem("via", "led_5v", "5V", led_vdd_via),
        RouteItem("segment", "led_gnd", "GND", led_gnd, led_gnd_via),
        RouteItem("via", "led_gnd", "GND", led_gnd_via),
        RouteItem("segment", "cap_5v", "5V", cap_vdd, cap_vdd_via),
        RouteItem("via", "cap_5v", "5V", cap_vdd_via),
        RouteItem("segment", "cap_gnd", "GND", cap_gnd, cap_gnd_via),
        RouteItem("via", "cap_gnd", "GND", cap_gnd_via),
    ]


def write_report(path: Path, results: list[CellResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(
            [
                "led_reference",
                "cap_reference",
                "rotation_deg",
                "status",
                "led_5v_via_x_mm",
                "led_5v_via_y_mm",
                "led_gnd_via_x_mm",
                "led_gnd_via_y_mm",
                "cap_5v_via_x_mm",
                "cap_5v_via_y_mm",
                "cap_gnd_via_x_mm",
                "cap_gnd_via_y_mm",
                "inserted_segments",
                "inserted_vias",
            ]
        )
        for result in sorted(results, key=lambda item: natural_number(item.led_ref)):
            writer.writerow(
                [
                    result.led_ref,
                    result.cap_ref,
                    result.rotation,
                    result.status,
                    "" if result.led_five_v_via is None else f"{result.led_five_v_via[0]:.4f}",
                    "" if result.led_five_v_via is None else f"{result.led_five_v_via[1]:.4f}",
                    "" if result.led_ground_via is None else f"{result.led_ground_via[0]:.4f}",
                    "" if result.led_ground_via is None else f"{result.led_ground_via[1]:.4f}",
                    "" if result.cap_five_v_via is None else f"{result.cap_five_v_via[0]:.4f}",
                    "" if result.cap_five_v_via is None else f"{result.cap_five_v_via[1]:.4f}",
                    "" if result.cap_ground_via is None else f"{result.cap_ground_via[0]:.4f}",
                    "" if result.cap_ground_via is None else f"{result.cap_ground_via[1]:.4f}",
                    result.inserted_segments,
                    result.inserted_vias,
                ]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", type=Path, default=DEFAULT_BOARD)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--skip",
        action="append",
        default=[],
        metavar="DREF",
        help="LED reference to leave untouched; may be repeated",
    )
    parser.add_argument(
        "--exclude-from-drc",
        action="append",
        default=[],
        type=Path,
        metavar="REPORT",
        help="KiCad DRC report whose generated problem cells should be skipped",
    )
    args = parser.parse_args()

    input_path = args.board.resolve()
    output_path = args.output.resolve()
    report_path = args.report.resolve()
    if input_path == output_path:
        raise ValueError("Input and output paths must differ")
    board = input_path.read_text(encoding="utf-8")
    footprints = parse_footprints(board)
    leds = {item.reference: item for item in footprints if item.value == LED_VALUE}
    all_footprints = {item.reference: item for item in footprints}
    pairs = paired_caps(footprints, leds)
    if len(pairs) != 144:
        raise ValueError(f"Expected 144 LED/cap pairs, found {len(pairs)}")

    cell_items: dict[str, list[RouteItem]] = {}
    custom_geometry: set[str] = set()
    for led_ref, cap_ref in pairs.items():
        try:
            cell_items[led_ref] = local_cell_items(leds[led_ref], all_footprints[cap_ref])
        except ValueError as error:
            if "no longer matches the generated cell geometry" not in str(error):
                raise
            custom_geometry.add(led_ref)

    skip = set(args.skip)
    excluded_roles: set[tuple[str, str]] = set()
    for exclusion_path in args.exclude_from_drc:
        excluded_roles.update(
            drc_problem_roles(exclusion_path.read_text(encoding="utf-8"), cell_items)
        )
    unknown = skip - set(leds)
    if unknown:
        raise ValueError(f"Unknown --skip references: {', '.join(sorted(unknown))}")
    existing_segments, existing_vias = parse_existing_routes(board)
    generated_segments = set(existing_segments)
    generated_vias = set(existing_vias)
    additions: list[str] = []
    results: list[CellResult] = []

    for led_ref in sorted(leds, key=natural_number):
        cap_ref = pairs[led_ref]
        led = leds[led_ref]
        cap = all_footprints[cap_ref]
        if led_ref in custom_geometry:
            results.append(
                CellResult(
                    led_ref,
                    cap_ref,
                    round(led.rotation) % 360,
                    "skipped_custom_geometry",
                    None,
                    None,
                    None,
                    None,
                    0,
                    0,
                )
            )
            continue
        items = cell_items[led_ref]
        via_by_role = {item.role: item.start for item in items if item.kind == "via"}
        if led_ref in skip:
            results.append(
                CellResult(
                    led_ref,
                    cap_ref,
                    round(led.rotation) % 360,
                    "skipped_by_request",
                    via_by_role["led_5v"],
                    via_by_role["led_gnd"],
                    via_by_role["cap_5v"],
                    via_by_role["cap_gnd"],
                    0,
                    0,
                )
            )
            continue

        blocked_roles = sorted(
            role for candidate_ref, role in excluded_roles if candidate_ref == led_ref
        )

        segment_count = 0
        via_count = 0
        for item in items:
            if item.role in blocked_roles:
                continue
            if item.kind == "segment":
                assert item.end is not None
                endpoints = tuple(sorted((clean_point(item.start), clean_point(item.end))))
                key = (item.net, "F.Cu", endpoints)
                if key in generated_segments or math.dist(item.start, item.end) < 1e-5:
                    continue
                additions.append(segment_text(item.net, item.start, item.end))
                generated_segments.add(key)
                segment_count += 1
            else:
                key = (item.net, clean_point(item.start))
                if key in generated_vias:
                    continue
                additions.append(via_text(item.net, item.start))
                generated_vias.add(key)
                via_count += 1
        results.append(
            CellResult(
                led_ref,
                cap_ref,
                round(led.rotation) % 360,
                "generated" if not blocked_roles else "partial_manual:" + "+".join(blocked_roles),
                via_by_role["led_5v"],
                via_by_role["led_gnd"],
                via_by_role["cap_5v"],
                via_by_role["cap_gnd"],
                segment_count,
                via_count,
            )
        )

    marker = "\n\t(zone\n"
    insertion = board.find(marker)
    if insertion < 0:
        raise ValueError("Could not locate first top-level zone for routing insertion")
    rewritten = board[:insertion] + "\n" + "\n".join(additions) + "\n" + board[insertion:]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rewritten, encoding="utf-8")
    write_report(report_path, results)
    full_cells = sum(item.status == "generated" for item in results)
    partial_cells = sum(item.status.startswith("partial_manual:") for item in results)
    custom_cells = sum(item.status == "skipped_custom_geometry" for item in results)
    requested_skips = sum(item.status == "skipped_by_request" for item in results)
    print(
        f"Wrote {output_path}\n"
        f"Wrote {report_path}\n"
        f"Generated {sum(item.inserted_segments for item in results)} segments and "
        f"{sum(item.inserted_vias for item in results)} vias. "
        f"Cells: {full_cells} complete, {partial_cells} partial, "
        f"{custom_cells} custom-geometry skipped, {requested_skips} user-skipped."
    )


if __name__ == "__main__":
    main()
