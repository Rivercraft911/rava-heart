#!/usr/bin/env python3
"""Place the HeartArray LEDs and their decoupling capacitors automatically.

The script discovers each WS2812 chain from the PCB's DIN/DOUT net names.  It
does not assume that D1, D2, ... are connected in numerical order.  The source
board is never modified; a new KiCad PCB, placement CSV, and SVG map are made.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path

from generate_heart_outline import (
    choose_led_positions,
    inside_polygon,
    standard_heart,
    svg_path,
)


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_INPUT = PROJECT_DIR / "hardware" / "HeartArray.kicad_pcb"
DEFAULT_OUTPUT = PROJECT_DIR / "hardware" / "HeartArray_autoplaced.kicad_pcb"
DEFAULT_CSV = SCRIPT_DIR / "heart_100x100_bus_placement.csv"
DEFAULT_SVG = SCRIPT_DIR / "heart_100x100_bus_placement.svg"

LED_VALUE = "WS2812B-MINI-V6"
CAP_VALUE = "100nF"
PIXELS_PER_CHAIN = 72
CAP_OFFSET_MM = 2.20
LAYOUT_SCALE = 0.94
MAX_BUS_STEP_MM = 6.30


@dataclass
class Footprint:
    start: int
    end: int
    block: str
    reference: str
    value: str
    x: float
    y: float
    rotation: float
    nets_by_function: dict[str, str]


@dataclass
class Placement:
    chain_index: int
    chain_step: int
    led_ref: str
    cap_ref: str
    x: float
    y: float
    led_rotation: int
    cap_x: float
    cap_y: float
    cap_rotation: int


def natural_number(reference: str) -> int:
    match = re.search(r"(\d+)$", reference)
    if not match:
        raise ValueError(f"Reference has no numeric suffix: {reference}")
    return int(match.group(1))


def matching_paren(text: str, start: int) -> int:
    """Return one-past the closing parenthesis at *start*, ignoring strings."""
    if text[start] != "(":
        raise ValueError("matching_paren() must start on '('")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    raise ValueError(f"Unclosed S-expression beginning at byte {start}")


def parse_pads(block: str) -> dict[str, str]:
    nets_by_function: dict[str, str] = {}
    for match in re.finditer(r"(?m)^\t\t(?=\(pad )", block):
        start = match.end()
        pad_block = block[start : matching_paren(block, start)]
        function_match = re.search(r'\(pinfunction "([^"]+)"\)', pad_block)
        net_match = re.search(r'\(net "([^"]+)"\)', pad_block)
        if function_match and net_match:
            # JLC-imported symbols append the pin number (DIN_4, DOUT_2).
            function = function_match.group(1).split("_", 1)[0].upper()
            nets_by_function[function] = net_match.group(1)
    return nets_by_function


def parse_footprints(board: str) -> list[Footprint]:
    footprints = []
    for match in re.finditer(r"(?m)^\t(?=\(footprint )", board):
        start = match.end()
        end = matching_paren(board, start)
        block = board[start:end]
        reference_match = re.search(r'\(property "Reference" "([^"]+)"', block)
        value_match = re.search(r'\(property "Value" "([^"]+)"', block)
        at_match = re.search(
            r"(?m)^\t\t\(at\s+([-+\d.eE]+)\s+([-+\d.eE]+)(?:\s+([-+\d.eE]+))?\)",
            block,
        )
        if not (reference_match and value_match and at_match):
            continue
        footprints.append(
            Footprint(
                start=start,
                end=end,
                block=block,
                reference=reference_match.group(1),
                value=value_match.group(1),
                x=float(at_match.group(1)),
                y=float(at_match.group(2)),
                rotation=float(at_match.group(3) or 0.0),
                nets_by_function=parse_pads(block),
            )
        )
    return footprints


def discover_chains(leds: dict[str, Footprint]) -> list[list[str]]:
    din_to_ref: dict[str, str] = {}
    for reference, led in leds.items():
        din = led.nets_by_function.get("DIN")
        dout = led.nets_by_function.get("DOUT")
        if not din or not dout:
            raise ValueError(f"{reference} does not have both DIN and DOUT nets")
        if din in din_to_ref:
            raise ValueError(f"DIN net {din!r} is used by more than one LED")
        din_to_ref[din] = reference

    successor = {
        reference: din_to_ref.get(led.nets_by_function["DOUT"])
        for reference, led in leds.items()
    }
    has_predecessor = {reference for reference in successor.values() if reference}
    heads = sorted(set(leds) - has_predecessor, key=natural_number)
    chains: list[list[str]] = []
    visited: set[str] = set()
    for head in heads:
        chain = []
        current: str | None = head
        while current:
            if current in visited:
                raise ValueError(f"Cycle or merged chains detected at {current}")
            visited.add(current)
            chain.append(current)
            current = successor[current]
        chains.append(chain)

    if visited != set(leds):
        missing = ", ".join(sorted(set(leds) - visited, key=natural_number))
        raise ValueError(f"LEDs not reached from a chain head: {missing}")
    return chains


def data_rotations(points: list[tuple[float, float]]) -> list[int]:
    """Orient each LED so DIN faces backward and DOUT faces forward."""
    rotations = []
    for index, point in enumerate(points):
        if index + 1 < len(points):
            direction_x = points[index + 1][0] - point[0]
        elif index:
            direction_x = point[0] - points[index - 1][0]
        else:
            direction_x = 1.0
        # At 180 degrees the imported footprint has DIN on the left and DOUT
        # on the right.  At 0 degrees, data travels right-to-left.
        rotations.append(180 if direction_x >= 0 else 0)
    return rotations


def body_safe_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Inset the center grid so complete LED/cap bodies clear the curved edge.

    The initial hex search uses center points.  A slight global contraction
    preserves every row and the 72/72 split.  The two narrow rows nearest the
    heart tip need a little extra vertical inset for a square 3.5 mm package.
    """
    safe = [
        (50.0 + (x - 50.0) * LAYOUT_SCALE, 50.0 + (y - 50.0) * LAYOUT_SCALE)
        for x, y in points
    ]
    # The center notch is concave, so radial scaling moves its nearest pixel
    # toward (rather than away from) the edge.  Nudge that one center pixel
    # down into the broad interior of the heart.
    safe = [
        (x, y + 1.00 if abs(x - 50.0) <= 2.0 and y < 30.0 else y)
        for x, y in safe
    ]
    bottom_rows = sorted({round(y, 8) for _, y in safe}, reverse=True)[:2]
    row_insets = {bottom_rows[0]: 1.50, bottom_rows[1]: 1.00}
    return [(x, y - row_insets.get(round(y, 8), 0.0)) for x, y in safe]


