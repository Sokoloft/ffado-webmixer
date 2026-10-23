"""Package and first-run tests; never write to the actual KDE directory."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.desktop_integration import (
    desktop_paths, install, is_installed, launcher_command, launcher_text, remove,
)
from ffado_webmixer.native_icons import NativeThemeIconAPI, sync_installed_launcher_icon
from ffado_webmixer.theme_icons import configured_theme_icon, themed_icon_svg, icon_file
from ffado_webmixer.themes import BUILTIN_THEMES


def test_all_bundled_icons_match_their_stylesheets():
    for css in BUILTIN_THEMES.glob('*.css'):
        icon = BUILTIN_THEMES / 'icons' / (css.stem + '.svg')
        assert icon.is_file()
        assert icon.read_text() == themed_icon_svg(css.stem)
        assert icon_file(css.stem) == icon
    assert len(list((BUILTIN_THEMES / 'icons').glob('*.svg'))) == len(list(BUILTIN_THEMES.glob('*.css')))


def test_installer_requires_opt_in_and_uses_theme_icon(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    desktop, icon = desktop_paths()
    assert not desktop.exists() and not icon.exists()
    config = Config(tmp_path / 'config.json')
    config.load()
    config.settings['theme'] = 'nordic'
    bridge = NativeThemeIconAPI(config)
    assert bridge.desktop_integration_status() == {'prompt': True}
    assert not desktop.exists()
    installed = bridge.desktop_integration_install()
    assert installed['ok'] is True
    assert is_installed()
    assert icon.read_text() == themed_icon_svg('nordic')
    assert bridge.desktop_integration_status()['prompt'] is False
    assert Config(config.path).load() is None
    assert remove() is True
    assert bridge.desktop_integration_status()['prompt'] is False  # only ask once


def test_decline_persists_and_does_not_create_launcher(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'share'))
    cfg = Config(tmp_path / 'preferences.json')
    cfg.load()
    bridge = NativeThemeIconAPI(cfg)
    assert bridge.desktop_integration_status()['prompt'] is True
    assert bridge.desktop_integration_dismiss()['ok'] is True
    assert not is_installed()
    reloaded = Config(cfg.path)
    reloaded.load()
    assert NativeThemeIconAPI(reloaded).desktop_integration_status()['prompt'] is False
    assert NativeThemeIconAPI(Config()).desktop_integration_status()['prompt'] is False


def test_does_not_replace_unrelated_desktop_entry(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    desktop, icon = desktop_paths()
    desktop.parent.mkdir(parents=True)
    desktop.write_text('[Desktop Entry]\nName=Other App\nIcon=unrelated\n')
    with pytest.raises(FileExistsError):
        install({'theme': 'light'}, argv0=__file__)
    assert desktop.read_text().endswith('Icon=unrelated\n')
    assert not icon.exists()
    with pytest.raises(PermissionError):
        remove()


def test_theme_switch_overwrites_owned_launcher_icon(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'share'))
    install({'theme': 'dark'}, argv0=__file__)
    _, path = desktop_paths()
    assert sync_installed_launcher_icon(icon_file('light'))
    assert path.read_text() == themed_icon_svg('light')
    assert sync_installed_launcher_icon(icon_file('nordic', '#112233', tmp_path / 'cache'))
    assert path.read_text() == themed_icon_svg('nordic', '#112233')
    assert not list(path.parent.glob('*.tmp'))


def test_package_assets_are_available():
    from ffado_webmixer import theme_icons
    root = Path(theme_icons.__file__).parent
    assert (root / 'assets/static/index.html').is_file()
    assert (root / 'assets/static/desktop-integration.js').is_file()
    assert (root / 'profiles/motu/motu_ultralite.xml').is_file()
    assert len(list((root / 'profiles').rglob('*.xml'))) >= 150


def test_manual_cli_install_does_not_require_ffado(tmp_path, monkeypatch):
    from ffado_webmixer import main
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'share'))
    monkeypatch.setattr(main, 'CONFIG_FILE', tmp_path / 'cfg.json')
    monkeypatch.setattr(main, 'parse_args', lambda: __import__('types').SimpleNamespace(
        install_desktop=True, remove_desktop=False, check_desktop=False))
    main.main()
    assert is_installed()
    monkeypatch.setattr(main, 'parse_args', lambda: __import__('types').SimpleNamespace(
        install_desktop=False, remove_desktop=True, check_desktop=False))
    main.main()
    assert not is_installed()
