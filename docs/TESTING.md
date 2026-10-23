# Testing and hardware verification

This is the **current** consolidated verification guide for ffado-webmixer 1.2.0.
The former one-topic-per-change guides (46 files) are preserved unchanged in
[`../docs_legacy.zip`](../docs_legacy.zip) under their original `docs/` paths.
Those older instructions reflect the interface *at the time of each change*;
some mention buttons and layouts that have since been replaced.

## Safety first

Before testing a real FireWire interface, back up `~/.config/ffado-webmixer/`,
reduce speaker/headphone/amp levels, and save known-good hardware routes.
Do not test changes during a live show. Do **not** deliberately create FireWire
failures by hot-unplugging devices (especially bus-powered devices) to test
rollback behavior. Such failures are covered by simulated regression tests.

## Offline smoke tests

From a source checkout with dependencies installed:

```sh
python main.py --debug list
python main.py --debug profire2626 --headless
# Alternative demo UI (no hardware):
python main.py --demo --headless
```

Open `http://127.0.0.1:5000/` in a browser. `--debug` simulates FFADO
controls and does not access live device D-Bus or save user mixer settings.
The listener is local-only unless `--host 0.0.0.0` is passed with
`FFADO_WEBMIXER_TOKEN` set to a password of at least 16 characters. Remote
browsers must authenticate as `ffado`; local desktop access remains automatic.
Confirm that remote requests without credentials return HTTP 401 and foreign
Origin POSTs return HTTP 403 without changing mixer state.
Available development checks (optional):

```sh
python -m pytest -q -rs
for file in tests/*.cjs; do node "$file" || exit 1; done
python benchmarks/benchmark_responsiveness.py --rpc-ms 1 --iterations 20
```

The benchmark uses **simulated** FFADO delays; it does not measure actual
FireWire latency or browser rendering. Nothing in this documentation implies
that physical-device verification has already succeeded.

## Mixer, routing, and stereo links

1. With monitoring level low, check all displayed input/output names against
   the connected hardware. Verify the selected output bus and corresponding
   master fader match the physical device.
2. On a Saffire PRO 40 or other supported DICE mixer, change a valid Crossbar
   Router source and read it back. Verify other destinations remain unchanged;
   verify Disconnected is represented consistently. Do not simulate a hardware
   timeout by disconnecting a live cable.
3. For bus tabs on devices with many buses, unpin an **unlinked** tab, drag it
   independently, and reload the page to verify persistence. Pinned tabs must
   not show a drag grip. Linked even/odd bus pairs must move as one unit.
4. Link only supported bus pairs (1+2, 3+4, etc.) through the ⋮ menu. Verify
   one combined tab is shown, rename it, refresh, then unlink and verify the
   separate names return. A custom pair name should not overwrite the original
   individual bus names.
5. Link two available channel strips through their ⋮ menus, including
   nonadjacent strips where the device supports this. Check Left/Right ordering,
   volume/balance, unlinking, and that a change on one bus does not silently
   affect another bus.
6. For native dB controls, check zero/unity display (`0.0 dB`) and numeric
   editing by right-click/long-press. Check valid/invalid input and
   double-click-to-unity only on controls with a declared dB scale.

## Multiple devices and desktop integration

1. With two mixers connected, choose between them using the toolbar device
   menu. The mixer shown, selected GUID, and native pywebview window title
   should agree. Errors during switching must not select the wrong device.
2. Select the Saffire, quit the desktop app, and relaunch it. If connected,
   that same mixer should be restored. If disconnected, another supported
   mixer may open without erasing the preferred GUID.
3. Confirm theme switches update the browser favicon immediately, while
   the XDG/KDE launcher icon updates on disk and may require a new app launch
   for the taskbar to refresh. First-run launcher installation remains opt-in.
4. Switch between devices and buses while a fader request is in flight; check
   that queued writes do not accidentally apply to the newly selected unit.

## Layout, editing, and settings persistence

1. Unpin, reorder, minimize/maximize and rename channel strips and bus tabs,
   refresh and restart. Confirm layout is scoped to its device and bus.
2. Enable **Hide minimized buses** and relevant channel-display preferences;
   verify the selected bus can still be reached and the setting survives restart.
3. Confirm normal clicks select controls without opening a text editor. Use
   right-click, long-press or F2 to edit. Enter saves; Escape cancels.
4. Confirm valid theme and settings updates persist. When an API save fails,
   the page must report the error and avoid pretending an unconfirmed change
   succeeded. Rejected malformed settings/layout payloads must not change data.
5. To verify startup failure handling without hardware, occupy port 5000 and
   launch a demo instance: it should report an error rather than hanging at
   the loading screen. Free the port afterward.

## Metering, performance, and readback

1. Apply a low-level test signal. Check that meters track their designated
   hardware channels, stay responsive with two browser clients, and follow
   device/bus changes without bleeding state between units.
2. For a linked DICE/RME bus, modify a coefficient through another FFADO
   controller and refresh webmixer. It must use *fresh* hardware values, not a
   cache left over from the previous request. Verify mute and stereo balance
   still reflect the same underlying matrix coefficients.
   After reconnecting a browser or overflowing its event queue, verify bus
   names, layouts, stereo links, faders and the visible routing view refresh.
3. Compare refresh timings with the same device, mix, sample rate and browser
   network. The offline synthetic benchmark is useful for regressions, not
   real-world FireWire latency claims.

## Still hardware-specific

For mapped pre-mark3 MOTU devices, verify channel, bus, Main and Phones faders
show 0 dB at the maximum, −84 dB at the quietest finite position, then −∞ one
native step lower. Confirm typed −84 dB remains finite and double-click restores
0 dB. Compare intermediate readouts with the device display: these values are
interpolated between the documented endpoints, not a verified native dB table.
The [original UltraLite manual](https://cdn-data.motu.com/manuals/firewire-usb-audio/UltraLite_Manual_Win.pdf#page=35)
documents the channel range. Main/Phones/bus display scales follow the same
mapped 0..128 control range and need separate physical confirmation.

FFADO hardware D-Bus behavior, live routing rollback, JACK behavior, PyQt6
window focus/title/icon integration, actual meter calibration, and mixer
readback must be verified on each supported physical model. Mark unsupported
controls as **not applicable** rather than asserting they passed.

See [profile architecture](PROFILE_ARCHITECTURE.md), [profile capabilities](PROFILE_CAPABILITIES.md),
[custom themes](USER_THEMES.md), and the original detailed test logs in
[`docs_legacy.zip`](../docs_legacy.zip) for historical reference.
