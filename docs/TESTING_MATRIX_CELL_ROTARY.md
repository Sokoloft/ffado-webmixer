# v1.1.1 development build — inline matrix-cell rotary controls

## What changed

**In/Out → Mixer matrix** now shows a small rotary knob and its current hardware gain value in **every writable crosspoint**. Click a knob to open the existing precise dB/percentage editor, including presets and the **Apply** button. The original crosspoint identities, matrix APIs, and readback rules are unchanged.

## ProFire 2626 / DICE tester checklist

1. Open the Matrix tab and identify a known input/output crosspoint that is safe to adjust. Verify its small knob and displayed value agree with the original FFADO/ProFire mixer.
2. **Mouse or touchscreen:** drag the knob upward or downward. The UI previews while moving and issues **one write on release**, not one for every pixel. Check the terminal or D-Bus trace if available.
3. **Wheel:** hover over that knob and scroll. The value changes by **0.1 dB per tick** (Shift: **1 dB**). It is written after a short idle pause (~320 ms). The same pause applies to repeated arrow-key adjustments.
4. **Keyboard:** Tab to a knob, use arrow keys (0.1 dB; Shift=1 dB), `Home` or `M` (silence), `End` (+6 dB on the current DICE/RME mapping), and `0` (unity). Verify screen-reader slider label and reported dB value. For percentage matrices, arrow step is 1% (Shift=5%).
5. **Exact adjustment:** click a knob, enter `-11.7` in the lower editor, select **Apply**, and confirm readback. Double-click the knob to stage unity in that editor without writing until Apply.
6. **Isolation:** modify Input 1→Output 1 while observing Input 1→Output 2 and Input 2→Output 1. They must retain their prior levels. This UI change never links, rewires, or copies matrix coefficients.
7. **Failure recovery:** with an FFADO device temporarily unavailable, try an adjustment. You should see an error and the control should reload the hardware value rather than pretending the write succeeded.
8. **Multiple users:** modify a knob in one browser while viewing the matrix in another. The displayed gain should update after a refresh or a device event; controls must not become permanently disabled.
9. Confirm that the **Bus → outputs** selectors (MOTU) and the **Crossbar router** tab have not changed. This update affects only available writable mixer matrices.

## Automated checks

From the project root:

```bash
python -m pytest -q
node tests/matrix_cell_rotary_ui_test.cjs
```

Node.js is optional and is needed **only** for the offline browser simulation test; it is not a runtime dependency of ffado-webmixer. The tests use simulated hardware; physical ProFire testing is still required.
