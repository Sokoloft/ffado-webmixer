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
python main.py --enable-remote-access
python main.py --headless
```

The setup command prompts for a username, a hidden password (at least 16 characters), and password confirmation, then exits without starting the mixer. The password is never passed as a command argument. You can also configure these credentials in **Settings → Remote Access** from the local app or localhost browser. Both methods store the username and a salted Argon2id password hash in `~/.config/ffado-webmixer/auth.json`, with directory permissions `0700` and file permissions `0600`.

After enabling remote access, start or restart the app and open `http://HOST-IP:5000/`. Sign in with your chosen username and password. The saved setting enables the LAN listener; `--host 127.0.0.1` overrides it for a local-only launch. Demo/debug sessions stay local by default and cannot change saved remote-access settings; an explicit `--host 0.0.0.0` uses previously saved credentials for remote testing.

The local desktop and localhost browser remain accessible without a password. GUI credential changes apply to new requests immediately; leave the password fields blank to keep the current password. Disabling remote access in the GUI immediately blocks new remote requests; restart to close the listener. For command-line disabling, run `python main.py --disable-remote-access` and restart any running instance. CLI changes are picked up on the next application start. The former `FFADO_WEBMIXER_TOKEN` variable is no longer used.

HTTP Basic authentication does not encrypt traffic. Use HTTPS or an SSH tunnel to protect credentials over the network. Do not forward this port to the public internet.

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
