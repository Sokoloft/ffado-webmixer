"""Offline three-unit regression suite. No Flask, DBus, Qt, or hardware required."""
import contextlib
import importlib
import io
import json
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.services.events import Hub


@contextlib.contextmanager
def isolated_modules(names):
    """Restore both import caches after loading modules against a Flask stub."""
    missing = object()
    modules = {name: sys.modules.get(name, missing) for name in names}
    attributes = []
    for name in names:
        parent_name, attribute = name.rsplit('.', 1)
        parent = importlib.import_module(parent_name)
        attributes.append((parent, attribute, getattr(parent, attribute, missing)))
        sys.modules.pop(name, None)
        # ``from .api import mixer`` consults this package attribute before
        # sys.modules, so clearing just sys.modules can reuse real Flask routes.
        if hasattr(parent, attribute):
            delattr(parent, attribute)
    try:
        yield
    finally:
        for name, previous in modules.items():
            sys.modules.pop(name, None)
            if previous is not missing:
                sys.modules[name] = previous
        for parent, attribute, previous in attributes:
            if previous is missing:
                if hasattr(parent, attribute):
                    delattr(parent, attribute)
            else:
                setattr(parent, attribute, previous)


def units(count=3):
    mixers = []
    for n in range(count):
        with contextlib.redirect_stdout(io.StringIO()):
            unit = make_debug_mixer('profire2626', Config())
        # Same exact FFADO model; three different physical 64-bit GUIDs.
        unit.guid = f'00130e00000000{n + 1:02x}'
        unit.device['guid'] = unit.guid
        mixers.append(unit)
    return mixers


@pytest.fixture
def manager_factory(monkeypatch, tmp_path):
    # Flask session proxy emulated with a plain dict, so the real DeviceManager
    # can run without Flask, D-Bus or audio interfaces being installed.
    flask_stub = types.ModuleType('flask')
    flask_stub.session = {}
    flask_stub.has_request_context = lambda: True
    monkeypatch.setitem(sys.modules, 'flask', flask_stub)
    with isolated_modules(('ffado_webmixer.device_manager',)):
        dm = importlib.import_module('ffado_webmixer.device_manager')
        root = Config(tmp_path / 'config.json')
        root.load()
        yield dm.DeviceManager, flask_stub.session, root


def test_three_identical_units_have_isolated_writable_hardware_and_settings(manager_factory):
    Manager, session, root = manager_factory
    a, b, c = units()
    manager = Manager([a, b, c], root, debug=True)
    assert manager.order == [a.guid, b.guid, c.guid]
    assert len({id(m.helper) for m in manager.devices.values()}) == 3
    assert len({m.config.path for m in manager.devices.values()}) == 3

    for i, unit in enumerate((a, b, c)):
        session['ffado_device'] = unit.guid
        manager.config.settings['device_alias'] = f'ProFire {i + 1}'
        manager.config.names['ch/00'] = f'Mic {i + 1}'
        manager.config.stereo[:] = [[f'ch/0{i}', f'ch/0{i + 1}']]
        manager.config.layouts[str(i)] = [{'id': 'ch/00', 'pinned': i != 0, 'minimized': i == 0}]
        manager.config.settings['accent_overrides'][f'{i}'] = f'#{i:06x}'
        manager.config.save()
        with contextlib.redirect_stdout(io.StringIO()):
            manager.backend.write(0, 'ch/00', 'fader', 40 + i * 10)
    assert len({u.helper.get_cell(u.roles['fader'][0], 0, 0) for u in (a,b,c)}) == 3
    assert manager.configs[a.guid].names['ch/00'] == 'Mic 1'
    assert manager.configs[b.guid].names['ch/00'] == 'Mic 2'
    assert manager.configs[c.guid].names['ch/00'] == 'Mic 3'
    assert manager.configs[a.guid].settings['accent_overrides'] == {'0': '#000000'}
    assert manager.configs[b.guid].settings['accent_overrides'] == {'1': '#000001'}
    assert manager.configs[c.guid].settings['accent_overrides'] == {'2': '#000002'}
    assert [d['name'] for d in manager.list_devices()] == ['ProFire 1', 'ProFire 2', 'ProFire 3']
    # Rearranging FFADO discovery order must not remap saved GUID-specific data.
    again = Manager([c,b,a], root, debug=True)
    assert [again.configs[u.guid].names['ch/00'] for u in (a,b,c)] == ['Mic 1','Mic 2','Mic 3']


