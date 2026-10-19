# Priority 2: arbitrary input stereo pairs and safe routing (v1.1.1 development build)

## Important: use low monitor levels

Please first check this release in `--debug profire2626` mode, then on
physical ProFire hardware with monitors turned down or disconnected. This
change has passed offline regression tests, **not** a real FireWire test.

## Link-button behavior

1. Open the mixer on any bus. Every visible, unpaired, unminimized **input**
   strip should have a chain/link button at the **lower right**.
2. Click channel **2**'s link button. That channel should be highlighted as
   **Left**, without immediately merging or changing an audio route.
3. Click channel **5**'s link button. Channel **2 is Left; channel 5 is Right**.
   The pair becomes one stereo strip at channel 2's position.
4. Unlink the pair using the same lower-right button. The two inputs should
   return, retaining their individual original matrix values.
5. Try **7 then 3**. The input order must remain **Left=7, Right=3**.
6. Click any unpaired link button twice: the first selection should cancel.
7. Try pairing a channel already linked to another pair: it should refuse
   without modifying either pair. Move between buses, refresh, and check the
   chosen order is preserved in settings.
8. Dragging strip handles should reorder, **not** link channels.

## Safety and matrix observations

1. In a stereo-linked *output bus* (Bus 1+2), set Input 2→Output 1 and
   Input 5→Output 2 to **−0.4 dB**, with both cross-routes **−∞**.
2. Record all four coefficients in the **In/Out → Mixer matrix** window.
3. Link **Input 2 (Left) → Input 5 (Right)**. **All four matrix coefficients
   must be unchanged**. Unlink and confirm they're still unchanged.
4. Link again. Adjust linked input **balance** from center, halfway Left,
   full Left, back to center, full Right, then center. Neither off-diagonal
   coefficient should ever become nonzero. The diagonal muted at the endstop
   should recover when the balance returns to center in the same session.
5. Repeat with all four coefficients preconfigured at −6.4 dB. Linking and
   unlinking must not replace this custom routing. Balance affects only the
   two designated diagonal coefficients; cross-routes remain at −6.4 dB.
6. Repeat with both diagonal routes **−∞**. Using balance or a linked-bus
   fader must not unexpectedly connect either of these routes.
7. While balance has a muted side, edit its diagonal matrix cell directly.
   This invalidates the in-memory balance restore reference, protecting your
   explicit matrix edit from being undone by the next pan gesture.
8. Verify the displayed pan is based on the **first-clicked input to the
   Left output** and **second-clicked input to the Right output**.

### Behavior and limits

- Input pairing is independent of output bus linking. Existing FFADO
  crosspoints are **never changed merely by linking or unlinking inputs**.
- An input that is totally disconnected from a stereo output pair stays
  disconnected when moving its fader. Use the matrix editor to deliberately
  create that routing first.
- Balance-on-input-pairs uses **existing diagonal coefficients only**, not
  a four-route stereo-to-mono conversion. Custom cross-routes remain in place.
- Full-left/right balance restoration uses an in-memory reference. Restarting
  the mixer, unlinking, or directly editing the related matrix cell clears it.
  The interface must never assume it can restore a previously silent route.
- This stage does not change the separate mono pan algorithm, bus linking,
  or introduce a new −6 dB center pan law. Hardware validation is required.

Please send the matrix before/after screenshots and any failed network request
from the browser console to the GitHub issue.
