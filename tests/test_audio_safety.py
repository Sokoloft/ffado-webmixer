"""Regression tests for routing/stereo writes that could otherwise leave live audio changed.

Uses simulated D-Bus routing and demo-mixer controls, not a FireWire device.
"""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.demo import DemoMixer
from test_router_strip_labels import simulated_router
from test_stereo_group_mute import api

DEST = 'Mixer/In:01'
OLD = 'Anlg/In:01'
NEW = '1394/In:01'


@pytest.mark.parametrize('failure', ['return_false', 'raise_before', 'raise_after', 'bad_readback'])
def test_router_restores_previous_connection_after_failure(failure):
    mixer, _, routes, _ = simulated_router()
    base = mixer.helper.router_call
    attempts = []
    bad_readback = False

    def unreliable(path, method, *args):
        nonlocal bad_readback
        if method == 'setConnectionState':
            source, dest, enabled = args
            attempts.append((source, enabled))
            if source == NEW and enabled:
                if failure == 'raise_before':
                    raise IOError('connection exception before write')
                if failure == 'return_false':
                    return False
                if failure == 'raise_after':
                    base(path, method, *args)
                    raise IOError('connection exception after write')
                if failure == 'bad_readback':
                    base(path, method, *args)
                    bad_readback = True
                    return True
        if method == 'getSourceForDestination' and bad_readback:
            bad_readback = False
            return 'SPDIF/In:01'  # device reports unexpected route on first read
        return base(path, method, *args)

    mixer.helper.router_call = unreliable
    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises((ValueError, IOError), match='connection|refused|readback'):
            mixer.router_set(DEST, NEW)
    assert routes[DEST] == OLD
    assert mixer._router_input_sources[DEST] == OLD
    assert (OLD, True) in attempts
    if failure == 'raise_after':
        assert (NEW, False) in attempts


def test_router_restores_mute_after_connect_raises_after_write():
    mixer, _, routes, attempts = simulated_router()
    routes[DEST] = 'Mute:00'
    base = mixer.helper.router_call

    def unreliable(path, method, *args):
        if method == 'setConnectionState' and args == (NEW, DEST, True):
            base(path, method, *args)
            raise IOError('write then timeout')
        return base(path, method, *args)

    mixer.helper.router_call = unreliable
    with pytest.raises(IOError, match='timeout'):
        mixer.router_set(DEST, NEW)
    assert routes[DEST] == 'Mute:00'
    assert not any(call[1] == ('Mute:00', DEST, True) for call in attempts)


def test_router_rollback_failure_is_explicit_and_does_not_update_cache():
    mixer, _, routes, _ = simulated_router()
    mixer.router_snapshot()
    base = mixer.helper.router_call

    def unreliable(path, method, *args):
        if method == 'setConnectionState' and args == (NEW, DEST, True):
            raise IOError('new connection fails')
        if method == 'setConnectionState' and args == (OLD, DEST, True):
            raise IOError('restore fails')
        return base(path, method, *args)

    mixer.helper.router_call = unreliable
    with pytest.raises(RuntimeError, match='rollback may be incomplete'):
        mixer.router_set(DEST, NEW)
    assert routes[DEST].startswith('Mute:')
    assert mixer._router_input_sources[DEST] == OLD  # stale cache, not a verified new route


@pytest.mark.parametrize('control, old, new', [
    ('fader', 70, 88), ('mute', False, True), ('gain', 10, 25), ('invert', False, True),
])
def test_linked_generic_controls_roll_back_after_second_leg_changes_then_throws(control, old, new):
    mixer = DemoMixer()
    config = Config(None)
    config.link('ch/01', 'ch/04', 0)
    mixer.write(0, 'ch/01', control, old)
    mixer.write(0, 'ch/04', control, old)
    original_write = mixer.write
    failed = False

    def unreliable(mix, channel, role, value):
        nonlocal failed
        original_write(mix, channel, role, value)
        if channel == 'ch/04' and role == control and value == new and not failed:
            failed = True
            raise IOError('right channel write timed out')

    mixer.write = unreliable
    body = {'strip': 'ch/01', 'mix': 0, 'control': control, 'value': new}
    for app, events in api(mixer, config, body):
        response, code = app.set_value()
        assert code == 500 and 'timed out' in response['error']
        assert mixer.read_mix(0)['ch/01'][control] == old
        assert mixer.read_mix(0)['ch/04'][control] == old
        assert events == []
        assert app.set_value() == {'ok': True}  # retry after failure succeeds
        assert mixer.read_mix(0)['ch/01'][control] == new
        assert mixer.read_mix(0)['ch/04'][control] == new
        assert len(events) == 1


def test_linked_gain_can_skip_an_input_without_that_control():
    mixer = DemoMixer()
    config = Config(None)
    config.link('ch/01', 'ch/04', 0)
    old_read = mixer.read_mix

    def no_right_gain(mix):
        result = old_read(mix)
        del result['ch/04']['gain']
        return result

    mixer.read_mix = no_right_gain
    body = {'strip': 'ch/01', 'mix': 0, 'control': 'gain', 'value': 20}
    for app, _ in api(mixer, config, body):
        assert app.set_value() == {'ok': True}
    assert mixer.chan['ch/01']['gain'] == 20
    assert mixer.chan['ch/04']['gain'] == 30  # unsupported side untouched