def test_identical_label_is_disambiguated_by_guid(manager_factory):
    Manager, _, root = manager_factory
    manager = Manager(units(), root, debug=True)
    devices = manager.list_devices()
    assert len({d['name'] for d in devices}) == 3
    assert all(d['name'].endswith(d['guid'][-6:]) for d in devices)
    assert all(d['alias'] == '' for d in devices)
    # Never bake the display suffix into the saved alias or profile resolution.
    assert len({d['profile'] for d in devices}) == 1


def test_duplicate_or_invalid_guid_is_rejected_not_silently_overwritten(manager_factory):
    Manager, _, root = manager_factory
    a, b, c = units()
    b.guid = a.guid
    with pytest.raises(ValueError, match='Duplicate FireWire GUID'):
        Manager([a,b,c],root,debug=True)
    b.guid = 'not-a-guid'
    with pytest.raises(ValueError, match='Invalid FireWire GUID'):
        Manager([a,b,c],root,debug=True)


def test_device_event_stream_is_scoped_to_selected_hardware():
    hub = Hub()
    a = hub.subscribe('00130e0000000001')
    b = hub.subscribe('00130e0000000002')
    all_events = hub.subscribe()
    hub.publish({'device': '00130e0000000001', 'type': 'strip'}, 'tab-a')
    assert a.get_nowait()['type'] == 'strip'
    assert b.empty()
    assert all_events.get_nowait()['device'] == '00130e0000000001'
    hub.unsubscribe(a)
    hub.publish({'device': '00130e0000000002', 'type': 'layout'}, 'tab-b')
    assert b.get_nowait()['type'] == 'layout'
    assert all_events.get_nowait()['device'] == '00130e0000000002'
    assert a.empty()


def test_defaults_are_not_shared_between_devices():
    a, b = Config(), Config()
    a.settings['window_size']['width'] = 10
    a.settings['accent_overrides']['dark'] = '#aabbcc'
    assert b.settings['window_size']['width'] == 1180
    assert b.settings['accent_overrides'] == {}


def test_pypi_desktop_entry_and_installer_match_qt_identity(monkeypatch, tmp_path):
    from ffado_webmixer import desktop_integration as module
    root = Path(__file__).resolve().parents[1]
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'share'))
    desktop, icon = module.desktop_paths()
    assert not module.is_installed()
    created, result_icon = module.install({'theme': 'nordic'}, argv0=str(root/'main.py'))
    assert (created, result_icon) == (desktop, icon)
    text = desktop.read_text()
    assert 'StartupWMClass=ffado-webmixer' in text
    assert 'Icon=ffado-webmixer' in text
    assert str(root/'main.py') in text
    assert sys.executable in text
    assert icon.read_bytes().startswith(b'<svg')
    assert module.is_installed()
    assert module.remove() is True
    assert not desktop.exists() and not icon.exists()
    assert not module.is_installed()
    assert "setDesktopFileName('ffado-webmixer')" in (root/'src/ffado_webmixer/client.py').read_text()


def test_browser_device_guards_are_used_for_reads_and_writes():
    root = Path(__file__).resolve().parents[1]/'src/ffado_webmixer/assets/static'
    index = (root/'index.js').read_text()
    routing = (root/'routing.js').read_text()
    peaks = (root/'peak-metering.js').read_text()
    assert 'function deviceFetch(url)' in index
    assert '"X-FFADO-Device": ACTIVE_DEVICE' in index
    assert "window.ffadoApi.latest('mixer-state', '/api/state?mix=' + mix, {device})" in index
    assert "headers['X-FFADO-Device'] = options.device" in (root/'frontend-api.js').read_text()
    assert "device: window.activeFfadoDevice" in routing
    assert "'X-FFADO-Device': this.guid" in peaks


