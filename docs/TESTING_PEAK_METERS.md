# Peak-metering test and diagnostic report (v1.1.1 development build)

## Full-track peak color fix (October 21, 2026)

The strip and Crossbar Router gradients are now anchored to the **entire
meter track**, not stretched across each current reading. A 50% peak shows a
half-height green strip (no false yellow or red), while warning colors only
appear near full-scale. See
[`TESTING_METER_COLOR_SCALE.md`](TESTING_METER_COLOR_SCALE.md) for exact
screen and Chromium regression checks. Actual FFADO normalization, meter
identity, and clip-hold behavior are unchanged.


## Saffire PRO 26 missing-meter regression (October 20, 2026)

The Saffire PRO 26 user's video shows live `Mixer/In:01` and `Mixer/In:02` peaks in
**In/Out → Crossbar router**, while the corresponding early channel strips are
unmetered. This was **not a missing hardware metering path**: `read_mix()` emits
zero-padded strip identifiers (`ch/00`, `ch/01`, ...), but `peak_snapshot()` emits
unpadded JSON channel indexes (`"0"`, `"1"`, ...). The JavaScript attempted to
look up `"00"` and `"01"`, so all indices 0–9 were dropped. Indices 10+
matched by coincidence. Earlier JavaScript tests used non-realistic padded
JSON keys; they now exercise the actual backend format.

This update fixes lookup for all FFADO DICE profiles sharing that code. We
tested simulated meter data from **all 16 current model fixtures** with
source-declared EAP metering, and tested backend-produced JSON through the
actual JavaScript renderer. No real device was connected in these tests.
A strip **still remains unmetered** when the router has no peak data for its
actual declared `Mixer/In:XX` destination; the code never copies a different
channel, substitutes `Anlg/In` source peaks, or invents post-fader readings.

### Fast read-only hardware verification

1. Open the Saffire PRO 26 mixer and the **Crossbar router** tab. With safe
   signal levels, verify that `Mixer/In:01` and `Mixer/In:02` show genuine peak
   activity.
2. Close the router dialog. The first two channel strips should now show
   corresponding activity beside their faders (even when the visible strip
   label is `Anlg/In:01` or `Anlg/In:02`, which names the router source).
3. Check remaining channels 3–10, then channels 11–18. Only strips whose
   own router destinations supply peaks are expected to meter.
4. Optionally pair inputs 2 then 5; verify the two independent Left/Right
   meters match their own router destinations. Pairing does not change routing.
5. Repeat on another DICE device, if available. Compare with FFADO's own
   Crossbar Router; do **not** change routing to make missing peaks appear.
6. If a destination meters in the Crossbar but the same strip does not,
   collect the read-only `/api/peaks` response below and send it with a
   screenshot and the name of that destination.

## Previous channel-strip refinements

The original DICE EAP meter support exposed source-mapped router-destination
levels. This release refines the **channel-strip** presentation with a separate
Left and Right meter for every linked stereo pair, while retaining 1.6-second
peak holds, 4-second near-full-scale warning holds, and click-to-clear.  Meters in the **In/Out → Crossbar router** panel represent the router's
actual destination names; strip meters appear only if the profile's FFADO
matrix input name maps to a metered router destination.

**Important:** FFADO extracts a 12-bit peak field and draws its original meter
using `sqrt(raw/4096)`. Webmixer uses the same normalized amplitude and labels
its decibel conversion relative to the FFADO full-scale reference; **this is
not verified, calibrated dBFS**. The red hold is triggered by the maximum
12-bit code (`4095`), which indicates *near full scale*, not conclusive proof
of digital clipping. The location of each meter is a router destination,
which may be pre-mixer or a different signal path than the visible fader.

## What to check without changing routing

1. Open your DICE EAP mixer (for example ProFire 2626 or Saffire Pro 26), and
   leave audio monitoring at a safe level. Compare the meter activity in
   **ffado-mixer → Crossbar Router** with the webmixer's **In/Out → Crossbar
   router**. The same destination names should respond to the same audio.
2. View the main mixer. Only input strips whose original FFADO matrix input
   names match metered `Mixer/In:XX` destinations should show meters. Meters
   may be absent even while routing-panel destination meters are working.
3. If a route can safely receive a test signal without disturbing monitoring,
   make a short signal and watch its meter. Do not change routing just to
   make an unrelated strip meter appear.
4. To check hold, briefly make a level rise and lower it. The thin hold line
   remains for about 1.6 seconds; red near-full-scale indication persists for
   about 4 seconds when the hardware actually reports the highest code.
   Click a meter to clear its hold; a sustained full-scale signal may relatch.
