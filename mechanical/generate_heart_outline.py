#!/usr/bin/env python3
"""Generate KiCad-importable heart outlines and a first-pass LED preview.

All dimensions are millimetres.  The DXF files use only an R12 closed POLYLINE,
which keeps KiCad's Edge.Cuts import simple and predictable.
"""

from __future__ import annotations

import math
import csv
from pathlib import Path


OUT_DIR = Path(__file__).resolve().parent


def standard_heart(width=100.0, height=100.0, margin=2.0, samples=360):
    raw = []
    for index in range(samples):
        t = 2.0 * math.pi * index / samples
        x = 16.0 * math.sin(t) ** 3
        y = (
            13.0 * math.cos(t)
            - 5.0 * math.cos(2.0 * t)
            - 2.0 * math.cos(3.0 * t)
            - math.cos(4.0 * t)
        )
        raw.append((x, y))

    min_x = min(x for x, _ in raw)
    max_x = max(x for x, _ in raw)
    min_y = min(y for _, y in raw)
    max_y = max(y for _, y in raw)
    usable_w = width - 2.0 * margin
    usable_h = height - 2.0 * margin

    # Flip mathematical +Y so the preview has its lobes at the top.
    return [
        (
            margin + (x - min_x) * usable_w / (max_x - min_x),
            margin + (max_y - y) * usable_h / (max_y - min_y),
        )
        for x, y in raw
    ]


def cubic(p0, p1, p2, p3, count=80):
    points = []
    for index in range(count):
        t = index / count
        u = 1.0 - t
        points.append(
            (
                u**3 * p0[0]
                + 3 * u * u * t * p1[0]
                + 3 * u * t * t * p2[0]
                + t**3 * p3[0],
                u**3 * p0[1]
                + 3 * u * u * t * p1[1]
                + 3 * u * t * t * p2[1]
                + t**3 * p3[1],
            )
        )
    return points


def radio_tab_heart():
    """100 x 110 mm heart with a 24 mm wide radio/electronics tab."""
    notch = (50.0, 20.0)
    left_upper = cubic(notch, (44.0, 5.0), (30.0, 2.0), (19.0, 7.0))
    left_side = cubic((19.0, 7.0), (4.0, 14.0), (1.0, 30.0), (5.0, 44.0))
    left_lower = cubic((5.0, 44.0), (9.0, 60.0), (24.0, 74.0), (38.0, 84.0))
    right_lower = cubic((62.0, 84.0), (76.0, 74.0), (91.0, 60.0), (95.0, 44.0))
    right_side = cubic((95.0, 44.0), (99.0, 30.0), (96.0, 14.0), (81.0, 7.0))
    right_upper = cubic((81.0, 7.0), (70.0, 2.0), (56.0, 5.0), notch)

    return (
        left_upper
        + left_side
        + left_lower
        + [(38.0, 84.0), (38.0, 109.0), (39.0, 110.0),
           (61.0, 110.0), (62.0, 109.0), (62.0, 84.0)]
        + right_lower
        + right_side
        + right_upper
    )


def write_r12_dxf(path, points):
    lines = [
        "0", "SECTION", "2", "HEADER", "9", "$ACADVER", "1", "AC1009",
        "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES",
        "0", "POLYLINE", "8", "EDGE_CUTS", "66", "1", "70", "1",
    ]
    for x, y in points:
        lines.extend(
            ["0", "VERTEX", "8", "EDGE_CUTS", "10", f"{x:.4f}",
             "20", f"{-y:.4f}", "30", "0.0"]
        )
    lines.extend(["0", "SEQEND", "0", "ENDSEC", "0", "EOF"])
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


def svg_path(points):
    commands = [f"M {points[0][0]:.4f},{points[0][1]:.4f}"]
    commands.extend(f"L {x:.4f},{y:.4f}" for x, y in points[1:])
    commands.append("Z")
    return " ".join(commands)


