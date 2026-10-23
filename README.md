<div align="center">
  <h1>FFADO WebMixer</h1>
  <img src="img/logo.svg" alt="FFADO WebMixer logo" width="128">
</div>

**FFADO WebMixer** is a web-based mixer for FireWire audio interfaces supported by [FFADO](https://ffado.org/). Control your mixer in a Linux desktop window or from a browser on your computer, phone, or tablet.

## Features

- Adjust channel levels, pan, and available mute/solo controls, with live peak meters.
- Configure supported input/output routing and mixer matrices.
- Link stereo channels and buses; rename, pin, minimize, and rearrange mixer controls.
- Switch between connected FireWire interfaces and remember the last selected mixer.
- Choose from built-in themes, including a matching desktop icon.
- Optionally access QjackCtl controls from the interface.

Available controls depend on what each device exposes through FFADO.

**Disclaimer:** This project was made entirely using AI (ChatGPT and Claude).

## Requirements

- Linux and Python 3.
- The Python dependencies listed in **[`requirements.txt`](requirements.txt)**. Install these in your Python environment before running the application.
- FFADO, `ffado-dbus-server`, and a supported FireWire audio interface for hardware control.
- A working Qt environment for the optional desktop window.

FFADO WebMixer controls hardware through D-Bus. It does **not** replace the FFADO audio driver or JACK.

## Usage

Run these commands from the project root:

```bash
# Open the desktop mixer
python main.py

# Try the interface without FireWire hardware
python main.py --demo

# Run only the web server (no desktop window)
python main.py --headless

# List available offline debug profiles
python main.py --debug list

# Open a simulated ProFire 2626 profile
python main.py --debug profire2626
```

By default the server listens only on the host computer. In headless mode, open **http://localhost:5000/**.

To enable access from another device on your trusted network, set a password of at least 16 characters and explicitly enable the LAN listener:

```bash
export FFADO_WEBMIXER_TOKEN='replace-this-with-a-long-random-password'
python main.py --headless --host 0.0.0.0
```

Open `http://HOST-IP:5000/` and sign in with username **ffado** and that password. The local desktop and localhost browser remain accessible without a password. HTTP Basic authentication does not encrypt traffic; use a trusted LAN or an SSH tunnel. Do not forward this port to the public internet.

On first desktop launch, the application can offer to install a launcher and themed icon. You can also manage it manually:

```bash
python main.py --install-desktop
python main.py --check-desktop
python main.py --remove-desktop
```

## Using the mixer

Select a connected interface from the device dropdown when more than one is available. Use the three-dot menus on buses and faders to link, pin, or minimize them. Right-click a name or numeric field to edit it, or long-press on a touchscreen.

## Documentation and screenshots

Additional reference information is in [`docs/`](docs/README.md). The [`img/`](img/) folder holds the project logo and will contain demo GIFs showing the interface.

## License

See [`LICENSE`](LICENSE) for the project's GPL terms. FFADO and its contributors retain their respective copyrights.
