# Regression: input stereo pairs must be independent per bus

This build fixes the issue where unlinking channels 7+8 on Bus 2 made channel 8
appear as an unpaired strip on Bus 1. It also replaces the fader button glyph
with a chain-link SVG. First-click Left/second-click Right behavior is unchanged.

## Reproduce with the ProFire debug backend

```bash
python main.py --debug profire2626
```

1. Select **Bus 1** and link **channel 7 (Left)** to **channel 8 (Right)**.
   Only the combined 7+8 strip should show on Bus 1.
2. Select **Bus 2**. Its channel 7 and 8 should still be independent.
3. Link **7→8** on Bus 2, then unlink that Bus 2 pair.
4. Return to **Bus 1**. Channel 8 must remain hidden behind the paired 7+8
   strip, and channel 7 must remain the visible Left strip.
5. Return to **Bus 2**. Channels 7 and 8 must be independent again.
6. Link **2→5** on Bus 2 and check that Bus 1's 7→8 pair is unchanged.
7. Test reverse order (8→3) to confirm the first click remains Left.
8. Change pin/minimize/order on Bus 2, link then unlink, and confirm that
   both channels recover their original saved layout attributes.
9. Refresh the browser and restart the app; the bus-specific pairings should
   persist. Verify the chain-link icon is shown on both paired and unpaired
   channels and follows the active theme color.

For a real ProFire: turn down/disconnect monitors before testing stereo pan,
faders, or router/matrix changes. The link/unlink operation itself must not
write matrix coefficients or introduce new audio paths.

## Saved settings compatibility

Old releases stored a single `stereo` list applying to every bus. This build
keeps that saved list as the starting value for unmodified buses, but writes
new changes to `stereo_by_mix` (keys are zero-based bus indexes). An explicit
`[]` for a bus means all pairs are intentionally unlinked **on that bus**.
Backing up `~/.config/ffado-webmixer/` before upgrading is recommended.
Downgrading to older releases will not preserve new per-bus customizations.

## Automated offline tests

```bash
python -m pytest -q
node tests/stereo_pair_ui_test.cjs
node tests/stereo_bus_scope_ui_test.cjs
```

These tests use a synthetic FFADO backend and do not verify actual FireWire
hardware behavior. Please share your Bus 1 and Bus 2 screenshots after testing.
