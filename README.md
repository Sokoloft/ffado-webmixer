# DISCLAIMER
**THIS PROJECT IS MADE USING AI (Claude and ChatGPT)**

I wanted something better than `ffado-mixer`. 
Originally this was going to be a front end with a modular back end like [Mixing Station](https://mixingstation.app/).
However, there is no need thus this project turned into `ffado-webmixer`

# FFADO WebMixer

**FFADO WebMixer** is a web-based mixer interface for FireWire audio devices supported by [FFADO](https://ffado.org/). It provides a modern alternative to the traditional `ffado-mixer` interface, accessible through a desktop window or a web browser on your local network.

The application uses Python, Flask, and FFADO's D-Bus control interface. A pywebview desktop client is available for local use; the same mixer can also run without a desktop window for access from another computer, tablet, or phone.

> **Project status:** Device features depend on the connected interface and its FFADO support. XML profiles help interpret device-specific controls; not every control is available on every device.

## Features

- Control supported mixer levels, gain, pan, mute, solo, and polarity/invert functions where available.
- Select available outputs and buses, with a master fader for the selected destination.
- Link compatible channels into stereo pairs.
- Rename, reorder, pin, minimize, and hide channel strips.
- Remember mixer layout, names, stereo links, selected theme, and other interface preferences.
- Use built-in color themes or add your own CSS themes, including accent color customization.
- Open the interface in a native desktop window or from a browser on your network.
- Try the interface without FireWire hardware using demo mode.
- Access QjackCtl integration where available.

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

Channel strips can be renamed and rearranged to suit your workflow. Minimized strips take less room, and hidden minimized strips can be excluded from view. Compatible channels can be linked into stereo pairs. The application preserves interface preferences between sessions; changes to hardware mixer controls are sent to FFADO.

Use the **settings** button to choose a theme and adjust available interface options. The browser version also includes a fullscreen control. The desktop client can remember its window dimensions for the next launch.

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