# Saffire PRO 26 — hardware testing and bug-report guide (ffado-webmixer 1.0.1)

**Please send failures back with evidence instead of trying to diagnose or fix them yourself.**
The purpose of this test is to learn exactly what the Saffire PRO 26 exposes through
FFADO and what `ffado-webmixer` actually reads/writes. The developer/ChatGPT can
inspect the reports and make the code or profile changes. No Python, XML, D-Bus,
or Linux debugging knowledge is required from the tester.

The current Saffire implementation has been exercised against an offline/mock
D-Bus backend; it has **not** been confirmed against a physical Saffire PRO 26.
A control moving on screen is not proof that the physical interface accepted it.

## What the application is supposed to do

- Detect **Focusrite Saffire PRO 26** rather than an unknown or simulated device.
- Display up to **18 internal mixer inputs** and **16 internal mixer outputs**
  (the output buses). They are *not* necessarily 18 physical sockets or 16
  physical line outputs.
- Let each input fader set the selected bus's gain crosspoint in FFADO's
  `/EAP/MatrixMixer`. These are *levels*, not routing assignments.
- Show an **In/Out** dialog with separate **Mixer matrix** (crosspoint gain)
  and **Crossbar router** (source-to-destination routing) views.
- Show individual monitoring levels/mutes for **Line Out 1–6**, when those
  controls are actually published by the connected FFADO server. The master
  strip controls the **selected line output**, not a global master.
- Show only controls actually reported by FFADO. Some paths and features may
  vary with driver version, routing, sample rate, and mixer configuration.

DICE matrix values are raw linear coefficients: `16384` is unity (0 dB) and
`0` is silence. The web interface converts these to its percentage/dB scale.
The DICE matrix has no dedicated per-crosspoint mute; the webmixer's matrix
mute temporarily remembers the old value **in its server memory**. Closing
or restarting webmixer loses that remembered mute value.

## Safety and preparation (please read)

1. **Keep speakers/amplifiers off, disconnected, or turned down** for initial
   tests. Routing changes, unmuting, and unity-gain settings can produce sudden
   loud sound or feedback. Do not test with an active live sound system.
2. If possible, take screenshots of **all relevant `ffado-mixer` mixer,
   router, and monitoring tabs BEFORE changing anything**. These show the
   original working state. Avoid resetting or reinitializing the interface.
3. Use the same Linux login/session to run the existing `ffado-dbus-server`,
   `ffado-mixer`, and `ffado-webmixer`. **Do not start a second D-Bus server.**
4. Run the actual hardware build, **not `--demo`**. Note whether JACK/your
   normal audio playback is running; the webmixer by itself does not create
   an audio stream.
5. If something fails, **stop that test**, note the exact time and action,
   gather the evidence below, and move to the next *safe* test. Do not
   repeatedly click a failed route, force values, edit profiles, reinstall
   packages, restart the interface, or run write-capable D-Bus commands.
6. If there is unexpected loud audio, turn the level down or disconnect
   speakers **first**. Restore known working settings via `ffado-mixer` only
   when safe. Tell us if a restart or power cycle became necessary.

## Quick test sequence

Write down which items passed or failed, including any control that moved
visually but did not produce an audible change.

| Test | What to do | What to record |
| --- | --- | --- |
| A. Startup | Launch webmixer normally and open its About tab | Detected device name and version; any terminal error |
| B. Mixer layout | Open the main mixer; switch between the first and last available bus | Number and labels of strips/buses; screenshot if reversed/missing/duplicated |
| C. Matrix read | Open **In/Out → Mixer matrix** and compare one input/output cell with `ffado-mixer` | Input label, output label, values in both apps, screenshot |
| D. Matrix write | At safe volume, change **one known cell slightly** and press **Apply**; refresh both apps | Before/after values, whether FFADO reflects the change, any error |
| E. Strip fader | Select the **same bus and input** and move its main strip fader slightly | Whether the corresponding matrix cell changes; whether any *other* cell changes |
| F. Mute | Mute/unmute a crosspoint which had a nonzero level (only if safe) | Before/muted/restored values; whether restoration worked |
| G. Monitoring | Select Line Out 1, carefully change its master level, and compare `ffado-mixer`'s Monitoring tab | Which physical line output moved, old/new level, mute behavior |
| H. Router read | Open **In/Out → Crossbar router**; compare displayed assignments with `ffado-mixer` | Destination/source names and screenshots; no need to change a route |
| I. Router write | **Optional, only if safe:** change one noncritical destination to another source, compare with `ffado-mixer`, then restore it | Destination, old/new source, response, whether it restored |
| J. Audio | If you already have a safe, working JACK/FFADO signal path, listen at low volume while changing one known matrix level | Input source, selected bus, routing destination, audible result |