def continuous_bus_path(
    points: list[tuple[float, float]], start: int
) -> list[tuple[float, float]]:
    """Find a deterministic path that visits every point by a hex-grid edge.

    A simple row snake jumps across the concave notch between the two lobes.
    This Warnsdorff-style backtracking search only permits near-neighbor steps,
    so every schematic DOUT->DIN connection remains physically local.
    """
    count = len(points)
    adjacency = [
        [
            other
            for other, other_point in enumerate(points)
            if index != other and math.dist(point, other_point) <= MAX_BUS_STEP_MM
        ]
        for index, point in enumerate(points)
    ]
    if any(not neighbors for neighbors in adjacency):
        raise ValueError("A placement point has no neighbor in the bus-path graph")

    seen = [False] * count
    path = [start]
    seen[start] = True
    calls = 0
    call_limit = 1_000_000

    def remainder_is_connected(last: int) -> bool:
        remaining = {index for index in range(count) if not seen[index]}
        remaining.add(last)
        reached = {last}
        stack = [last]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor in remaining and neighbor not in reached:
                    reached.add(neighbor)
                    stack.append(neighbor)
        return len(reached) == len(remaining)

    def search(current: int) -> bool:
        nonlocal calls
        calls += 1
        if calls > call_limit:
            return False
        if len(path) == count:
            return True
        candidates = [neighbor for neighbor in adjacency[current] if not seen[neighbor]]
        candidates.sort(
            key=lambda candidate: (
                sum(not seen[next_point] for next_point in adjacency[candidate]),
                math.dist(points[current], points[candidate]),
                candidate,
            )
        )
        for candidate in candidates:
            seen[candidate] = True
            path.append(candidate)
            stranded = any(
                not seen[point]
                and not any(
                    not seen[neighbor] or neighbor == candidate
                    for neighbor in adjacency[point]
                )
                for point in range(count)
            )
            connected = len(path) % 6 != 0 or remainder_is_connected(candidate)
            if not stranded and connected and search(candidate):
                return True
            path.pop()
            seen[candidate] = False
        return False

    if not search(start):
        raise ValueError(
            f"Could not find a continuous {count}-point bus path within "
            f"{MAX_BUS_STEP_MM:.2f} mm steps"
        )
    return [points[index] for index in path]


