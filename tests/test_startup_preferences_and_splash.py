"""Regression tests for the Qt splash's persisted preferences and theme."""
import importlib
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse


from ffado_webmixer.config import Config


class FakeApp:
    def __init__(self):
        self.routes = {}

    def get(self, path):
        def decorator(fn):
            self.routes[('GET', path)] = fn
            return fn
        return decorator

    def post(self, path):
        def decorator(fn):
            self.routes[('POST', path)] = fn
            return fn
        return decorator


def test_setting_is_saved_globally_and_visible_on_another_device(tmp_path, monkeypatch):
    """Previously /api/settings saved to a GUID file, main.py read config.json."""
    root = Config(tmp_path / 'config.json')
    root.load()
    first = Config(tmp_path / 'devices' / 'one.json')
    first.load()
    second = Config(tmp_path / 'devices' / 'two.json')
    second.load()
    payload = {}
    request = types.SimpleNamespace(get_json=lambda force=True: payload)
    flask_stub = types.ModuleType('flask')
    flask_stub.request = request
    flask_stub.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    monkeypatch.setitem(sys.modules, 'flask', flask_stub)
    sys.modules.pop('ffado_webmixer.api.settings', None)
    api = importlib.import_module('ffado_webmixer.api.settings')
    app = FakeApp()
    try:
        api.register(app, first, lambda event: None, startup_config=root)
        assert app.routes[('GET', '/api/settings')]()['skip_loading_screen'] is False
        payload.update({'skip_loading_screen': True, 'theme': 'light',
                        'accent_overrides': {'light': '#123456'}})
        assert app.routes[('POST', '/api/settings')]() == {'ok': True}

        # Desktop startup reads the global config, not the GUID-specific file.
        reloaded = Config(root.path)
        reloaded.load()
        assert reloaded.settings['skip_loading_screen'] is True
        assert reloaded.settings['theme'] == 'light'
        assert reloaded.settings['accent_overrides'] == {'light': '#123456'}
        assert reloaded.settings['_startup_preferences_migrated'] is True
        saved_first = Config(first.path)
        saved_first.load()
        assert saved_first.settings["skip_loading_screen"] is True

        # Switching to a different device still shows the window-wide setting.
        another_app = FakeApp()
        api.register(another_app, second, lambda event: None, startup_config=root)
        assert another_app.routes[('GET', '/api/settings')]()['skip_loading_screen'] is True
        payload.clear()
        payload['skip_loading_screen'] = False
        assert another_app.routes[('POST', '/api/settings')]() == {'ok': True}
        root_reload = Config(root.path)
        root_reload.load()
        assert root_reload.settings['skip_loading_screen'] is False
        # Previous device's stale preference cannot override the global state.
        assert app.routes[('GET', '/api/settings')]()['skip_loading_screen'] is False

        payload['skip_loading_screen'] = 'false'  # string is not a boolean
        response, status = another_app.routes[('POST', '/api/settings')]()
        assert status == 400
        assert 'boolean' in response['error']
        assert root.settings['skip_loading_screen'] is False
    finally:
        sys.modules.pop('ffado_webmixer.api.settings', None)


def test_legacy_per_device_intro_preference_is_imported_once(tmp_path, monkeypatch):
    root = Config(tmp_path / 'config.json')
    root.load()
    guid = '00130e0000000001'
    legacy = Config(tmp_path / 'devices' / (guid + '.json'))
    legacy.load()
    legacy.settings['skip_loading_screen'] = True
    legacy.settings['theme'] = 'nordic'
    legacy.settings['accent_overrides'] = {'nordic': '#abcdef'}
    legacy.save()

    flask_stub = types.ModuleType('flask')
    flask_stub.session = {}
    flask_stub.has_request_context = lambda: False
    monkeypatch.setitem(sys.modules, 'flask', flask_stub)
    sys.modules.pop('ffado_webmixer.device_manager', None)
    dm = importlib.import_module('ffado_webmixer.device_manager')

    class Hardware:
        def __init__(self):
            self.guid = guid
            self.nickname_path = None
        def describe(self):
            return {'device': 'Saffire PRO 40'}
    try:
        dm.DeviceManager([Hardware()], root, debug=True)
        assert root.settings['skip_loading_screen'] is True
        assert root.settings['theme'] == 'nordic'
        assert root.settings['accent_overrides'] == {'nordic': '#abcdef'}
        # Turning the option back off must remain off after future restarts.
        root.settings['skip_loading_screen'] = False
        root.save()
        restored = Config(root.path)
        restored.load()
        dm.DeviceManager([Hardware()], restored, debug=True)
        assert restored.settings['skip_loading_screen'] is False
    finally:
        sys.modules.pop('ffado_webmixer.device_manager', None)


def test_desktop_splash_uses_saved_theme_accent_and_background(tmp_path, monkeypatch):
    # Fake webview: inspect create_window arguments without a real Qt display.
    created = []
    started = []
    class Event:
        def __init__(self): self.handlers = []
        def __iadd__(self, handler):
            self.handlers.append(handler)
            return self
    events = types.SimpleNamespace(before_show=Event(), shown=Event(), closing=Event())
    window = types.SimpleNamespace(events=events, width=1180, height=800)
    webview_stub = types.ModuleType('webview')
    webview_stub.create_window = lambda *args, **kwargs: created.append(kwargs) or window
    webview_stub.start = lambda *args, **kwargs: started.append(kwargs)
    monkeypatch.setitem(sys.modules, 'webview', webview_stub)
    server_stub = types.ModuleType('ffado_webmixer.server')
    server_stub.PORT = 5000
    monkeypatch.setitem(sys.modules, 'ffado_webmixer.server', server_stub)
    sys.modules.pop('ffado_webmixer.client', None)
    client = importlib.import_module('ffado_webmixer.client')
    try:
        root = Config(tmp_path / 'config.json')
        root.load()
        root.settings['accent_overrides'] = {'light': '#124578'}
        client.run_window('Mixer', theme='light', config=root)
        window_args = created[-1]
        url = urlparse(window_args['url'])
        query = parse_qs(url.query)
        assert query['theme'] == ['light']
        assert query['accent'] == ['#124578']
        assert window_args['background_color'].lower() == '#eef1f5'
        from ffado_webmixer.theme_icons import themed_icon_svg
        assert 'icon_url' in query
        from urllib.parse import unquote
        assert Path(unquote(urlparse(query['icon_url'][0]).path)).read_text() == themed_icon_svg('light', '#124578')
        assert started[-1]['icon'] == str(Path(unquote(urlparse(query['icon_url'][0]).path)))
        assert window_args['js_api'].__class__.__name__ == 'NativeThemeIconAPI'
        assert window_args['js_api']._window is window
        client.run_window('Mixer', theme='light', config=root, skip_loading_screen=True)
        assert created[-1]['url'] is None
        assert created[-1]['html'] == ''
    finally:
        sys.modules.pop('ffado_webmixer.client', None)


def test_splash_theme_css_and_asset_variables_exist():
    static = Path(__file__).resolve().parents[1] / 'src/ffado_webmixer/assets/static'
    html = (static / 'loading.html').read_text()
    themes = (static / 'themes.js').read_text()
    assert 'data-base="../themes/"' in html
    assert 'var(--accent-color)' in html
    assert 'var(--pin-color)' in html
    assert 'var(--text-primary)' in html
    assert 'location.protocol === "file:"' in themes
    assert 'setMixerAccent(accent)' in themes
