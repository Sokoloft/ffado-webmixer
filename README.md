# DISCLAIMER
**THIS PROJECT IS MADE USING AI (Claude and ChatGPT)**

I wanted something better than `ffado-mixer`. 
Originally this was going to be a front end with a modular back end like [Mixing Station](https://mixingstation.app/).
However, there is no need thus this project turned into `ffado-webmixer`

# FFADO WebMixer

**FFADO WebMixer** is a web-based mixer interface for FireWire audio devices supported by [FFADO](https://ffado.org/). It provides a modern alternative to the traditional `ffado-mixer` interface, accessible through a desktop window or a web browser on your local network.

The application uses Python, Flask, and FFADO's D-Bus control interface. A pywebview desktop client is available for local use; the same mixer can also run without a desktop window for access from another computer, tablet, or phone.

> **Project status:** Device selection uses exact source-derived FFADO identities and explicit model-level capability declarations. The catalogue identifies more devices than the application can currently control: an identity-only profile deliberately exposes **no guessed writable mixer**. Actual hardware control additionally requires matching D-Bus endpoints. See [`ffado_webmixer/profiles/CAPABILITIES.md`](ffado_webmixer/profiles/CAPABILITIES.md).

## Features

- Control supported mixer levels, gain, pan, mute, solo, and polarity/invert functions where available.
- Select available outputs and buses, with a master fader for the selected destination.
- Link odd/even hardware input channels (1/2, 3/4, ...) using explicit link buttons, rather than dragging them together.
- Link consecutive output buses on supported gain matrices and use per-channel stereo balance.
- Show DICE/RME mixer gain in dB rather than raw percentages; soft mute and solo where supported.
- Show real, matched DICE EAP router-destination peak meters when exposed by FFADO.
- Recover interrupted software mute/solo safely using per-device gain journals, explicit restore/discard controls, and verified hardware readback.
- Switch among multiple connected, source-profiled FFADO interfaces by FireWire GUID, with optional local aliases.
- Edit supported DICE/RME matrix coefficients with a rotary control, numeric dB entry, and presets.
- Rename, reorder, pin, minimize, and hide channel strips.
- Remember mixer layout, names, stereo links, selected theme, and other interface preferences.
- Use built-in color themes or add your own CSS themes, including accent color customization.
- Open the interface in a native desktop window or from a browser on your network.
- Try the interface without FireWire hardware using demo mode.
- Enable QjackCtl support in **Settings → General** to reveal a dedicated **QjackCtl** tab with Graph and Patchbay controls.
- Open the dedicated **In/Out** dialog for hardware routing. MOTU pre-Mk3 devices
  show mix-bus-to-output assignment, while supported DICE devices expose their
  mixer-gain and crossbar controls separately.

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

See [`TESTING_MULTIPLE_DEVICES_KDE.md`](TESTING_MULTIPLE_DEVICES_KDE.md) for
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
[`TESTING_CAPABILITIES.md`](TESTING_CAPABILITIES.md).

Each interface's layout, stereo links and aliases are kept in
`~/.config/ffado-webmixer/devices/<guid>.json`; the original `config.json` is
kept as an initial migration source and for desktop-window preferences.

See `TESTING_V1_1.md` for live-hardware validation and known limitations.

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

## Using the mixer

Select an output or bus to view and adjust its mix. Drag faders to change levels; use the controls available on each strip for gain, pan, mute, solo, or polarity as supported by the device. The master strip controls the currently selected destination.

Channel strips can be renamed and rearranged to suit your workflow. Minimized strips take less room, and hidden minimized strips can be excluded from view. Odd/even channels can be linked with the button between their strips; dragging is for reordering only. The application preserves interface preferences between sessions; changes to hardware mixer controls are sent to FFADO.

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
