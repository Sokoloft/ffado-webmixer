# ffado-webmixer Python package

`ffado-webmixer` is a Python/Flask web-based alternative to FFADO's Qt mixer. It supports a browser UI and an optional pywebview desktop window.

## Package layout

| Path | Responsibility |
| --- | --- |
| `config.py` | Validated application preferences in `~/.config/ffado-webmixer/config.json` and per-GUID files under `devices/`; malformed files are preserved as unique `.bad` backups. |
| `access.py` | Local/LAN listener policy, remote authentication, and browser-write checks. |
| `server.py` | Flask application setup and API route registration. |
| `api/` | HTTP endpoints for mixer operations, settings, stereo linking, events, and QjackCtl integration. |
| `services/` | Application services for stereo-linking operations and server-sent event broadcasting. |
| `client.py` | Optional pywebview desktop window and Flask readiness check. |
| `mixer.py` | Runtime mixer state and channel control reads/writes; composes routing and output controls. |
| `mixer_routing.py` | Matrix, crossbar, stereo playback, and bus destination operations. |
| `mixer_outputs.py` | Master-output levels and verified software mute transitions. |
| `interrogate.py` | Live FFADO D-Bus discovery of device identity and available endpoints. |
| `device_registry.py` | FFADO device-to-mixer family matching using installed FFADO configuration. |
| `helper.py` | Low-level D-Bus access and connection handling. |
| `controls.py` | Value normalization and control conversions. |
| `profile_loader.py` | Compatibility imports for the profile modules. |
| `profiles/loader.py` | XML profile loading, matching, and inheritance. |
| `profiles/resolver.py` | Interpretation of live controls and matrix topology using profiles. |
| `profiles/<family>/` | Shared (`common.xml`) and device-specific XML definitions. |
| `demo.py` | Simulated mixer backend for `--demo`. |
| `qjackctl.py` | QjackCtl integration through D-Bus. |
| `assets/` | Application assets: `static/` for web pages, `themes/` for theme CSS, and `icon.svg` for the desktop icon. |
| `assets/static/live-sync.js` | Device-scoped event handling and complete state refresh after overflow or reconnect. |

## Data ownership

Device identity and available D-Bus controls are discovered at runtime. XML profiles describe device-family and model-specific control interpretation. `config.json` stores webmixer preferences and user layout choices, not cached FFADO topology.

## Python package marker

`src/ffado_webmixer/__init__.py` defines `__version__`, currently `1.2.0`.
Setuptools reads this value for distribution metadata, and the application uses
it for CLI and About versions. Keep this module free of runtime dependency
imports so packaging and `--version` work without Flask, Qt or D-Bus.

## Maintenance

The `api/` and `services/` folders are Python packages and should retain their `__init__.py` files. The same applies to `profiles/`. Generated `__pycache__/` directories can be deleted while the application is stopped; Python recreates them automatically.
