"""Physical DICE stereo outputs and source-mapped hardware output peaks."""
import contextlib
import importlib.util
import io
import math
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.peak_metering import output_peak_samples
from ffado_webmixer.profiles.resolver import match_outputs


@pytest.fixture
def mixer(tmp_path):
    with contextlib.redirect_stdout(io.StringIO()):
        result = make_debug_mixer('saffirepro40', Config(tmp_path / 'device.json'))
    # The generic debug fixture has a matrix only. Supply the real model's
    # optional discovered monitoring controls, then resolve through its profile.
    for number in range(1, 11):
        for role, kind in [('Volume', 'Discrete'), ('Mute', 'Boolean')]:
            path = result.device['device'] + f'/EAP/Monitoring/LineOut/{role}{number}'
            result.device['controls'].append({'path': path, 'kind': kind})
            result.helper.values[path] = -20 if role == 'Volume' else False
    result.helper.get_selected = lambda path, kind: result.helper.values[path]
    result.helper.select = lambda path, value, kind: result.helper.values.__setitem__(path, value)
    result.outputs = match_outputs(result.device, result.mixes, result.profile)
    result.config.settings['stereo_outputs'] = ['line/1']
    return result


def test_pair_read_and_write_from_either_leg(mixer):
    assert mixer.output_pairs()[0] == ['line/1', 'line/2']
    mixer.write_output('line/1', 'fader', 25)
    mixer.write_output('line/2', 'fader', 75)
    assert mixer.read_linked_output('line/2')['level'] == 75
    for out in ('line/1', 'line/2'):
        mixer.write_linked_output(out, 'fader', 50)
        assert mixer.read_output('line/1')['level'] == 50
        assert mixer.read_output('line/2')['level'] == 50
    mixer.write_linked_output('line/2', 'mute', True)
    assert all(mixer.read_output(out)['mute'] for out in ('line/1', 'line/2'))
    mixer.write_linked_output('line/1', 'mute', False)
    assert not any(mixer.read_output(out)['mute'] for out in ('line/1', 'line/2'))


@pytest.mark.parametrize('control,value', [('fader', 90), ('mute', True)])
def test_partial_write_restores_both_outputs(mixer, control, value):
    mixer.write_output('line/1', 'fader', 25)
    mixer.write_output('line/2', 'fader', 75)
    before = {out: mixer.read_output(out) for out in ('line/1', 'line/2')}
    write = mixer.write_output
    failed = False

    def fail_after_write(out, kind, level):
        nonlocal failed
        write(out, kind, level)
        if out == 'line/2' and not failed:
            failed = True
            raise OSError('second output failed after write')

    mixer.write_output = fail_after_write
    with pytest.raises(OSError, match='second output'):
        mixer.write_linked_output('line/1', control, value)
    assert {out: mixer.read_output(out) for out in before} == before


def test_pending_recovery_and_bad_values_touch_neither_leg(mixer):
    writes = []
    mixer.write_output = lambda *args: writes.append(args)
    mixer._pending_output_recovery = {'line/2'}
    with pytest.raises(RuntimeError, match='pending mute recovery'):
        mixer.write_linked_output('line/1', 'fader', 20)
    mixer._pending_output_recovery.clear()
    for control, value in [('fader', True), ('fader', math.nan), ('fader', 101),
                           ('mute', 1), ('name', 'test')]:
        with pytest.raises(ValueError):
            mixer.write_linked_output('line/1', control, value)
    assert writes == []


def api(mixer, payload):
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    flask.request = types.SimpleNamespace(get_json=lambda **kwargs: payload)
    routes, events = {}, []
    app = types.SimpleNamespace(
        get=lambda path: lambda fn: routes.setdefault(('GET', path), fn),
        post=lambda path: lambda fn: routes.setdefault(('POST', path), fn))
    name = 'ffado_webmixer.api._output_stereo_test'
    path = Path(__file__).parents[1] / 'src/ffado_webmixer/api/mixer.py'
    with patch.dict(sys.modules, {'flask': flask}):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.register(app, mixer, {}, mixer.config, events.append)
    return routes, events


def test_link_persistence_validation_and_save_rollback(mixer):
    payload = {'left': 'line/1', 'linked': False}
    routes, events = api(mixer, payload)
    writes = []
    mixer.helper.set_value = lambda *args: writes.append(args)
    assert routes['POST', '/api/output-stereo']() == {'ok': True}
    payload['linked'] = True
    assert routes['POST', '/api/output-stereo']() == {'ok': True}
    saved = Config(mixer.config.path)
    saved.load()
    assert saved.settings['stereo_outputs'] == ['line/1']
    assert routes['GET', '/api/describe']()['stereo_outputs'] == ['line/1']
    assert len(events) == 2 and not writes
    for left in ('line/2', 'line/99', 'bus/0', None, 1):
        payload['left'] = left
        assert routes['POST', '/api/output-stereo']()[1] == 400
    payload.update(left='line/1', linked=False)
    original_save = mixer.config.save
    count = 0

    def fail_once():
        nonlocal count
        count += 1
        if count == 1:
            raise OSError('disk unavailable')
        original_save()

    mixer.config.save = fail_once
    assert routes['POST', '/api/output-stereo']()[1] == 500
    assert mixer.config.settings['stereo_outputs'] == ['line/1']
    assert len(events) == 2


