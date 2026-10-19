# Initial stereo pan display — Priority 3

This change is readback / display only. **Do not assume it has been validated
on physical ProFire hardware.** Linking/unlinking is still routing-neutral,
and the write-side pan law is unchanged.

## Requirements

- Current ffado-webmixer 1.1.1 development build with the initial-pan-readback changes included
  over the **stereo bus visibility** release.
- Supported DICE/RME hardware, such as the ProFire 2626; FFADO mixer service
  running and a compatible output bus pair configured as stereo.
- Hardware output levels turned down while testing and a backup of the
  current routing/matrix values.

## Manual reproduction

1. On Bus 1 (Left of a linked output pair), open the matrix editor. Silence
   the four cells at Left Input 2 / Right Input 5 × Left / Right output.
2. Set Input 2 → Left Output to approximately **−0.4 dB** and Input 5 →
   Right Output to approximately **−6.4 dB**. Keep their two cross-routes
   disconnected.
3. Close the matrix editor, click Input 2's chain link button, then Input 5's.
   Input 2 is **Left** and Input 5 is **Right**.
4. **Without touching the new PAN slider**, confirm the combined strip shows
   about **L50**. It should not start centered. Opening the matrix editor
   must not change any of the four gains.
5. Swap the two diagonal gains and reload/switch buses. The readout should
   be about **R50**, without any pan movement.
6. Equalize both diagonals; on refresh the pan should read **0**. Move PAN
   to L50, center, R50 and refresh after each change; the same values should
   be displayed again (allow small native rounding errors).
7. Silence both diagonal routes. The display should read **—**, and the
   slider should be disabled. Changing the link must not activate a route.
8. Connect only one diagonal route. PAN should show **L100** or **R100**,
   with a tooltip noting that the other side cannot be reconnected from PAN.
9. Add a deliberate cross-route. The balance value should receive an `*`
   and a tooltip explaining that it summarizes **diagonal** balance only.
   Removing cross-routes should remove the asterisk; they must never be
   changed by a pan **read** or pair link.
10. Link **8 first, then 3** on an otherwise unpaired bus and confirm the
    opposite physical numbering does not change which is Left/Right. Change
    buses and confirm each bus displays its own hardware state and pairs.

## Offline regression tests

From the project root:

```bash
python -m pytest -q tests/test_initial_stereo_pan.py
node tests/initial_pan_ui_test.cjs
```

Other existing tests must also pass. An unavailable balance is an intentional
state: the UI should not fake a centered value when the selected diagonal
routes provide no information. These tests exercise FFADO simulation, not
FireWire hardware or KDE/Qt.
