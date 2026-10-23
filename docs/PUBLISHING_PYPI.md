# Building and publishing FFADO Webmixer on PyPI

This project is a Linux-focused Python package in the **src layout**. The
published distribution name is `ffado-webmixer`, and its console command is
`ffado-webmixer`. The package and `--version` both report `1.2.0`.
Setuptools reads the version from `ffado_webmixer.__version__`.
Check that the name is available on PyPI before your first upload.

## 1. Dependencies on the host

The hardware requires `ffado-dbus-server` and the OS FireWire stack (these
are **not** provided by pip). Building `dbus-python` may require D-Bus/GLib
headers, `pkg-config`, and a compiler. The pip package includes Flask and
pywebview's PyQt6 desktop backend. On Arch/EndeavourOS, you can satisfy
native build tools with pacman packages such as `base-devel`, `pkgconf`,
`dbus`, and `glib2` as needed. A working FFADO service is still required.

Use `pipx install ffado-webmixer` for a CLI application install or
`python -m pip install ffado-webmixer` inside an activated venv.

## 2. Build from a clean checkout

```bash
python -m pip install --upgrade build twine
python -m pytest -q
python -m build
python -m twine check dist/*
```

`python -m build` creates `dist/ffado_webmixer-1.2.0-py3-none-any.whl`
and `dist/ffado_webmixer-1.2.0.tar.gz`. Verify the wheel includes
`src` package code, all XML profiles, all static assets, and the ten
built-in theme icons. A source checkout can also run `python main.py`.

## 3. Test the built artifacts

```bash
python -m venv /tmp/ffado-webmixer-release-test
/tmp/ffado-webmixer-release-test/bin/pip install dist/*.whl
/tmp/ffado-webmixer-release-test/bin/ffado-webmixer --version
/tmp/ffado-webmixer-release-test/bin/ffado-webmixer --debug list
/tmp/ffado-webmixer-release-test/bin/ffado-webmixer --demo
```

The first **native desktop** launch prompts once to install a KDE/XDG
launcher and icon. Declining is remembered in
`~/.config/ffado-webmixer/config.json`. An ordinary LAN browser never
receives the desktop-install prompt; `--headless` never opens it. To add
it later, run `ffado-webmixer --install-desktop`. To remove it, run
`ffado-webmixer --remove-desktop`. Neither pip nor wheel installation
creates or changes a desktop launcher automatically.

The launcher is in `$XDG_DATA_HOME/applications` (default
`~/.local/share/applications`) and the matching theme icon under
`$XDG_DATA_HOME/icons/hicolor/scalable/apps`. The icon is overwritten
when you change themes inside the desktop client and resynchronized on
its next launch. Plasma may retain its cached launcher/taskbar artwork
until the next run. In-browser favicons update on every theme change.

Built-in theme icons are checked into `src/ffado_webmixer/assets/themes/icons`.
For user-defined themes and custom accent overrides, a per-user cache SVG
is generated and copied into the same icon destination; no files are
written inside Python's installed site-packages directory.

## 4. Publish (only when ready)

```bash
python -m twine upload --repository testpypi dist/*
# Install and verify from TestPyPI, checking dependency sources as needed.
python -m twine upload dist/*
```

Use a token-scoped API credential or PyPI Trusted Publishing. Never commit
tokens to Git. Uploading is an explicit release step and is **not** performed
by the build scripts. To publish a subsequent revision, increment the version
in `src/ffado_webmixer/__init__.py` first; PyPI does not allow replacing uploaded files.

## 5. License check

The source repository contains the GNU GPL v2 text. The metadata currently
identifies the intended project distribution license as GPL-2.0-or-later.
**Before publishing**, verify rights/attribution of all bundled profiles
and third-party code and confirm compatibility with the free PyQt6 backend.
If your project's actual licensing grant is GPL-2.0-only, clarify this
before uploading: a GPLv3-licensed Qt dependency can affect distribution
compatibility. The third-party QR code license lives at
`src/ffado_webmixer/assets/static/QR-LICENSE.txt`.
