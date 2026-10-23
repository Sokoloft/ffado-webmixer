"""Linked tab names are independent of the two FFADO bus identities."""
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from ffado_webmixer.config import Config


class Routes:
    def __init__(self):
        self.routes = {}

    def get(self, path):
        return self._register('GET', path)

    def post(self, path):
        return self._register('POST', path)

    def _register(self, method, path):
        def wrapper(fn):
            self.routes[(method, path)] = fn
            return fn
        return wrapper


@pytest.fixture
def api(tmp_path):
    config = Config(tmp_path / 'device.json')
    config.load()
    config.names['bus:0'] = 'Guitar'
    config.names['bus:1'] = 'Vocals'
    config.save()
    backend = types.SimpleNamespace(
        mixes=['mix'] * 10,
        describe=lambda: {'matrix': {'available': True},
                          'mixes': [{'id': i, 'name': 'Bus ' + str(i + 1)} for i in range(10)],
                          'outputs': []},
    )
    body = {'value': None}
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    flask.request = types.SimpleNamespace(get_json=lambda **kwargs: body['value'])
    module_file = Path(__file__).resolve().parents[1] / 'src/ffado_webmixer/api/mixer.py'
    with patch.dict(sys.modules, {'flask': flask}):
        spec = importlib.util.spec_from_file_location('ffado_webmixer.api._test_bus_pair_alias', module_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    routes, events = Routes(), []
    module.register(routes, backend, {}, config, events.append)
    return config, body, routes.routes, events


def test_link_rename_unlink_reverts_to_individual_names(api):
    config, body, routes, events = api
    body['value'] = {'left': 0, 'linked': True}
    assert routes['POST', '/api/bus-stereo']() == {'ok': True}
    body['value'] = {'left': 0, 'name': 'Front of House'}
    assert routes['POST', '/api/bus-pair-name']() == {'ok': True}
    info = routes['GET', '/api/describe']()
    assert info['stereo_buses'] == [0]
    assert info['stereo_bus_names'] == {'0': 'Front of House'}
    assert [m['name'] for m in info['mixes'][:2]] == ['Guitar', 'Vocals']
    stored = Config(config.path)
    stored.load()
    assert stored.names['bus-pair:0'] == 'Front of House'
    body['value'] = {'left': 0, 'linked': False}
    assert routes['POST', '/api/bus-stereo']() == {'ok': True}
    info = routes['GET', '/api/describe']()
    assert info['stereo_buses'] == []
    assert info['stereo_bus_names'] == {}
    assert [m['name'] for m in info['mixes'][:2]] == ['Guitar', 'Vocals']
    stored = Config(config.path)
    stored.load()
    assert 'bus-pair:0' not in stored.names
    assert events[-1]['type'] == 'bus-stereo'


@pytest.mark.parametrize('payload', [
    None, [], {'left': 1, 'name': 'Wrong pair'},
    {'left': 2, 'name': 'Not linked'},
    {'left': True, 'name': 'Bad'}, {'left': 0, 'name': ''},
    {'left': 0, 'name': 'A' * 33},
])
def test_invalid_pair_name_does_not_change_saved_state(api, payload):
    config, body, routes, events = api
    saved = config.path.read_bytes()
    body['value'] = payload
    response, code = routes['POST', '/api/bus-pair-name']()
    assert code == 400
    assert response['error']
    assert config.path.read_bytes() == saved
    assert events == []


def test_pair_rename_failure_rolls_back(api, monkeypatch):
    config, body, routes, events = api
    body['value'] = {'left': 2, 'linked': True}
    assert routes['POST', '/api/bus-stereo']() == {'ok': True}
    original = config.path.read_bytes()
    save = config.save
    attempts = [0]
    def fail_once():
        attempts[0] += 1
        if attempts[0] == 1:
            raise OSError('simulated write failure')
        return save()
    monkeypatch.setattr(config, 'save', fail_once)
    body['value'] = {'left': 2, 'name': 'Stereo 3+4'}
    response, code = routes['POST', '/api/bus-pair-name']()
    assert code == 500
    assert 'bus-pair:2' not in config.names
    assert config.path.read_bytes() == original
    assert events[-1]['type'] == 'bus-stereo'


def test_unlink_save_failure_keeps_link_and_alias(api, monkeypatch):
    config, body, routes, events = api
    body['value'] = {'left': 0, 'linked': True}
    routes['POST', '/api/bus-stereo']()
    body['value'] = {'left': 0, 'name': 'Stereo mix'}
    routes['POST', '/api/bus-pair-name']()
    original = config.path.read_bytes()
    saved_events = list(events)
    save = config.save
    n = [0]
    def once():
        n[0] += 1
        if n[0] == 1:
            raise OSError('offline failure')
        return save()
    monkeypatch.setattr(config, 'save', once)
    body['value'] = {'left': 0, 'linked': False}
    response, code = routes['POST', '/api/bus-stereo']()
    assert code == 500
    assert config.settings['stereo_buses'] == [0]
    assert config.names['bus-pair:0'] == 'Stereo mix'
    assert config.path.read_bytes() == original
    assert events == saved_events


@pytest.mark.parametrize('bad', [
    {'left': 1, 'linked': True}, {'left': 0, 'linked': 1},
    {'left': '0', 'linked': True}, {'left': -2, 'linked': True},
    {'left': 10, 'linked': True}, {'left': 0}, [], None,
])
def test_invalid_bus_link_rejected(api, bad):
    config, body, routes, events = api
    saved = config.path.read_bytes()
    body['value'] = bad
    response, code = routes['POST', '/api/bus-stereo']()
    assert code == 400
    assert config.path.read_bytes() == saved
    assert not events
