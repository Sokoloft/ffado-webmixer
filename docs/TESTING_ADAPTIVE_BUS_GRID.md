# Adaptive bus selector — v1.1.1 development verification

This is a **UI-only** change to the output/bus selector at the right of the mixer. It does not change FFADO D-Bus controls, matrix coefficients, bus linking, saved settings, or device profiles.

## Intended behavior

- **MOTU UltraLite and other small mixers (up to eight bus entries):** The bus grid uses at most **two columns**; a manually narrowed sidebar may display one. The separate Outputs group always uses at most two columns.
- **ProFire 2626 and other mixers with more buses:** If two columns make the panel too tall, the bus group grows leftward to **four, six, or additional columns** as the available window width permits. Devices without bus stereo links may use intermediate column counts.
- **Stereo bus links:** Both bus buttons remain directly above the link/unlink button for their pair; the entire pair is kept together when the grid becomes wider. Existing link status, selected bus, and event handling are unchanged.
- **Bounds:** Default width growth is limited to the application's sidebar maximum (60% of browser width, capped at 800 px). A saved or manually resized sidebar width takes precedence; narrow and mobile windows can scroll vertically instead of overflowing horizontally.
- **Resizing:** Drag the sidebar splitter left or right, double-click it to reset, and resize the browser vertically and horizontally. The bus-grid column count should adapt without losing bus selection or pair state.

## Tester steps

1. Start an interface with many buses, such as `python main.py --debug profire2626` (offline) or a real ProFire 2626 with the FFADO D-Bus service running.
2. At approximately 1440 × 900, check that the bus group grows beyond two columns when needed. Reduce window height to approximately 700 px and verify that it uses more columns when enough width is available.
3. Confirm each stereo bus pair still shows **Left bus**, **Right bus**, then its matching **Link/Unlink** button directly below those two buttons.
4. Link and unlink one bus pair, change buses, and confirm the original selection and pair states still update correctly. The layout must not rewrite hardware coefficients.
5. Drag the sidebar narrower; the panel should reduce the number of columns. Double-click the splitter to restore automatic sizing.
6. Repeat using `python main.py --debug motuultralite`: it should remain no wider than two bus columns regardless of window size.
7. Open the page on a phone-sized viewport. With many buses, the selector may scroll vertically instead of forcing the sidebar wider than the available space.

## Offline verification

```bash
python -m pytest -q
node tests/adaptive_bus_grid_ui_test.cjs
```

Node.js is only needed for the optional frontend regression test, not to run ffado-webmixer.

Real physical FFADO hardware verification is still recommended before declaring this a stable release.
