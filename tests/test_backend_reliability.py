"""Offline backend reliability tests; no Flask/Qt/FireWire runtime needed."""
import ast
import importlib
import sys
import types
from pathlib import Path

import pytest

from ffado_webmixer.config import Config


class Routes:
    def __init__(self):
        self.routes = {}

    def get(self, path):
        def add(func):
            self.routes['GET', path] = func
            return func
        return add

    def post(self, path):
        def add(func):
            self.routes['POST', path] = func
            return func
        return add


@pytest.fixture
def api(monkeypatch, tmp_path):
    root = Config(tmp_path / 'global.json')
    root.load()
    device = Config(tmp_path / 'device.json')
    device.load()
    body = {'payload': {}, 'mix': '0'}
    request = types.SimpleNamespace(
        get_json=lambda force=True: body['payload'],
        args=types.SimpleNamespace(get=lambda key, default=None: body['mix'] if key == 'mix' else default),
    )
    stub = types.ModuleType('flask')
    stub.request = request
    stub.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    monkeypatch.setitem(sys.modules, 'flask', stub)
    sys.modules.pop('ffado_webmixer.api.settings', None)
    module = importlib.import_module('ffado_webmixer.api.settings')
    routes = Routes()
    events = []
    module.register(routes, device, events.append, startup_config=root)
    yield root, device, body, routes.routes, events
    sys.modules.pop('ffado_webmixer.api.settings', None)


def test_invalid_settings_do_not_partially_commit_to_either_file(api):
    global_config, device, body, routes, _ = api
    global_before = global_config.path.read_bytes()
    device_before = device.path.read_bytes()
    original = dict(device.settings)
    for bad in (
        {'hide_minimized': True, 'enable_qjackctl': 'no'},
        {'theme': 'light', 'mix': 'not an integer'},
        {'skip_loading_screen': True, 'side_width': []},
        {'accent_overrides': {'light': 'red'}, 'hide_minimized': True},
        {'mix': True},
        {'output': None},
        {'hide_minimized': 1},
        [], None,
    ):
        body['payload'] = bad
        result, status = routes['POST', '/api/settings']()
        assert status == 400 and not result['ok']
        assert device.settings == original
        assert global_config.settings['skip_loading_screen'] is False
        assert device.path.read_bytes() == device_before
        assert global_config.path.read_bytes() == global_before


def test_successful_settings_save_is_synchronized_across_configs(api):
    global_config, device, body, routes, _ = api
    body['payload'] = {'skip_loading_screen': True, 'theme': 'light',
                       'accent_overrides': {'light': '#ABCDEF'},
                       'enable_qjackctl': True, 'side_width': 250}
    assert routes['POST', '/api/settings']() == {'ok': True}
    assert device.settings['side_width'] == 250
    assert global_config.settings['skip_loading_screen'] is True
    assert Config_read(global_config.path).settings['theme'] == 'light'
    assert Config_read(device.path).settings['accent_overrides'] == {'light': '#abcdef'}
    assert routes['GET', '/api/settings']()['skip_loading_screen'] is True


def Config_read(path):
    loaded = Config(path)
    loaded.load()
    return loaded


def test_global_persistence_failure_restores_both_configs(api, monkeypatch):
    global_config, device, body, routes, _ = api
    body['payload'] = {'skip_loading_screen': True, 'theme': 'light', 'enable_qjackctl': True}
    original_save = global_config.save
    attempts = {'count': 0}

    def fail_once():
        attempts['count'] += 1
        if attempts['count'] == 1:
            original_save()  # simulate write succeeded before an IO exception
            raise OSError('disk interrupted')
        original_save()

    monkeypatch.setattr(global_config, 'save', fail_once)
    result, status = routes['POST', '/api/settings']()
    assert status == 500 and 'disk interrupted' in result['error']
    for conf in (device, global_config, Config_read(device.path), Config_read(global_config.path)):
        assert conf.settings['skip_loading_screen'] is False
        assert conf.settings['theme'] == 'dark'
        assert conf.settings['enable_qjackctl'] is False


def test_per_device_persistence_failure_restores_in_memory_and_disk(api, monkeypatch):
    _, device, body, routes, _ = api
    body['payload'] = {'mix': 3, 'hide_minimized': True}
    original_save = device.save
    count = {'n': 0}

    def fail_once():
        count['n'] += 1
        if count['n'] == 1:
            original_save()
            raise OSError('cannot finish save')
        original_save()

    monkeypatch.setattr(device, 'save', fail_once)
    result, status = routes['POST', '/api/settings']()
    assert status == 500 and 'cannot finish save' in result['error']
    assert device.settings['mix'] == 0
    assert Config_read(device.path).settings['mix'] == 0


