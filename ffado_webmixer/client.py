import time
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

import webview
from .server import PORT
from .themes import USER_THEMES

ASSETS_DIR = Path(__file__).resolve().parent / "assets"

LOADING_PAGE = ASSETS_DIR / "static" / "loading.html"
ICON = ASSETS_DIR / "icon.svg"

MIN_LOADING_SECONDS = 5.0
def wait_until_ready():
    """Wait for Flask to respond before navigating to the mixer."""
    while True:
        try:
            with urlopen(f'http://127.0.0.1:{PORT}/api/settings', timeout=0.2) as response:
                if response.status == 200:
                    return
        except (OSError, TimeoutError):
            pass
        time.sleep(0.05)


def run_window(title, theme='dark', skip_loading_screen=False, config=None):
    # Qt on Plasma Wayland uses desktopFileName for task-manager grouping.
    # Use an identity distinct from FFADO's Qt mixer; the supplied desktop
    # launcher must be installed with the matching basename.
    os.environ['QT_WAYLAND_APP_ID'] = 'ffado-webmixer'
    mixer_url = f'http://127.0.0.1:{PORT}/'
    params = {'theme': theme}
    user_css = USER_THEMES / f'{theme}.css'
    if user_css.is_file():
        params['local_theme_url'] = user_css.resolve().as_uri()
    loading_url = LOADING_PAGE.as_uri() + '?' + urlencode(params)
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
        background_color='#17191d',
    )


    def set_desktop_identity():
        try:
            from PyQt6.QtGui import QGuiApplication
            app = QGuiApplication.instance()
            if app:
                app.setDesktopFileName('ffado-webmixer')
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
                config.settings['window_size'] = {
                    'width': window.width,
                    'height': window.height,
                }
                config.save()

        window.events.closing += save_window_size

    def open_mixer():
        started = time.monotonic()
        wait_until_ready()
        if not skip_loading_screen:
            time.sleep(max(0, MIN_LOADING_SECONDS - (time.monotonic() - started)))
        window.load_url(mixer_url)

    webview.start(open_mixer, icon=str(ICON))