**Do not guess from silence alone.** If the fader value changes in
`ffado-mixer` but no sound changes, we still need to know the bus, selected
router source/destination, any monitoring mutes, and whether the input had
an audio signal. That is different from a D-Bus write that fails entirely.

## If anything goes wrong: what to send

**Please send these items even if you do not know what the error means:**

1. **Short description in plain English:** what you clicked, which input,
   bus/output or router destination was selected, what you expected, and what
   actually happened. Include **before and after** fader values if possible.
2. **Screenshots:** the failed webmixer page (including the selected bus),
   the corresponding `ffado-mixer` page, and any error popup/message.
3. **The diagnostic archive** produced by the copy/paste command in the
   next section. Run it while both the hardware and failing application are
   still accessible, if possible.
4. **Terminal output** from the window used to start `python main.py` and,
   if accessible, the terminal where `ffado-dbus-server` is already running.
   Preserve the **first** error and its traceback, not just the last line.
5. If a button fails in the **browser**, open Developer Tools (usually F12),
   copy the **Console** errors and, if possible, the failing request from
   **Network** (URL, HTTP status, request body, response body). Screenshots
   are fine if copying is difficult.
6. **Environment:** Linux distribution, FFADO/libffado version, whether
   `ffado-mixer` works, desktop window vs browser vs phone, sample rate,
   JACK state, and the approximate time of failure.

**You do not need to explain or interpret any command output.** Attach the
files as-is. If any diagnostic command says "permission denied", "command not
found", or "service not found", **include that output** instead of trying
to resolve it first.

### One copy/paste block: collect read-only diagnostics

Run the following **from the `ffado-webmixer` project folder**, in a terminal
with the same Python virtual environment normally used to start the app.
Leave the current `ffado-webmixer` and `ffado-dbus-server` running if they
are already running. This block **does not change mixer levels or routing**.
It only reads system/device/API state, creates a folder, and archives it.

```bash
REPORT="saffire-pro26-report-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$REPORT"

{
  date -Is
  uname -a
  cat /etc/os-release
  python --version
  python main.py --version
  command -v ffado-dbus-server || true
  command -v ffado-mixer || true
  command -v ffado-diag || true
  command -v jack_lsp || true
  pacman -Q libffado 2>&1 || dpkg-query -W libffado2 2>&1 || true
} > "$REPORT/system.txt" 2>&1

{
  busctl --user list 2>&1 | grep -i ffado || true
  busctl --user tree org.ffado.Control 2>&1
} > "$REPORT/dbus-tree.txt" 2>&1

python -m ffado_webmixer.interrogate \
  > "$REPORT/ffado-inventory.json" \
  2> "$REPORT/ffado-inventory-errors.txt" || true

{
  ls -l /dev/fw* 2>&1
  pgrep -af 'ffado-dbus-server|ffado-mixer|main.py|jackd' 2>&1 || true
  jack_lsp 2>&1 || true
} > "$REPORT/device-and-jack.txt" 2>&1

for item in \
  'about|/api/about' \
  'describe|/api/describe' \
  'settings|/api/settings' \
  'state-bus0|/api/state?mix=0' \
  'state-bus1|/api/state?mix=1' \
  'state-bus15|/api/state?mix=15' \
  'matrix|/api/matrix' \
  'router|/api/router' \
  'line-out1|/api/output?out=line/1' \
  'line-out6|/api/output?out=line/6'; do
  name=${item%%|*}
  url=${item#*|}
  curl --noproxy '*' --max-time 15 --silent --show-error \
    --include "http://127.0.0.1:5000$url" \
    > "$REPORT/api-$name.txt" 2>&1 || true
done

if [ -f "$HOME/.config/ffado-webmixer/config.json" ]; then
  cp "$HOME/.config/ffado-webmixer/config.json" "$REPORT/webmixer-config.json"
fi

tar -czf "$REPORT.tar.gz" "$REPORT"
echo "Report created: $REPORT.tar.gz"
```

