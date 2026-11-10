#!/usr/bin/env python3
"""Generate heart outlines that accommodate ESP32-C3 antenna placement.

The preview SVGs are explanatory drawings.  Files ending in ``_edgecuts``
contain only one closed black path and are suitable for KiCad graphics import.
DXF copies are also produced because KiCad handles their millimetre geometry
more predictably for a final board outline.
"""

from __future__ import annotations

from pathlib import Path

from generate_heart_outline import cubic, standard_heart, svg_path, write_r12_dxf


OUT_DIR = Path(__file__).resolve().parent
WIDTH = 100.0
HEIGHT = 100.0

# ESP32-C3-WROOM-02 mechanical envelope, measured from the KiCad/Espressif
# module origin.  Its PCB antenna occupies the first 6.1 mm at the top end.
WROOM_WIDTH = 18.0
WROOM_HEIGHT = 20.0
ANTENNA_DEPTH = 6.1


def interpolate(a: tuple[float, float], b: tuple[float, float], count: int):
    return [
        (
            a[0] + (b[0] - a[0]) * index / count,
            a[1] + (b[1] - a[1]) * index / count,
        )
        for index in range(count)
    ]


def wide_notch_heart() -> list[tuple[float, float]]:
    """Heart with a 20 mm wide open notch for the WROOM antenna end.

    The WROOM is mounted on the back.  Its main body and all pads remain over
    FR4, while only the antenna end bridges the already-open centre notch.
    Nothing protrudes beyond the heart's 100 x 100 mm overall envelope.
    """
    base = standard_heart(samples=720)
    right_join = base[70]
    left_join = base[650]

    points: list[tuple[float, float]] = []
    points.extend(interpolate((42.0, 26.0), (58.0, 26.0), 24))
    points.extend(cubic((58.0, 26.0), (59.2, 26.0), (60.0, 25.2), (60.0, 24.0), 18))
    points.extend(cubic((60.0, 24.0), (60.0, 18.0), (60.1, 11.0), right_join, 36))
    points.extend(base[70:651])
    points.extend(cubic(left_join, (39.9, 11.0), (40.0, 18.0), (40.0, 24.0), 36))
    points.extend(cubic((40.0, 24.0), (40.0, 25.2), (40.8, 26.0), (42.0, 26.0), 18))
    return points


def soft_chin_heart() -> list[tuple[float, float]]:
    """Heart with a small rounded-flat chin for a bottom WROOM mount."""
    base = standard_heart(samples=720)
    right_join = base[280]
    left_join = base[440]

    points = list(base[:281])
    points.extend(cubic(right_join, (62.0, 84.0), (60.5, 90.0), (60.0, 94.0), 28))
    points.extend(cubic((60.0, 94.0), (59.7, 96.4), (58.5, 98.0), (56.0, 98.0), 18))
    points.extend(interpolate((56.0, 98.0), (44.0, 98.0), 20))
    points.extend(cubic((44.0, 98.0), (41.5, 98.0), (40.3, 96.4), (40.0, 94.0), 18))
    points.extend(cubic((40.0, 94.0), (39.5, 90.0), (38.0, 84.0), left_join, 28))
    points.extend(base[440:])
    return points


def usb_c_heart() -> list[tuple[float, float]]:
    """Classic heart with only a short 12 mm flat for a centered USB-C port."""
    base = standard_heart(samples=720)
    right_join = base[280]
    left_join = base[440]

    points = list(base[:281])
    points.extend(cubic(right_join, (58.7, 82.0), (57.2, 91.0), (57.0, 96.5), 30))
    points.extend(cubic((57.0, 96.5), (56.9, 97.4), (56.5, 98.0), (56.0, 98.0), 12))
    points.extend(interpolate((56.0, 98.0), (44.0, 98.0), 20))
    points.extend(cubic((44.0, 98.0), (43.5, 98.0), (43.1, 97.4), (43.0, 96.5), 12))
    points.extend(cubic((43.0, 96.5), (42.8, 91.0), (41.3, 82.0), left_join, 30))
    points.extend(base[440:])
    return points


def write_edgecuts_svg(path: Path, points: list[tuple[float, float]]):
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}mm" height="{HEIGHT}mm"
 viewBox="0 0 {WIDTH} {HEIGHT}">
  <path d="{svg_path(points)}" fill="none" stroke="#000000" stroke-width="0.20"/>
