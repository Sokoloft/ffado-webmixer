"""Real HTTP requests must keep their validated device during concurrent selection."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from flask import request

from ffado_webmixer.config import Config
from ffado_webmixer.demo import DemoMixer
from ffado_webmixer.device_manager import DeviceManager, SelectedBackend, SelectedConfig
from ffado_webmixer import server
from ffado_webmixer.services.events import Hub
from ffado_webmixer.theme_icons import themed_icon_svg


class Device(DemoMixer):
    def __init__(self, guid):
        super().__init__()
        self.guid = guid
        self.profile = {}
        self.nickname_path = None

    def describe(self):
        return dict(super().describe(), guid=self.guid)


@pytest.fixture
def devices(tmp_path, monkeypatch):
    first, second = Device('0000000000000001'), Device('0000000000000002')
    root = Config(tmp_path / 'config.json')
    root.load()
    manager = DeviceManager([first, second], root)
    backend = SelectedBackend(manager)
    hub = Hub()
    monkeypatch.setattr(server, 'Hub', lambda: hub)
    app = server.create_app(backend, backend.describe(), SelectedConfig(manager),
                            device_manager=manager)
    app.config['TESTING'] = True
    return app, manager, first, second, hub


@pytest.mark.parametrize('operation', ['fader', 'settings'])
@pytest.mark.parametrize('send_device_header', [True, False])
def test_concurrent_default_change_keeps_hardware_settings_and_events_on_validated_device(
        devices, operation, send_device_header):
    app, manager, first, second, hub = devices
    validated, resume = Event(), Event()
    first_events, second_events = hub.subscribe(first.guid), hub.subscribe(second.guid)
    path, body = ('/api/set', {'strip': 'ch/01', 'control': 'fader', 'value': 12, 'mix': 0}) \
        if operation == 'fader' else ('/api/settings', {'hide_minimized': True})

    # This hook runs after the application's stale-device guard, just before
    # dispatch. A second browser changes the default while this request waits.
    @app.before_request
    def pause_after_validation():
        if request.path == path:
            validated.set()
            if not resume.wait(timeout=5):
                raise RuntimeError('Timed out waiting for concurrent device selection')

    first_browser, second_browser = app.test_client(), app.test_client()
    headers = {'X-FFADO-Device': first.guid} if send_device_header else {}
    with ThreadPoolExecutor(max_workers=1) as executor:
        write = executor.submit(first_browser.post, path, json=body, headers=headers)
        try:
            assert validated.wait(timeout=5), 'First request did not reach device validation'
            response = second_browser.post('/api/device', json={'guid': second.guid})
            assert response.status_code == 200
            assert response.json['selected'] == second.guid
        finally:
            resume.set()
        response = write.result(timeout=5)

    assert response.status_code == 200
    assert manager.preferred_guid == second.guid
    if operation == 'fader':
        assert first.mixes[0]['ch/01']['fader'] == 12
        assert second.mixes[0]['ch/01']['fader'] == 75
        assert first_events.get_nowait()['device'] == first.guid
        assert second_events.empty()
    else:
        for device, expected in ((first, True), (second, False)):
            config = manager.configs[device.guid]
            assert config.settings['hide_minimized'] is expected
            persisted = Config(config.path)
            persisted.load()
            assert persisted.settings['hide_minimized'] is expected


def test_selection_expires_with_request_and_stale_headers_still_fail(devices):
    app, manager, first, second, _ = devices
    browser, other_browser = app.test_client(), app.test_client()
    # Even callers reusing an application context must get a fresh selection
    # for each HTTP request; an application-global cache would retain A here.
    with app.app_context():
        assert browser.get('/api/devices').json['selected'] == first.guid
        assert other_browser.post('/api/device', json={'guid': second.guid}).status_code == 200
        assert browser.get('/api/devices').json['selected'] == second.guid
        response = browser.post('/api/set', headers={'X-FFADO-Device': first.guid},
                                json={'strip': 'ch/01', 'control': 'fader', 'value': 12})
        assert response.status_code == 409
        assert browser.get('/api/describe', headers={
            'X-FFADO-Device': second.guid}).json['guid'] == second.guid
    assert first.mixes[0]['ch/01']['fader'] == second.mixes[0]['ch/01']['fader'] == 75
    assert manager.current_guid == second.guid  # startup/background fallback still works


def test_explicit_browser_selection_remains_independent_of_new_default(devices):
    app, _, first, second, _ = devices
    browser, other_browser = app.test_client(), app.test_client()
    assert browser.post('/api/device', json={'guid': first.guid}).status_code == 200
    assert other_browser.post('/api/device', json={'guid': second.guid}).json['selected'] == second.guid
    assert browser.get('/api/devices').json['selected'] == first.guid
    response = browser.post('/api/set', headers={'X-FFADO-Device': first.guid},
                            json={'strip': 'ch/01', 'control': 'fader', 'value': 12})
    assert response.status_code == 200
    assert first.mixes[0]['ch/01']['fader'] == 12
    assert second.mixes[0]['ch/01']['fader'] == 75


@pytest.mark.parametrize('theme,accents', [('light', {'light': '#123456'}), ('dark', {})])
def test_global_appearance_wins_over_stale_device_settings(devices, theme, accents):
    app, manager, first, second, _ = devices
    root = manager.global_config
    root.settings.update(theme=theme, accent_overrides=accents, skip_loading_screen=True)
    root.save()
    browsers = [app.test_client(), app.test_client()]
    for index, (browser, device) in enumerate(zip(browsers, (first, second))):
        config = manager.configs[device.guid]
        config.settings.update(theme='gruvbox', accent_overrides={'gruvbox': '#abcdef'},
                               skip_loading_screen=False, mix=index, hide_minimized=bool(index))
        config.save()
        assert browser.post('/api/device', json={'guid': device.guid}).status_code == 200
    original = {config.path: config.path.read_bytes() for config in manager.configs.values()}
    original[root.path] = root.path.read_bytes()
    for index, browser in enumerate(browsers):
        response = browser.get('/api/settings')
        assert response.status_code == 200
        assert response.json['theme'] == theme
        assert response.json['accent_overrides'] == accents
        assert response.json['skip_loading_screen'] is True
        assert response.json['mix'] == index
        assert response.json['hide_minimized'] is bool(index)
        assert browser.get('/favicon.svg').text == themed_icon_svg(theme, accents.get(theme))
    assert all(path.read_bytes() == data for path, data in original.items())
    assert all(config.settings['theme'] == 'gruvbox' for config in manager.configs.values())


def test_appearance_saved_from_either_device_is_visible_on_both(devices):
    app, manager, first, second, _ = devices
    browsers = [app.test_client(), app.test_client()]
    for browser, device in zip(browsers, (first, second)):
        assert browser.post('/api/device', json={'guid': device.guid}).status_code == 200
    for browser, theme, accents in ((browsers[0], 'light', {'light': '#aabbcc'}),
                                    (browsers[1], 'nordic', {})):
        response = browser.post('/api/settings', json={'theme': theme, 'accent_overrides': accents})
        assert response.status_code == 200
        saved = Config(manager.global_config.path)
        saved.load()
        assert saved.settings['theme'] == theme
        assert saved.settings['accent_overrides'] == accents
        for viewer in browsers:
            settings = viewer.get('/api/settings').json
            assert settings['theme'] == theme
            assert settings['accent_overrides'] == accents
            assert viewer.get('/favicon.svg').text == themed_icon_svg(theme, accents.get(theme))


@pytest.mark.parametrize('query,theme,accent', [
    ({}, 'light', '#123456'),
    ({'theme': 'dark'}, 'dark', None),
    ({'theme': 'dark', 'accent': '#abcdef'}, 'dark', '#abcdef'),
    ({'accent': '#fedcba'}, 'light', '#fedcba'),
    ({'accent': 'invalid'}, 'light', '#123456'),
])
def test_favicon_previews_preserve_explicit_theme_and_accent(devices, query, theme, accent):
    app, manager, first, second, _ = devices
    manager.global_config.settings.update(theme='light', accent_overrides={
        'light': '#123456', 'dark': '#654321'})
    for device in (first, second):
        manager.configs[device.guid].settings.update(theme='gruvbox', accent_overrides={
            'gruvbox': '#999999'})
        browser = app.test_client()
        assert browser.post('/api/device', json={'guid': device.guid}).status_code == 200
        response = browser.get('/favicon.svg', query_string=query)
        assert response.status_code == 200
        assert response.text == themed_icon_svg(theme, accent)


def test_appearance_without_device_manager_uses_the_supplied_config():
    config = Config(None)
    config.settings.update(theme='nordic', accent_overrides={'nordic': '#123456'})
    backend = Device('0000000000000001')
    app = server.create_app(backend, backend.describe(), config)
    browser = app.test_client()
    settings = browser.get('/api/settings').json
    assert settings['theme'] == 'nordic'
    assert settings['accent_overrides'] == {'nordic': '#123456'}
    assert browser.get('/favicon.svg').text == themed_icon_svg('nordic', '#123456')
