"""Saffire PRO 40 / ProFire DICE matrix mute regressions (offline FFADO simulation).

These tests exercise the actual profile-driven Mixer and /api/set path, but
hardware routing outside the EAP mixer still requires a real device to test.
"""
import contextlib
import importlib.util
import io
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from test_soft_mute_recovery import UnreliableHelper

ROOT = Path(__file__).resolve().parents[1]


def mixer_for(tmp_path, model='saffirepro40'):
    config = Config(tmp_path / 'devices' / f'{model}.json')
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer(model, config)
    mixer.helper = UnreliableHelper(mixer.helper)
    mixer.attach_mute_recovery()
    return mixer, config


def api(mixer, config, body=None, mix=0):
    body = body or {}
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    flask.request = types.SimpleNamespace(
        get_json=lambda force=True: body,
        args=types.SimpleNamespace(get=lambda name, default=None, type=None: mix),
    )
    class App:
        def get(self, path):
            def wrapper(fn):
                if path == '/api/state': self.state = fn
                return fn
            return wrapper
        def post(self, path):
            def wrapper(fn):
                if path == '/api/set': self.set_value = fn
                return fn
            return wrapper
    events = []
    with patch.dict(sys.modules, {'flask': flask}):
        spec = importlib.util.spec_from_file_location('ffado_webmixer.api._group_mute_test',
                                                      ROOT / 'src/ffado_webmixer/api/mixer.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app = App()
        module.register(app, mixer, {}, config, events.append)
        yield app, events


@pytest.mark.parametrize('model', ['saffirepro40', 'saffirepro401', 'profire2626', 'profire610'])
def test_model_single_mute_does_not_affect_other_buses(tmp_path, model):
    mixer, _ = mixer_for(tmp_path, model)
    path = mixer.roles['fader'][0]
    original = mixer._get_cell(path, 0, 1)
    neighbor = mixer._get_cell(path, 1, 1)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0,), (1,), True)
    assert mixer._is_zero(mixer._get_cell(path, 0, 1))
    assert mixer._get_cell(path, 1, 1) == neighbor
    assert mixer.read_mix(0)['ch/01']['mute']
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0,), (1,), False)
    assert mixer._get_cell(path, 0, 1) == original
    assert not mixer.read_mix(0)['ch/01']['mute']


def test_linked_input_and_stereo_bus_mute_all_four_routes(tmp_path):
    mixer, config = mixer_for(tmp_path)
    config.link('ch/01', 'ch/04', 0)  # 2 Left / 5 Right
    config.settings['stereo_buses'] = [0]
    path = mixer.roles['fader'][0]
    targets = {(bus, col) for bus in (0, 1) for col in (1, 4)}
    before = {key: mixer._get_cell(path, *key) for key in targets}
    outside = mixer._get_cell(path, 2, 1)
    body = {'strip': 'ch/01', 'mix': 0, 'control': 'mute', 'value': True}
    for app, events in api(mixer, config, body):
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        assert set(mixer._matrix_mutes) == targets
        assert all(mixer._is_zero(mixer._get_cell(path, *key)) for key in targets)
        assert mixer._get_cell(path, 2, 1) == outside
        state = app.state()
        assert state['ch/01']['mute']
        assert not state['ch/01']['mute_partial']
        assert len(events) == 1
        body['value'] = False
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        assert {key: mixer._get_cell(path, *key) for key in targets} == before
        assert not app.state()['ch/01']['mute']
        assert not mixer._matrix_mutes
        assert not mixer._user_mutes


def test_partial_existing_mute_is_reported_and_completed(tmp_path):
    mixer, config = mixer_for(tmp_path)
    config.link('ch/01', 'ch/04', 0)
    config.settings['stereo_buses'] = [0]
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write(0, 'ch/01', 'mute', True)  # old versions only muted the left route
    body = {'strip': 'ch/01', 'mix': 0, 'control': 'mute', 'value': True}
    for app, _ in api(mixer, config, body):
        state = app.state()
        assert not state['ch/01']['mute']
        assert state['ch/01']['mute_partial']
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        assert app.state()['ch/01']['mute']
        assert all((bus, col) in mixer._user_mutes for bus in (0, 1) for col in (1, 4))


def test_stereo_bus_mute_without_input_link_suppresses_both_rows(tmp_path):
    mixer, config = mixer_for(tmp_path)
    config.settings['stereo_buses'] = [0]
    body = {'strip': 'ch/03', 'mix': 0, 'control': 'mute', 'value': True}
    for app, _ in api(mixer, config, body):
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        assert (0, 3) in mixer._user_mutes
        assert (1, 3) in mixer._user_mutes
        assert app.state()['ch/03']['mute']