**Attach the resulting `.tar.gz` file.** It includes the D-Bus control tree,
raw discovered model information, API responses and HTTP errors, and enough
system context to correlate them. A failing endpoint returning `400`, `500`,
or a connection error is useful evidence; do not rerun it until it succeeds.
Some queries may be unavailable or out of range on particular configurations.

Important: `config.json` may contain your custom channel names and UI layout;
logs and D-Bus output can include your computer username, LAN IP, FireWire
GUID, or other local details. **Review the report before sharing it publicly**
and redact information you don't want to publish. Keep the vendor/model IDs,
control paths, numeric values, and error messages where possible. Send the
report privately if you prefer.

**If webmixer cannot start**, the `/api/…` results will show connection errors;
that is expected. Still attach the archive and the startup error using the
next section. If Python or a diagnostic command isn't available, screenshot
or copy the error: no need to install additional tools just for the report.

### Capture application startup errors (if needed)

If webmixer fails to start, in the project folder run the **same command**
you normally use, but capture its output. For example, if you normally use
`python main.py`, run:

```bash
python -u main.py 2>&1 | tee webmixer-startup.log
```

If you normally launch in the browser only:

```bash
python -u main.py --headless 2>&1 | tee webmixer-startup.log
```

**Do not launch a second copy while one is already running** (port 5000 may
already be in use). Reproduce the problem, then press Ctrl+C and attach
`webmixer-startup.log`. If the service won't start at all, attach the entire
failed startup output. If you already have `ffado-dbus-server` output in a
terminal or log file, save that too; do not restart it just to generate a log.

### Capture before/after values for a control that does nothing

A before-and-after pair lets us determine whether the webmixer or FFADO
accepted the write. For a **single safe, low-level** adjustment:

1. Run the diagnostic collection block **before** the change.
2. Note the selected **bus**, **input**, and **expected result** (for example,
   `Bus 1 / Analog In 1, 38% → 42%`). Take a screenshot of `ffado-mixer`.
3. Make **one** small adjustment in webmixer. Record the exact error message,
   if any, and whether the on-screen control jumps back or stays put.
4. Run the block again **immediately after**, without restarting anything.
   It creates a separate timestamped report. Take another `ffado-mixer`
   screenshot, then restore the previous value if safe.
5. Send **both archives and both screenshots**, and state whether the audio
   changed. If the first change risks loud sound, skip the write entirely.

## Which extra evidence helps for each symptom?

| Symptom | Extra evidence to include | Why it helps the developer |
| --- | --- | --- |
| App refuses to launch; device not found | Complete startup traceback; D-Bus tree; whether `ffado-mixer` opens; USB/FireWire device and power state | Distinguishes a Python error, unavailable D-Bus server, or missing FFADO hardware |
| Wrong model name, wrong input/output counts or labels | Webmixer main view; `ffado-mixer` mixer tabs; inventory JSON; sample rate | Identifies profile-selection or matrix-orientation mismatches |
| Fader moves but does nothing | Before/after API `matrix` and `state-busN` files; same cell in `ffado-mixer`; selected router destination | Shows whether a gain coefficient was written to the right cell |
| Error on fader, mute, gain, pan or Apply | Exact error text; browser Network POST `/api/set` or `/api/matrix` request+response; backend terminal traceback | Identifies wrong value range, bad D-Bus path/method, or rejected write |
| A different input/bus changes | Screenshot of selected input/bus and changed cell in both apps, plus before/after snapshots | Tests row/column transposition and strip-to-cell mapping |
| Faders display `NaN`, jump, reset, or show strange dB values | Close-up of value; `api-matrix.txt`; selected input/output cell, sample rate | Tests raw coefficient conversion and nonnumeric values |
| Missing master fader / Line Out volume or mute does nothing | Which `Line Out` was selected; `/api/describe`; `api-line-out1.txt`/`api-line-out6.txt`; Monitoring tab | Reveals absent or misclassified monitoring D-Bus controls |
| Router shows wrong assignments / source names | Screenshots of **both** routers; `api-router.txt` and inventory JSON | Compares device-reported router endpoints and selected connections |
| Route Apply changes nothing or routes unexpectedly | Original destination/source, new source; network POST `/api/router` and response; before/after router files | Distinguishes router selection/write problems from UI selection problems |
| Audio missing even though control values change | FFADO/JACK state; selected input, bus and physical destination; signal source; mixer/router/monitoring screenshots | Separates streaming/audio path issues from working mixer controls |
| `ffado-mixer` works but webmixer doesn't | Matching controls/screenshots from both applications immediately after the same test | Most useful evidence for mapping/FFADO API differences |
| Works in desktop app but not browser/phone, or vice versa | Device type, URL (redact IP if sharing publicly), browser name/version, Console + Network errors | Separates web API/connectivity issues from hardware behavior |
| Works at one sample rate but not another | Both sample rates, device clock source, state/layout screenshots and inventories at each rate | Tests channel availability/routing changes with rate |
| App freezes or becomes unresponsive | Last action, elapsed wait time, terminal output, browser Console/Network request marked pending | Shows where a D-Bus request or UI call may be stuck |
| Stops working after sleep, reconnect, server restart | Exact sequence and times, logs around disconnection, new inventory/API snapshots | Tests stale D-Bus objects and device re-enumeration |
| Mute cannot restore audio after restart | Whether webmixer was restarted, prior matrix gain, `ffado-mixer` crosspoint after restart | Helps distinguish expected in-memory mute limitation from a new regression |
| Saved names, stereo pairs, theme or UI state behave strangely | Relevant screenshots plus `webmixer-config.json` (after review) | Separates persistent UI state from hardware capability |

