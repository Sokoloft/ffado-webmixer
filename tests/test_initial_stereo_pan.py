"""Regression tests: stereo input pan is read from FFADO immediately after linking.

The initial state must invert write_input_pair_balance's peak-normalized
attenuation, not the sum-normalized mono-bus balance algorithm.
"""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.mixer import input_pair_balance_from_raw
from test_arbitrary_stereo_pairs import edit, stub_stereo_handler
from test_bus_scoped_stereo import state_on


def profire():
    with contextlib.redirect_stdout(io.StringIO()):
        return make_debug_mixer('profire2626', Config(None))


def clear_diagonal(mixer, left, right, bus=0):
    for channel in (left, right):
        for output in (bus, bus + 1):
            edit(mixer, channel, output, None)


def state(mixer, config, mix=0):
    with contextlib.redirect_stdout(io.StringIO()):
        return state_on(mixer, config, mix)


@pytest.mark.parametrize('left,right,result', [
    (16384, 16384, 0),
    (16384, 8192, -0.5),
    (8192, 16384, +0.5),
    (16384, 0, -1),
    (0, 16384, +1),
    (16384, 4096, -0.75),
    (4096, 16384, +0.75),
    (0, 0, None),
    (16, 16, None),
    (16, 16384, +1),
])
def test_initial_pair_pan_inverse_of_peak_attenuation(left, right, result):
    assert input_pair_balance_from_raw(left, right) == result


@pytest.mark.parametrize('bad', [(float('nan'), 3), (-1, 10), (float('inf'), 10)])
def test_invalid_matrix_values_never_display_a_pan(bad):
    with pytest.raises(ValueError):
        input_pair_balance_from_raw(*bad)


def test_first_read_after_nonadjacent_link_uses_actual_diagonal_levels():
    mixer, config = profire(), Config(None)
    config.settings['stereo_buses'] = [0]
    clear_diagonal(mixer, 1, 4)
    edit(mixer, 1, 0, -0.4)
    edit(mixer, 4, 1, -6.4206)  # ~50% of left coefficient
    before = dict(mixer.helper.cells)
    result = stub_stereo_handler(mixer, config)(
        {'action': 'link', 'dragged': 'ch/01', 'target': 'ch/04'}, mix=0)
    assert result['ok']
    first = state(mixer, config)['ch/01']
    assert first['partner'] == 'ch/04'
    assert first['pan'] == pytest.approx(-0.5, abs=.005)
    assert first['pan_available'] is True
    assert dict(mixer.helper.cells) == before, 'link/read must never write routing'


def test_reversed_order_picks_first_click_as_left_not_channel_number():
    mixer, config = profire(), Config(None)
    config.settings['stereo_buses'] = [0]
    clear_diagonal(mixer, 7, 2)
    edit(mixer, 7, 0, -6.4206)
    edit(mixer, 2, 1, -0.4)
    stub_stereo_handler(mixer, config)(
        {'action': 'link', 'dragged': 'ch/07', 'target': 'ch/02'}, mix=0)
    first = state(mixer, config)['ch/07']
    assert first['partner'] == 'ch/02'
    assert first['pan'] == pytest.approx(+0.5, abs=.005)


@pytest.mark.parametrize('value', [-1, -.75, -.5, 0, .25, .5, .75, 1])
def test_hardware_readback_matches_each_pan_written_by_stereo_pair(value):
    mixer, config = profire(), Config(None)
    config.settings['stereo_buses'] = [0]
    config.link('ch/01', 'ch/04', 0)
    clear_diagonal(mixer, 1, 4)
    edit(mixer, 1, 0, -.4)
    edit(mixer, 4, 1, -.4)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_input_pair_balance(0, 1, 4, value)
    data = state(mixer, config)['ch/01']
    assert data['pan'] == pytest.approx(value, abs=.001)


def test_zero_diagonal_pair_is_not_misrepresented_as_center():
    mixer, config = profire(), Config(None)
    config.settings['stereo_buses'] = [0]
    config.link('ch/01', 'ch/04', 0)
    clear_diagonal(mixer, 1, 4)
    edit(mixer, 1, 1, -3)  # Custom cross-route is not diagonal
    first = state(mixer, config)['ch/01']
    assert first['pan'] is None
    assert first['pan_available'] is False
    assert 'Both diagonal stereo routes' in first['pan_note']
    # No crosspoint writes from a read, and disabled pan won't open a route.
    assert mixer._matrix_raw(1, 1) > 0
    assert mixer._matrix_raw(0, 1) == 0
    assert mixer._matrix_raw(1, 4) == 0


def test_only_one_diagonal_route_shows_endstop_and_warning():
    mixer, config = profire(), Config(None)
    config.settings['stereo_buses'] = [0]
    config.link('ch/01', 'ch/04', 0)
    clear_diagonal(mixer, 1, 4)
    edit(mixer, 4, 1, -5)
    first = state(mixer, config)['ch/01']
    assert first['pan'] == 1
    assert first['pan_available'] is True
    assert 'One diagonal route' in first['pan_note']


def test_state_after_bus_change_is_scoped_and_does_not_use_other_bus_pan():
    mixer, config = profire(), Config(None)
    config.settings['stereo_buses'] = [0, 2]
    config.link('ch/01', 'ch/04', mix=0)
    config.link('ch/01', 'ch/04', mix=2)
    for bus in (0, 2):
        clear_diagonal(mixer, 1, 4, bus)
    edit(mixer, 1, 0, -.4); edit(mixer, 4, 1, -6.4206)
    edit(mixer, 1, 2, -6.4206); edit(mixer, 4, 3, -.4)
    assert state(mixer, config, 0)['ch/01']['pan'] == pytest.approx(-.5, abs=.005)
    assert state(mixer, config, 2)['ch/01']['pan'] == pytest.approx(+.5, abs=.005)
    assert state(mixer, config, 0)['ch/01']['pan'] == pytest.approx(-.5, abs=.005)


def test_custom_crosspoints_are_reported_as_partial_stereo_pan():
    mixer, config = profire(), Config(None)
    config.settings['stereo_buses'] = [0]
    config.link('ch/01', 'ch/04', 0)
    clear_diagonal(mixer, 1, 4)
    edit(mixer, 1, 0, -6.4)
    edit(mixer, 4, 1, -6.4)
    # The actual hardware image also includes both cross-routes. A single
    # PAN percentage cannot describe this 2x2 routing faithfully.
    edit(mixer, 1, 1, -6.4)
    edit(mixer, 4, 0, -6.4)
    first = state(mixer, config)['ch/01']
    assert first['pan'] == 0
    assert first['pan_partial'] is True
    assert 'Cross-routes' in first['pan_note']
    edit(mixer, 1, 1, None)
    edit(mixer, 4, 0, None)
    clean = state(mixer, config)['ch/01']
    assert clean['pan'] == 0
    assert clean['pan_partial'] is False
    assert 'pan_note' not in clean