def test_three_device_routes_and_stale_client_isolation(monkeypatch, tmp_path):
    """Exercise real route handlers with a minimal Flask surface (no Flask wheel)."""
    flask_stub = types.ModuleType('flask')
    session = {}
    flask_stub.session = session
    flask_stub.has_request_context = lambda: True
    request = types.SimpleNamespace(method='GET', path='', headers={}, args={},
                                    remote_addr='127.0.0.1', host_url='http://localhost/',
                                    is_json=True,
                                    get_json=lambda force=False, silent=False: {})
    flask_stub.request = request
    flask_stub.jsonify = lambda *a, **kw: a[0] if a else kw
    flask_stub.send_from_directory = lambda *a, **kw: ''
    flask_stub.send_file = lambda *a, **kw: ''
    flask_stub.Response = lambda *a, **kw: a

    class FakeFlask:
        def __init__(self, *a, **kw):
            self.routes = {}
            self.before = []
            self.after = []
            self.root_path = str(tmp_path)
        def decorator(self, method, route):
            def dec(handler):
                self.routes[method, route] = handler
                return handler
            return dec
        def get(self, route): return self.decorator('GET', route)
        def post(self, route): return self.decorator('POST', route)
        def before_request(self, handler):
            self.before.append(handler); return handler
        def after_request(self, handler):
            self.after.append(handler); return handler

    flask_stub.Flask = FakeFlask
    monkeypatch.setitem(sys.modules, 'flask', flask_stub)
    prefixes = ('ffado_webmixer.device_manager', 'ffado_webmixer.server',
                'ffado_webmixer.api.mixer', 'ffado_webmixer.api.settings',
                'ffado_webmixer.api.integrations', 'ffado_webmixer.api.events',
                'ffado_webmixer.api.stereo', 'ffado_webmixer.services.stereo')
    with isolated_modules(prefixes):
        from ffado_webmixer.device_manager import DeviceManager, SelectedBackend, SelectedConfig
        from ffado_webmixer.server import create_app
        a,b,c = units()
        config = Config(tmp_path/'config.json')
        config.load()
        manager = DeviceManager([a,b,c], config, debug=True)
        app = create_app(SelectedBackend(manager), a.describe(), SelectedConfig(manager),
                         device_manager=manager, about={'version':'1.1.1'})

        def call(method, path, *, header=None, body=None):
            request.method, request.path = method, path
            request.headers = {'X-FFADO-Device':header} if header else {}
            request.get_json = lambda force=False, silent=False: body or {}
            for handler in app.before:
                result = handler()
                if result is not None:
                    return result
            return app.routes[method,path]()

        initial = call('GET','/api/devices')
        assert [x['guid'] for x in initial['devices']] == [a.guid,b.guid,c.guid]
        assert initial['selected'] == a.guid
        # Malformed JSON objects may not select a different device or alias.
        assert call('POST', '/api/device', body={'guid': 10})[1] == 400
        assert call('POST', '/api/device-alias', body={'name': [123]})[1] == 400
        assert manager.configs[a.guid].settings.get('device_alias') is None
        result = call('POST','/api/device',header=a.guid,body={'guid':b.guid})
        assert result == {'ok':True,'selected':b.guid}
        # A failed persistent update must not silently switch this browser,
        # including if the disk was replaced before the failure was reported.
        original_global_save = config.save
        attempts = [0]
        def fail_global_once():
            original_global_save()
            attempts[0] += 1
            if attempts[0] == 1:
                raise OSError('simulated selection save interruption')
        monkeypatch.setattr(config, 'save', fail_global_once)
        fail_response, fail_status = call('POST', '/api/device', body={'guid': c.guid})
        assert fail_status == 500
        assert 'simulated selection save interruption' in fail_response['error']
        assert attempts[0] == 2
        assert session['ffado_device'] == b.guid
        assert config.settings['last_device_guid'] == b.guid
        persisted_selection = Config(config.path)
        persisted_selection.load()
        assert persisted_selection.settings['last_device_guid'] == b.guid
        monkeypatch.setattr(config, 'save', original_global_save)
        blocked = call('POST','/api/set',header=a.guid,
                       body={'strip':'ch/00','control':'fader','value':15,'mix':0})
        assert blocked[1] == 409
        blocked_read = call('GET','/api/describe',header=a.guid)
        assert blocked_read[1] == 409
        assert call('GET','/api/describe',header=b.guid)['guid'] == b.guid
        with contextlib.redirect_stdout(io.StringIO()):
            assert call('POST','/api/set',header=b.guid,
                        body={'strip':'ch/00','control':'fader','value':33,'mix':0}) == {'ok':True}
        assert b.helper.cells
        assert not a.helper.cells
        assert not c.helper.cells
        # Alias changes must apply only to the selected unit.
        assert call('POST','/api/device-alias',header=b.guid,body={'name':'Rack B'}) == {'ok':True}
        assert manager.configs[b.guid].settings['device_alias'] == 'Rack B'
        assert manager.configs[a.guid].settings.get('device_alias') != 'Rack B'
        original_save = manager.configs[b.guid].save
        save_count = [0]
        def fail_alias_save_once():
            original_save()
            save_count[0] += 1
            if save_count[0] == 1:
                raise OSError('simulated interrupted alias save')
        monkeypatch.setattr(manager.configs[b.guid], 'save', fail_alias_save_once)
        error, status = call('POST', '/api/device-alias', header=b.guid,
                             body={'name': 'Wrong alias'})
        assert status == 500 and 'simulated interrupted' in error['error']
        assert manager.configs[b.guid].settings['device_alias'] == 'Rack B'
        saved_alias = Config(manager.configs[b.guid].path)
        saved_alias.load()
        assert saved_alias.settings['device_alias'] == 'Rack B'
        # A new browser session defaults to the last selected device (B),
        # while a still-active browser session may have its own choice.
        session.clear()
        assert call('GET','/api/devices')['selected'] == b.guid
        assert call('GET','/api/describe',header=b.guid)['guid'] == b.guid
        assert config.settings['last_device_guid'] == b.guid
        saved = Config(config.path)
        saved.load()
        assert saved.settings['last_device_guid'] == b.guid