**If there's a crash or kernel/FireWire error**, optionally add this output:

```bash
journalctl -k -b --no-pager 2>&1 | grep -Ei 'firewire|ohci|fw[0-9]|1394|permission|denied|access' | tail -n 150 > firewire-kernel.log
```

Attach `firewire-kernel.log`, or attach the "permission denied" output if
reading the kernel journal is restricted. **Do not change kernel parameters,
FireWire permissions, audio packages, or driver configuration as part of this
test.** That is a separate decision for the developer and device owner.

## Copy-and-fill report message

Copy this into the message accompanying the attachments. Unknown answers are
fine: write "unknown" or leave them blank. **Do not attempt to diagnose it.**

```text
Device: Focusrite Saffire PRO 26
ffado-webmixer version: 1.0.1 (or actual version)
Linux distribution:
libffado version:
Does ffado-mixer work correctly? yes / no / partly
Using: desktop window / local browser / remote browser or phone
JACK running and passing audio? yes / no / unknown
Sample rate / clock source (if known):

Problem (one sentence):
Exact steps before failure:
Selected mixer bus:
Input/channel or physical line output:
Router source and destination (if relevant):
Value before -> after:
Expected result:
Actual result (including whether audio changed):
Exact error message (if any):
Did webmixer and/or ffado-dbus-server restart?:
Approximate date/time of failure:

Attached:
[ ] saffire-pro26-report-*.tar.gz
[ ] Before/after reports (if testing a control write)
[ ] Webmixer screenshots
[ ] Corresponding ffado-mixer screenshots
[ ] Webmixer/FFADO terminal log or error screenshot
[ ] Browser Console / Network errors (if present)
[ ] FireWire kernel log (only if relevant)
```

**Suggested request to ChatGPT when sending a report:**

> Here is the Saffire PRO 26 bug report and diagnostic archive for
> ffado-webmixer 1.0.1. Analyze the evidence, identify the most likely broken
> mapping or API call, and provide the corrected source files/patch. Please
> do not ask the tester to debug the code or make speculative system changes.
> If any essential data is still missing, request only the specific read-only
> command or screenshot needed to establish it.

## For developers: relevant FFADO source files

- `src/dice/dice_eap.cpp` — matrix dimensions, raw coefficients and router API
- `src/dice/focusrite/saffire_pro26.cpp` — monitoring elements
- `src/dice/focusrite/focusrite_eap.cpp` — monitor level register interpretation
- `support/mixer-qt4/ffado/mixer/generic_dice_eap.py` — matrix orientation
- `support/mixer-qt4/ffado/mixer/saffire_dice.py` — monitoring D-Bus paths
- `support/mixer-qt4/ffado/widgets/crossbarrouter.py` — router methods
- `support/dbus/control-interface.xml` — D-Bus method signatures

These references are for whoever fixes the code; the tester is **not** expected
to read or understand them.
