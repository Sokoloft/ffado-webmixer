# Bus selector toolbar clearance — 1.1.1 development test

The bus selector must never touch or cover the routing, settings, or fullscreen
buttons above it, even for high bus counts, a maximized 2560×1440 window, or
on phones/tablets. The picker remains anchored to the bottom of the sidebar
and expands to the left when space permits.

## Manual checks

1. On a 2560 × 1440 desktop with a ProFire-style mixer with many buses, maximize
   the app. The top of the bus picker must stay clearly below the bottom of the
   routing/settings buttons. Check the same with the sidebar manually resized.
2. Reduce the window height to 900, 700 and 600 pixels. The grid should use
   more columns when possible and scroll within its own box when not possible;
   the buttons above it remain exposed.
3. Repeat with a 768 × 1024 tablet viewport and a 390 × 844 phone viewport.
   The bus box must stay below the toolbar with usable touch targets; it may
   scroll vertically. Test a short landscape viewport as well.
4. Check an UltraLite or another small mixer: the bus grid stays at two columns
   or fewer, with the same clearance under the toolbar.
5. Switch buses, select a stereo bus pair, open Settings and the hardware router,
   and confirm clicks still target the intended controls.

## Implementation details

The CSS `--bus-toolbar-gap` property reserves 28 px in a normal desktop window,
20 px in a phone-width viewport, or 14 px in a very short window. These values
are minimums; a shorter bus panel will leave more space because it is
bottom-aligned. The bus-grid JavaScript subtracts both vertical paddings from
the measured sidebar body height when selecting columns.

## Automated verification

```bash
python -m pytest -q
node tests/adaptive_bus_grid_ui_test.cjs
```

The UI regression covers the reserved height budget. A headless Chromium
geometry check at multiple window sizes also verifies the actual computed
separation between the header buttons and the picker. Physical mixer testing
remains recommended for general UI integration, but this change makes no
FFADO D-Bus writes.
