"""Regression: PRO 40 ordered stereo inputs, safe pan writes and compact UI names."""
import contextlib
import io
from pathlib import Path

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from test_arbitrary_stereo_pairs import edit, stub_stereo_handler
from test_stereo_group_mute import api


def saffire():
    with contextlib.redirect_stdout(io.StringIO()):
        return make_debug_mixer('saffirepro40', Config(None))


def pair_fixture():
    mixer, config = saffire(), Config(None)
    for col in (1, 4):
        for bus in (0, 1):
            edit(mixer, col, bus, None)
    edit(mixer, 1, 0, -0.4)
    # A common PRO 40 mono setup: both faders previously sent to Bus 1.
    # The right channel is not yet connected to stereo Bus 2.
    edit(mixer, 4, 0, -7)
    config.settings['stereo_buses'] = [0]
    response = stub_stereo_handler(mixer, config)({
        'action': 'link', 'dragged': 'ch/01', 'target': 'ch/04'
    })
    assert response['ok']
    return mixer, config


def test_pro40_link_does_not_change_matrix_and_pan_completes_missing_right_diagonal():
    mixer, config = pair_fixture()
    path = mixer.roles['fader'][0]
    original_left = mixer._get_cell(path, 0, 1)
    original_cross = mixer._get_cell(path, 0, 4)
    before_others = {(bus, col): mixer._get_cell(path, bus, col)
                     for bus in (0, 1, 2) for col in (2, 3, 6)}
    assert mixer._is_zero(mixer._get_cell(path, 1, 4))
    body = {'strip': 'ch/01', 'control': 'pan', 'value': 0, 'mix': 0}
    for app, events in api(mixer, config, body):
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        # Explicit pan completes only the missing RIGHT diagonal route.
        assert mixer._get_cell(path, 0, 1) == original_left
        assert mixer._get_cell(path, 1, 4) == original_left
        assert mixer._get_cell(path, 0, 4) == original_cross  # custom crossfeed untouched
        assert mixer._is_zero(mixer._get_cell(path, 1, 1))
        assert app.state()['ch/01']['pan'] == 0
        assert app.state()['ch/01']['pan_available'] is True
        for position in (1, -1, 0):
            body['value'] = position
            with contextlib.redirect_stdout(io.StringIO()):
                assert app.set_value() == {'ok': True}
            assert app.state()['ch/01']['pan'] == pytest.approx(position)
        assert mixer._get_cell(path, 0, 1) == original_left
        assert mixer._get_cell(path, 1, 4) == original_left
        assert {(bus, col): mixer._get_cell(path, bus, col)
                for bus in (0, 1, 2) for col in (2, 3, 6)} == before_others


def test_pro40_unlinked_output_bus_refuses_pan_without_partial_write():
    mixer, config = pair_fixture()
    config.settings['stereo_buses'] = []
    before = dict(mixer.helper.cells)
    body = {'strip': 'ch/01', 'control': 'pan', 'value': -0.2, 'mix': 0}
    for app, events in api(mixer, config, body):
        response = app.set_value()
        assert response[1] == 400
        assert 'Link the stereo output buses first' in response[0]['error']
        assert dict(mixer.helper.cells) == before
        assert not events


def test_pan_on_disconnected_stereo_pair_never_creates_two_routes():
    mixer, config = pair_fixture()
    for col in (1, 4):
        for bus in (0, 1):
            edit(mixer, col, bus, None)
    path = mixer.roles['fader'][0]
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_input_pair_balance(0, 1, 4, 0.25, activate_missing=True)
    assert mixer._is_zero(mixer._get_cell(path, 0, 1))
    assert mixer._is_zero(mixer._get_cell(path, 1, 4))


def test_reversed_pair_input_order_remains_left_then_right():
    mixer, config = saffire(), Config(None)
    for col in (2, 7):
        for bus in (0, 1):
            edit(mixer, col, bus, None)
    edit(mixer, 7, 0, -2)
    config.settings['stereo_buses'] = [0]
    assert stub_stereo_handler(mixer, config)({
        'action': 'link', 'dragged': 'ch/07', 'target': 'ch/02'})['ok']
    body = {'strip': 'ch/07', 'control': 'pan', 'value': 0, 'mix': 0}
    for app, _ in api(mixer, config, body):
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        path = mixer.roles['fader'][0]
        assert mixer._get_cell(path, 1, 2) == mixer._get_cell(path, 0, 7)
        assert mixer._is_zero(mixer._get_cell(path, 0, 2))
        assert mixer._is_zero(mixer._get_cell(path, 1, 7))
        assert app.state()['ch/07']['pan'] == 0


def test_view_only_names_module_keeps_hardware_strings():
    project = Path(__file__).resolve().parents[1]
    html = (project/'src/ffado_webmixer/assets/static/index.html').read_text()
    js = (project/'src/ffado_webmixer/assets/static/index.js').read_text()
    routing = (project/'src/ffado_webmixer/assets/static/routing.js').read_text()
    assert html.index('/static/labels.js') < html.index('/static/routing.js')
    assert 'shortFfadoLabel(data.input' in js
    assert 'shortFfadoLabel(m.name)' in js
    assert 'shortFfadoLabel(o.name)' in js
    assert 'th.textContent = shortFfadoLabel(name)' in routing
    assert 'shortFfadoLabel(matrixInputLabel(i))' in routing
    assert 'matrix.input_labels' in routing
    assert 'matrix.inputs[i]' in routing  # immutable FFADO fallback
    assert 'shortFfadoLabel(matrix.outputs[o])' in routing