def write_outline_svg(path, points, width, height):
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm"
 viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#111827"/>
  <path d="{svg_path(points)}" fill="#ec4899" fill-opacity="0.18"
        stroke="#f472b6" stroke-width="0.45"/>
</svg>\n''',
        encoding="utf-8",
    )


def inside_polygon(point, polygon):
    x, y = point
    inside = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
        previous = current
    return inside


def point_segment_distance(point, a, b):
    px, py = point
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def edge_distance(point, polygon):
    return min(
        point_segment_distance(point, polygon[index - 1], polygon[index])
        for index in range(len(polygon))
    )


def inset_for_preview(polygon, clearance):
    """Fast visual inset; exact fabrication clearance is checked in KiCad later."""
    min_x = min(x for x, _ in polygon)
    max_x = max(x for x, _ in polygon)
    min_y = min(y for _, y in polygon)
    max_y = max(y for _, y in polygon)
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    scale_x = (max_x - min_x - 2.0 * clearance) / (max_x - min_x)
    scale_y = (max_y - min_y - 2.0 * clearance) / (max_y - min_y)
    return [
        (center_x + (x - center_x) * scale_x, center_y + (y - center_y) * scale_y)
        for x, y in polygon
    ]


def hex_candidates(polygon, width, height, pitch, x_phase, y_phase, exclusions=()):
    row_height = pitch * math.sqrt(3.0) / 2.0
    candidates = []
    row = 0
    y = y_phase
    while y <= height:
        x = x_phase + (pitch / 2.0 if row % 2 else 0.0)
        while x <= width:
            point = (x, y)
            excluded = any(x1 <= x <= x2 and y1 <= y <= y2 for x1, y1, x2, y2 in exclusions)
            if inside_polygon(point, polygon) and not excluded:
                candidates.append((row, x, y))
            x += pitch
        row += 1
        y = y_phase + row * row_height
    return candidates


def choose_led_positions(
    polygon,
    width=100.0,
    height=100.0,
    target=144,
    clearance=3.0,
    exclusions=(),
    split_at=None,
):
    best = None
    search_polygon = inset_for_preview(polygon, clearance)[::3]
    # Search both pitch and phase. Exact-count solutions are common; otherwise
    # choose the closest count and trim symmetric edge-most points.
    pitch_steps = range(800, 559, -2) if split_at else range(560, 801, 2)
    phase_steps = 10 if split_at else 5
    for pitch_step in pitch_steps:
        pitch = pitch_step / 100.0
        row_height = pitch * math.sqrt(3.0) / 2.0
        for x_index in range(phase_steps):
            for y_index in range(phase_steps):
                points = hex_candidates(
                    search_polygon,
                    width,
                    height,
                    pitch,
                    pitch * x_index / phase_steps,
                    row_height * y_index / phase_steps,
                    exclusions,
                )
                count = len(points)
                score = (abs(count - target), 0 if count >= target else 1, -pitch)
                if best is None or score < best[0]:
                    best = (score, pitch, points)
                if count == target:
                    ordered = serpentine(points)
                    if split_at is None:
                        return pitch, ordered
                    row_counts = []
                    for row in sorted({item[0] for item in points}):
                        row_counts.append(sum(item[0] == row for item in points))
                    cumulative = 0
                    for row_count in row_counts:
                        cumulative += row_count
                        if cumulative == split_at:
                            return pitch, ordered

    _, pitch, points = best
    if len(points) > target:
        # Remove the most weakly supported boundary positions in mirrored pairs.
        points = sorted(points, key=lambda item: edge_distance((item[1], item[2]), polygon))
        while len(points) > target:
            points.pop(0)
    return pitch, serpentine(points)


def serpentine(points):
    rows = {}
    for row, x, y in points:
        rows.setdefault(row, []).append((x, y))
    ordered = []
    for output_row, row in enumerate(sorted(rows)):
        row_points = sorted(rows[row], reverse=bool(output_row % 2))
        ordered.extend(row_points)
    return ordered


def write_led_preview(path, polygon, leds, pitch, width=100.0, height=100.0, module=None):
    led_size = 3.5
    elements = [
        f'<path d="{svg_path(polygon)}" fill="#f9a8d4" fill-opacity="0.13" '
        'stroke="#f472b6" stroke-width="0.45"/>',
    ]
    for number, (x, y) in enumerate(leds, start=1):
        color = "#fb7185" if number % 2 else "#f472b6"
        elements.append(
            f'<rect x="{x-led_size/2:.3f}" y="{y-led_size/2:.3f}" '
            f'width="{led_size}" height="{led_size}" rx="0.4" fill="{color}" '
            'stroke="#ffe4e6" stroke-width="0.18"/>'
        )
    if module:
        x, y, w, h = module
        elements.extend(
            [
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                'fill="#111827" fill-opacity="0.85" stroke="#67e8f9" stroke-width="0.45"/>',
                f'<rect x="{x}" y="{y+h-6.5}" width="{w}" height="6.5" '
                'fill="#22d3ee" fill-opacity="0.3" stroke="#67e8f9" stroke-width="0.25"/>',
                f'<text x="{x+w/2}" y="{y+h/2-1}" text-anchor="middle" '
                'font-family="sans-serif" font-size="2.5" fill="#cffafe">ESP32-C3</text>',
                f'<text x="{x+w/2}" y="{y+h-2}" text-anchor="middle" '
                'font-family="sans-serif" font-size="2.1" fill="#cffafe">antenna</text>',
            ]
        )
    elements.append(
        f'<text x="3" y="{height-2}" font-family="sans-serif" font-size="2.8" '
        f'fill="#e5e7eb">{len(leds)} LEDs · hex pitch {pitch:.2f} mm · 3.0 mm edge clearance</text>'
    )
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm"
 viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#111827"/>
  {''.join(elements)}
</svg>\n''',
        encoding="utf-8",
    )


