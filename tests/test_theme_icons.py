"""Offline verification of themed favicon, native client and KDE icon support."""
import importlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import re
import sys
import types
from pathlib import Path

from ffado_webmixer.theme_icons import themed_icon_svg, theme_colors, icon_file, configured_theme_icon
from ffado_webmixer.native_icons import NativeThemeIconAPI, sync_installed_launcher_icon


def test_theme_icon_matches_splash_palette_and_has_same_eight_shapes():
    for theme in ('dark', 'light', 'gruvbox', 'nordic', 'high-contrast'):
        colors = theme_colors(theme)
        svg = themed_icon_svg(theme)
        assert svg.count('<rect ') == 7  # tile plus three bars and three sliders
        assert svg.count('<svg') == 1
        for color in colors.values():
            assert f'fill="{color}"' in svg
        assert 'var(' not in svg
    assert themed_icon_svg('light') != themed_icon_svg('dark')


def test_theme_accent_override_matches_splash_behavior():
    colors = theme_colors('gruvbox', '#AA10CF')
    assert colors['accent-color'] == colors['pin-color'] == '#aa10cf'
    assert colors['fader-value-color'] == theme_colors('gruvbox')['fader-value-color']
    assert colors['text-primary'] == theme_colors('gruvbox')['text-primary']
    assert theme_colors('gruvbox', 'javascript:evil') == theme_colors('gruvbox')
    assert themed_icon_svg('../../secret') == themed_icon_svg('dark')


def test_icon_cache_is_versioned_by_theme_and_accent(tmp_path):
    default = icon_file('dark', cache_dir=tmp_path)
    special = icon_file('dark', '#123456', cache_dir=tmp_path)
    light = icon_file('light', cache_dir=tmp_path)
    assert len({default, special, light}) == 3
    assert default.read_text() == themed_icon_svg('dark')
    assert icon_file('dark', cache_dir=tmp_path) == default
    assert configured_theme_icon({'theme': 'dark', 'accent_overrides': {'dark': '#123456'}}, tmp_path) == special


def test_only_owned_kde_launcher_icons_are_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    entry = tmp_path/'data/applications/ffado-webmixer.desktop'
    installed = tmp_path/'data/icons/hicolor/scalable/apps/ffado-webmixer.svg'
    entry.parent.mkdir(parents=True)
    installed.parent.mkdir(parents=True)
    installed.write_text('<svg>old</svg>')
    wanted = icon_file('light', '#554433', tmp_path/'cache')
    assert not sync_installed_launcher_icon(wanted)
    assert installed.read_text() == '<svg>old</svg>'
    entry.write_text('[Desktop Entry]\nIcon=other\nStartupWMClass=ffado-webmixer\n')
    assert not sync_installed_launcher_icon(wanted)
    entry.write_text('[Desktop Entry]\nName=FFADO Webmixer\nIcon=ffado-webmixer\nStartupWMClass=ffado-webmixer\n')
    assert sync_installed_launcher_icon(wanted)
    assert installed.read_bytes() == wanted.read_bytes()


def test_native_api_rejects_unknown_theme_without_touching_disk(monkeypatch):
    module = importlib.import_module('ffado_webmixer.native_icons')
    touched = []
    monkeypatch.setattr(module, 'icon_file', lambda *a: touched.append(a) or Path('/tmp/theme-icon.svg'))
    monkeypatch.setattr(module, 'sync_installed_launcher_icon', lambda path: True)
    bridge = NativeThemeIconAPI()
    assert bridge.set_theme_icon('../trick')['ok'] is False
    assert not touched
    assert bridge.set_theme_icon('gruvbox', '#ff44aa')['ok'] is True
    assert touched == [('gruvbox', '#ff44aa')]
    assert bridge._pending == Path('/tmp/theme-icon.svg')


def test_native_icon_bridge_queues_qt_window_update(monkeypatch):
    module = importlib.import_module('ffado_webmixer.native_icons')
    ui_calls = []
    class Signal:
        def __init__(self, *args): self.slot = None
        def connect(self, func, *args): self.slot = func
        def emit(self, value): self.slot(value)
    class QObject:
        def moveToThread(self, thread): ui_calls.append(('thread', thread))
    class QIcon:
        def __init__(self, path): self.path = path
    class Window:
        def isTopLevel(self): return True
        def setIcon(self, icon): ui_calls.append(('window', icon.path))
    class App:
        def thread(self): return 'GUI'
        def setWindowIcon(self, icon): ui_calls.append(('app', icon.path))
        def allWindows(self): return [Window()]
    fakeapp = App()
    core = types.ModuleType('PyQt6.QtCore')
    core.QObject = QObject
    core.Qt = types.SimpleNamespace(ConnectionType=types.SimpleNamespace(QueuedConnection=1))
    core.pyqtSignal = lambda *args: Signal()
    core.pyqtSlot = lambda *args: (lambda fn: fn)
    gui = types.ModuleType('PyQt6.QtGui')
    gui.QGuiApplication = types.SimpleNamespace(instance=lambda: fakeapp)
    gui.QIcon = QIcon
    pyqt = types.ModuleType('PyQt6')
    monkeypatch.setitem(sys.modules, 'PyQt6', pyqt)
    monkeypatch.setitem(sys.modules, 'PyQt6.QtCore', core)
    monkeypatch.setitem(sys.modules, 'PyQt6.QtGui', gui)
    monkeypatch.setattr(module, 'icon_file', lambda theme, accent=None: Path('/tmp/' + theme + '.svg'))
    monkeypatch.setattr(module, 'sync_installed_launcher_icon', lambda path: True)
    bridge = NativeThemeIconAPI()
    bridge.set_theme_icon('light')
    bridge.attach_qt()
    assert ('app', '/tmp/light.svg') in ui_calls
    bridge.set_theme_icon('gruvbox')
    assert ('window', '/tmp/gruvbox.svg') in ui_calls
    assert ('thread', 'GUI') in ui_calls


def test_concurrent_pywebview_icon_requests_use_unique_temp_files(tmp_path, monkeypatch):
    """Two same-PID threads must not race to rename the same temp SVG."""
    module = importlib.import_module('ffado_webmixer.theme_icons')
    real_replace = module.os.replace
    both_ready = Barrier(2)
    sources = []

    def synchronized_replace(src, dst):
        sources.append(Path(src))
        both_ready.wait(timeout=5)
        return real_replace(src, dst)

    monkeypatch.setattr(module.os, 'replace', synchronized_replace)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(icon_file, 'dark', '#e8460c', tmp_path) for _ in range(2)]
        paths = [f.result(timeout=10) for f in futures]

    assert paths[0] == paths[1]
    assert paths[0].read_text(encoding='utf-8') == themed_icon_svg('dark', '#e8460c')
    assert len(set(sources)) == 2, 'concurrent writers used the same temporary name'
    assert list(tmp_path.glob('*.tmp')) == []
    assert list(tmp_path.glob('.*.tmp')) == []


def test_icon_cache_cleans_up_after_failed_atomic_replace(tmp_path, monkeypatch):
    module = importlib.import_module('ffado_webmixer.theme_icons')
    with monkeypatch.context() as scoped:
        def fail_replace(src, dest):
            raise PermissionError('simulated cache write failure')
        scoped.setattr(module.os, 'replace', fail_replace)
        try:
            icon_file('gruvbox', cache_dir=tmp_path)
        except PermissionError:
            pass
        else:
            raise AssertionError('cache write failure was not propagated')
    assert list(tmp_path.glob('.*.tmp')) == []
    assert icon_file('gruvbox', cache_dir=tmp_path).is_file()
