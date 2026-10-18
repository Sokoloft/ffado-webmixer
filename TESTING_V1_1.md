# ffado-webmixer 1.1.0-dev — hardware and debug testing

This build contains broad changes to discovery, profile matching, routing, and
mixer behavior. **Use a low monitor level and do not test on a live performance.**
Make a backup of `~/.config/ffado-webmixer/` and save known-good FFADO mixer
routing before changing any hardware assignments. This build has no live
ProFire/DICE/RME verification; the tests use an offline D-Bus double.

## Start without hardware (`--debug`)

From the project root, with the release dependencies installed:

```bash
python main.py --debug list
python main.py --debug profire2626 --headless
# Or open the desktop GUI:
python main.py --debug motuultralite
python main.py --debug saffirepro26
```

Open `http://127.0.0.1:5000/` in headless mode. The debug backend **does not
import, connect to, read, or write FFADO D-Bus**. It synthesizes UI sample
values and prints actions like:

```text
[DEBUG would call D-Bus] /org/ffado/Control/DeviceManager/.../EAP/MatrixMixer MatrixMixer.setValue (0, 0, 16384)
```

The synthetic channels/dimensions are UI fixtures, **not** a source of truth
for the real hardware. `--debug` never modifies `~/.config/ffado-webmixer/`.
Debug is useful to check page layout, buttons, and the planned D-Bus methods.
It is not a substitute for live hardware testing.

## Connect real FFADO devices

```bash
python main.py --headless
```

Connect one device first. Confirm `ffado-dbus-server` is running in the same
D-Bus session. Open the mixer and verify the model shown is the actual device,
not just a generic DICE or MOTU identity. The server reads ConfigROM
identifiers, resolves an **exact model-specific XML profile** from FFADO's
source-defined configuration, and then accesses the named D-Bus endpoints.
It no longer guesses gain matrices from dimensions or labels.

A recognized ConfigROM identity is **not** a guarantee that its mixer is
supported: a control profile must declare the precise matrix path. Devices
without such a profile will be reported as unsupported instead of guessing.

## Feedback checklist

1. **Device selection.** If multiple devices are connected, confirm each GUID
   appears in a separate tab and each tab displays the correct name/profile.
   Give duplicate models unique local aliases in Settings; switch between them
   and verify settings and faders stay isolated.
2. **Stereo input pairs.** Press the small button between channels 1/2, 3/4,
   etc. (odd-numbered input = left, even = right). Confirm one strip replaces
   the pair and that unlink restores both. Dragging strips should reorder,
   *not* link them.
3. **Stereo bus pairs.** Link Bus 1/2, Bus 3/4, etc. In the linked bus, check
   that a fader changes both mixer-output gain coefficients and pan/balance
   moves gain between left and right.
4. **Mute and solo.** Using a low-level test signal on the active mix bus,
   mute an input, adjust its fader while muted, then unmute. It should restore
   the adjusted level. Solo one input and check other **mixer crosspoints**
   become silent; undo solo and confirm earlier user mutes remain in force.
   Direct hardware crossbar passthrough can bypass the mixer matrix, so
   report any such paths rather than assuming mute acts on the ADC itself.
5. **Gain scale.** On a DICE or RME device, check −∞, 0 dB (unity), and +6 dB
   values against FFADO's native mixer UI. Check displayed levels against
   coefficient readback, not against the percentage label in the old release.
6. **Matrix editor.** In/Out → Matrix, edit one crosspoint with the rotary
   dial, numeric dB field, −∞, −6 dB, and Unity controls. Confirm the
   corresponding gain changes in the original `ffado-mixer`.
7. **DICE crossbar.** In/Out → Crossbar, route one destination to a source,
   and then choose Disconnected. Some devices return `Mute:00`; that should
   be accepted, not reported as HTTP 500. Confirm the audio path actually
   disconnects.
8. **MOTU routes.** In/Out must show output destination assignments only, not
   a gain matrix. The original UltraLite must not expose ADAT/AES routing.
9. **Peak meters.** Feed a low-level signal and check for meters on channels
   that FFADO's router reports as actual mixer-input destinations. Router
   meters are **destination meters**; an input without a matching reported
   destination deliberately has no bar rather than a synthetic reading.
10. **KDE Plasma.** Install the `packaging/ffado-webmixer.desktop` launcher and
    a matching application icon before evaluating taskbar grouping. Confirm
    the webmixer and original FFADO mixer appear separately. Window identity
    depends on the Qt backend and desktop environment; this needs a real KDE
    test.

## What to send to ChatGPT if anything fails

Please attach a single report with:

- Exact connected device models, their GUIDs (you may redact the middle bytes
  when posting publicly), and the name shown by ffado-webmixer.
- Your Linux distribution, desktop environment (KDE Wayland/X11),
  `libffado` version and Python version.
- `python main.py --headless` terminal output **including the Python traceback**.
- A screenshot showing which fader, bus, router destination or menu failed.
- The request/response for the failed operation from the browser's Developer
  Tools → Network panel, including the HTTP status and JSON error response.
- Before/after `curl` snapshots (substitute `MIX` with the affected bus index):

```bash
curl -sS http://127.0.0.1:5000/api/devices
curl -sS http://127.0.0.1:5000/api/describe
curl -sS http://127.0.0.1:5000/api/state?mix=0
curl -sS http://127.0.0.1:5000/api/matrix
curl -sS http://127.0.0.1:5000/api/router
curl -sS http://127.0.0.1:5000/api/peaks
```

Unavailable endpoints may return 400; include those errors. Use the diagnostic
collection steps in `TESTING_SAFFIRE_PRO26.md` if you need the complete D-Bus
inventory. Do not send personal identifiers, network passwords or credentials.

Please **do not change random hardware registers or try to fix FFADO yourself**;
the source and these reports should be enough to isolate most mapping bugs.