def test_demo_mode_keeps_valid_synthetic_guid(manager_factory):
    Manager, _, root = manager_factory
    from ffado_webmixer import main
    args = types.SimpleNamespace(debug=None, demo=True)
    demo = main.create_backends(args, root)[0]
    assert len(demo.guid) == 16
    import re
    assert re.fullmatch('[0-9a-f]{16}', demo.guid)
    manager = Manager([demo], root, debug=True)
    assert manager.current_guid == demo.guid


def test_last_selected_mixer_survives_restart_and_discovery_reordering(manager_factory):
    Manager, session, root = manager_factory
    a, b, c = units()
    manager = Manager([a, b, c], root, debug=True)
    assert manager.current_guid == a.guid
    manager.remember_device(b.guid)
    assert root.settings['last_device_guid'] == b.guid
    assert Config(root.path).path.is_file()

    # A running browser session can select a different unit independently.
    session['ffado_device'] = c.guid
    assert manager.current_guid == c.guid
    session.clear()
    assert manager.current_guid == b.guid

    # Emulate closing and reopening the app with a different discovery order.
    saved = Config(root.path)
    saved.load()
    reopened = Manager([c, a, b], saved, debug=True)
    assert reopened.current_guid == b.guid
    assert reopened.backend.guid == b.guid
    assert reopened.backend.describe()['device'] == b.describe()['device']
    # Startup title is sourced from backend.describe() outside request context.
    import sys
    old = sys.modules['flask'].has_request_context
    try:
        sys.modules['flask'].has_request_context = lambda: False
        assert reopened.current_guid == b.guid
    finally:
        sys.modules['flask'].has_request_context = old


def test_missing_preferred_mixer_falls_back_without_forgetting_it(manager_factory):
    Manager, session, root = manager_factory
    a, b, c = units()
    Manager([a, b, c], root, debug=True).remember_device(b.guid)
    session.clear()
    reopened_config = Config(root.path)
    reopened_config.load()
    missing = Manager([c, a], reopened_config, debug=True)
    assert missing.current_guid == c.guid
    assert reopened_config.settings['last_device_guid'] == b.guid
    with_b_again = Manager([a, b, c], reopened_config, debug=True)
    assert with_b_again.current_guid == b.guid
    # An invalid or obsolete saved value must not prevent startup.
    reopened_config.settings['last_device_guid'] = 'not-a-physical-guid'
    assert with_b_again.current_guid == a.guid
    session['ffado_device'] = 'stale-browser-guid'
    assert with_b_again.current_guid == a.guid
    session['ffado_device'] = ['malformed-session-value']
    assert with_b_again.current_guid == a.guid


def test_failed_selected_mixer_save_rolls_back_memory_and_disk(manager_factory, monkeypatch):
    Manager, session, root = manager_factory
    a, b, c = units()
    manager = Manager([a, b, c], root, debug=True)
    manager.remember_device(a.guid)
    original_save = root.save
    writes = [0]

    def fail_after_write_once():
        original_save()  # Replaces the JSON file, then reports an error.
        writes[0] += 1
        if writes[0] == 1:
            raise OSError('simulated config I/O failure')

    monkeypatch.setattr(root, 'save', fail_after_write_once)
    with pytest.raises(OSError, match='simulated config I/O failure'):
        manager.remember_device(b.guid)
    assert writes[0] == 2
    assert manager.current_guid == a.guid
    assert root.settings['last_device_guid'] == a.guid
    persisted = Config(root.path)
    persisted.load()
    assert persisted.settings['last_device_guid'] == a.guid
    # Invalid direct requests cannot overwrite the working preference.
    with pytest.raises(ValueError, match='Unknown FFADO device'):
        manager.remember_device('0000000000000000')


def test_last_selected_mixer_is_in_memory_only_for_demo_mode(manager_factory):
    Manager, session, _ = manager_factory
    a, b, c = units()
    root = Config(None)
    manager = Manager([a, b, c], root, debug=True)
    manager.remember_device(c.guid)
    assert root.settings['last_device_guid'] == c.guid
    session.clear()
    assert manager.current_guid == c.guid
    fresh = Manager([a, b, c], Config(None), debug=True)
    assert fresh.current_guid == a.guid
