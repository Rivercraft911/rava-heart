# Mechanical

The scripts that shaped the board. All dimensions are millimetres.

- `heart_matrix_94x88_refined_edgecuts.dxf`: the outline the board actually uses, 94.0 × 88.3 mm.
- `generate_heart_outline.py`, `generate_rf_heart_options.py`: generate heart outlines (and variants
  that leave room for the ESP32-C3 antenna) as KiCad-importable DXF.
- `place_leds_and_caps.py`, `place_heart_matrix.py`: place the 144 LEDs and their 100 nF capacitors.
  Placement follows the PCB's real DIN/DOUT nets, not the reference numbers. Without `--apply`,
  `place_heart_matrix.py` only writes the preview (`heart_matrix_94mm_preview.svg`) and the placement
  CSV (`heart_matrix_94mm_placement.csv`).
- `refine_heart_outline.py`: shortens the USB-C chin and rounds the centre notch. Only Edge.Cuts
  changes.
- `route_led_power.py`: stamps the 5 V / GND fan-out onto every LED cell
  (`led_power_autoroute_report.csv`).
