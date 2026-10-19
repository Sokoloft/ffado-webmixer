# Peak-metering test and diagnostic report (v1.1.1 development build)

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