def make_placements(
    chains: list[list[str]],
    points: list[tuple[float, float]],
    origin_x: float,
    origin_y: float,
) -> list[Placement]:
    if len(chains) != 2 or any(len(chain) != PIXELS_PER_CHAIN for chain in chains):
        lengths = ", ".join(str(len(chain)) for chain in chains)
        raise ValueError(f"Expected two {PIXELS_PER_CHAIN}-LED chains; found [{lengths}]")
    if len(points) != 2 * PIXELS_PER_CHAIN:
        raise ValueError(f"Expected 144 placement points; found {len(points)}")
    if math.isclose(points[PIXELS_PER_CHAIN - 1][1], points[PIXELS_PER_CHAIN][1]):
        raise ValueError("The 72/72 split cuts through a physical LED row")

    # Each chain owns complete rows, but the order within that region is a
    # true hex-grid path.  This avoids a long jump across the top notch.
    upper_points = points[:PIXELS_PER_CHAIN]
    lower_points = points[PIXELS_PER_CHAIN:]
    upper_start = max(
        range(len(upper_points)),
        key=lambda index: (upper_points[index][1], -upper_points[index][0]),
    )
    lower_start = max(range(len(lower_points)), key=lambda index: lower_points[index][1])
    point_sets = [
        continuous_bus_path(upper_points, upper_start),
        continuous_bus_path(lower_points, lower_start),
    ]
    placements = []
    for chain_index, (chain, local_points) in enumerate(zip(chains, point_sets), start=1):
        rotations = data_rotations(local_points)
        for chain_step, (reference, (local_x, local_y), rotation) in enumerate(
            zip(chain, local_points, rotations), start=1
        ):
            x = origin_x + local_x
            y = origin_y + local_y
            cap_ref = f"C{natural_number(reference)}"
            if rotation == 0:
                cap_x, cap_y, cap_rotation = x, y + CAP_OFFSET_MM, 0
            else:
                cap_x, cap_y, cap_rotation = x, y - CAP_OFFSET_MM, 180
            placements.append(
                Placement(
                    chain_index=chain_index,
                    chain_step=chain_step,
                    led_ref=reference,
                    cap_ref=cap_ref,
                    x=x,
                    y=y,
                    led_rotation=rotation,
                    cap_x=cap_x,
                    cap_y=cap_y,
                    cap_rotation=cap_rotation,
                )
            )
    return placements


def replace_footprint_at(block: str, x: float, y: float, rotation: int) -> str:
    pattern = re.compile(
        r"(?m)^(\t\t)\(at\s+[-+\d.eE]+\s+[-+\d.eE]+(?:\s+[-+\d.eE]+)?\)"
    )
    replacement = rf"\1(at {x:.4f} {y:.4f} {rotation})"
    new_block, count = pattern.subn(replacement, block, count=1)
    if count != 1:
        raise ValueError("Could not replace a footprint's top-level (at ...) field")
    return new_block


