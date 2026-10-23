"""Bus-tab preference validation and persistence, without Flask/FireWire."""
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

from ffado_webmixer.config import Config


class Routes:
    def __init__(self):
        self.routes = {}

    def get(self, path):
        return lambda handler: self._add('GET', path, handler)

    def post(self, path):
        return lambda handler: self._add('POST', path, handler)

    def _add(self, method, path, handler):
        self.routes[method, path] = handler
        return handler


@pytest.fixture
def endpoint(monkeypatch, tmp_path):
    conf = Config(tmp_path / 'device.json')
    conf.load()
    values = {'payload': None}
    request = types.SimpleNamespace(get_json=lambda force=True: values['payload'])
    flask = types.ModuleType('flask')
    flask.request = request
    flask.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    monkeypatch.setitem(sys.modules, 'flask', flask)
    sys.modules.pop('ffado_webmixer.api.settings', None)
    api = importlib.import_module('ffado_webmixer.api.settings')
    routes, events = Routes(), []
    api.register(routes, conf, events.append)
    yield conf, values, routes.routes, events
    sys.modules.pop('ffado_webmixer.api.settings', None)


def test_bus_layout_survives_restart_without_affecting_channel_layout(endpoint):
    conf, values, routes, events = endpoint
    conf.layouts['0'] = [{'id': 'ch/01', 'pinned': True, 'minimized': False}]
    before = json.dumps(conf.layouts)
    values['payload'] = [
        {'id': '3', 'pinned': True, 'minimized': False},
        {'id': '2', 'pinned': False, 'minimized': True},
        {'id': '0', 'pinned': False, 'minimized': False},
    ]
    assert routes['POST', '/api/bus-layout']() == {'ok': True}
    assert events == [{'type': 'bus-layout'}]
    assert routes['GET', '/api/bus-layout']() == values['payload']
    assert json.dumps(conf.layouts) == before
    loaded = Config(conf.path)
    loaded.load()
    assert loaded.bus_layout == values['payload']
    assert loaded.layouts == conf.layouts


@pytest.mark.parametrize('invalid', [
    {}, None, 'bus 0', [{'id': 'x'}], [{'id': '-1'}], [{'id': '01'}],
    [{'id': '0'}, {'id': '0'}], [{'id': '0', 'pinned': 1}],
    [{'id': '1', 'minimized': 'yes'}], [None],
])
def test_bad_bus_layout_cannot_overwrite_saved_preferences(endpoint, invalid):
    conf, values, routes, events = endpoint
    original = [{'id': '1', 'pinned': False, 'minimized': False}]
    conf.bus_layout = list(original)
    conf.save()
    previous = conf.path.read_bytes()
    values['payload'] = invalid
    body, status = routes['POST', '/api/bus-layout']()
    assert status == 400 and body['ok'] is False
    assert conf.bus_layout == original
    assert conf.path.read_bytes() == previous
    assert not events


def test_failed_disk_save_restores_layout(endpoint, monkeypatch):
    conf, values, routes, events = endpoint
    original = [{'id': '0', 'pinned': True, 'minimized': True}]
    conf.bus_layout = original.copy()
    conf.save()
    normal = conf.save
    attempts = [0]

    def fail_once():
        attempts[0] += 1
        if attempts[0] == 1:
            raise OSError('simulated disk failure')
        return normal()

    monkeypatch.setattr(conf, 'save', fail_once)
    values['payload'] = [{'id': '0', 'pinned': False, 'minimized': False}]
    body, status = routes['POST', '/api/bus-layout']()
    assert status == 500 and 'simulated disk failure' in body['error']
    assert conf.bus_layout == original
    assert json.loads(conf.path.read_text())['bus_layout'] == original
    assert events == []


def test_hide_minimized_buses_validated_and_saved(endpoint):
    conf, values, routes, events = endpoint
    values['payload'] = {'hide_minimized_buses': True}
    assert routes['POST', '/api/settings']() == {'ok': True}
    assert conf.settings['hide_minimized_buses'] is True
    assert Config(conf.path).settings['hide_minimized_buses'] is False  # defaults before load
    loaded = Config(conf.path)
    loaded.load()
    assert loaded.settings['hide_minimized_buses'] is True
    values['payload'] = {'hide_minimized_buses': 'yes'}
    assert routes['POST', '/api/settings']()[1] == 400
    assert conf.settings['hide_minimized_buses'] is True


def test_bus_rename_is_stored_without_mutating_physical_mix_names(monkeypatch, tmp_path):
    """Bus aliases are UI-only and do not write hardware routing or gain."""
    import importlib.util
    from unittest.mock import patch
    conf = Config(tmp_path / 'bus-names.json')
    conf.load()
    body = {'mix': 4, 'name': '  Vocals  '}
    request = types.SimpleNamespace(get_json=lambda silent=False: body)
    flask = types.ModuleType('flask')
    flask.request = request
    flask.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    backend = types.SimpleNamespace(
        mixes=['mix'] * 18,
        describe=lambda: {'mixes': [{'id': i, 'name': f'Physical {i}'} for i in range(18)],
                          'outputs': [], 'matrix': {'available': True}},
    )
    module_name = 'ffado_webmixer.api._bus_rename_test'
    module_path = Path(__file__).parents[1] / 'src/ffado_webmixer/api/mixer.py'
    with patch.dict(sys.modules, {'flask': flask}):
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    routes, events = Routes(), []
    module.register(routes, backend, {}, conf, events.append)
    response = routes.routes['POST', '/api/bus-name']()
    assert response == {'ok': True}
    assert conf.names['bus:4'] == 'Vocals'
    assert Config(conf.path).names == {}
    reread = Config(conf.path)
    reread.load()
    assert reread.names['bus:4'] == 'Vocals'
    mixes = routes.routes['GET', '/api/describe']()['mixes']
    assert mixes[4]['name'] == 'Vocals'
    assert mixes[3]['name'] == 'Physical 3'
    assert events[-1] == {'type': 'bus-name', 'mix': 4, 'name': 'Vocals'}
    for bad in ({'mix': 18, 'name': 'Bad'}, {'mix': -1, 'name': 'Bad'},
                {'mix': True, 'name': 'Bad'}, {'mix': 2, 'name': ' '},
                {'mix': 3, 'name': 'x'*17}):
        body.clear()
        body.update(bad)
        assert routes.routes['POST', '/api/bus-name']()[1] == 400
    assert list(conf.names) == ['bus:4']