def test_linked_write_reports_if_rollback_itself_fails():
    mixer = DemoMixer()
    config = Config(None)
    config.link('ch/01', 'ch/04', 0)
    before = mixer.read_mix(0)
    old_left, old_right = before['ch/01']['fader'], before['ch/04']['fader']
    original_write = mixer.write

    def unreliable(mix, channel, role, value):
        if channel == 'ch/04' and role == 'fader' and value == 92:
            raise IOError('right failed')
        if channel == 'ch/01' and role == 'fader' and value == old_left:
            raise IOError('left restore failed')
        return original_write(mix, channel, role, value)

    mixer.write = unreliable
    body = {'strip': 'ch/01', 'mix': 0, 'control': 'fader', 'value': 92}
    for app, events in api(mixer, config, body):
        response, code = app.set_value()
        assert code == 500
        assert 'rollback may be incomplete' in response['error']
        assert 'ch/01' in response['error']
        assert not events
    assert mixer.read_mix(0)['ch/01']['fader'] == 92
    assert mixer.read_mix(0)['ch/04']['fader'] == old_right


@pytest.mark.parametrize('model', ['motuultralite', 'saffirepro40'])
def test_source_defined_matrix_pair_restores_original_levels_after_failure(model):
    """Exercise the actual generic /api/set path against native FFADO profile models."""
    from ffado_webmixer.debug_backend import make_debug_mixer
    config = Config(None)
    config.link('ch/00', 'ch/01', 0)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer(model, config)
        path = mixer.roles['fader'][0]
        old = (mixer._get_cell(path, 0, 0), mixer._get_cell(path, 0, 1))
        original_set = mixer.helper.set_cell
        failed = False

        def partial_write(p, row, col, raw):
            nonlocal failed
            original_set(p, row, col, raw)
            if not failed and (row, col) == mixer._coordinates(0, 1):
                failed = True
                raise IOError('simulated matrix second write timeout')

        mixer.helper.set_cell = partial_write
        body = {'strip': 'ch/00', 'mix': 0, 'control': 'fader', 'value': 45}
        for app, events in api(mixer, config, body):
            response, code = app.set_value()
            assert code == 500 and 'timeout' in response['error']
            assert (mixer._get_cell(path, 0, 0), mixer._get_cell(path, 0, 1)) == old
            assert not events


def test_router_disconnect_exception_after_hardware_change_restores_only_target():
    """A D-Bus timeout can occur *after* the old route was disconnected."""
    mixer, _, routes, calls = simulated_router()
    before = dict(routes)
    original = mixer.helper.router_call
    failed = False

    def break_during_disconnect(path, method, *args):
        nonlocal failed
        if (not failed and method == 'setConnectionState'
                and args == (OLD, DEST, False)):
            failed = True
            original(path, method, *args)  # real device has already changed
            raise IOError('disconnect acknowledged too late')
        return original(path, method, *args)

    mixer.helper.router_call = break_during_disconnect
    mixer.router_snapshot()
    with pytest.raises(IOError, match='disconnect acknowledged too late'):
        mixer.router_set(DEST, NEW)
    assert routes == before, 'rollback must not disturb other router destinations'
    assert mixer._router_input_sources[DEST] == OLD
    assert not any(method == 'setConnectionState' and args[:2] == (NEW, DEST)
                   for method, args in calls), 'new connection must never be attempted'


def test_first_stereo_leg_failure_after_write_restores_and_does_not_touch_partner():
    """A first-leg timeout must not attempt the right leg or broadcast success."""
    mixer = DemoMixer()
    config = Config(None)
    config.link('ch/01', 'ch/04', 2)
    old_left, old_right = 33, 68
    mixer.write(2, 'ch/01', 'fader', old_left)
    mixer.write(2, 'ch/04', 'fader', old_right)
    write = mixer.write
    calls = []
    failed = False

    def time_out_after_first_write(mix, channel, control, value):
        nonlocal failed
        calls.append((mix, channel, control, value))
        write(mix, channel, control, value)
        if channel == 'ch/01' and value == 91 and not failed:
            failed = True
            raise OSError('first channel timed out')

    mixer.write = time_out_after_first_write
    payload = {'strip': 'ch/01', 'mix': 2, 'control': 'fader', 'value': 91}
    for app, events in api(mixer, config, payload):
        response, status = app.set_value()
        assert status == 500 and 'first channel timed out' in response['error']
        assert not events
    assert mixer.read_mix(2)['ch/01']['fader'] == old_left
    assert mixer.read_mix(2)['ch/04']['fader'] == old_right
    assert (2, 'ch/04', 'fader', 91) not in calls
    assert (2, 'ch/01', 'fader', old_left) in calls
