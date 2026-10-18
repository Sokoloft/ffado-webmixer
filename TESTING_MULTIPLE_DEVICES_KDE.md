# Three interfaces + KDE Plasma: v1.1.0-dev validation

This is a **test and data-collection guide**, not a claim of verified physical
three-device operation. The code-level tests use simulated, independent ProFire
2626 mixer instances. The tester's real FireWire setup is required to verify
FFADO startup, write behavior, meter identity and KDE window grouping.

## Before starting

1. Keep a copy of the last known-working release and back up
   `~/.config/ffado-webmixer/`. Do not change JACK's routing or volume while
   running the isolation test. Lower speaker monitoring levels first.
2. Power on all three interfaces and start the FFADO D-Bus service using the
   normal FFADO workflow. Then start the updated application **once**.
3. The top tabs should show all three recognized devices. Identical labels get
   a distinguishing six-hex-digit GUID suffix until you save individual local
   aliases in **Settings → General → Device alias**.
4. If a device is absent, do not change its XML profile. Capture the discovery
   log and diagnostic outputs below and send them to the project maintainer.

## Test A: verify device selection and isolation

Record the displayed model, tab label, and GUID for all three devices.
Choose a distinctive local alias for each (e.g. `ProFire A`, `ProFire B`,
`ProFire C`) and **restart the application**. Verify that every alias remains
with its original physical unit, even if FFADO changes discovery order.

On each device, rename one harmless channel (no audio change); give all three
**different** names. Switch A → B → C → A and verify the names do not cross
between devices. Optionally change one strip's pinned/minimized state on B and
verify A and C keep their previous layout. These are UI-only checks.

**Optional controlled hardware test:** With outputs at safe levels, change one
mixer gain on A, then switch to B and C without touching their gains. Verify
only A changed in `ffado-mixer`. Restore A's original gain after the test. For
real-time peak meter identity, play a small test signal into only one
interface and confirm that only that interface's tab displays it.

## Test B: two simultaneous browser clients

Open one browser/profile on A and a **separate browser/profile** on B (e.g.
Firefox and Chromium, or Firefox normal and a separate container/profile).
Each browser should retain its own selected device. Rename a strip on A and
verify B does not respond. With two tabs in the *same browser profile*, device
selection is intentionally shared through the Flask session cookie: when a
second tab switches to B, stale requests from the first tab must be rejected
with **HTTP 409**, not applied to B. Reload the first tab to select again.

After editing in two browser clients, verify that each GUID has its own file:

```bash
find ~/.config/ffado-webmixer/devices -maxdepth 1 -type f -name '*.json' -printf '%f\n' | sort
```

Do not post these JSON files publicly without reviewing channel labels or
other custom names.

## Test C: FFADO recovery and reconnect limitations

If FFADO is restarted, or a FireWire interface is powered off while the web
mixer runs, capture the terminal error and restart ffado-webmixer after FFADO
has re-established all devices. Hotplug re-enumeration **without a webmixer
restart is not implemented** in this release. In particular, do not assume
that a missing device can be recovered by switching tabs alone.

## Test D: KDE Plasma taskbar and default web browser

The application identity is `ffado-webmixer` and must match an installed
`ffado-webmixer.desktop` file. For a development checkout, there is an
**optional local installer** (no sudo, no driver or FFADO changes):

```bash
python packaging/desktop_integration.py --check
python packaging/desktop_integration.py --python /path/to/your/.venv/bin/python
python packaging/desktop_integration.py --check
```

The installer writes a launcher under `$XDG_DATA_HOME/applications` (or
`~/.local/share/applications`) and an SVG icon under the corresponding
`icons/hicolor/scalable/apps/` directory. `--remove` uninstalls these entries.
Run **the installed launcher from the KDE application menu** for the taskbar
check. Opening the Python program inside PyCharm may get a different taskbar
association even when the application works correctly. Compare taskbar
buttons for `ffado-mixer` and `ffado-webmixer`, their icons, and whether pinning
one changes the other's task manager entry. Also test the About → Open in
browser button. Different Plasma/pywebview/Qt versions may behave differently;
these have **not** been tested live in this build environment.

## Diagnostic capture for the tester

Please send the full app terminal log and these commands' outputs **without
editing files or retrying hardware writes**:

```bash
printf '%s\n' '=== FFADO processes ==='
pgrep -a -f 'ffado|jackdbus|qjackctl' || true
printf '%s\n' '=== DeviceManager object tree ==='
busctl --user tree org.ffado.Control /org/ffado/Control/DeviceManager || true
printf '%s\n' '=== Device tabs and current session ==='
curl -sS http://127.0.0.1:5000/api/devices || true
printf '\n%s\n' '=== Qt, Plasma, desktop identity ==='
printenv XDG_SESSION_TYPE XDG_CURRENT_DESKTOP QT_QPA_PLATFORM QT_WAYLAND_APP_ID || true
plasmashell --version || true
python packaging/desktop_integration.py --check || true
printf '%s\n' '=== Installed launcher ==='
grep -E '^(Exec|Icon|StartupWMClass|Name)=' ~/.local/share/applications/ffado-webmixer.desktop || true
```

For an incorrect fader or meter, attach the app's API `/api/describe`,
`/api/state?mix=0`, `/api/peaks` and one before/after screenshot **for the
selected device**, with the corresponding device GUID noted. The `/api/devices`
response gives the visible GUID/model labels; it does not dump mixer levels.
The cookies of curl and the browser are independent, so curl uses the first
unit unless you explicitly establish its own session.

If a tab is missing, include the full startup exception for that GUID. If a
cross-device write happens, stop immediately and describe which GUID was
selected, which physical unit changed, and which browsers/tabs were open.
