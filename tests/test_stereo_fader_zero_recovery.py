"""Stereo output bus faders must never get stranded at -infinity.

Tests use real source-derived DICE/RME models with fake D-Bus hardware.
They do not establish behavior on physical FireWire devices.
"""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.gain import db_to_raw, raw_to_ui
from test_stereo_group_mute import api


def mixer_and_config(model='saffirepro40'):
    config = Config(None)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer(model, config)
    return mixer, config


def zero(mixer, *cols):
    for col in cols:
        for bus in (0, 1):
            mixer.matrix_set(col, bus, db=None, use_db=True)


def levels(mixer, col):
    path = mixer.roles['fader'][0]
    return tuple(mixer._get_cell(path, bus, col) for bus in (0, 1))


@pytest.mark.parametrize('model', ['saffirepro40', 'saffirepro401', 'profire2626', 'profire610'])
def test_mono_input_fader_explicitly_activates_centered_stereo_from_silence(model):
    mixer, config = mixer_and_config(model)
    zero(mixer, 2)
    before_other = levels(mixer, 3)
    before_next_bus = mixer._get_cell(mixer.roles['fader'][0], 2, 2)
    config.settings['stereo_buses'] = [0]
    payload = {'strip': 'ch/02', 'mix': 0, 'control': 'fader', 'value': 80}
    for app, events in api(mixer, config, payload):
        assert app.set_value() == {'ok': True}
        a, b = levels(mixer, 2)
        assert a == b and a > 16
        assert levels(mixer, 3) == before_other
        assert mixer._get_cell(mixer.roles['fader'][0], 2, 2) == before_next_bus
        assert app.state()['ch/02']['pan_available']
        assert app.state()['ch/02']['pan'] == 0
        assert events and events[-1]['control'] == 'fader'


def test_pair_at_infinity_raises_only_its_two_diagonals():
    mixer, config = mixer_and_config()
    zero(mixer, 1, 4)
    before_other = levels(mixer, 3)
    config.settings['stereo_buses'] = [0]
    config.link('ch/01', 'ch/04', 0)  # input 2 = Left; input 5 = Right
    payload = {'strip': 'ch/01', 'mix': 0, 'control': 'fader', 'value': 91}
    for app, _ in api(mixer, config, payload):
        assert app.set_value() == {'ok': True}
        a, b = levels(mixer, 1)
        c, d = levels(mixer, 4)
        assert a > 16 and mixer._is_zero(b)
        assert d > 16 and mixer._is_zero(c)
        assert a == d
        assert levels(mixer, 3) == before_other
        assert app.state()['ch/01']['pan_available']
        assert app.state()['ch/01']['pan'] == 0
        payload['value'] = 0
        assert app.set_value() == {'ok': True}
        assert all(mixer._is_zero(x) for x in levels(mixer, 1) + levels(mixer, 4))
        payload['value'] = 65
        assert app.set_value() == {'ok': True}
        a, b = levels(mixer, 1)
        c, d = levels(mixer, 4)
        assert a == d and a > 16
        assert mixer._is_zero(b) and mixer._is_zero(c)


def test_reversed_order_preserved_when_reviving_stereo_pair():
    mixer, config = mixer_and_config()
    zero(mixer, 1, 4)
    config.settings['stereo_buses'] = [0]
    config.link('ch/04', 'ch/01', 0)  # input 5 = Left; input 2 = Right
    payload = {'strip': 'ch/04', 'mix': 0, 'control': 'fader', 'value': 80}
    for app, _ in api(mixer, config, payload):
        assert app.set_value() == {'ok': True}
        a, b = levels(mixer, 4)
        c, d = levels(mixer, 1)
        assert a == d and a > 16
        assert mixer._is_zero(b) and mixer._is_zero(c)


def test_existing_mono_pan_routes_are_scaled_not_rewired():
    mixer, _ = mixer_and_config()
    zero(mixer, 2)
    mixer.matrix_set(2, 0, db=-1, use_db=True)
    mixer.matrix_set(2, 1, db=None, use_db=True)
    mixer.write_stereo_level(0, 2, 60)
    a, b = levels(mixer, 2)
    assert a > 16 and mixer._is_zero(b)
    mixer.write_stereo_level(0, 2, 0)
    assert all(mixer._is_zero(x) for x in levels(mixer, 2))
    mixer.write_stereo_level(0, 2, 75)
    a, b = levels(mixer, 2)
    assert a > 16 and mixer._is_zero(b)