def edge_cuts_text(outline: list[tuple[float, float]], origin_x: float, origin_y: float) -> str:
    lines = []
    for start, end in zip(outline, outline[1:] + outline[:1]):
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


def rewrite_board(
    board: str,
    footprints: list[Footprint],
    placements: list[Placement],
    outline: list[tuple[float, float]],
    origin_x: float,
    origin_y: float,
) -> str:
    coordinates: dict[str, tuple[float, float, int]] = {}
    for placement in placements:
        coordinates[placement.led_ref] = (
            placement.x,
            placement.y,
            placement.led_rotation,
        )
        coordinates[placement.cap_ref] = (
            placement.cap_x,
            placement.cap_y,
            placement.cap_rotation,
        )

    rewritten = board
    targets = [footprint for footprint in footprints if footprint.reference in coordinates]
    if len(targets) != len(coordinates):
        present = {footprint.reference for footprint in targets}
        missing = ", ".join(sorted(set(coordinates) - present, key=natural_number))
        raise ValueError(f"Placement targets missing from board: {missing}")
    for footprint in sorted(targets, key=lambda item: item.start, reverse=True):
        x, y, rotation = coordinates[footprint.reference]
        new_block = replace_footprint_at(footprint.block, x, y, rotation)
        rewritten = rewritten[: footprint.start] + new_block + rewritten[footprint.end :]

    # This exact expression occurs only in actual graphics, not the layer table.
    if '(layer "Edge.Cuts")' in rewritten:
        raise ValueError("The input already has Edge.Cuts graphics; refusing to add a second outline")
    final_marker = "\n\t(embedded_fonts no)\n)"
    insertion = rewritten.rfind(final_marker)
    if insertion < 0:
        raise ValueError("Could not locate the end of the KiCad board")
    return rewritten[:insertion] + "\n" + edge_cuts_text(outline, origin_x, origin_y) + rewritten[insertion:]


def overlap_issues(placements: list[Placement]) -> list[str]:
    # Conservative component-body rectangles, plus 0.10 mm inspection gap.
    bodies: list[tuple[str, float, float, float, float]] = []
    for placement in placements:
        bodies.append((placement.led_ref, placement.x, placement.y, 1.75, 1.75))
        bodies.append((placement.cap_ref, placement.cap_x, placement.cap_y, 0.50, 0.31))
    issues = []
    for index, first in enumerate(bodies):
        for second in bodies[index + 1 :]:
            if (
                abs(first[1] - second[1]) < first[3] + second[3] + 0.10
                and abs(first[2] - second[2]) < first[4] + second[4] + 0.10
            ):
                issues.append(f"{first[0]} overlaps or crowds {second[0]}")
    return issues


def containment_issues(
    placements: list[Placement], outline: list[tuple[float, float]], origin_x: float, origin_y: float
) -> list[str]:
    local_outline = outline
    issues = []

    def rounded_pad_boundary(
        center_x: float, center_y: float, half_w: float, half_h: float, clearance: float
    ) -> list[tuple[float, float]]:
        boundary = []
        for sign_x in (-1, 1):
            for sign_y in (-1, 1):
                for step in range(7):
                    angle = math.pi * step / 12.0
                    boundary.append(
                        (
                            center_x + sign_x * (half_w + clearance * math.cos(angle)),
                            center_y + sign_y * (half_h + clearance * math.sin(angle)),
                        )
                    )
        return boundary

    for placement in placements:
        # Check the plastic body and a rounded 0.50 mm expansion around each
        # copper pad.  Rounded expansion matches KiCad's Euclidean clearance;
        # a single large bounding box is too conservative at curved corners.
        led_local_points = [
            (sx * 1.75, sy * 1.75) for sx in (-1, 1) for sy in (-1, 1)
        ]
        for pad_x in (-1.637541, 1.637541):
            for pad_y in (-0.890018, 0.890018):
                led_local_points.extend(
                    rounded_pad_boundary(pad_x, pad_y, 1.545009 / 2.0, 0.997003 / 2.0, 0.50)
                )
        cap_local_points = [
            (sx * 0.50, sy * 0.31) for sx in (-1, 1) for sy in (-1, 1)
        ]
        for pad_x in (-0.50, 0.50):
            cap_local_points.extend(rounded_pad_boundary(pad_x, 0.0, 0.28, 0.31, 0.50))

        objects = [
            (placement.led_ref, placement.x, placement.y, led_local_points),
            (placement.cap_ref, placement.cap_x, placement.cap_y, cap_local_points),
        ]
        for reference, x, y, local_points in objects:
            absolute_points = [
                (x - origin_x + local_x, y - origin_y + local_y)
                for local_x, local_y in local_points
            ]
            if not all(inside_polygon(point, local_outline) for point in absolute_points):
                issues.append(f"{reference} violates body or 0.50 mm copper-edge clearance")
    return issues


