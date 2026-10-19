# DISCLAIMER
**THIS PROJECT IS MADE USING AI (Claude and ChatGPT)**

I wanted something better than `ffado-mixer`. 
Originally this was going to be a front end with a modular back end like [Mixing Station](https://mixingstation.app/).
However, there is no need thus this project turned into `ffado-webmixer`

# FFADO WebMixer

**FFADO WebMixer** is a web-based mixer interface for FireWire audio devices supported by [FFADO](https://ffado.org/). It provides a modern alternative to the traditional `ffado-mixer` interface, accessible through a desktop window or a web browser on your local network.

The application uses Python, Flask, and FFADO's D-Bus control interface. A pywebview desktop client is available for local use; the same mixer can also run without a desktop window for access from another computer, tablet, or phone.

> **Project status:** Device selection uses exact source-derived FFADO identities and explicit model-level capability declarations. The catalogue identifies more devices than the application can currently control: an identity-only profile deliberately exposes **no guessed writable mixer**. Actual hardware control additionally requires matching D-Bus endpoints. See [`ffado_webmixer/profiles/CAPABILITIES.md`](ffado_webmixer/profiles/CAPABILITIES.md).

**Current version: 1.1.1 (development branch).** This is not a stable-release designation. [Changelog](docs/CHANGELOG.md) · [Test and developer documentation](docs/README.md).

## Features

- Control digital mixer volume, pan, mute, solo, and polarity/invert functions where available; hardware input gain/trim is a separate control when the device exposes it.
- Select available outputs and buses, with a master fader for the selected destination.
- Link **any two input channels** using the bottom-right chain-link buttons. First click selects **Left**, second click selects **Right** (for example, channel 2 then channel 5). Clicking the first again cancels. **Pairs are independent for each output bus**; dragging strips only reorders them.
- Reject conflicting stereo pairs with an explicit message and preserve previous pairs and strip layouts on invalid operations. Pair changes from simultaneous browser clients are serialized.
- Link consecutive output buses on supported mixer matrices and use per-channel stereo balance.
- Show DICE/RME digital mixer **volume** in dB rather than raw percentages; soft mute and solo where supported.
- Show real, matched DICE EAP router-destination peak meters beside channel faders when exposed by FFADO. Arbitrary stereo pairs display **separate Left/Right lanes** with independent hold and near-full-scale warnings. These are router readings, not verified post-fader dBFS.
- Recover interrupted software mute/solo safely using per-device gain journals, explicit restore/discard controls, and verified hardware readback.
- Switch among multiple connected, source-profiled FFADO interfaces by FireWire GUID, with optional local aliases.
- Edit supported matrix coefficients with a **rotary control in every crosspoint cell**, plus the existing precise numeric dB editor and presets (where dB hardware mapping is available). Each drag writes once on release; wheel and keyboard changes are grouped before writing.
- Rename, reorder, pin, minimize, and hide channel strips.
- Remember mixer layout, names, stereo links, selected theme, and other interface preferences.
- Use built-in color themes or add your own CSS themes, including accent color customization.
- Open the interface in a native desktop window or from a browser on your network.
- Try the interface without FireWire hardware using demo mode.
- Enable QjackCtl support in **Settings → General** to reveal a dedicated **QjackCtl** tab with Graph and Patchbay controls.
- Open the dedicated **In/Out** dialog for hardware routing. MOTU pre-Mk3 devices
  show mix-bus-to-output assignment, while supported DICE devices expose their
  mixer-volume and crossbar controls separately.

## Requirements

- Linux with Python 3 and the project's Python dependencies, including Flask and pywebview for the desktop client.
- FFADO and a compatible FireWire audio interface for hardware control.
- A running FFADO D-Bus control service (`ffado-dbus-server`) accessible to the application.
- A supported Qt backend for the optional pywebview desktop client (this project uses PyQt6).

FFADO hardware support, FireWire permissions, and audio routing must be configured separately. **WebMixer controls the device mixer; it is not an audio driver and does not replace JACK or FFADO itself.**

## Running the application

Run the commands from the repository root:

```bash
python main.py
```

This starts the Flask server and opens the desktop mixer window.

### Browser-only / headless mode

```bash
python main.py --headless
```

Open the URL printed by the server in your browser. To use the mixer from another device, open the host computer's LAN address and the same port (the project's default is port `5000`), for example:

```text
http://192.168.1.100:5000/
```

The server may be reachable by other devices on your network. Only expose it on networks you trust; the mixer provides controls for real hardware.

### Source-defined offline debug mode

To open a named hardware profile without talking to D-Bus:

```bash
python main.py --debug profire2626 --headless
python main.py --debug saffirepro26
python main.py --debug motuultralite
python main.py --debug list
```

**No FFADO D-Bus operations occur in this mode.** Intended methods and their
arguments are printed as `"[DEBUG would call D-Bus]"` to the console. Mixer
values and dimensions are simulated for testing the UI, not authoritative
hardware capabilities. No persistent configuration files are written.

### Multiple FireWire interfaces and KDE Plasma

Recognized FFADO devices appear in tabs. Each physical GUID has independent
mixer state, local aliases, layouts, and mute-recovery data. Identical display
names show a short GUID suffix until individually renamed. Separate browser
profiles can select separate units; tabs in the same browser profile share a
session cookie, so changing devices in one tab requires reloading the other.
Old-tab requests are rejected rather than sent to the wrong device.

For a source checkout on Plasma, an optional developer launcher can be installed
without root or changes to FFADO/JACK:

```bash
python packaging/desktop_integration.py --python /path/to/.venv/bin/python
python packaging/desktop_integration.py --check
# To uninstall the app launcher/icon only:
python packaging/desktop_integration.py --remove
```

See [[`TESTING_MULTIPLE_DEVICES_KDE.md`](docs/TESTING_MULTIPLE_DEVICES_KDE.md)](docs/TESTING_MULTIPLE_DEVICES_KDE.md) for
a full three-device verification and diagnostic checklist. Live hotplug device
re-enumeration is not supported; restart webmixer after FFADO changes units.

### Exact hardware profile matching

The included `ffado_webmixer/profiles/ffado_configuration` is a snapshot of
the FFADO source `configuration` registry; local FFADO definitions may override
entries. A ConfigROM vendor/model (and the relevant unit-version overrides for
MOTU/RME) selects a specific model XML. Live D-Bus supplies only real values,
available paths, and matrix dimensions; **an unknown model is never assigned a
guessed writable matrix**. A model in the registry is not automatically fully
supported unless its control profile includes an explicit mixer mapping.

**Model-level capability catalogue:** the source-backed schema v2 declares each
model's gain matrices, input/output orientation, routing, mute/solo, monitoring,
peak meters, nickname support, and other feature states. `mapped` permits only
specified D-Bus endpoints, `optional` requires live probing, `source_only`
records known FFADO functionality not implemented in webmixer, and `unmapped`
never implies hardware absence. The catalogue covers **101 distinct FFADO
configuration identities** plus **five MOTU pre-mk3 internal model variants**;
this is an identification/coverage count, **not 106 working mixers**. Unknown or
identity-only devices do not receive generic matrix heuristics. See
[`CAPABILITIES.md`](ffado_webmixer/profiles/CAPABILITIES.md) and
[[`TESTING_CAPABILITIES.md`](docs/TESTING_CAPABILITIES.md)](docs/TESTING_CAPABILITIES.md).

Each interface's layout, stereo links and aliases are kept in
`~/.config/ffado-webmixer/devices/<guid>.json`; the original `config.json` is
kept as an initial migration source and for desktop-window preferences.
**Input pairs are now stored separately for each bus** in `stereo_by_mix`. An
older `stereo` list remains as the initial fallback for buses not yet edited;
unlinking in one bus overrides only that bus, without affecting other buses.
Hidden Right-channel layout entries are retained, so unlinking restores each
channel's previous pin/minimize/position settings on that bus.

See [`TESTING_V1_1.md`](docs/TESTING_V1_1.md) for live-hardware validation and known limitations.

### Demo mode

```bash
python main.py --demo
```

Demo mode uses a simulated mixer instead of FFADO hardware. Its settings are kept in memory rather than written to your normal configuration file.

To run the demo in a browser without a desktop window:

```bash
python main.py --demo --headless
```

To see command-line options:

```bash
python main.py --help
```


### Volume vs. gain terminology

**Volume** in the web interface is the digital mixer level: channel and master faders, and writable mixer matrix crosspoint rotary/numeric controls. These controls attenuate or boost a routed signal; they do not adjust an analog microphone preamp.

The separate **Input Gain** box is shown only when a device declares a writable gain/trim/preamp control. It is not part of the digital matrix volume. On the ProFire 2626, microphone preamp gain is adjusted on the hardware; the webmixer does not invent a software preamp control.

The public API, FFADO XML capability names, D-Bus mappings, and internal Python/JS field identifiers (for example `gain`, `gain_scale`, `matrix_gain`, and `fader`) are deliberately unchanged for compatibility. Existing configuration and third-party callers should continue working. See [[`TESTING_VOLUME_TERMINOLOGY.md`](docs/TESTING_VOLUME_TERMINOLOGY.md)](docs/TESTING_VOLUME_TERMINOLOGY.md) for a browser and hardware checklist.

## Using the mixer

Select an output or bus to view and adjust its mix. Drag faders to change digital mixer **volume**; use the controls available on each strip for pan, mute, solo, polarity or separate hardware input gain/trim as supported by the device. The master strip controls the currently selected destination.

Channel strips can be renamed and rearranged to suit your workflow. Minimized strips take less room, and hidden minimized strips can be excluded from view. Any two unpaired channels can be linked with the chain-link buttons at the bottom-right of each strip: first click selects Left and second click selects Right. Dragging is for reordering only. The application preserves interface preferences between sessions; changes to hardware mixer controls are sent to FFADO.

Use the **settings** button to choose a theme and adjust available interface options. In **General**, enable QjackCtl support to show a dedicated integration tab; it is disabled by default. **About** displays the server URL with buttons to open the mixer in your browser or show a scannable QR code. Closing the QR view returns to About. The browser version also includes a fullscreen control. The desktop client can remember its window dimensions for the next launch.

## Configuration and custom themes

User data is stored outside the source tree:

```text
~/.config/ffado-webmixer/
├── config.json
└── themes/
    └── my-theme.css
```

`config.json` contains UI preferences such as names, layouts, stereo pairs, selected theme, and saved desktop window size. Device control endpoints are discovered from FFADO at runtime rather than cached in this file.

To create a theme:

1. Copy a built-in CSS theme from `ffado_webmixer/assets/themes/` into `~/.config/ffado-webmixer/themes/`.
2. Rename it (for example, `my-theme.css`) and edit its CSS variables.
3. Refresh the mixer and select **my-theme** in the theme dropdown.

The theme filename, without `.css`, is its identifier. User themes with the same filename as a built-in theme take precedence. Existing root-level configuration files are imported on first launch when applicable.

## Project structure

```text
main.py                         Application entry point
README.md                       GitHub project overview
docs/                           Changelog and hardware/testing guides
packaging/                      KDE desktop integration helpers
tests/                          Regression test suite
ffado_webmixer/
├── api/                         Flask API endpoints
├── assets/
│   ├── icon.svg                 Application icon
│   ├── static/                  HTML, JavaScript, and layout CSS
│   └── themes/                  Built-in CSS themes
├── profiles/                    Device-family and model XML profiles
├── services/                    Stereo linking and event services
├── client.py                    pywebview desktop client
├── config.py                    User settings persistence
├── demo.py                      Simulated mixer
├── helper.py                    FFADO D-Bus communication
├── interrogate.py               Live device/control discovery
├── mixer.py                     Mixer backend
├── server.py                    Flask server setup
└── themes.py                    Built-in and user theme discovery
```

Additional modules handle device identification, profile loading, control conversion, and QjackCtl integration. See the documentation inside `ffado_webmixer/` and `ffado_webmixer/profiles/` for implementation details.

### Documentation location and patch upgrades

All testing guides and the development changelog now live in [`docs/`](docs/README.md). The top-level `README.md` stays at the root so GitHub displays the project overview. New hardware testing notes should be added under `docs/`, not at the root.

If you **extract the patch ZIP over an older checkout**, ZIP extraction won't delete the old root-level Markdown files automatically. After extracting the patch, run:

```bash
python packaging/migrate_legacy_docs.py
```

The cleanup helper removes only root-level guides that exactly match their original 1.1.0-dev contents and already have replacements in `docs/`. If you edited a guide locally, it is left alone for manual merging. A clean checkout of the full release ZIP does not need this migration step.


### Matrix and strip readback

When DICE/RME output buses are stereo-linked, the strip's level and pan are
derived from the same pair of FFADO matrix coefficients. If stereo-linked
inputs have unequal effective levels, the combined strip shows `MAX` and
provides both channel levels in a tooltip. The arbitrary-input-pair update
keeps link/unlink operations **routing-neutral**: no matrix coefficients are
copied, no silent crosspoint is activated, and a pair can be 2→5 or 7→3.
On linked DICE/RME output buses, a pair's **balance** adjusts only the existing
Left-input→Left-output and Right-input→Right-output coefficients. Custom
crosspoints remain unchanged; disconnected diagonal routes stay disconnected.
A temporary in-memory balance reference allows recovering from full L/R; an
independent matrix edit invalidates that reference. The initial PAN readout
uses the same peak-normalized diagonal balance as the stereo-input write
calculation, so current hardware values appear as soon as the pair is linked.
If both diagonal routes are silent, PAN shows **—** instead of a false center;
use the matrix editor to connect a route. If custom cross-routes are active,
PAN shows `*` and a warning tooltip because a single balance percentage does
not fully describe the stereo matrix. Hardware validation is still required.
See [matrix/strip synchronization tests](docs/TESTING_MATRIX_STRIP_SYNC.md),
[arbitrary stereo routing tests](docs/TESTING_ARBITRARY_STEREO.md),
[bus-isolated stereo regression](docs/TESTING_STEREO_BUS_VISIBILITY.md),
[stereo validation checks](docs/TESTING_STEREO_PAIR_VALIDATION.md), and
[initial pan readback testing](docs/TESTING_INITIAL_PAN.md).

## Troubleshooting

**The application cannot connect to the mixer:** Confirm that your FireWire interface is detected, FFADO supports it, and `ffado-dbus-server` is running and accessible. Try `--demo` to check the web interface independently of the hardware.

**The desktop window does not open:** Check that the pywebview Qt dependencies are installed in the same Python environment used to launch the application. Use `--headless` to test the browser interface separately.

**A custom theme does not appear:** Confirm that the file ends in `.css`, is located in `~/.config/ffado-webmixer/themes/`, and refresh the page.

**Changes to a mixer control have no effect:** Check the device's FFADO support and its XML profile. Available controls vary by device and mixer destination.

## Development

The frontend is built with HTML, CSS, and JavaScript; the backend uses Flask and Python. Device-specific interpretation is defined through XML profiles so that mixer behavior does not need to be hardcoded for every interface.

Contributions, bug reports, and device-profile improvements are welcome. When reporting hardware issues, include the interface model, FFADO version, relevant logs, and the control that behaves unexpectedly.

## License

FFADO WebMixer is free and open-source software licensed under the **GNU General Public License, version 2 or version 3 (GPL-2.0-or-GPL-3.0)**.

This project incorporates code derived from [FFADO](https://ffado.org/), the Free FireWire Audio Drivers project.

FFADO and its original contributors retain their respective copyrights. All FFADO-derived code remains subject to its original licensing terms.

See [LICENSE](LICENSE) for the full license text.
### QR code for the web interface

Settings → About shows a QR-code button next to the server URL. It opens a QR-only
view in the same application window; X or Escape returns to the About tab. The
code contains the server's LAN URL, so the scanning phone/tablet must be able to
reach the host on the network (including TCP port 5000). QR generation works
without internet access or an additional Python dependency. The bundled
JavaScript QR generator is MIT-licensed (see `ffado_webmixer/assets/static/QR-LICENSE.txt`).