</svg>\n''',
        encoding="utf-8",
    )


def dimension_line(x1, y1, x2, y2, label, tx, ty):
    return (
        f'<path d="M{x1},{y1} L{x2},{y2}" class="dimension"/>'
        f'<path d="M{x1},{y1-1.0} L{x1},{y1+1.0} M{x2},{y2-1.0} L{x2},{y2+1.0}" class="dimension"/>'
        f'<text x="{tx}" y="{ty}" class="dimension-label">{label}</text>'
    )


def write_option_preview(
    path: Path,
    title: str,
    subtitle: str,
    outline: list[tuple[float, float]],
    module: tuple[float, float, float] | None,
    external_antenna: bool = False,
):
    elements = [f'<path d="{svg_path(outline)}" class="board"/>']

    if module:
        cx, cy, rotation = module
        elements.append(
            f'<g transform="translate({cx} {cy}) rotate({rotation})">'
            f'<rect x="{-WROOM_WIDTH/2}" y="{-13.1}" width="{WROOM_WIDTH}" height="{WROOM_HEIGHT}" class="module"/>'
            f'<rect x="{-WROOM_WIDTH/2}" y="{-13.1}" width="{WROOM_WIDTH}" height="{ANTENNA_DEPTH}" class="antenna"/>'
            '<text x="0" y="-1.0" class="module-label">WROOM-02</text>'
            '<text x="0" y="-9.7" class="antenna-label">6.1 mm antenna</text>'
            '</g>'
        )

    if external_antenna:
        elements.extend(
            [
                '<rect x="41" y="58" width="18" height="14.3" class="module"/>',
                '<text x="50" y="66" class="module-label">02U</text>',
                '<path d="M50,58 C54,48 67,45 71,31" class="coax"/>',
                '<rect x="64" y="20" width="20" height="10" rx="1" class="fpc"/>',
                '<text x="74" y="26" class="antenna-label">FPC antenna</text>',
            ]
        )

    if "notch" in path.name:
        elements.append(dimension_line(40, 28.5, 60, 28.5, "20 mm notch", 50, 31.5))
    elif "bottom" in path.name:
        elements.append(dimension_line(41, 106, 59, 106, "6.1 mm module overhang", 50, 109))

    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="120mm" height="124mm" viewBox="-10 -12 120 124">
  <style>
    .board {{ fill:#f9a8d4; fill-opacity:.30; stroke:#db2777; stroke-width:.55; }}
    .module {{ fill:#172554; fill-opacity:.92; stroke:#93c5fd; stroke-width:.45; }}
    .antenna {{ fill:#22d3ee; fill-opacity:.78; stroke:#0891b2; stroke-width:.35; }}
    .module-label,.antenna-label,.dimension-label {{ font-family:system-ui,sans-serif; text-anchor:middle; }}
    .module-label {{ fill:#dbeafe; font-size:2.5px; }}
    .antenna-label {{ fill:#083344; font-size:1.8px; font-weight:600; }}
    .dimension-label {{ fill:#334155; font-size:2.3px; }}
    .dimension {{ fill:none; stroke:#64748b; stroke-width:.28; }}
    .coax {{ fill:none; stroke:#0f172a; stroke-width:.65; }}
    .fpc {{ fill:#fbbf24; fill-opacity:.85; stroke:#b45309; stroke-width:.4; }}
    .title {{ font-family:system-ui,sans-serif; font-size:4px; font-weight:600; fill:#0f172a; text-anchor:middle; }}
    .subtitle {{ font-family:system-ui,sans-serif; font-size:2.5px; fill:#475569; text-anchor:middle; }}
  </style>
  <text x="50" y="-6" class="title">{title}</text>
  <text x="50" y="-1.5" class="subtitle">{subtitle}</text>
  {''.join(elements)}
</svg>\n''',
        encoding="utf-8",
    )