def test_layout_validation_does_not_change_saved_data(api):
    _, device, body, routes, events = api
    device.legacy_layout = [{'id': 'ch/00', 'pinned': True, 'minimized': False}]
    device.save()
    original_bytes = device.path.read_bytes()
    for bad in ({'id': 'ch/01'}, [None], [42],
                [{'id': ''}], [{'id': 'ch/01', 'pinned': 'false'}],
                [{'id': 'ch/01'}, {'id': 'ch/01'}]):
        body['payload'] = bad
        result, status = routes['POST', '/api/layout']()
        assert status == 400 and not result['ok']
        assert device.path.read_bytes() == original_bytes
        assert device.layouts == {}
        assert not events
    body['mix'] = 'invalid'
    body['payload'] = []
    assert routes['POST', '/api/layout']()[1] == 400
    assert routes['GET', '/api/layout']()[1] == 400


def test_layout_valid_save_preserves_hidden_channels_and_broadcasts_after_save(api):
    _, device, body, routes, events = api
    device.legacy_layout = [{'id': 'ch/00', 'pinned': True, 'minimized': False},
                            {'id': 'ch/01', 'pinned': False, 'minimized': True}]
    device.save()
    body['payload'] = [{'id': 'ch/01', 'pinned': True, 'minimized': False}]
    assert routes['POST', '/api/layout']() == {'ok': True}
    assert device.layouts['0'] == [
        {'id': 'ch/01', 'pinned': True, 'minimized': False},
        {'id': 'ch/00', 'pinned': True, 'minimized': False}
    ]
    assert Config_read(device.path).layouts['0'] == device.layouts['0']
    assert events == [{'type': 'layout', 'mix': 0}]


def test_layout_save_error_rolls_back_and_does_not_broadcast(api, monkeypatch):
    _, device, body, routes, events = api
    device.layouts['0'] = [{'id': 'ch/01', 'pinned': False, 'minimized': True}]
    device.save()
    original_save = device.save
    count = {'n': 0}

    def broken_save():
        count['n'] += 1
        original_save()
        if count['n'] == 1:
            raise OSError('disk full')

    monkeypatch.setattr(device, 'save', broken_save)
    body['payload'] = [{'id': 'ch/02'}]
    result, status = routes['POST', '/api/layout']()
    assert status == 500 and 'disk full' in result['error']
    assert device.layouts['0'][0]['id'] == 'ch/01'
    assert Config_read(device.path).layouts['0'][0]['id'] == 'ch/01'
    assert events == []


def _extract_prepare_server():
    """Isolate the listener factory; dependencies are absent in offline test runs."""
    source = Path(__file__).resolve().parents[1] / 'src/ffado_webmixer/server.py'
    function = next(n for n in ast.parse(source.read_text()).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'prepare_server')
    ns = {'HOST': '0.0.0.0', 'PORT': 5000}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), ns)
    return ns['prepare_server']


@pytest.mark.parametrize('reason', [OSError('Address already in use'), SystemExit(1)])
def test_server_binding_fails_before_desktop_window(monkeypatch, reason):
    serving = types.ModuleType('werkzeug.serving')

    def unable(*_args, **_kwargs):
        raise reason

    serving.make_server = unable
    monkeypatch.setitem(sys.modules, 'werkzeug', types.ModuleType('werkzeug'))
    monkeypatch.setitem(sys.modules, 'werkzeug.serving', serving)
    with pytest.raises(RuntimeError, match='0.0.0.0:5000'):
        _extract_prepare_server()(object())


def test_server_preserves_threaded_flask_handling(monkeypatch):
    calls = []
    serving = types.ModuleType('werkzeug.serving')
    serving.make_server = lambda *args, **kwargs: calls.append((args, kwargs)) or object()
    monkeypatch.setitem(sys.modules, 'werkzeug', types.ModuleType('werkzeug'))
    monkeypatch.setitem(sys.modules, 'werkzeug.serving', serving)
    server = _extract_prepare_server()(object())
    assert server is not None
    assert calls[0][1]['threaded'] is True


def test_client_readiness_timeout_and_dead_thread(monkeypatch):
    stub = types.ModuleType('webview')
    monkeypatch.setitem(sys.modules, 'webview', stub)
    server_stub = types.ModuleType('ffado_webmixer.server')
    server_stub.PORT = 5000
    monkeypatch.setitem(sys.modules, 'ffado_webmixer.server', server_stub)
    sys.modules.pop('ffado_webmixer.client', None)
    client = importlib.import_module('ffado_webmixer.client')
    try:
        def unavailable(*args, **kwargs):
            raise OSError('refused')
        monkeypatch.setattr(client, 'urlopen', unavailable)
        with pytest.raises(RuntimeError, match='not ready'):
            client.wait_until_ready(timeout=0.01)
        dead = types.SimpleNamespace(is_alive=lambda: False)
        with pytest.raises(RuntimeError, match='exited'):
            client.wait_until_ready(timeout=0.2, server_thread=dead)
    finally:
        sys.modules.pop('ffado_webmixer.client', None)