def test_group_muting_failure_rolls_back_all_matrix_legs(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    path = mixer.roles['fader'][0]
    targets = [(0, 1), (0, 4), (1, 1), (1, 4)]
    before = {key: mixer._get_cell(path, *key) for key in targets}
    mixer.helper.fail = lambda row, col, val: (row, col, val) == (4, 0, 0)  # DICE coords swapped
    with pytest.raises(RuntimeError, match='hardware refused'):
        with contextlib.redirect_stdout(io.StringIO()):
            mixer.write_group_mute((0, 1), (1, 4), True)
    assert {key: mixer._get_cell(path, *key) for key in targets} == before
    assert not mixer._matrix_mutes
    assert not mixer._user_mutes
    assert not mixer._recovery_journal.path.exists()


def test_group_unmute_failure_restores_mute_state_and_saved_levels(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0, 1), (1, 4), True)
    saved = dict(mixer._matrix_mutes)
    mixer.helper.fail = lambda row, col, val: (row, col, val) == (4, 0, 16384)
    with pytest.raises(RuntimeError, match='hardware refused'):
        with contextlib.redirect_stdout(io.StringIO()):
            mixer.write_group_mute((0, 1), (1, 4), False)
    assert mixer._matrix_mutes == saved
    assert mixer._recovery_journal.load() == saved
    assert all(mixer._is_zero(mixer._get_cell(mixer.roles['fader'][0], *key)) for key in saved)
    mixer.helper.fail = None
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0, 1), (1, 4), False)
    assert not mixer._matrix_mutes


def test_native_silence_sentinel_is_not_external_override(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    helper = mixer.helper
    original = helper.set_cell
    def ffado_sentinel(path, row, col, val):
        return original(path, row, col, 16 if val == 0 else val)
    helper.set_cell = ffado_sentinel
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0,), (1,), True)
    assert mixer._get_cell(mixer.roles['fader'][0], 0, 1) == 16
    assert mixer.read_mix(0)['ch/01']['mute']
    assert (0, 1) in mixer._matrix_mutes
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0,), (1,), False)
    assert mixer._get_cell(mixer.roles['fader'][0], 0, 1) == 16384
    assert not mixer._matrix_mutes


def test_already_silent_cell_does_not_claim_user_pressed_mute(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    path = mixer.roles['fader'][0]
    mixer.helper.real.cells[(path, 1, 0)] = 0  # profile's DICE transposed coordinates
    state = mixer.read_mix(0)['ch/01']
    assert not state['mute']
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0,), (1,), True)
    assert mixer.read_mix(0)['ch/01']['mute']
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0,), (1,), False)
    assert mixer._get_cell(path, 0, 1) == 0  # never create a disconnected route


def test_group_mute_preserves_preexisting_user_mutes_and_solo(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write(0, 'ch/02', 'mute', True)
        mixer.write(0, 'ch/01', 'solo', True)
        # Mixing can be muted while another channel is soloed. The user's
        # explicit mute must survive both grouped mute and solo cleanup.
        mixer.write_group_mute((0,), (1, 4), True)
        mixer.write_group_mute((0,), (1, 4), False)
        mixer.write(0, 'ch/01', 'solo', False)
    assert (0, 2) in mixer._user_mutes
    assert mixer._is_zero(mixer._get_cell(mixer.roles['fader'][0], 0, 2))
    assert mixer._get_cell(mixer.roles['fader'][0], 0, 4) == 16384


def test_group_mute_rejects_bad_targets_and_invalid_boolean(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    with pytest.raises(ValueError, match='target'):
        mixer.write_group_mute((-1,), (2,), True)
    with pytest.raises(ValueError, match='target'):
        mixer.write_group_mute((0,), (999,), True)
    with pytest.raises(ValueError, match='true or false'):
        mixer.write_group_mute((0,), (2,), 1)
    assert not mixer._matrix_mutes


def test_group_mute_does_not_enable_diagonal_or_cross_routes(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    path = mixer.roles['fader'][0]
    # Explicitly disconnected cross-route is never made audible by mute/unmute.
    mixer.helper.real.cells[(path, 1, 0)] = 0
    mixer.helper.real.cells[(path, 4, 1)] = 0
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0, 1), (1, 4), True)
        mixer.write_group_mute((0, 1), (1, 4), False)
    assert mixer._get_cell(path, 0, 1) == 0
    assert mixer._get_cell(path, 1, 4) == 0
    assert mixer._get_cell(path, 0, 4) == 16384
    assert mixer._get_cell(path, 1, 1) == 16384
