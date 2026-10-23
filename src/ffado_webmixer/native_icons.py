"""Optional pywebview Qt icon bridge (does not require Qt in headless mode)."""
from __future__ import annotations

from pathlib import Path

from .theme_icons import icon_file
from .themes import theme_path


def sync_installed_launcher_icon(path):
    """Atomically update the opt-in KDE icon without requiring a Plasma restart."""
    from .desktop_integration import desktop_paths, is_installed, _atomic_write
    if not is_installed():
        return False
    try:
        _, dest = desktop_paths()
        content = Path(path).read_bytes()
        if dest.read_bytes() != content:
            _atomic_write(dest, content)
        return True
    except OSError:
        return False


class NativeThemeIconAPI:
    """Called by the trusted pywebview page's JS API on theme changes.

    JS API methods run outside the Qt UI thread. Queue QIcon updates through
    a QObject slot rather than calling any QWidget/QWindow methods directly.
    """

    def __init__(self, config=None):
        self._config = config
        self._receiver = None
        self._pending = None
        self._window = None
        self._pending_title = None

    def attach_window(self, window):
        """Keep a reference to the specific pywebview window this bridge owns."""
        self._window = window

    def set_device_title(self, device):
        """Queue a selected-device title update onto the Qt GUI thread."""
        if not isinstance(device, str):
            return {'ok': False, 'error': 'Device name must be a string'}
        name = ' '.join(device.split())
        if not name or len(name) > 128:
            return {'ok': False, 'error': 'Invalid device name'}
        title = f'ffado-webmixer: {name}'
        self._pending_title = title
        if self._receiver is not None:
            self._receiver.title_requested.emit(title)
        return {'ok': True}

    def attach_qt(self):
        if self._receiver is not None:
            return
        try:
            from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot
            from PyQt6.QtGui import QGuiApplication, QIcon
            app = QGuiApplication.instance()
            if app is None:
                return
        except (ImportError, RuntimeError, AttributeError):
            return

        class Receiver(QObject):
            icon_requested = pyqtSignal(str)
            title_requested = pyqtSignal(str)

            def __init__(self):
                super().__init__()
                self.icon_requested.connect(self.apply_icon, Qt.ConnectionType.QueuedConnection)
                self.title_requested.connect(self.apply_title, Qt.ConnectionType.QueuedConnection)

            @pyqtSlot(str)
            def apply_icon(self, filename):
                icon = QIcon(filename)
                app.setWindowIcon(icon)
                for window in app.allWindows():
                    if window.isTopLevel():
                        window.setIcon(icon)

            @pyqtSlot(str)
            def apply_title(self, title):
                # pywebview owns the native Qt surface; do not touch it from
                # pywebview's background JS-API worker threads.
                if native_window is not None:
                    native_window.title = title

        native_window = self._window
        receiver = Receiver()
        receiver.moveToThread(app.thread())
        self._receiver = receiver
        if self._pending is not None:
            receiver.icon_requested.emit(str(self._pending))
        if self._pending_title is not None:
            receiver.title_requested.emit(self._pending_title)

    def set_theme_icon(self, theme, accent=None):
        if not isinstance(theme, str) or theme_path(theme) is None:
            return {'ok': False, 'error': 'Unknown theme'}
        # Invalid accents are ignored by icon_file, exactly like the CSS.
        filename = icon_file(theme, accent)
        self._pending = filename
        # A normal browser never calls the native bridge; when a Qt window
        # exists, emit a thread-safe queued update to that window.
        if self._receiver is not None:
            self._receiver.icon_requested.emit(str(filename))
        # Keep the installed per-user KDE launcher icon in sync as well.
        sync_installed_launcher_icon(filename)
        return {'ok': True}

    def desktop_integration_status(self):
        """Only the native pywebview bridge can request the first-run prompt."""
        from .desktop_integration import is_installed
        if self._config is None or self._config.path is None:
            return {'prompt': False}
        with self._config._save_lock:
            prompted = self._config.settings.get('desktop_integration_prompted', False)
        return {'prompt': not prompted and not is_installed()}

    def _mark_desktop_prompted(self):
        if self._config is None:
            return
        with self._config._save_lock:
            self._config.settings['desktop_integration_prompted'] = True
            self._config.save()

    def desktop_integration_dismiss(self):
        self._mark_desktop_prompted()
        return {'ok': True}

    def desktop_integration_install(self):
        if self._config is None:
            return {'ok': False, 'error': 'Desktop integration is unavailable'}
        from .desktop_integration import install
        try:
            desktop, _ = install(self._config.settings)
            self._mark_desktop_prompted()
            return {'ok': True, 'desktop_file': str(desktop)}
        except (OSError, ValueError) as exc:
            return {'ok': False, 'error': str(exc)}
