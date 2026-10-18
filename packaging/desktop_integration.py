#!/usr/bin/env python3
"""Install/check/remove a per-user KDE/Wayland desktop entry for a source checkout.

No root privilege or third-party packages. Intended for developers who run the
project from PyCharm or a local venv rather than a distro-installed package.
The FFADO control service and audio configuration are never modified.
"""
import argparse
import os
from pathlib import Path
import shutil
import sys

APP_ID = 'ffado-webmixer'
ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / 'ffado_webmixer' / 'assets' / 'icon.svg'


def desktop_quote(value):
    """Quote one Exec argument according to the Desktop Entry specification."""
    value = str(value).replace('%', '%%')
    value = value.replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    return '"' + value + '"'


def paths(home):
    home = Path(home)
    data_home = Path(os.environ.get('XDG_DATA_HOME', str(home / '.local/share'))).expanduser()
    return (data_home / 'applications' / (APP_ID + '.desktop'),
            data_home / 'icons/hicolor/scalable/apps' / (APP_ID + '.svg'))


def entry(python, root=ROOT):
    return '\n'.join([
        '[Desktop Entry]',
        'Type=Application',
        'Name=FFADO Webmixer',
        'GenericName=FireWire Audio Mixer',
        'Comment=Control supported FFADO FireWire audio interfaces',
        'Exec=' + desktop_quote(python) + ' ' + desktop_quote(Path(root) / 'main.py'),
        'TryExec=' + str(Path(python).resolve()),
        'Icon=' + APP_ID,
        'Terminal=false',
        'Categories=AudioVideo;Audio;Mixer;',
        'StartupNotify=true',
        'StartupWMClass=' + APP_ID,
        '',
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    op = parser.add_mutually_exclusive_group()
    op.add_argument('--check', action='store_true', help='Check for matching installed desktop entry/icon')
    op.add_argument('--remove', action='store_true', help='Remove only the desktop entry/icon installed by this tool')
    parser.add_argument('--python', dest='interpreter', type=Path,
                        help='Interpreter used to start main.py (defaults to .venv/bin/python when present)')
    args = parser.parse_args(argv)
    desktop, icon = paths(Path.home())
    default = ROOT / '.venv/bin/python'
    interpreter = args.interpreter or (default if default.is_file() else Path(sys.executable))
    if args.check:
        found = desktop.is_file() and icon.is_file()
        valid = found and f'StartupWMClass={APP_ID}' in desktop.read_text() and (f'Icon={APP_ID}' in desktop.read_text())
        print(('OK' if valid else 'NOT INSTALLED / INVALID') + f': {desktop} | {icon}')
        return 0 if valid else 1
    if args.remove:
        # Never delete another application's desktop file or icon.
        if desktop.is_file() and f'StartupWMClass={APP_ID}' in desktop.read_text():
            desktop.unlink()
        if icon.is_file():
            icon.unlink()
        print('Removed FFADO Webmixer desktop entry/icon where present.')
        return 0
    if not interpreter.is_file():
        parser.error(f'Python interpreter not found: {interpreter}')
    if not (ROOT / 'main.py').is_file() or not ICON.is_file():
        parser.error('Run the installer from an extracted ffado-webmixer release')
    desktop.parent.mkdir(parents=True, exist_ok=True)
    icon.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(entry(interpreter), encoding='utf-8')
    shutil.copyfile(ICON, icon)
    print('Installed desktop entry:', desktop)
    print('Installed app icon:', icon)
    print('Launcher Python:', interpreter)
    print('For KDE taskbar matching, launch this entry once and pin the new window.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
