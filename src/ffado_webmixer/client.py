import time
import os
import sys
from html import escape
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

os.environ.setdefault('QT_API', 'pyqt6')
import webview
from .server import PORT
from .themes import USER_THEMES, theme_path
from .theme_icons import icon_file
from .native_icons import NativeThemeIconAPI, sync_installed_launcher_icon

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

LOADING_PAGE = ASSETS_DIR / "static" / "loading.html"
ICON = ASSETS_DIR / "icon.svg"

MIN_LOADING_SECONDS = 5.0


def theme_background(theme):
    """Use the real theme's page color for Qt's first frame, not fixed dark."""
    import re
    path = theme_path(theme)
    if path:
        match = re.search(r'--page-background:\s*(#[0-9a-fA-F]{6})\s*;',
                          path.read_text(encoding='utf-8', errors='replace'))
        if match:
            return match.group(1)
    return '#17191d'
def wait_until_ready(timeout=10.0, server_thread=None, *, port=PORT):
    """Verify the local server responds, or raise instead of waiting forever."""
    deadline = time.monotonic() + timeout
    while True:
        if server_thread is not None and not server_thread.is_alive():
            raise RuntimeError('ffado-webmixer web server exited before becoming ready')
        try:
            with urlopen(f'http://127.0.0.1:{port}/api/settings', timeout=0.2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError(f'ffado-webmixer web server was not ready within {timeout:g} seconds')
        time.sleep(min(0.05, remaining))


def run_window(title, theme='dark', skip_loading_screen=False, config=None, *, port=PORT):
    # Qt on Plasma Wayland uses desktopFileName for task-manager grouping.
    # Use an identity distinct from FFADO's Qt mixer; the supplied desktop
    # launcher must be installed with the matching basename.
    os.environ['QT_WAYLAND_APP_ID'] = 'ffado-webmixer'
    mixer_url = f'http://127.0.0.1:{port}/'
    params = {'theme': theme}
    accents = config.settings.get('accent_overrides', {}) if config else {}
    accent = accents.get(theme) if isinstance(accents, dict) else None
    if isinstance(accent, str):
        import re
        if re.fullmatch(r'#[0-9a-fA-F]{6}', accent):
            params['accent'] = accent
    user_css = USER_THEMES / f'{theme}.css'
    if user_css.is_file():
        params['local_theme_url'] = user_css.resolve().as_uri()
    theme_icon = icon_file(theme, accent)
    sync_installed_launcher_icon(theme_icon)
    params['icon_url'] = theme_icon.resolve().as_uri()
    loading_url = LOADING_PAGE.as_uri() + '?' + urlencode(params)
    icon_api = NativeThemeIconAPI(config=config)
    size = config.settings.get('window_size', {}) if config else {}
    width = size.get('width', 1180) if isinstance(size, dict) else 1180
    height = size.get('height', 800) if isinstance(size, dict) else 800
    width = width if isinstance(width, int) and width > 0 else 1180
    height = height if isinstance(height, int) and height > 0 else 800
    window = webview.create_window(
        title,
        html='' if skip_loading_screen else None,
        url=None if skip_loading_screen else loading_url,
        width=width,
        height=height,
        background_color=theme_background(theme),
        js_api=icon_api,
    )
    icon_api.attach_window(window)


    def set_desktop_identity():
        try:
            from PyQt6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app:
                app.setDesktopFileName('ffado-webmixer')
                icon_api.attach_qt()
        except (ImportError, RuntimeError, AttributeError):
            # Browser/webview backend without Qt: taskbar grouping is handled
            # by the desktop environment instead.
            pass

    # Set the desktopFileName as early as the Qt backend allows: waiting until
    # shown is often too late for Plasma to match the initial Wayland surface.
    before_show = getattr(window.events, 'before_show', None)
    if before_show is not None:
        before_show += set_desktop_identity
    window.events.shown += set_desktop_identity  # fallback for older pywebview

    if config is not None:
        def save_window_size():
            if window.width > 0 and window.height > 0:
                with config._save_lock:
                    config.settings['window_size'] = {
                        'width': window.width,
                        'height': window.height,
                    }
                    config.save()

        window.events.closing += save_window_size

    def open_mixer():
        started = time.monotonic()
        try:
            wait_until_ready(port=port)
        except RuntimeError as exc:
            # If the listener dies after the initial readiness check, the Qt
            # window must report the failure instead of showing a stuck splash.
            print(str(exc), file=sys.stderr)
            window.load_html('<h2>ffado-webmixer server unavailable</h2><p>'
                             + escape(str(exc)) + '</p>')
            return
        if not skip_loading_screen:
            time.sleep(max(0, MIN_LOADING_SECONDS - (time.monotonic() - started)))
        window.load_url(mixer_url)

    webview.start(open_mixer, icon=str(theme_icon))
