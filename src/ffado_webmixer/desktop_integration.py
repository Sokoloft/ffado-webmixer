"""Opt-in, per-user XDG desktop launcher installation for PyPI/source installs.

Never writes to /usr and never installs desktop entries during pip install.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

APP_ID = "ffado-webmixer"
OWNERSHIP = "X-FFADO-Webmixer-Managed=true"


def desktop_paths():
    data = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share').expanduser()
    return (data / 'applications' / f'{APP_ID}.desktop',
            data / 'icons/hicolor/scalable/apps' / f'{APP_ID}.svg')


def _owns_launcher(path):
    try:
        content = path.read_text(encoding='utf-8')
    except OSError:
        return False
    # Support launcher files produced by our previous source installer.
    return (OWNERSHIP in content or
            ('Icon=ffado-webmixer' in content.splitlines() and
             'StartupWMClass=ffado-webmixer' in content.splitlines() and
             'Name=FFADO Webmixer' in content.splitlines()))


def is_installed():
    desktop, icon = desktop_paths()
    return desktop.is_file() and icon.is_file() and _owns_launcher(desktop)


def _quote_exec(value):
    """One Desktop Entry Exec token. Encode reserved %, $, backtick etc."""
    value = str(value).replace('%', '%%')
    for orig, escaped in (('\\', '\\\\'), ('"', '\\"'), ('`', '\\`'), ('$', '\\$')):
        value = value.replace(orig, escaped)
    return '"' + value + '"'


def launcher_command(argv0=None):
    """Prefer the actual pipx/pip console-script path, including symlinks."""
    raw = str(sys.argv[0] if argv0 is None else argv0)
    filename = Path(raw).name
    if filename == 'main.py':
        return [sys.executable, str(Path(raw).absolute())]
    if filename == '__main__.py':
        return [sys.executable, '-m', 'ffado_webmixer']
    if os.path.sep not in raw:
        located = shutil.which(raw)
        if located:
            raw = located
    command = Path(raw).absolute()
    if not command.is_file():
        # CLI option in an unusual embedding: python -m remains usable.
        return [sys.executable, '-m', 'ffado_webmixer']
    return [str(command)]


def launcher_text(argv0=None):
    command = launcher_command(argv0)
    return '\n'.join((
        '[Desktop Entry]',
        'Type=Application',
        'Name=FFADO Webmixer',
        'GenericName=FireWire Audio Mixer',
        'Comment=Control supported FFADO FireWire audio interfaces',
        'Exec=' + ' '.join(map(_quote_exec, command)),
        'Icon=' + APP_ID,
        'Terminal=false',
        'Categories=AudioVideo;Audio;Mixer;',
        'StartupNotify=true',
        'StartupWMClass=' + APP_ID,
        OWNERSHIP,
        '',
    ))


def _atomic_write(path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
        os.replace(tmp_name, path)
    finally:
        Path(tmp_name).unlink(missing_ok=True)


def install(settings=None, argv0=None):
    """Install launcher and current theme icon, only after explicit consent.

    Decline to overwrite an unrelated desktop file. Use per-user XDG paths.
    """
    from .theme_icons import configured_theme_icon
    desktop, icon = desktop_paths()
    if desktop.exists() and not _owns_launcher(desktop):
        raise FileExistsError(f'An unrelated launcher already exists: {desktop}')
    icon_source = configured_theme_icon(settings or {})
    # Install icon first so a newly-visible launcher never references a missing icon.
    _atomic_write(icon, icon_source.read_bytes())
    _atomic_write(desktop, launcher_text(argv0).encode('utf-8'))
    return desktop, icon


def remove():
    desktop, icon = desktop_paths()
    if not desktop.exists():
        return False
    if not _owns_launcher(desktop):
        raise PermissionError('Existing launcher is not owned by FFADO Webmixer')
    desktop.unlink()
    icon.unlink(missing_ok=True)
    return True