def test_output_peaks_use_shared_ffado_frame_without_gain_or_routing_reads(mixer):
    calls = []
    values = [('Line/Out:02', 4095), ('Mixer/In:01', 4095),
              ('Line/Out:01', 256), ('Mixer/Out:01', 1024)]

    def forbidden_read(*args):
        raise AssertionError('Output metering must not read gain or routing controls')

    def track_route(path, method, *args):
        calls.append(method)
        if method == 'hasPeakMetering':
            return True
        if method == 'getPeakValues':
            return values
        return forbidden_read()

    mixer.helper.get_cell = forbidden_read
    mixer.helper.get_value = forbidden_read
    mixer.helper.router_call = track_route
    first = mixer.peak_snapshot()
    left, right = first['outputs']['line/1'], first['outputs']['line/2']
    assert left == {'destination': 'Line/Out:01', **first['destination_levels']['Line/Out:01']}
    assert left['level'] == .25 and left['raw'] == 256
    assert left['db'] == pytest.approx(-12.04)
    assert right['near_full_scale'] and not left['near_full_scale']
    assert right['raw'] == 4095 and first['channels']['0']['raw'] == 4095
    assert 'estimated' not in left and 'source' not in left
    assert 'line/3' not in first['outputs'] and 'bus/0' not in first['outputs']
    assert calls == ['hasPeakMetering', 'getPeakValues']
    # An output can be silent while a loud input is present. A missing side
    # must not retain an old reading or copy the available side/input peak.
    values[:] = [('Mixer/In:01', 4095), ('Line/Out:02', 0)]
    second = mixer.peak_snapshot()
    assert set(second['outputs']) == {'line/2'}
    assert second['outputs']['line/2']['raw'] == 0
    assert second['outputs']['line/2']['db'] is None
    assert not second['outputs']['line/2']['near_full_scale']
    # Actual output peaks are available even when input readings are absent.
    values[:] = [('Line/Out:01', 1024)]
    third = mixer.peak_snapshot()
    assert third['channels'] == {} and third['outputs']['line/1']['level'] == .5
    values[:] = [('Line/Out:01', math.nan), ('Line/Out:02', 4096)]
    assert mixer.peak_snapshot()['outputs'] == {}
    assert calls == ['hasPeakMetering'] + ['getPeakValues'] * 4


def test_output_meter_mapping_uses_declared_destination_and_ignores_aliases(mixer):
    destinations = {'Line/Out:01': {'raw': 1024, 'level': .5, 'db': -6.02},
                    'Line/Out:03': {'raw': 256, 'level': .25, 'db': -12.04}}
    mixer.outputs['line/1']['name'] = 'Line Out 3'
    assert output_peak_samples(mixer, destinations)['line/1']['destination'] == 'Line/Out:01'
    # A matching label or ordinal never supplies missing source metadata.
    del mixer.outputs['line/1']['meter_destination']
    assert 'line/1' not in output_peak_samples(mixer, destinations)


def test_other_families_never_gain_line_pairing(tmp_path):
    with contextlib.redirect_stdout(io.StringIO()):
        motu = make_debug_mixer('motuultralite', Config(None))
    assert motu.output_pairs() == []


def output_client(mixer):
    from flask import Flask
    from ffado_webmixer.api import mixer as mixer_routes
    app = Flask(__name__)
    mixer_routes.register(app, mixer, mixer.describe(), mixer.config, lambda event: None)
    return app.test_client()


def test_pair_rename_matches_input_faders_and_survives_restart_and_unlink(mixer):
    client = output_client(mixer)
    for out in ('line/1', 'line/2'):
        assert client.get('/api/output', query_string={'out': out}).json['name'] == 'Line Out 1+2'
    info = client.get('/api/describe').json
    assert not info['outputs'][0]['custom_name']
    response = client.post('/api/set', json={'strip': 'out:line/1', 'control': 'name', 'value': '  Monitors  '})
    assert response.status_code == 200
    for out in ('line/1', 'line/2'):
        assert client.get('/api/output', query_string={'out': out}).json['name'] == 'Monitors'
    outputs = {out['id']: out for out in client.get('/api/describe').json['outputs']}
    assert outputs['line/1']['name'] == 'Monitors' and outputs['line/1']['custom_name']
    assert outputs['line/2']['name'] == 'Line Out 2' and not outputs['line/2']['custom_name']
    restored = Config(mixer.config.path)
    restored.load()
    mixer.config = restored
    client = output_client(mixer)
    assert client.get('/api/output?out=line/1').json['name'] == 'Monitors'
    assert client.post('/api/output-stereo', json={'left': 'line/1', 'linked': False}).status_code == 200
    assert client.get('/api/output?out=line/1').json['name'] == 'Monitors'
    assert client.get('/api/output?out=line/2').json['name'] == 'Line Out 2'
    assert client.post('/api/output-stereo', json={'left': 'line/1', 'linked': True}).status_code == 200
    assert client.get('/api/output?out=line/1').json['name'] == 'Monitors'


def test_right_output_alias_only_contributes_to_an_unrenamed_pair(mixer):
    client = output_client(mixer)
    assert client.post('/api/set', json={'strip': 'out:line/2', 'control': 'name', 'value': 'Right speaker'}).status_code == 200
    assert client.get('/api/output?out=line/1').json['name'] == 'Line Out 1 + Right speaker'
    assert client.post('/api/set', json={'strip': 'out:line/1', 'control': 'name', 'value': 'Speakers'}).status_code == 200
    assert client.get('/api/output?out=line/2').json['name'] == 'Speakers'


def test_failed_pair_rename_restores_automatic_pair_name(mixer):
    client = output_client(mixer)
    save, attempts = mixer.config.save, 0

    def fail_once():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError('rename failed')
        save()

    mixer.config.save = fail_once
    response = client.post('/api/set', json={'strip': 'out:line/1', 'control': 'name', 'value': 'Rejected'})
    assert response.status_code == 500
    assert client.get('/api/output?out=line/1').json['name'] == 'Line Out 1+2'
    assert not client.get('/api/describe').json['outputs'][0]['custom_name']