def write_recommended_preview(path: Path, outline: list[tuple[float, float]]):
    """Show the lobe-crown radio placement and the small USB-C flat."""
    # Put the WROOM's top at y=0.  The heart's crown is y=2 to y=4 below
    # most of the antenna, so the physical protrusion beyond the 100 mm
    # envelope is only about 2 mm while the RF end sees mostly open air.
    module_left = 64.5
    module_top = 0.0
    elements = [
        f'<path d="{svg_path(outline)}" class="board"/>',
        '<rect x="59.25" y="-5.25" width="28.5" height="11.5" class="keepout"/>',
        f'<rect x="{module_left}" y="{module_top}" width="18" height="20" class="module"/>',
        f'<rect x="{module_left}" y="{module_top}" width="18" height="6.1" class="antenna"/>',
        '<text x="73.5" y="14" class="module-label">WROOM-02 · back</text>',
        '<text x="73.5" y="3.7" class="antenna-label">antenna</text>',
        '<path d="M88.2,3.5 L95,7.5" class="leader"/>',
        '<text x="96" y="8.5" class="callout" text-anchor="start">all-layer RF keepout</text>',
        '<rect x="45.5" y="91.5" width="9" height="7" rx="0.8" class="usb"/>',
        '<path d="M44,98 L56,98" class="usb-edge"/>',
        '<text x="50" y="90" class="usb-label">USB-C</text>',
        '<path d="M61,0 L61,-2 M61,-1 L64.5,-1" class="dimension"/>',
        '<text x="62.7" y="-2.2" class="dimension-label">≈2 mm beyond heart envelope</text>',
    ]
    path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="130mm" height="126mm" viewBox="-10 -18 130 126">
  <style>
    .board {{ fill:#f9a8d4; fill-opacity:.30; stroke:#db2777; stroke-width:.55; }}
    .module {{ fill:#172554; fill-opacity:.92; stroke:#93c5fd; stroke-width:.45; }}
    .antenna {{ fill:#22d3ee; fill-opacity:.78; stroke:#0891b2; stroke-width:.35; }}
    .keepout {{ fill:#fde047; fill-opacity:.10; stroke:#ca8a04; stroke-width:.35; stroke-dasharray:1.2 1.0; }}
    .usb {{ fill:#64748b; stroke:#0f172a; stroke-width:.35; }}
    .usb-edge {{ stroke:#0f172a; stroke-width:.8; }}
    .leader,.dimension {{ fill:none; stroke:#64748b; stroke-width:.3; }}
    text {{ font-family:system-ui,sans-serif; fill:#0f172a; text-anchor:middle; }}
    .module-label {{ fill:#dbeafe; font-size:2.1px; }}
    .antenna-label {{ fill:#083344; font-size:1.9px; font-weight:600; }}
    .callout,.dimension-label,.usb-label {{ fill:#334155; font-size:2.2px; }}
    .title {{ font-size:4px; font-weight:600; }}
    .subtitle {{ fill:#475569; font-size:2.5px; }}
  </style>
  <text x="50" y="-13" class="title">Recommended · clean heart + lobe-edge radio</text>
  <text x="50" y="-8.5" class="subtitle">Current WROOM · tiny crown overhang · copper/component keepout · USB-C flat</text>
  {''.join(elements)}
</svg>\n''',
        encoding="utf-8",
    )


def main():
    pure = standard_heart(samples=720)
    notch = wide_notch_heart()
    chin = soft_chin_heart()
    usb = usb_c_heart()

    options = {
        "heart_rf_pure_100x100_edgecuts": pure,
        "heart_rf_center_notch_100x100_edgecuts": notch,
        "heart_rf_soft_chin_100x100_edgecuts": chin,
        "heart_rf_usb_lobe_100x100_edgecuts": usb,
    }
    for stem, points in options.items():
        write_edgecuts_svg(OUT_DIR / f"{stem}.svg", points)
        write_r12_dxf(OUT_DIR / f"{stem}.dxf", points)

    # Origin y=33.1 places the WROOM antenna between y=20.0 and y=26.1,
    # completely in the widened centre notch while its pads begin on the FR4.
    write_option_preview(
        OUT_DIR / "heart_rf_center_notch_preview.svg",
        "A · Centre-notch mount",
        "Current WROOM · no protrusion beyond the 100 mm heart envelope",
        notch,
        (50.0, 33.1, 0.0),
    )
    # After a 180° rotation the antenna begins at y=98 and ends at y=104.1.
    write_option_preview(
        OUT_DIR / "heart_rf_bottom_preview.svg",
        "B · Bottom mount",
        "Current WROOM · simplest RF placement · 6.1 mm physical overhang",
        chin,
        (50.0, 90.9, 180.0),
    )
    write_option_preview(
        OUT_DIR / "heart_rf_external_fpc_preview.svg",
        "C · WROOM-02U + hidden FPC",
        "Pure heart outline · no module overhang · antenna mounts in diffuser",
        pure,
        None,
        external_antenna=True,
    )
    write_recommended_preview(OUT_DIR / "heart_rf_usb_lobe_preview.svg", usb)


if __name__ == "__main__":
    main()
