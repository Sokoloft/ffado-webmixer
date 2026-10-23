"""The pywebview window title follows the selected device without Qt in CI."""
import importlib
import sys
import types

from ffado_webmixer.native_icons import NativeThemeIconAPI


def fake_qt(monkeypatch, calls):
    """Stub QObject signals and assert the signal's queued-connection request."""
    class Signal:
        def connect(self, fn, mode):
            assert mode == 'queued'
            self.slot = fn
        def emit(self, value):
            self.slot(value)
    class QObject:
        def moveToThread(self, thread):
            assert thread == 'gui'
    class App:
        def thread(self): return 'gui'
        def setWindowIcon(self, icon): pass
        def allWindows(self): return []
    core = types.ModuleType('PyQt6.QtCore')
    core.QObject = QObject
    core.Qt = types.SimpleNamespace(ConnectionType=types.SimpleNamespace(QueuedConnection='queued'))
    core.pyqtSignal = lambda *args: Signal()
    core.pyqtSlot = lambda *args: lambda fn: fn
    gui = types.ModuleType('PyQt6.QtGui')
    gui.QGuiApplication = types.SimpleNamespace(instance=lambda: App())
    gui.QIcon = lambda path: path
    monkeypatch.setitem(sys.modules, 'PyQt6', types.ModuleType('PyQt6'))
    monkeypatch.setitem(sys.modules, 'PyQt6.QtCore', core)
    monkeypatch.setitem(sys.modules, 'PyQt6.QtGui', gui)


class TitleWindow:
    def __init__(self): self._title = 'ffado-webmixer: MOTU UltraLite'; self.changes = []
    @property
    def title(self): return self._title
    @title.setter
    def title(self, name):
        self._title = name
        self.changes.append(name)


def test_native_title_switches_devices_on_qt_thread(monkeypatch):
    fake_qt(monkeypatch, [])
    api = NativeThemeIconAPI()
    window = TitleWindow()
    api.attach_window(window)
    api.attach_qt()
    assert api.set_device_title('Saffire PRO 40') == {'ok': True}
    assert window.title == 'ffado-webmixer: Saffire PRO 40'
    assert api.set_device_title('MOTU UltraLite') == {'ok': True}
    assert window.title == 'ffado-webmixer: MOTU UltraLite'
    assert window.changes == ['ffado-webmixer: Saffire PRO 40', 'ffado-webmixer: MOTU UltraLite']


def test_native_title_sent_before_qt_ready_is_applied_later(monkeypatch):
    fake_qt(monkeypatch, [])
    api = NativeThemeIconAPI()
    window = TitleWindow()
    api.attach_window(window)
    assert api.set_device_title('Saffire PRO 40')['ok'] is True
    assert window.title == 'ffado-webmixer: MOTU UltraLite'  # queued until Qt exists
    api.attach_qt()
    assert window.title == 'ffado-webmixer: Saffire PRO 40'


def test_native_title_rejects_invalid_names(monkeypatch):
    fake_qt(monkeypatch, [])
    api = NativeThemeIconAPI()
    window = TitleWindow()
    api.attach_window(window)
    api.attach_qt()
    for value in ('', ' \n ', 'x' * 129, None, 123):
        assert api.set_device_title(value)['ok'] is False
    assert window.changes == []
    assert api.set_device_title('  Saffire   PRO 40\n')['ok'] is True
    assert window.title == 'ffado-webmixer: Saffire PRO 40'
