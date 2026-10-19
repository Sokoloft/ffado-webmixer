# Matrix → strip synchronization (v1.1.1 development build)

This change is based on the ProFire 2626 screenshots in GitHub issue #2.
It **does not change the hardware pan law, stereo routing, or matrix writes**.
Only hardware-state readback and channel-strip presentation change.

## What changed

- When output buses 1+2, 3+4, etc. are linked, `/api/state` now reads
  both native matrix coefficients for each input in one serialized transaction.
  The displayed mono-strip fader is the louder of the two coefficients; the
  pan position is the left/right coefficient ratio. Both are computed from
  that same read, including software-muted coefficients saved for recovery.
- With linked *inputs*, the displayed fader is the louder input, not
  arbitrarily the left input. When the two inputs differ by more than about
  0.1 dB, the label displays `MAX` and its tooltip reports both levels. It is
  **not** claiming that the two inputs have equal gain.
- When both input and output pairs are linked, the combined pan display is
  derived from the sum of the **native left** and **native right** coefficients
  for both inputs, not from an unweighted average of two pan percentages.
- The browser reloads strip state from FFADO after a matrix edit, and remote
  matrix edits delivered by the app's SSE stream trigger the same reload.
- The `/api/state` response includes `matrix_legs` (`left_db`, `right_db`) for
  each input on a linked output pair. A `null` leg represents the FFADO mute
  sentinel, not -60 dB.

## Check with the ProFire tester

1. Select a linked output bus pair (e.g., Bus 1+2). Set Input 4 → Output 1
   to -3.7 dB and Input 4 → Output 2 to -50.1 dB using the matrix editor.
   The Input 4 strip should show around **-3.7 dB**, with pan almost hard left.
2. Change the second crosspoint to -3.7 dB. The strip volume should stay
   around -3.7 dB and the pan should become centered **without needing to
   touch the pan control**.
3. Link Input 1+2. Set Input 1 → Output 1 to -0.4 dB and Input 2 → Output 2
   to -0.4 dB, with the other two cells disconnected. The linked strip should
   show around **-0.4 dB** and **centered balance**.
4. Change only Input 2 → Output 2 to -20 dB. The linked input strip should
   show `MAX -0.4 dB`; hover its level label to see the mismatch. Balance should
   shift left because the right output now has less signal.
5. Set all four crosspoints in this 2×2 block to -6.4 dB. The UI should
   display approximately -6.4 dB with centered balance. **Note:** this is
   **not the same stereo routing** as step 3; all four cells are active.
6. Open a second browser tab with the same device selected, edit the matrix
   in one tab, and check that the strip updates in the other tab. A different
   browser/external mixer writing directly to FFADO does not emit this app's
   SSE events, so its changes are visible on the next mixer state reload.
7. Repeat one edit with software mute active: the matrix editor and strip
   should display the *stored unmute level* while the actual FFADO cell is
   still silent. Do not test on loud speakers without monitoring levels down.

## Offline regression

Run from the extracted project root:

```bash
python -m pytest -q tests/test_matrix_live_strip_sync.py
python -m pytest -q
node --check ffado_webmixer/assets/static/index.js
```

These are simulated DICE/ProFire tests. Actual M-Audio hardware validation is
still required; in particular, this change does not establish the desired
-6 dB center pan law or correct stereo-linking write semantics.