5. Link **any two channels** (for example, channel 2 Left + channel 5 Right,
   or channel 8 Left + channel 3 Right). The stereo strip shows **two
   independent lanes** in the selected Left/Right order. The old single
   maximum-peak display has been replaced, so unequal stereo levels remain
   visible. Confirm that a spike on one channel does not spike the other.
6. Verify the **1.6-second hold and 4-second near-full-scale warnings are
   independent per lane**. Clicking the enclosing meter clears both holds.
   Changing buses must not swap the channels' Left/Right positions or invent
   readings for unmetered channels.
7. Switch between several FFADO devices. Each browser-selected device should
   show only that unit's meter data. Unsupported devices such as the original
   MOTU UltraLite must not display fabricated peak meters.
8. Try `python main.py --debug profire2626 --headless` for *synthetic UI tests
   only*. This mode never opens FFADO D-Bus and deliberately returns example
   12-bit readings; it must not be used as proof of hardware behavior.

## Limitations and interpretation

- Strip meters reflect the **actual FFADO DICE EAP router destination** for
  each mapped matrix input. They are not verified post-fader signals; no
  pre/post selector is offered because FFADO does not expose separate,
  proven pre- and post-fader readings through this endpoint.
- Only strips with a real matching FFADO `Mixer/In:XX` destination display
  levels. A stereo pair with only one metered channel shows only that lane;
  the other lane stays hidden rather than duplicating it.
- If `destination_levels` are present in `/api/peaks` but `channels` is empty,
  we still need **actual FFADO matrix row names and a verified mapping** from
  the tester before adding meters to those strips. Do not substitute the
  sequential strip number for an undocumented router mapping.
- The hold and near-full-scale warnings are derived from FFADO's 12-bit code,
  **not a verified calibrated digital clipping indicator**.

## If any meter is missing, stuck, wrong, or the app reports an error

**Please send the following to the developer or ChatGPT. Do not try to repair
FFADO, force route changes, or edit profiles yourself.**

Describe the interface model, which devices are attached, the sample rate,
which destination/channel was expected to meter, and whether `ffado-mixer`
shows activity for that *same* router destination. Attach a screenshot of
`ffado-mixer → Crossbar Router` and webmixer's In/Out router view, plus the
main faders if those are affected.

With the mixer application running, execute this read-only capture in a
terminal (replace PORT if the webmixer uses a different HTTP port):

```bash
PORT=5000
OUT="$HOME/ffado-peak-report-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
python -m pip show ffado-webmixer > "$OUT/package-version.txt" 2>&1 || true
curl -fsS "http://127.0.0.1:$PORT/api/describe" > "$OUT/describe.json" 2>&1 || true
curl -fsS "http://127.0.0.1:$PORT/api/peaks" > "$OUT/peaks-idle.json" 2>&1 || true
printf 'Now play a short, safe-level test signal; press Enter to collect 3 more readings...\n'
read -r _
for n in 1 2 3; do
    curl -fsS "http://127.0.0.1:$PORT/api/peaks" > "$OUT/peaks-signal-$n.json" 2>&1 || true
    sleep 0.2
done
busctl --user tree org.ffado.Control > "$OUT/ffado-dbus-tree.txt" 2>&1 || true
uname -a > "$OUT/kernel.txt"
python --version > "$OUT/python-version.txt" 2>&1
cd "$HOME" && tar -czf "$(basename "$OUT").tar.gz" "$(basename "$OUT")"
printf 'Attach this file: %s.tar.gz\n' "$OUT"
```

If D-Bus peak values are reported correctly but no strip meter appears, include
**the unmodified FFADO matrix input row labels** (not just the renamed webmixer
strip names); this tells us whether that device's input rows correspond to
router destinations. The `api/peaks` response contains `channels` and
`destination_levels`: when `destination_levels` is populated but `channels`
is empty, inspect these labels and the selected model's meter mapping.

If `GET /api/peaks` returns HTTP 500, include the exception traceback from the
terminal running webmixer, or the journal output for the service. If metering
works in ffado-mixer but `hasPeakMetering()` is false, send the requested
D-Bus inventory and identify the destination tested.

The capture is read-only. Review the archive before sharing: device identifiers,
local hostnames, and some system information may be included. Avoid including
personal audio recordings or secret configuration values.

## Source references

- `ffado-master/src/dice/dice_eap.cpp`: `PeakSpace::read`, `getPeakValues`.
- `ffado-master/support/mixer-qt4/ffado/widgets/crossbarrouter.py`: original FFADO visual meter `sqrt(value/4096)`.
- `ffado-master/support/dbus/control-interface.xml`: `getPeakValues`, `hasPeakMetering`.
- `ffado_webmixer/peak_metering.py`: model-declared channel mapping and normalized value conversion.

The original MOTU UltraLite has meter **settings**, but FFADO does not expose
an equivalent live peak-reading D-Bus interface in the provided source. This
release therefore does not render live strip meters for that device.