def _mock_main(monkeypatch, prepare):
    """Exercise the real main() startup order without hardware/Flask/Qt."""
    from ffado_webmixer import main
    args = types.SimpleNamespace(demo=True, debug=None, headless=False)
    monkeypatch.setattr(main, 'parse_args', lambda: args)
    monkeypatch.setattr(main, 'create_backends', lambda args, cfg: [object()])
    server = types.ModuleType('ffado_webmixer.server')
    server.create_app = lambda **kwargs: object()
    server.prepare_server = prepare
    monkeypatch.setitem(sys.modules, 'ffado_webmixer.server', server)
    device_manager = types.ModuleType('ffado_webmixer.device_manager')
    device_manager.DeviceManager = lambda devices, cfg, debug=False: object()
    device_manager.SelectedBackend = lambda manager: types.SimpleNamespace(describe=lambda: {'device': 'Demo'})
    device_manager.SelectedConfig = lambda manager: object()
    monkeypatch.setitem(sys.modules, 'ffado_webmixer.device_manager', device_manager)
    return main


def test_main_fails_before_opening_desktop_when_port_is_busy(monkeypatch):
    def failed_bind(app):
        raise RuntimeError('Port 5000 is occupied')
    main = _mock_main(monkeypatch, failed_bind)
    with pytest.raises(SystemExit, match='Port 5000 is occupied'):
        main.main()
    # The import of the Qt client occurs strictly after prepare_server().


def test_main_releases_server_when_initial_readiness_fails(monkeypatch):
    calls = []

    class FakeServer:
        def serve_forever(self):
            calls.append('serve')
        def shutdown(self):
            calls.append('shutdown')
        def server_close(self):
            calls.append('close')

    server = FakeServer()
    main = _mock_main(monkeypatch, lambda app: server)
    client = types.ModuleType('ffado_webmixer.client')
    def fail_ready(server_thread):
        raise RuntimeError('listener quit unexpectedly')
    client.wait_until_ready = fail_ready
    client.run_window = lambda *args, **kwargs: calls.append('opened window')
    monkeypatch.setitem(sys.modules, 'ffado_webmixer.client', client)
    with pytest.raises(SystemExit, match='listener quit unexpectedly'):
        main.main()
    assert 'shutdown' in calls and 'close' in calls
    assert 'opened window' not in calls


def test_simultaneous_settings_updates_remain_consistent(api, monkeypatch):
    """Two browser threads must not interleave the device/global writes."""
    import threading
    root, device, _, routes, _ = api
    import ffado_webmixer.api.settings as settings
    local = threading.local()
    monkeypatch.setattr(settings.request, 'get_json', lambda force=True: local.payload)
    original_save = device.save
    entered_first_save = threading.Event()
    allow_first_save = threading.Event()
    entered_second_request = threading.Event()
    calls = []
    results = []
    failures = []

    def blocked_save():
        if not calls:
            calls.append('blocked')
            entered_first_save.set()
            assert allow_first_save.wait(5), 'timed out while testing concurrent writes'
        return original_save()

    monkeypatch.setattr(device, 'save', blocked_save)

    def update(theme, loading, signal=None):
        try:
            local.payload = {'theme': theme, 'skip_loading_screen': loading}
            if signal:
                signal.set()
            results.append(routes['POST', '/api/settings']())
        except Exception as error:
            failures.append(error)

    first = threading.Thread(target=update, args=('light', True))
    second = threading.Thread(target=update, args=('dark', False, entered_second_request))
    first.start()
    try:
        assert entered_first_save.wait(5)
        second.start()
        assert entered_second_request.wait(5)
    finally:
        allow_first_save.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert not failures
    assert results == [{'ok': True}, {'ok': True}]
    assert device.settings['theme'] == root.settings['theme']
    assert device.settings['skip_loading_screen'] == root.settings['skip_loading_screen']
    assert Config_read(device.path).settings['theme'] == Config_read(root.path).settings['theme']
    assert (Config_read(device.path).settings['skip_loading_screen']
            == Config_read(root.path).settings['skip_loading_screen'])


def test_invalid_layout_then_valid_layout_is_not_poisoned(api):
    """A malformed request cannot leave a partial layout for the next request."""
    _, device, body, routes, events = api
    initial = [{'id': 'ch/01', 'pinned': False, 'minimized': True},
               {'id': 'ch/02', 'pinned': True, 'minimized': False}]
    device.layouts['1'] = initial
    device.save()
    body['mix'] = '1'
    body['payload'] = [{'id': 'ch/04'}, {'id': 'ch/04'}]
    assert routes['POST', '/api/layout']()[1] == 400
    assert device.layouts['1'] == initial
    body['payload'] = [{'id': 'ch/02', 'pinned': False, 'minimized': True}]
    assert routes['POST', '/api/layout']() == {'ok': True}
    assert device.layouts['1'] == [
        {'id': 'ch/02', 'pinned': False, 'minimized': True}, initial[0]
    ]
    assert Config_read(device.path).layouts['1'] == device.layouts['1']
    assert events == [{'type': 'layout', 'mix': 1}]