def write_csv(path: Path, placements: list[Placement], leds: dict[str, Footprint]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(
            [
                "chain",
                "chain_step",
                "led_reference",
                "cap_reference",
                "led_x_mm",
                "led_y_mm",
                "led_rotation_deg",
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
                    f"{item.x:.4f}",
                    f"{item.y:.4f}",
                    item.led_rotation,
                    f"{item.cap_x:.4f}",
                    f"{item.cap_y:.4f}",
                    item.cap_rotation,
                    leds[item.led_ref].nets_by_function["DIN"],
                    leds[item.led_ref].nets_by_function["DOUT"],
                ]
            )


def write_svg(
    path: Path,
    outline: list[tuple[float, float]],
    placements: list[Placement],
    origin_x: float,
    origin_y: float,
) -> None:
    colors = {1: "#fb7185", 2: "#a78bfa"}
    local_by_chain: dict[int, list[Placement]] = {1: [], 2: []}
    for placement in placements:
        local_by_chain[placement.chain_index].append(placement)
    elements = [
        '<rect width="100" height="100" fill="#111827"/>',
        f'<path d="{svg_path(outline)}" fill="#ec4899" fill-opacity="0.14" '
        'stroke="#f9a8d4" stroke-width="0.45"/>',
    ]
    for chain_index, chain in local_by_chain.items():
        points = " ".join(
            f"{item.x - origin_x:.4f},{item.y - origin_y:.4f}" for item in chain
        )
        color = colors[chain_index]
        elements.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="0.45" stroke-opacity="0.65"/>'
        )
        for item in chain:
            x = item.x - origin_x
            y = item.y - origin_y
            cap_x = item.cap_x - origin_x
            cap_y = item.cap_y - origin_y
            elements.append(
                f'<rect x="{x - 1.75:.4f}" y="{y - 1.75:.4f}" width="3.5" height="3.5" '
                f'rx="0.35" fill="{color}" fill-opacity="0.88"/>'
            )
            elements.append(
                f'<rect x="{cap_x - 0.5:.4f}" y="{cap_y - 0.31:.4f}" width="1" height="0.62" '
                'fill="#fde68a"/>'
            )
            if item.chain_step == 1 or item.chain_step % 12 == 0:
                elements.append(
                    f'<text x="{x:.4f}" y="{y + 0.7:.4f}" text-anchor="middle" '
                    f'font-family="monospace" font-size="1.45" fill="#111827">{item.led_ref}</text>'
                )
        first = chain[0]
        elements.append(
            f'<circle cx="{first.x - origin_x:.4f}" cy="{first.y - origin_y:.4f}" r="2.45" '
            f'fill="none" stroke="#ffffff" stroke-width="0.55"/>'
        )
    elements.extend(
        [
            '<rect x="2" y="91.5" width="43" height="6.5" rx="1.2" fill="#111827" fill-opacity="0.86"/>',
            '<circle cx="4.5" cy="94.6" r="1.2" fill="#fb7185"/>',
            '<text x="7" y="95.2" font-family="sans-serif" font-size="2.1" fill="#f9fafb">Chain 1 / 72</text>',
            '<circle cx="25" cy="94.6" r="1.2" fill="#a78bfa"/>',
            '<text x="27.5" y="95.2" font-family="sans-serif" font-size="2.1" fill="#f9fafb">Chain 2 / 72</text>',
        ]
    )
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm" '
        'viewBox="0 0 100 100">\n  '
        + "\n  ".join(elements)
        + "\n</svg>\n",
        encoding="utf-8",
    )