def test_external_edit_while_zero_discards_old_stereo_ratio():
    mixer, _ = mixer_and_config()
    zero(mixer, 2)
    mixer.matrix_set(2, 0, db=-1, use_db=True)
    mixer.write_stereo_level(0, 2, 0)
    # Someone reconnects only the other bus through the matrix editor.
    mixer.matrix_set(2, 1, db=-12, use_db=True)
    mixer.write_stereo_level(0, 2, 75)
    a, b = levels(mixer, 2)
    assert mixer._is_zero(a) and b > 16


def test_invalid_input_and_silence_move_do_not_activate_routes():
    mixer, _ = mixer_and_config()
    zero(mixer, 2)
    mixer.write_stereo_level(0, 2, 0)
    assert all(mixer._is_zero(x) for x in levels(mixer, 2))
    for channels in ([(2, 'bad')], [(2, 'left'), (2, 'right')], [(99, 'mono')]):
        with pytest.raises(ValueError):
            mixer.write_stereo_levels(0, channels, 85)
    assert all(mixer._is_zero(x) for x in levels(mixer, 2))


def test_second_leg_failure_rolls_back_group_without_losing_other_routes():
    mixer, _ = mixer_and_config()
    zero(mixer, 2)
    path = mixer.roles['fader'][0]
    original = mixer.helper.set_cell
    failed = {'once': False}
    def reject_second_leg(p, row, col, val):
        if not failed['once'] and (row, col) == mixer._coordinates(1, 2) and val > 16:
            failed['once'] = True
            raise IOError('simulated right leg failed')
        return original(p, row, col, val)
    mixer.helper.set_cell = reject_second_leg
    with pytest.raises(IOError, match='right leg failed'):
        mixer.write_stereo_level(0, 2, 80)
    assert all(mixer._is_zero(x) for x in levels(mixer, 2))
    # Retry after the failed write must work; no stale pair memory remains.
    mixer.write_stereo_level(0, 2, 80)
    a, b = levels(mixer, 2)
    assert a == b and a > 16


def test_pair_failure_rolls_back_both_channels():
    mixer, _ = mixer_and_config()
    zero(mixer, 1, 4)
    old = {col: levels(mixer, col) for col in (1, 4)}
    original = mixer.helper.set_cell
    failed = {'once': False}
    def fail_right(p, row, col, val):
        if not failed['once'] and (row, col) == mixer._coordinates(1, 4) and val > 16:
            failed['once'] = True
            raise IOError('simulated pair right failure')
        return original(p, row, col, val)
    mixer.helper.set_cell = fail_right
    with pytest.raises(IOError, match='pair right failure'):
        mixer.write_stereo_levels(0, [(1, 'left'), (4, 'right')], 80)
    for col in (1, 4):
        assert all(mixer._is_zero(v) for v in levels(mixer, col))


def test_original_matrix_route_unchanged_when_only_buses_are_linked():
    mixer, config = mixer_and_config()
    zero(mixer, 2)
    before = dict(mixer.helper.cells)
    config.settings['stereo_buses'] = [0]
    assert dict(mixer.helper.cells) == before


def test_pair_created_after_mono_fader_off_does_not_restore_mono_cross_routes():
    mixer, _ = mixer_and_config()
    zero(mixer, 1, 4)
    # Both channels were previously running centered MONO, then faded out.
    mixer.write_stereo_level(0, 1, 75)
    mixer.write_stereo_level(0, 4, 75)
    mixer.write_stereo_level(0, 1, 0)
    mixer.write_stereo_level(0, 4, 0)
    assert all(mixer._is_zero(v) for v in levels(mixer, 1) + levels(mixer, 4))
    # Now pair them in the UI. Old mono restore data must not create the
    # inappropriate cross-routes after the paired fader is raised.
    mixer.write_stereo_levels(0, [(1, 'left'), (4, 'right')], 75)
    a, b = levels(mixer, 1)
    c, d = levels(mixer, 4)
    assert a > 16 and d > 16
    assert mixer._is_zero(b) and mixer._is_zero(c)


def test_unpair_after_stereo_fader_off_defaults_to_centered_mono():
    mixer, _ = mixer_and_config()
    zero(mixer, 1)
    mixer.write_stereo_levels(0, [(1, 'left')], 65)
    mixer.write_stereo_levels(0, [(1, 'left')], 0)
    mixer.write_stereo_levels(0, [(1, 'mono')], 65)
    a, b = levels(mixer, 1)
    assert a == b and a > 16
