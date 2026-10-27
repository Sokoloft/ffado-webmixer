"""Pan every Pro 40 matrix input, including inputs initially at silence."""
import contextlib
import io
from pathlib import Path
import subprocess

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from test_arbitrary_stereo_pairs import edit
from test_stereo_group_mute import api


def fixture(model='saffirepro40'):
    config = Config(None)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer(model, config)
    return mixer, config


@pytest.mark.parametrize('model', ['saffirepro40', 'saffirepro401'])
@pytest.mark.parametrize('bus', [0, 2, 14])
def test_every_input_can_be_raised_then_panned_on_each_bus_pair(model, bus):
    mixer, config = fixture(model)
    config.settings['stereo_buses'] = [bus]
    body = {'strip': '', 'control': 'fader', 'value': 70, 'mix': bus}
    path = mixer.roles['fader'][0]
    with contextlib.redirect_stdout(io.StringIO()):
        for app, _ in api(mixer, config, body, mix=bus):
            for col in mixer._visible_cols():
                strip = f'ch/{col:02d}'
                edit(mixer, col, bus, None)
                edit(mixer, col, bus + 1, None)
                assert app.state()[strip]['pan_available'] is False
                body.update(strip=strip, control='fader', value=70)
                assert app.set_value() == {'ok': True}
                assert app.state()[strip]['pan_available'] is True
                for position in (-1, -.5, 0, .5, 1, 0):
                    before = dict(mixer.helper.cells)
                    body.update(control='pan', value=position)
                    assert app.set_value() == {'ok': True}
                    assert app.state()[strip]['pan'] == pytest.approx(position, abs=.001)
                    points = {(path, *mixer._coordinates(leg, col)) for leg in (bus, bus + 1)}
                    assert all(value == mixer.helper.cells[key]
                               for key, value in before.items() if key not in points)


@pytest.mark.parametrize('leg', [0, 1])
@pytest.mark.parametrize('after_write', [False, True])
def test_mono_pan_failure_restores_both_legs(leg, after_write):
    mixer, config = fixture()
    config.settings['stereo_buses'] = [0]
    edit(mixer, 6, 0, -6)
    edit(mixer, 6, 1, -9)
    before = dict(mixer.helper.cells)
    original = mixer.helper.set_cell
    failed = False

    def fail_once(path, row, col, value):
        nonlocal failed
        if not failed and (row, col) == mixer._coordinates(leg, 6):
            failed = True
            if after_write:
                original(path, row, col, value)
            raise IOError('pan leg timed out')
        return original(path, row, col, value)

    mixer.helper.set_cell = fail_once
    body = {'strip': 'ch/06', 'control': 'pan', 'value': .5, 'mix': 0}
    with contextlib.redirect_stdout(io.StringIO()):
        for app, events in api(mixer, config, body):
            response, status = app.set_value()
            assert status == 500 and 'timed out' in response['error']
            assert mixer.helper.cells == before
            assert not events
            assert app.set_value() == {'ok': True}


@pytest.mark.parametrize('col,value', [(-1, 0), (999, 0), (1, 2), (1, float('nan'))])
def test_invalid_pan_never_writes(col, value):
    mixer, _ = fixture()
    before = dict(mixer.helper.cells)
    with pytest.raises(ValueError):
        mixer.write_bus_balance(0, col, value)
    assert mixer.helper.cells == before


def test_pan_cannot_turn_silence_sentinels_into_an_audible_route():
    mixer, _ = fixture()
    path = mixer.roles['fader'][0]
    for bus in (0, 1):
        mixer.helper.cells[path, *mixer._coordinates(bus, 6)] = 16
    before = dict(mixer.helper.cells)
    with pytest.raises(ValueError, match='Raise this channel fader'):
        mixer.write_bus_balance(0, 6, -1)
    assert mixer.helper.cells == before


@pytest.mark.parametrize('model,native_max', [('saffirepro40', 65535), ('fireface400', 32768)])
def test_pan_never_writes_a_coefficient_above_the_device_limit(model, native_max):
    mixer, _ = fixture(model)
    path = mixer.roles['fader'][0]
    for bus in (0, 1):
        mixer.helper.cells[path, *mixer._coordinates(bus, 6)] = native_max
    before = dict(mixer.helper.cells)
    with pytest.raises(ValueError, match='native mixer gain range'):
        mixer.write_bus_balance(0, 6, -1)
    assert mixer.helper.cells == before


def test_pro40_pan_browser_state():
    result = subprocess.run(['node', str(Path(__file__).with_name('pro40_all_input_pan_ui_test.cjs'))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
