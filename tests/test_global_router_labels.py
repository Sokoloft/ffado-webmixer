"""Live DICE router-source labels must agree across mixer and matrix views."""
import contextlib
import io

import pytest

from test_router_strip_labels import simulated_router


@pytest.mark.parametrize('model', ['saffirepro40', 'saffirepro26', 'profire2626'])
def test_matrix_labels_follow_verified_routes_but_keep_stable_matrix_inputs(model):
    mixer, _config, routes, calls = simulated_router(model)
    raw_inputs = list(mixer.columns)
    with contextlib.redirect_stdout(io.StringIO()):
        snapshot = mixer.matrix_snapshot()
        assert snapshot['inputs'] == raw_inputs
        assert snapshot['input_labels'][:2] == ['Anlg/In:01', 'Mic/Lin/In:03']
        assert snapshot['input_labels'][2:] == raw_inputs[2:]
        assert mixer.read_mix(0)['ch/00']['input'] == snapshot['input_labels'][0]
        before_levels = [list(row) for row in snapshot['values']]
        mixer.router_set('Mixer/In:01', '1394/In:01')
        snapshot = mixer.matrix_snapshot()
        assert snapshot['input_labels'][0] == '1394/In:01'
        assert snapshot['inputs'] == raw_inputs
        assert snapshot['values'] == before_levels
        mixer.router_set('Mixer/In:01', '')
        snapshot = mixer.matrix_snapshot()
        assert snapshot['input_labels'][0] == 'Disconnected'
        assert mixer.read_mix(0)['ch/00']['input'] == 'Disconnected'
        # Matrix row is still addressable by its original numeric column.
        assert snapshot['inputs'][0] == raw_inputs[0]
        assert snapshot['values'] == before_levels
        assert not any(name == 'setConnectionState' for name, _ in calls[-3:])


def test_matrix_refresh_picks_up_external_router_changes():
    mixer, _config, routes, _calls = simulated_router()
    with contextlib.redirect_stdout(io.StringIO()):
        first = mixer.matrix_snapshot()
        routes['Mixer/In:02'] = 'Mute:00'     # changed in ffado-mixer
        next_snapshot = mixer.matrix_snapshot()
        assert first['input_labels'][1] == 'Mic/Lin/In:03'
        assert next_snapshot['input_labels'][1] == 'Disconnected'
        assert mixer.read_mix(0)['ch/01']['input'] == 'Disconnected'
        routes['Mixer/In:02'] = '1394/In:02'
        assert mixer.matrix_snapshot()['input_labels'][1] == '1394/In:02'


def test_output_only_routes_do_not_change_matrix_input_labels():
    mixer, _config, routes, _calls = simulated_router()
    with contextlib.redirect_stdout(io.StringIO()):
        before = mixer.matrix_snapshot()['input_labels']
        routes['Line/Out:01'] = '1394/In:01'
        assert mixer.matrix_snapshot()['input_labels'] == before


def test_disconnected_cache_survives_failed_router_refresh():
    mixer, _config, routes, _calls = simulated_router()
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.router_set('Mixer/In:01', '')
        normal_call = mixer.helper.router_call
        def broken(path, method, *args):
            if method == 'getDestinationNames':
                raise IOError('Transient D-Bus error')
            return normal_call(path, method, *args)
        mixer.helper.router_call = broken
        snapshot = mixer.matrix_snapshot()
        assert snapshot['input_labels'][0] == 'Disconnected'
        assert snapshot['values']


def test_device_without_crossbar_keeps_original_matrix_labels():
    from ffado_webmixer.config import Config
    from ffado_webmixer.debug_backend import make_debug_mixer
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer('motuultralite', Config(None))
        snapshot = mixer.matrix_snapshot()
        assert snapshot['input_labels'] == snapshot['inputs']
