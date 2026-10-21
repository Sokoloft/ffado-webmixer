# Peak-meter color scale — v1.1.1 development build

## What was corrected

Previously, the gradient lived on a dynamically resized peak fill. Even a
half-height green/yellow/red bar therefore looked red near its own top. That
could falsely suggest near-clipping at normal levels.

The full-height fader meter now carries a fixed, full-track green/yellow/red
color scale, clipped to reveal only the part the measured value reaches.
Crossbar Router meters use the same approach horizontally.

This is **not a calibrated dBFS meter**. The 0..1 scale represents FFADO's
visual mapping of actual DICE EAP 12-bit destination peaks. Its scale and
raw hardware normalization are unchanged. The red top band is a *visual near-
full-scale region*, while the separate red near-full-scale warning/hold is
triggered by the FFADO raw code at 4095 and persists for 4 seconds.

## Expected colors

| Normalized FFADO display level | Expected meter appearance |
| --- | --- |
| 0% | Empty/dark |
| 50% | Half-height green; no yellow/red |
| 85% | Green; no yellow/red |
| 93% | Green with yellow only near the top |
| 99% | Green, a short yellow band and red only at the very top |

The precise CSS color transitions are near 89–90% for yellow and 96–97% for
red. They are fixed positions on the meter track and not thresholds for
verified analogue or digital clipping.

## Tester checklist (Saffire / ProFire / other mapped DICE devices)

1. Start the v1.1.1-dev build and select a device that exposes a verified
   FFADO DICE EAP destination peak.
2. At safe signal levels, observe a mono channel meter at lower and normal
   levels. Its top edge should remain **green**, even if the bar occupies half
   or most of the track.
3. Increase a test signal carefully only if safe to do so. Yellow should
   appear only as the live bar enters the top section; red should occur only
   very close to the physical top. **Do not intentionally clip the hardware**
   merely to validate the warning colors.
4. Open In/Out → Crossbar Router and compare the horizontal destination meter
   for the same FFADO destination. It should follow the same absolute color
   distribution from left to right.
5. Link any two inputs (e.g. 2+5) and verify the Left and Right meter colors
   are independent, even when levels differ.
6. Confirm that peak-hold lines and actual near-full-scale warning holds still
   work; clicking a meter still clears its holds.
7. Repeat on another available FFADO DICE device. Unsupported devices, such
   as the original MOTU UltraLite without that API, should remain unmetered.

## Offline checks

From the project root:

```bash
python -m pytest -q
node tests/peak_display_test.cjs
```

If Chromium and Playwright are available for **testing only**:

```bash
python tests/verify_meter_colors_browser.py
```

That optional browser test samples the actual rendered pixels at normalized
levels 0.50, 0.85, 0.93 and 0.99, for both the vertical channel-strip meter
and the horizontal Crossbar Router meter. Those test packages are not required
for normal ffado-webmixer runtime.
