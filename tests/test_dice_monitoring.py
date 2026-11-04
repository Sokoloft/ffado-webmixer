"""Global DICE monitoring uses native controls, never matrix mute emulation."""
import contextlib
import io

import pytest
from flask import Flask

from ffado_webmixer.api import mixer as mixer_routes
from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer


@pytest.fixture
def mixer():
    with contextlib.redirect_stdout(io.StringIO()):
        return make_debug_mixer('saffirepro40', Config(None))


def path(mixer, suffix):
    return mixer.device['device'] + '/EAP/Monitoring/' + suffix


def test_disabled_dim_displays_retained_level_without_overwriting_hardware(mixer):
    mixer.helper.values[path(mixer, 'GlobalDim/Level')] = -20
    before = dict(mixer.helper.values)
    result = mixer.read_linked_output('dice/dim')
    assert result['level'] == pytest.approx(6800 / 88) and not result['dim_active']
    assert result['mute']
    assert not result['emulated_mute']
    assert mixer.helper.values == before
    output = next(out for out in mixer.describe()['outputs'] if out['id'] == 'dice/dim')
    assert output['controllable'] and output['gain_scale']['mode'] == 'dice_dim'


def test_dim_automatically_activates_and_clears_with_verified_native_level(mixer):
    for position, raw in [(1, -87), (12, -76), (44, -44), (87, -1), (88, 0), (0, 0)]:
        mixer.write_linked_output('dice/dim', 'fader', position * 100 / 88)
        assert mixer.helper.values[path(mixer, 'GlobalDim/Level')] == raw
        assert mixer.helper.values[path(mixer, 'GlobalDim/State')] is (position > 0)
        assert mixer.read_output('dice/dim')['level'] == pytest.approx((position or 88) * 100 / 88)
        assert all(mixer.helper.values[path(mixer, f'LineOut/GDim{n}')] for n in range(1, 11))
    assert mixer.helper.cells == {} and mixer.mute_memory == {}


def test_dim_mute_toggles_dim_and_retains_level_without_hardware_mute(mixer):
    mixer.write_output('dice/dim', 'fader', 50)
    level = mixer.helper.values[path(mixer, 'GlobalDim/Level')]
    for muted in (True, False):
        mixer.write_linked_output('dice/dim', 'mute', muted)
        assert mixer.helper.values[path(mixer, 'GlobalMute/State')] is False
        assert mixer.helper.values[path(mixer, 'GlobalDim/State')] is (not muted)
        assert mixer.read_output('dice/dim')['mute'] is muted
        assert mixer.read_output('dice/dim')['level'] == 50
        assert all(mixer.helper.values[path(mixer, f'LineOut/GDim{n}')] for n in range(1, 11))
        assert mixer.helper.values[path(mixer, 'GlobalDim/Level')] == level
    assert mixer.helper.cells == {} and mixer.mute_memory == {}


def test_hw_monitor_toggles_every_line_without_reading_or_rewriting_gain(mixer):
    mixer.config.settings['stereo_outputs'] = ['line/1']
    for n in range(1, 11):
        mixer.helper.values[path(mixer, f'LineOut/Volume{n}')] = -n
    before = dict(mixer.helper.values)
    assert not mixer.read_dice_monitoring()['hw_monitor']
    mixer.write_dice_monitoring('hw_monitor', True)
    assert mixer.read_dice_monitoring()['hw_monitor']
    for n in range(1, 11):
        assert mixer.helper.values[path(mixer, f'LineOut/UnActivate{n}')] is True
    get_value = mixer.helper.get_value

    def no_line_gain_reads(p, kind):
        assert '/LineOut/Volume' not in p
        return get_value(p, kind)

    mixer.helper.get_value = no_line_gain_reads
    result = mixer.read_linked_output('line/1')
    assert result['level'] is None and result['hardware_controlled']
    with pytest.raises(ValueError, match='hardware monitor knob'):
        mixer.write_linked_output('line/1', 'fader', 50)
    mixer.helper.get_value = get_value
    mixer.write_dice_monitoring('hw_monitor', False)
    assert mixer.helper.values == before
    assert mixer.read_linked_output('line/1')['level'] is not None


