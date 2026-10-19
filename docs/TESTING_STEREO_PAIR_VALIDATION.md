# Stereo pairing validation (Priority 4)

This update builds on the **initial stereo pan display** release. It is a
validation/transaction fix only: it does **not** change stereo pan laws, FFADO
matrix gain values, or live routing.

## Expected behavior

1. Run `python main.py --debug profire2626` (or `--headless`).
2. On Bus 1, click the chain-link button on Input 2, then Input 5. The
   resulting strip shows **2+5** (Left 2, Right 5). A second click on the
   pending first channel cancels without changing anything.
3. Try selecting Input 2 or Input 5 for another pair. The existing pair
   remains unchanged; an invalid request does not move, rename, hide, or
   unhide any channel.
4. Switch to Bus 2. Pair Input 8 (Left) with Input 3 (Right); confirm the
   reverse numeric order works. Bus 1 still contains 2+5.
5. On Bus 2, unlink 8+3 by clicking its chain-link button. Bus 1's pair
   remains intact, and both Bus 2 channels regain their saved positions,
   pinned state, and minimized state.
6. Open two browser windows pointing to the same running mixer. Have the
   windows try to pair a shared channel to different partners on the same
   bus. The server accepts at most one operation; the losing browser shows
   an error and refreshes to the actual state.
7. With a slow connection, click link/unlink buttons repeatedly. While one
   operation is pending, the controls are disabled; duplicate changes aren't
   submitted. Changing output buses during an in-flight request must not
   overwrite the newly selected bus's pending selection.
8. Test invalid requests using the API (do **not** try on real hardware):

   ```bash
   curl -i -H 'Content-Type: application/json' \
      -d '{"action":"link","dragged":"ch/01","target":"ch/01"}' \
      'http://127.0.0.1:5000/api/stereo?mix=0'
   curl -i -H 'Content-Type: application/json' \
      -d '{"action":"link","dragged":"ch/01","target":"ch/04"}' \
      'http://127.0.0.1:5000/api/stereo?mix=invalid'
   ```

   Both should return HTTP 400 and preserve existing pair and layout state.

9. Reload the browser and restart the application. Confirm valid pairs remain
   saved. A malformed or overlapping pair in an older config is ignored; the
   first valid pair keeps its original Left→Right order. Back up the config
   before deliberately testing corruption.
10. Observe that link/unlink and rejected operations do **not** write any
    FFADO matrix coefficients or turn disconnected routes on.

## Automated checks

```bash
python -m pytest -q
node tests/stereo_validation_ui_test.cjs
node tests/stereo_pair_ui_test.cjs
node tests/stereo_bus_scope_ui_test.cjs
```

`tests/test_stereo_pair_validation.py` covers malformed link/unlink messages,
wrong bus indexes, duplicate channel assignments, two simultaneous browser
requests, save-failure rollback, corrupted saved pair lists, and per-bus
isolation. `stereo_validation_ui_test.cjs` exercises the actual JavaScript
pair-button state machine without needing a browser.

**Limits:** These are synthetic/debug-mode tests. They are not a substitute
for live ProFire 2626/FFADO verification, especially when multiple browsers
and multiple FireWire devices are attached.
