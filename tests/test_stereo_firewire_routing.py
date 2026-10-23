"""Saffire PRO 40 explicit stereo playback setup (no physical FireWire device)."""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from test_router_strip_labels import simulated_router


def patched_pro40():
    mixer, config, routes, calls = simulated_router('saffirepro40')
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.router_set('Mixer/In:01', '1394/In:01')
        mixer.router_set('Mixer/In:02', '1394/In:02')
    return mixer, config, routes, calls


def test_pro40_stereo_patch_detects_live_sources_not_fixed_column_numbers():
    mixer, _, routes, _ = patched_pro40()
    # These are the FFADO mixer *columns*. JACK's physical playback 1/2
    # can be assigned to any two different Mixer/In router destinations.
    routes['Mixer/In:01'] = '1394/In:02'
    routes['Mixer/In:02'] = '1394/In:01'
    with contextlib.redirect_stdout(io.StringIO()):
        options = mixer.stereo_firewire_options()
    assert options['available']
    assert options['pairs'] == [{
        'left_source': '1394/In:01', 'right_source': '1394/In:02',
        'left_input': 1, 'right_input': 0, 'label': 'Firewire 1+2',
    }]
    assert options['buses'][0] == {'left': 0, 'label': 'Bus 1+2'}


def test_pro40_stereo_patch_changes_only_target_2x2_and_preserves_router():
    mixer, _, routes, _ = patched_pro40()
    path = mixer.roles['fader'][0]
    before_router = dict(routes)
    # Reproduce a mono result: playback 1 and 2 both to left bus.
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.matrix_set(0, 0, db=-3, use_db=True)
        mixer.matrix_set(0, 1, db=-9, use_db=True)
        mixer.matrix_set(1, 0, db=-13, use_db=True)
        mixer.matrix_set(1, 1, db=None, use_db=True)
    # FFADO's user-defined routing for other bus, another channel stays.
    unrelated = {(2, 0): mixer._get_cell(path, 2, 0),
                 (0, 2): mixer._get_cell(path, 0, 2)}
    with contextlib.redirect_stdout(io.StringIO()):
        result = mixer.stereo_firewire_apply('1394/In:01', 0)
    assert result['ok'] and result['left_input'] == 0 and result['right_input'] == 1
    assert mixer._get_cell(path, 0, 0) == 16384
    assert mixer._get_cell(path, 1, 1) == 16384
    assert mixer._is_zero(mixer._get_cell(path, 0, 1))
    assert mixer._is_zero(mixer._get_cell(path, 1, 0))
    assert {point: mixer._get_cell(path, *point) for point in unrelated} == unrelated
    assert routes == before_router  # physical output routing preserved


def test_apply_is_explicit_and_does_not_modify_source_on_discovery():
    mixer, _, routes, _ = patched_pro40()
    path = mixer.roles['fader'][0]
    before = dict(mixer.helper.cells)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.stereo_firewire_options()
    assert mixer.helper.cells == before
    assert routes['Line/Out:01'] == 'Mixer/Out:01'


def test_missing_or_duplicate_assignments_are_not_guessed():
    mixer, _, routes, _ = patched_pro40()
    routes['Mixer/In:02'] = 'Mute:00'
    with contextlib.redirect_stdout(io.StringIO()):
        assert not mixer.stereo_firewire_options()['available']
        with pytest.raises(ValueError, match='not uniquely assigned'):
            mixer.stereo_firewire_apply('1394/In:01', 0)
    routes['Mixer/In:02'] = '1394/In:02'
    routes['Mixer/In:03'] = '1394/In:02'
    mixer._router_input_columns['Mixer/In:03'] = 2
    with contextlib.redirect_stdout(io.StringIO()):
        assert not mixer.stereo_firewire_options()['pairs']


def test_invalid_bus_and_unavailable_mixer_are_rejected_without_writes():
    mixer, _, _, _ = patched_pro40()
    before = dict(mixer.helper.cells)
    for bus in (-1, 1, 16, True, 0.0):
        with pytest.raises(ValueError):
            mixer.stereo_firewire_apply('1394/In:01', bus)
    assert mixer.helper.cells == before
    with contextlib.redirect_stdout(io.StringIO()):
        motu = make_debug_mixer('motuultralite', Config(None))
    assert not motu.stereo_firewire_options()['available']


def test_partial_write_failure_restores_previous_crosspoints():
    mixer, _, routes, _ = patched_pro40()
    path = mixer.roles['fader'][0]
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.matrix_set(0, 0, db=-18, use_db=True)
        mixer.matrix_set(1, 1, db=-24, use_db=True)
        mixer.matrix_set(1, 0, db=-11, use_db=True)
        mixer.matrix_set(0, 1, db=-4, use_db=True)
    points = [(0, 0), (1, 1), (0, 1), (1, 0)]
    saved = {point: mixer._get_cell(path, *point) for point in points}
    original = mixer.helper.set_cell
    state = {'failed': False}
    def fails_once(p, row, col, value):
        # Works for DICE's transposed coordinates, so trigger by target value
        # on the second attempted unity write only.
        if not state['failed'] and value == 16384 and (row, col) == mixer._coordinates(1, 1):
            state['failed'] = True
            raise IOError('test device rejected one write')
        return original(p, row, col, value)
    mixer.helper.set_cell = fails_once
    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(IOError, match='rejected'):
            mixer.stereo_firewire_apply('1394/In:01', 0)
    assert {point: mixer._get_cell(path, *point) for point in points} == saved
    assert routes['Line/Out:01'] == 'Mixer/Out:01'


def test_mutes_block_stereo_patch_to_preserve_recovery():
    mixer, _, _, _ = patched_pro40()
    mixer._matrix_mutes[(0, 0)] = 16384
    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(ValueError, match='Unmute'):
            mixer.stereo_firewire_apply('1394/In:01', 0)