def test_partial_monitor_state_is_reported_and_can_be_enabled(mixer):
    mixer.helper.values[path(mixer, 'LineOut/UnActivate1')] = True
    state = mixer.read_dice_monitoring()
    assert state['hw_monitor_partial'] and not state['hw_monitor']
    mixer.write_dice_monitoring('hw_monitor', True)
    assert not mixer.read_dice_monitoring()['hw_monitor_partial']


def test_existing_hardware_switch_state_is_read_without_inversion(mixer):
    for n in range(1, 11):
        mixer.helper.values[path(mixer, f'LineOut/UnActivate{n}')] = True
    before = dict(mixer.helper.values)
    assert mixer.read_dice_monitoring()['hw_monitor']
    assert mixer.read_output('line/1')['hardware_controlled']
    assert mixer.helper.values == before


def test_dim_disables_before_clearing_native_attenuation(mixer):
    mixer.write_output('dice/dim', 'fader', 100 / 88)
    write = mixer._write_scalar
    changes = []

    def record(control, value):
        changes.append((control['path'], value))
        write(control, value)

    mixer._write_scalar = record
    mixer.write_output('dice/dim', 'fader', 0)
    assert changes[:2] == [(path(mixer, 'GlobalDim/State'), False),
                           (path(mixer, 'GlobalDim/Level'), 0)]


@pytest.mark.parametrize('control,value', [('hw_monitor', 1), ('bad', True)])
def test_invalid_hardware_requests_never_write(mixer, control, value):
    before = dict(mixer.helper.values)
    with pytest.raises(ValueError):
        mixer.write_dice_monitoring(control, value)
    assert mixer.helper.values == before


@pytest.mark.parametrize('control,value', [('mute', 1), ('fader', True), ('fader', -1),
                                         ('fader', 101), ('fader', float('nan'))])
def test_invalid_dim_requests_never_write(mixer, control, value):
    before = dict(mixer.helper.values)
    with pytest.raises(ValueError):
        mixer.write_output('dice/dim', control, value)
    assert mixer.helper.values == before


@pytest.mark.parametrize('operation', ['dim', 'hw', 'mute'])
def test_partial_write_failure_restores_all_attempted_native_controls(mixer, operation):
    before = dict(mixer.helper.values)
    write = mixer._write_scalar
    failed = False

    def fail_after_write(control, value):
        nonlocal failed
        write(control, value)
        if not failed and control['path'].endswith(('GDim3', 'UnActivate3', 'GMute3')):
            failed = True
            raise IOError('disconnected after write')

    mixer._write_scalar = fail_after_write
    with pytest.raises(IOError, match='disconnected'):
        if operation == 'dim':
            mixer.write_output('dice/dim', 'fader', 50)
        elif operation == 'mute':
            mixer.write_dice_monitoring('mute', True)
        else:
            mixer.write_dice_monitoring('hw_monitor', True)
    assert mixer.helper.values == before


def test_rejected_write_is_detected_by_readback(mixer):
    mixer.helper.set_value = lambda *args: None
    with pytest.raises(IOError, match='acknowledge'):
        mixer.write_output('dice/dim', 'fader', 50)


def test_missing_or_wrong_interface_does_not_expose_monitoring(mixer):
    mixer.device['controls'] = [c for c in mixer.device['controls']
                                if not c['path'].endswith(('UnActivate10', 'GDim10'))]
    assert 'hw_monitor' not in mixer.dice_monitor_description()
    assert 'dim' not in mixer.dice_monitor_description()
    with pytest.raises(ValueError, match='not supported'):
        mixer.write_dice_monitoring('hw_monitor', True)
    for control in mixer.device['controls']:
        if control['path'].endswith('GlobalMute/State'):
            control['kind'] = 'Discrete'
    assert 'mute' not in mixer.dice_monitor_description()


