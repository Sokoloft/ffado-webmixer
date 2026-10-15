# ffado-webmixer Python package

`ffado-webmixer` is a Python/Flask web-based alternative to FFADO's Qt mixer. It supports a browser UI and an optional pywebview desktop window.

## Package layout

| Path | Responsibility |
| --- | --- |
| `config.py` | Application preferences and user-specific channel/layout settings persisted to the project's `config.json`; not a hardware discovery cache. |
| `server.py` | Flask application setup and API route registration. |
| `api/` | HTTP endpoints for mixer operations, settings, stereo linking, events, and QjackCtl integration. |
| `services/` | Application services for stereo-linking operations and server-sent event broadcasting. |
| `client.py` | Optional pywebview desktop window and Flask readiness check. |
| `mixer.py` | Runtime mixer state and FFADO hardware control reads/writes. |
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

## Data ownership

Device identity and available D-Bus controls are discovered at runtime. XML profiles describe device-family and model-specific control interpretation. `config.json` stores webmixer preferences and user layout choices, not cached FFADO topology.

## Python package marker

Keep `ffado_webmixer/__init__.py` as an empty file. Although Python supports namespace packages, the marker maintains conventional package behavior for relative imports, packaging tools, and IDEs. Documentation belongs in this README.

## Maintenance

The `api/` and `services/` folders are Python packages and should retain their `__init__.py` files. The same applies to `profiles/`. Generated `__pycache__/` directories can be deleted while the application is stopped; Python recreates them automatically.
