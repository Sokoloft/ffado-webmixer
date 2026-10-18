# v1.1.0-dev — Matrix gain precision testing

This update modifies **mixer gain coefficients** only where the exact source-defined FFADO profile declares a DICE EAP or RME matrix. It does **not** change the MOTU UltraLite bus-to-output assignment grid.

## Safety first

Use a low listening level, and start on a crosspoint that is not connected to important speakers. A value of **+6 dB** can substantially increase audio level. In/Out matrix editing affects the device hardware and can remain active after closing webmixer.

## Offline first (no D-Bus access)

```bash
python main.py --debug profire2626 --headless
```

Open the local mixer page. In **In/Out → Mixer matrix**, choose a cell and enter `-11.7` dB, then Apply. The debug terminal should show an intended `MatrixMixer.setValue` with a native integer coefficient, not the decimal `-11.7`. No FFADO D-Bus command is sent in debug mode.

Test the **−∞**, **0 dB**, **−6 dB**, **+3 dB**, **+6 dB** presets. Verify that the cell displays a value rounded to one decimal after applying it. Changes can differ by a small fraction at low levels because FFADO stores **integer native coefficients**.

Double-click a cell to select 0 dB in the editor; **Apply** is still required to change the device. Keyboard shortcuts when the knob is focused: `0` for 0 dB, `M` for silence, arrow keys in 0.1 dB increments, Shift+arrows in 1 dB increments.

## On a real DICE / RME interface

1. Open the device's **Mixer matrix** in the In/Out dialog.
2. Note the input and output labels and their current level before changing anything.
3. On an appropriate quiet signal path, enter `-12.3` dB and click **Apply**. Confirm that the returned level is approximately −12.3 dB.
4. Compare the same crosspoint in the original `ffado-mixer`. It should show essentially the same gain (within the hardware's native integer precision).
5. Test silence (−∞), unity (0 dB), and a non-round value such as −7.3 dB.
6. If using software mute, mute a channel, edit its matrix level, then unmute. The matrix should retain the new level, without briefly enabling the channel during editing.
7. Confirm the ordinary vertical fader displays one decimal place in dB and can be moved through fine adjustments without rounding every move to whole-percent steps.
8. On a MOTU UltraLite, confirm the In/Out view still assigns whole mix buses to physical stereo destinations and **never** offers a matrix gain editor there.

## Reporting any issue

Send the exact hardware model, GUID (if convenient), FFADO version, the selected input/output names and index, **requested dB**, **reported dB**, what the original `ffado-mixer` shows, and what the audible result was. Also include the application terminal traceback/error and a screenshot of the matrix editor if the UI behaves incorrectly. You do not need to troubleshoot the source yourself.

Read-only API snapshot:

```bash
curl -sS http://127.0.0.1:5000/api/describe > ffado-describe.json
curl -sS http://127.0.0.1:5000/api/matrix > ffado-matrix.json
```

The returned matrix may be large. These commands **read** the device; they don't alter audio settings.

The new matrix API also accepts a direct request with a `db` key, for example `{"input":0,"output":0,"db":-12.3}`; `null` represents −∞. This is a **write**, not a diagnostic command. The legacy `value` field (0–100) is still accepted for backward compatibility.

## Source and precision notes

Conversions are based on FFADO's `support/mixer-qt4/ffado/widgets/matrixmixer.py`, specifically `toDBvalue()` and `fromDBvalue()`: unity `16384`, and a lower silence sentinel at 16 native units. FFADO's Qt matrix editor uses a practical range of −60 to +6 dB. The DICE native field can encode values higher than +6 dB; the app reports those accurately but doesn't offer writing values beyond FFADO's UI range. At very low gain, the difference between adjacent native integer values may exceed 0.1 dB; the server returns the actual readback instead of a falsely exact requested value.

No calibrated physical dBu/dBV claims are made here; this is **digital matrix gain in dB relative to unity**, not analog input sensitivity or DICE peak-meter dBFS.