@pytest.mark.parametrize('alias,count', [('saffirepro14', 4), ('saffirepro26', 6), ('saffirepro40', 10)])
def test_monitor_count_is_model_specific(alias, count):
    m = make_debug_mixer(alias, Config(None))
    assert len(m.dice_monitor_controls()['hw_monitor']) == count
    assert len(m.dice_monitor_controls()['dim']['members']) == count


def test_unrelated_devices_cannot_gain_monitoring_controls():
    m = make_debug_mixer('motuultralite', Config(None))
    assert m.dice_monitor_description() == {}
    assert 'dice/dim' not in m.outputs
    with pytest.raises(ValueError):
        m.write_dice_monitoring('hw_monitor', True)


def test_discovery_probes_all_declared_native_monitor_endpoints(mixer, monkeypatch):
    from ffado_webmixer import interrogate
    import dbus
    inventory = {c['path']: c['kind'] for c in mixer.device['controls']}
    device = {**mixer.device, 'controls': [], 'matrices': [], 'routers': []}

    def inspect(_bus, p):
        if p not in inventory:
            raise dbus.exceptions.DBusException('not exposed')
        return {interrogate.NS + inventory[p]}, []

    monkeypatch.setattr(interrogate, 'introspect', inspect)
    monkeypatch.setattr(interrogate, 'try_call', lambda *args, **kwargs: kwargs.get('default'))
    interrogate.inventory_profile(object(), device, mixer.profile)
    mixer.device = device
    assert mixer.dice_monitor_description() == {'dim': True, 'mute': True, 'hw_monitor': True}


def test_api_validation_and_broadcast(mixer):
    app = Flask(__name__)
    events = []
    mixer_routes.register(app, mixer, mixer.describe(), mixer.config, events.append)
    client = app.test_client()
    assert not client.get('/api/dice-monitoring').json['hw_monitor']
    response = client.post('/api/dice-monitoring', json={'control': 'hw_monitor', 'value': True})
    assert response.status_code == 200 and response.json['hw_monitor']
    assert events == [{'type': 'dice-monitoring'}]
    assert client.post('/api/dice-monitoring', json=[]).status_code == 400
    assert client.post('/api/dice-monitoring', json={'control': 'hw_monitor', 'value': 'false'}).status_code == 400
    response = client.post('/api/output', json={'out': 'dice/dim', 'control': 'mute', 'value': True})
    assert response.status_code == 200
    assert client.get('/api/output?out=dice/dim').json['mute']
    response = client.post('/api/dice-monitoring', json={'control': 'mute', 'value': True})
    assert response.status_code == 200 and response.json['mute']
    assert mixer.helper.values[path(mixer, 'GlobalMute/State')] is True
    assert client.post('/api/dice-monitoring', json={'control': 'mute', 'value': 1}).status_code == 400
    assert client.post('/api/output', json={'out': 'dice/master', 'control': 'fader', 'value': 50}).status_code == 400


@pytest.mark.parametrize('linked', [False, True])
def test_line_unity_uses_its_native_scale_independently_of_bus_gain(mixer, linked):
    if linked:
        mixer.config.settings['stereo_outputs'] = ['line/1']
    outputs = {out['id']: out for out in mixer.describe()['outputs']}
    line = outputs['line/1']['gain_scale']
    bus = outputs['bus/0']['gain_scale']
    assert line['mode'] == 'dice_line'
    assert (line['min_db'], line['max_db'], line['step_db']) == (-40, 0, 1)
    assert (bus['min_db'], bus['max_db']) == (-60, 6)
    # The UI maps 0 dB to 100% for physical attenuation, 90.909...% for buses.
    for out, scale in [('line/1', line), ('bus/0', bus)]:
        unity = 100 * (0 - scale['min_db']) / (scale['max_db'] - scale['min_db'])
        mixer.write_linked_output(out, 'fader', unity)
        actual = mixer.read_linked_output(out)['level']
        assert scale['min_db'] + actual * (scale['max_db'] - scale['min_db']) / 100 == pytest.approx(0)
    assert mixer.helper.values[path(mixer, 'LineOut/Volume1')] == 0
    if linked:
        assert mixer.helper.values[path(mixer, 'LineOut/Volume2')] == 0
