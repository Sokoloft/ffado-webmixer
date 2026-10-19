# Priority 7 — mixer Volume vs. hardware Input Gain

This release is a **label-only** clarification. The FFADO hardware commands, backend data fields, matrix coefficients, balances, mute journals and saved configurations have **not** been renamed or modified.

## Browser test (no FireWire hardware needed)

1. Start with `python main.py --demo`, then open the web interface.
2. Check the channel-strip fader: hovering over the fader/value should identify **Digital mixer volume**.
3. Check the separate scalar channel control: it should say **INPUT GAIN** and have a tooltip explaining that it is independent of digital mixer volume. Changing this field must still send the same `gain` API control as before.
4. Check the master fader: its tooltip should say **Output volume**.
5. In **In / Out**, on devices that expose a writable matrix, open the **Mixer matrix** tab and select a crosspoint. The knob, slider, numeric dB input, and preset selector should use **volume** terminology. Every cell's accessible label should describe the corresponding input → output mixer volume.
6. The exact dB values, percent-mode knob operation, write/readback behavior, solo/mute recovery, and stereo pairing should be unchanged.
7. Test keyboard or screen-reader access to the matrix knobs and precise editor: accessible names should say **volume**, not **gain**.

## Real ProFire 2626 verification

The ProFire's front-panel microphone preamp gain is **not** managed by webmixer's digital matrix knobs or channel faders. The software's digital matrix should label its adjustable levels **Volume**. The separate **INPUT GAIN** control should not be fabricated on a model lacking a source-mapped scalar gain/trim endpoint.

Run a routing/volume change and confirm the same matrix readback and channel-strip state as in the preceding channel-peak-meter build.

## Technical compatibility

The following existing identifiers are intentionally unchanged:

- `gain` for independently supported input trim/gain controls
- `gain_scale`, `matrix_gain`, and the internal coefficient helpers
- `fader` for the API's digital volume control
- FFADO D-Bus paths, XML profiles, `/api/matrix` payloads, mute-recovery journal records and saved settings

Do not rename these identifiers merely to match the user-facing wording: that would be a breaking, functional change unrelated to this priority.

## Automated checks

```bash
python -m pytest -q
node tests/matrix_cell_rotary_ui_test.cjs
```

This release was validated without the physical ProFire; verify appearance and behavior with rusk911's hardware before treating the UI as fully tested.
