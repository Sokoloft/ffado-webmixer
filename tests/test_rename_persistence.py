"""Real HTTP rename failures must restore preferences and return JSON errors."""
from copy import deepcopy

import pytest
from flask import Flask

from ffado_webmixer.api import mixer as mixer_routes, settings as settings_routes
from ffado_webmixer.config import Config
from ffado_webmixer.demo import DemoMixer


@pytest.fixture
def api(tmp_path, monkeypatch):
    config = Config(tmp_path / 'device.json')
    config.load()
    mixer, events, writes = DemoMixer(), [], []
    original_write = mixer.write

    def record_write(*args):
        writes.append(args)
        return original_write(*args)

    monkeypatch.setattr(mixer, 'write', record_write)
    app = Flask(__name__)
    app.config.update(TESTING=True, PROPAGATE_EXCEPTIONS=False)
    mixer_routes.register(app, mixer, mixer.describe(), config, events.append)
    settings_routes.register(app, config, events.append)
    return app.test_client(), config, mixer, events, writes


def saved_names(config):
    restored = Config(config.path)
    restored.load()
    return restored.names


@pytest.mark.parametrize('strip', ['ch/01', 'out:main'])
@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('failure_after_replace', [False, True])
def test_failed_rename_restores_memory_disk_and_later_saves(
        api, monkeypatch, strip, existing, failure_after_replace):
    client, config, _, events, writes = api
    config.names['ch/02'] = 'Unrelated'
    if existing:
        config.names[strip] = 'Original'
    config.save()
    before = dict(config.names)
    save = config.save
    attempts = 0

    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            if failure_after_replace:
                save()
            raise OSError('simulated rename save failure')
        save()

    monkeypatch.setattr(config, 'save', fail_once)
    response = client.post('/api/set', json={'strip': strip, 'control': 'name', 'value': 'Failed name'})
    assert response.status_code == 500 and response.is_json
    assert 'simulated rename save failure' in response.json['error']
    assert config.names == before and saved_names(config) == before
    assert attempts == 2 and not events and not writes
    # An unrelated preferences save must never make the rejected name reappear.
    assert client.post('/api/settings', json={'hide_minimized': True}).status_code == 200
    assert saved_names(config) == before


@pytest.mark.parametrize('strip', ['ch/01', 'out:main'])
def test_rename_reports_incomplete_disk_rollback_but_restores_memory(api, monkeypatch, strip):
    client, config, _, events, writes = api
    config.names[strip] = 'Original'
    config.save()
    save, attempts = config.save, 0

    def fail_both():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            save()  # The failed operation has already replaced the file.
        raise OSError('disk unavailable')

    monkeypatch.setattr(config, 'save', fail_both)
    response = client.post('/api/set', json={'strip': strip, 'control': 'name', 'value': 'Failed name'})
    assert response.status_code == 500 and response.is_json
    assert 'rollback may be incomplete' in response.json['error']
    assert config.names[strip] == 'Original'
    assert attempts == 2 and not events and not writes


@pytest.mark.parametrize('strip', ['ch/01', 'out:main'])
def test_rename_holds_save_lock_through_save_and_rollback(api, monkeypatch, strip):
    client, config, _, events, _ = api
    save, ownership = config.save, []

    def checked_save():
        # Check before Config.save acquires its own reentrant lock: the route
        # must already hold it across mutation, persistence and restoration.
        ownership.append(config._save_lock._is_owned())
        if len(ownership) == 1:
            raise OSError('save failed')
        save()

    monkeypatch.setattr(config, 'save', checked_save)
    response = client.post('/api/set', json={'strip': strip, 'control': 'name', 'value': 'Failed name'})
    assert response.status_code == 500
    assert ownership == [True, True]
    assert strip not in config.names and not events


@pytest.mark.parametrize('strip', ['ch/01', 'out:main'])
def test_successful_rename_is_persisted_and_broadcast_without_hardware_changes(api, strip):
    client, config, mixer, events, writes = api
    before = deepcopy((mixer.mixes, mixer.chan, mixer.out))
    response = client.post('/api/set', json={'strip': strip, 'control': 'name', 'value': '  New label  '})
    assert response.status_code == 200 and response.json == {'ok': True}
    assert config.names[strip] == saved_names(config)[strip] == 'New label'
    assert events == [{'type': 'name', 'strip': strip, 'value': 'New label'}]
    assert (mixer.mixes, mixer.chan, mixer.out) == before and not writes
    if strip.startswith('out:'):
        assert client.get('/api/output?out=main').json['name'] == 'New label'
    else:
        assert client.get('/api/state?mix=0').json[strip]['name'] == 'New label'


@pytest.mark.parametrize('payload', [
    None, [], 'rename', 12, {},
    {'control': 'name', 'value': 'Label'},
    {'strip': 'ch/01', 'value': 'Label'},
    {'strip': 'ch/01', 'control': 'name'},
    {'strip': [], 'control': 'name', 'value': 'Label'},
    {'strip': None, 'control': 'name', 'value': 'Label'},
    {'strip': '', 'control': 'name', 'value': 'Label'},
    {'strip': 'ch/01', 'control': [], 'value': 1},
    {'strip': 'ch/01', 'control': None, 'value': 1},
    {'strip': 'ch/01', 'control': 'unknown', 'value': 1},
    {'strip': 'ch/01', 'control': 'name', 'value': []},
    {'strip': 'ch/01', 'control': 'name', 'value': None},
    {'strip': 'ch/01', 'control': 'name', 'value': 123},
    {'strip': 'ch/01', 'control': 'name', 'value': '  '},
    {'strip': 'ch/01', 'control': 'name', 'value': 'x' * 17},
    *({'strip': 'ch/01', 'control': 'fader', 'value': 50, 'mix': mix}
      for mix in ('bad', None, [], {}, True, -1, 1.5)),
    *({'strip': 'ch/01', 'control': control, 'value': value}
      for control, value in [('fader', None), ('pan', []), ('gain', {}),
                             ('fader', 'invalid'), ('fader', True),
                             ('fader', float('nan')), ('pan', float('inf')),
                             ('mute', 'false'), ('solo', 1), ('invert', None)]),
])
def test_malformed_set_payload_is_json_400_without_writes_or_preference_changes(api, payload):
    import json
    client, config, mixer, events, writes = api
    before = deepcopy((config.names, mixer.mixes, mixer.chan, mixer.out))
    stored = config.path.read_bytes()
    response = client.post('/api/set', data=json.dumps(payload), content_type='application/json')
    assert response.status_code == 400 and response.is_json
    assert isinstance(response.json['error'], str) and response.json['error']
    assert (config.names, mixer.mixes, mixer.chan, mixer.out) == before
    assert config.path.read_bytes() == stored and not writes and not events


@pytest.mark.parametrize('body', ['{', '', '{"strip":'])
def test_invalid_json_syntax_returns_json_400(api, body):
    client, config, _, events, writes = api
    stored = config.path.read_bytes()
    response = client.post('/api/set', data=body, content_type='application/json')
    assert response.status_code == 400 and response.is_json
    assert response.json['error']
    assert config.path.read_bytes() == stored and not writes and not events


def test_set_preserves_numeric_string_bus_compatibility(api):
    client, _, mixer, events, _ = api
    response = client.post('/api/set', json={
        'strip': 'ch/01', 'control': 'fader', 'value': 44, 'mix': '2'})
    assert response.status_code == 200
    assert mixer.mixes[2]['ch/01']['fader'] == 44
    assert events[0]['mix'] == 2