def write_positions_csv(path, leds):
    """Write a serpentine D1..Dn placement list for a future KiCad script."""
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(("reference", "x_mm", "y_mm", "rotation_deg"))
        previous_y = None
        row_index = -1
        for number, (x, y) in enumerate(leds, start=1):
            if previous_y is None or abs(y - previous_y) > 0.1:
                row_index += 1
                previous_y = y
            writer.writerow((f"D{number}", f"{x:.3f}", f"{y:.3f}", 180 if row_index % 2 else 0))


def main():
    heart = standard_heart()
    write_r12_dxf(OUT_DIR / "heart_100x100_edgecuts.dxf", heart)
    write_outline_svg(OUT_DIR / "heart_100x100_outline.svg", heart, 100, 100)

    pitch, leds = choose_led_positions(heart, split_at=72)
    write_led_preview(
        OUT_DIR / "heart_100x100_led_preview.svg", heart, leds, pitch, 100, 100
    )
    write_positions_csv(OUT_DIR / "heart_100x100_led_positions.csv", leds)

    tab = radio_tab_heart()
    write_r12_dxf(OUT_DIR / "heart_radio_tab_100x110_edgecuts.dxf", tab)
    write_outline_svg(OUT_DIR / "heart_radio_tab_100x110_outline.svg", tab, 100, 112)
    tab_pitch, tab_leds = choose_led_positions(
        tab,
        width=100,
        height=110,
        exclusions=((34.0, 80.0, 66.0, 116.0),),
    )
    write_led_preview(
        OUT_DIR / "heart_radio_tab_layout_preview.svg",
        tab,
        tab_leds,
        tab_pitch,
        width=100,
        height=116,
        module=(41, 96, 18, 20),
    )
    write_positions_csv(OUT_DIR / "heart_radio_tab_led_positions.csv", tab_leds)

    print(f"Pure heart: {len(leds)} LEDs at {pitch:.2f} mm pitch")
    print(f"Radio-tab heart: {len(tab_leds)} LEDs at {tab_pitch:.2f} mm pitch")


if __name__ == "__main__":
    main()