def validate_rewrite(output_text: str, placements: list[Placement]) -> None:
    reparsed = {footprint.reference: footprint for footprint in parse_footprints(output_text)}
    for item in placements:
        expected = {
            item.led_ref: (item.x, item.y, item.led_rotation),
            item.cap_ref: (item.cap_x, item.cap_y, item.cap_rotation),
        }
        for reference, (x, y, rotation) in expected.items():
            footprint = reparsed[reference]
            if not (
                math.isclose(footprint.x, x, abs_tol=5e-5)
                and math.isclose(footprint.y, y, abs_tol=5e-5)
                and math.isclose(footprint.rotation % 360, rotation % 360, abs_tol=1e-6)
            ):
                raise ValueError(f"Rewrite verification failed for {reference}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--svg", type=Path, default=DEFAULT_SVG)
    parser.add_argument("--origin-x", type=float, default=100.0)
    parser.add_argument("--origin-y", type=float, default=50.0)
    args = parser.parse_args()

    if args.input.resolve() == args.output.resolve():
        raise ValueError("Input and output must be different; the source board is intentionally protected")
    board = args.input.read_text(encoding="utf-8")
    footprints = parse_footprints(board)
    leds = {
        footprint.reference: footprint
        for footprint in footprints
        if footprint.value == LED_VALUE and footprint.reference.startswith("D")
    }
    caps = {
        footprint.reference: footprint
        for footprint in footprints
        if footprint.value == CAP_VALUE and footprint.reference.startswith("C")
    }
    expected_caps = {f"C{natural_number(reference)}" for reference in leds}
    missing_caps = expected_caps - set(caps)
    if missing_caps:
        missing = ", ".join(sorted(missing_caps, key=natural_number))
        raise ValueError(f"Missing paired 100 nF capacitors: {missing}")

    chains = discover_chains(leds)
    outline = standard_heart()
    pitch, points = choose_led_positions(outline, split_at=PIXELS_PER_CHAIN)
    points = body_safe_points(points)
    placements = make_placements(chains, points, args.origin_x, args.origin_y)

    overlaps = overlap_issues(placements)
    containment = containment_issues(placements, outline, args.origin_x, args.origin_y)
    if overlaps or containment:
        problems = "\n".join(f"  - {problem}" for problem in overlaps + containment)
        raise ValueError(f"Placement geometry validation failed:\n{problems}")

    output_text = rewrite_board(
        board, footprints, placements, outline, args.origin_x, args.origin_y
    )
    validate_rewrite(output_text, placements)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output_text, encoding="utf-8")
    write_csv(args.csv, placements, leds)
    write_svg(args.svg, outline, placements, args.origin_x, args.origin_y)

    print(f"Found {len(leds)} LEDs and {len(expected_caps)} paired capacitors")
    print(f"Discovered chain lengths: {', '.join(str(len(chain)) for chain in chains)}")
    for index, chain in enumerate(chains, start=1):
        first = leds[chain[0]]
        last = leds[chain[-1]]
        print(
            f"  Chain {index}: {chain[0]} ({first.nets_by_function['DIN']}) -> "
            f"{chain[-1]} ({last.nets_by_function['DOUT']})"
        )
    print(
        f"Hex pitch: {pitch * LAYOUT_SCALE:.2f} mm body-safe "
        f"({pitch:.2f} mm nominal); split is between complete rows"
    )
    print(f"Wrote PCB: {args.output}")
    print(f"Wrote CSV: {args.csv}")
    print(f"Wrote SVG: {args.svg}")


if __name__ == "__main__":
    main()
