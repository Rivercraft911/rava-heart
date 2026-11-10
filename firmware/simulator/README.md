# Heart LED Lab

Open `index.html` directly in a browser. It has no build step and does not need
a local server.

The lab uses the exact ordered LED positions generated from the KiCad board. It
previews Heartbeat, Gravity Red, Flowing Rainbow, I-♥-U, Find Heart, and uploaded images or animated
GIFs. Hover an LED to see its diode reference, chain, address, and rendered RGB
value. Image/GIF mode uses a 5x5 area average at every physical LED location so
thin features do not disappear from single-pixel sampling.

`Export current frame JSON` writes pixels in the same order as the firmware:
chain 0 addresses 0-71 followed by chain 1 addresses 0-71.

After PCB LED placement or connectivity changes, regenerate all maps from the
project root:

```sh
python3 firmware/tools/generate_pixel_map.py
```

Run the dependency-free simulator tests with:

```sh
node firmware/simulator/test-engine.cjs
```

The Gravity Red panel has a two-dimensional acceleration pad. Drag to select
both direction and magnitude; the edge is 1 g and the center is 0 g. The liquid
uses the same conserved hydraulic-graph math as the firmware, while the Shake
button injects a directional momentum impulse.

The lab advances Heartbeat, Gravity Red, Flowing Rainbow, and Find Heart on the firmware's fixed
60 Hz frame cadence. Its effect, brightness, and gamma math mirror the firmware;
it does not emulate RMT interrupt scheduling or electrical propagation. Browser
image/GIF decoding exists only in the lab.

For an offline, deterministic conversion—including every animated GIF frame
and its duration—run:

```sh
python3 firmware/tools/convert_media.py input.gif --output output.json
```

The converter uses the same PCB outline, 5x5 physical-location sampling,
brightness, gamma, chain order, and addresses as the lab. Use `--help` for fit,
scale, offset, brightness, and gamma options.
