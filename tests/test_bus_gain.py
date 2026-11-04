"""DICE per-bus software gain preserves channel levels and physical outputs."""
import contextlib
import io
import json
from copy import deepcopy
from pathlib import Path
import shutil
import subprocess

import pytest
from flask import Flask

from ffado_webmixer.api import mixer as mixer_routes
from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.gain import UNITY, db_to_raw, raw_to_ui
from ffado_webmixer.mixer import input_pair_balance_from_raw


def ui(db):
    return 0 if db is None else (db + 60) * 100 / 66


@pytest.fixture
def mixer(tmp_path):
    with contextlib.redirect_stdout(io.StringIO()):
        m = make_debug_mixer('saffirepro40', Config(tmp_path / 'device.json'))
    path = m.roles['fader'][0]
    for bus in range(len(m.mixes)):
        for col in range(len(m.columns)):
            m.helper.set_cell(path, *m._coordinates(bus, col), [UNITY, UNITY // 2, 0][col % 3])
    m.attach_mute_recovery()
    return m


def native(m, bus):
    return [m.helper.get_cell(m.roles['fader'][0], *m._coordinates(bus, col))
            for col in range(len(m.columns))]


def test_bus_gain_changes_only_selected_bus_and_preserves_channel_faders(mixer):
    before = native(mixer, 0)
    other = native(mixer, 1)
    outputs = dict(mixer.helper.values)
    strips = mixer.read_mix(0)
    mixer.write_linked_output('bus/0', 'fader', ui(-6))
    factor = db_to_raw(-6, 'dice_db') / UNITY
    assert native(mixer, 0) == [round(raw * factor) for raw in before]
    assert native(mixer, 1) == other
    assert mixer.helper.values == outputs
    assert mixer.read_mix(0) == strips
    assert mixer.read_linked_output('bus/0')['level'] == pytest.approx(ui(-6))
    assert mixer.read_output('bus/1')['level'] == pytest.approx(ui(0))
    mixer.write_linked_output('bus/0', 'fader', ui(0))
    assert native(mixer, 0) == before
    assert 'dice/master' not in mixer.outputs


@pytest.mark.parametrize('silence', ['mute', 'fader'])
def test_bus_silence_retains_and_allows_channel_edits(mixer, silence):
    mixer.write_output('bus/0', 'fader', ui(-6))
    mixer.write_output('bus/0', silence, True if silence == 'mute' else 0)
    assert not any(native(mixer, 0))
    mixer.matrix_set(0, 0, db=-12, use_db=True)
    assert not any(native(mixer, 0))
    assert mixer.read_mix(0)['ch/00']['fader'] == pytest.approx(raw_to_ui(db_to_raw(-12, 'dice_db'), 'dice_db'))
    mixer.write_output('bus/0', silence, False if silence == 'mute' else ui(-6))
    assert native(mixer, 0)[0] == round(db_to_raw(-12, 'dice_db') * db_to_raw(-6, 'dice_db') / UNITY)
    assert mixer.read_output('bus/0')['level'] == pytest.approx(ui(-6))


def test_bus_mute_is_independent_of_channel_mute_solo_and_hardware_mute(mixer):
    mixer.write(0, 'ch/00', 'mute', True)
    mixer.write(0, 'ch/01', 'solo', True)
    mixer.write_output('bus/0', 'mute', True)
    assert not any(native(mixer, 0))
    mixer.write_output('bus/0', 'fader', ui(-6))
    mixer.write_output('bus/0', 'mute', False)
    assert native(mixer, 0)[0] == 0
    assert native(mixer, 0)[1] > 0
    assert native(mixer, 0)[3] == 0
    assert not mixer.read_dice_monitoring()['mute']
    mixer.write_dice_monitoring('mute', True)
    before = native(mixer, 0)
    mixer.write_output('bus/0', 'mute', True)
    mixer.write_output('bus/0', 'mute', False)
    assert native(mixer, 0) == before
    assert mixer.read_dice_monitoring()['mute']
    mixer.write(0, 'ch/01', 'solo', False)
    assert native(mixer, 0)[0] == 0
    assert native(mixer, 0)[3] > 0


def test_linked_bus_gain_changes_both_legs_and_keeps_cross_routes(mixer):
    mixer.config.settings['stereo_buses'] = [0]
    original = [native(mixer, bus) for bus in (0, 1)]
    mixer.write_linked_output('bus/1', 'fader', ui(-12))
    assert mixer.read_linked_output('bus/1')['level'] == pytest.approx(ui(-12))
    for bus in (0, 1):
        assert native(mixer, bus) == [round(raw * db_to_raw(-12, 'dice_db') / UNITY) for raw in original[bus]]
    mixer.write_linked_output('bus/0', 'mute', True)
    assert not any(native(mixer, 0) + native(mixer, 1))
    mixer.write_linked_output('bus/1', 'mute', False)
    mixer.write_linked_output('bus/1', 'fader', ui(0))
    assert [native(mixer, bus) for bus in (0, 1)] == original


def test_stereo_channel_edits_under_bus_mute_retain_diagonals_and_balance(mixer):
    mixer.config.settings['stereo_buses'] = [0]
    for col in (0, 1):
        for bus in (0, 1):
            mixer.matrix_set(col, bus, db=None, use_db=True)
    mixer.write_linked_output('bus/0', 'mute', True)
    mixer.write_stereo_levels(0, [(0, 'left'), (1, 'right')], ui(-12))
    assert not any(native(mixer, 0) + native(mixer, 1))
    mixer.write_input_pair_balance(0, 0, 1, .5)
    mixer.write_linked_output('bus/0', 'fader', ui(-6))
    mixer.write_linked_output('bus/0', 'mute', False)
    assert native(mixer, 0)[1] == native(mixer, 1)[0] == 0
    assert native(mixer, 1)[1] > native(mixer, 0)[0] > 0
    assert input_pair_balance_from_raw(native(mixer, 0)[0], native(mixer, 1)[1]) == pytest.approx(.5, abs=.001)


def test_boost_rejects_overflow_before_writing_either_stereo_leg(mixer):
    mixer.config.settings['stereo_buses'] = [0]
    mixer._set_cell(mixer.roles['fader'][0], 1, 0, 65535)
    before = [native(mixer, bus) for bus in (0, 1)]
    with pytest.raises(ValueError, match='range'):
        mixer.write_linked_output('bus/0', 'fader', ui(6))
    assert [native(mixer, bus) for bus in (0, 1)] == before
    assert mixer._bus_gains == {}


def test_gain_update_rolls_back_writes_after_failure(mixer):
    mixer.write_output('bus/0', 'fader', ui(-6))
    before = native(mixer, 0)
    write, failed = mixer.helper.set_cell, False

    def fail_once(path, row, col, value):
        nonlocal failed
        write(path, row, col, value)
        if not failed:
            failed = True
            raise IOError('disconnected after write')

    mixer.helper.set_cell = fail_once
    with pytest.raises(IOError, match='disconnected'):
        mixer.write_output('bus/0', 'mute', True)
    assert native(mixer, 0) == before
    assert not mixer.read_output('bus/0')['mute']
    assert mixer.read_output('bus/0')['level'] == pytest.approx(ui(-6))


def test_channel_edit_rolls_back_while_bus_is_scaled(mixer):
    mixer.write_output('bus/0', 'fader', ui(-6))
    before = native(mixer, 0)
    write, failed = mixer.helper.set_cell, False

    def fail_once(*args):
        nonlocal failed
        write(*args)
        if not failed:
            failed = True
            raise IOError('channel write failed')

    mixer.helper.set_cell = fail_once
    with pytest.raises(IOError, match='channel write failed'):
        mixer.matrix_set(0, 0, db=-12, use_db=True)
    assert native(mixer, 0) == before
    assert mixer.read_output('bus/0')['level'] == pytest.approx(ui(-6))


def test_bus_journal_failure_leaves_hardware_untouched(mixer):
    before = dict(mixer.helper.cells)

    def reject(_levels):
        raise OSError('cannot persist recovery')

    mixer._recovery_journal.write = reject
    with pytest.raises(OSError, match='recovery'):
        mixer.write_output('bus/0', 'mute', True)
    assert mixer.helper.cells == before
    assert mixer._bus_gains == {}


def test_incomplete_bus_rollback_blocks_edits_and_keeps_recovery(mixer):
    write = mixer.helper.set_cell
    attempts = 0

    def fail(*args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            write(*args)
        raise IOError('device disconnected')

    mixer.helper.set_cell = fail
    with pytest.raises(RuntimeError, match='rollback incomplete'):
        mixer.write_output('bus/0', 'mute', True)
    assert mixer.mute_recovery_status()['pending'] > 0
    assert mixer._recovery_journal.load()[0, 0] == UNITY
    with pytest.raises(RuntimeError, match='Previous software mute'):
        mixer.write_output('bus/0', 'fader', ui(0))


def test_external_write_resets_session_gain_without_rewriting_hardware(mixer):
    mixer.write_output('bus/0', 'mute', True)
    mixer.helper.set_cell(mixer.roles['fader'][0], *mixer._coordinates(0, 0), 8192)
    before = dict(mixer.helper.cells)
    assert mixer.read_output('bus/0')['level'] == pytest.approx(ui(0))
    assert not mixer.read_output('bus/0')['mute']
    assert mixer.helper.cells == before
    assert mixer.read_mix(0)['ch/00']['fader'] == raw_to_ui(8192, 'dice_db')


def test_journal_precedes_bus_mute_and_clean_shutdown_preserves_it(mixer):
    write = mixer.helper.set_cell

    def check_journal(*args):
        assert mixer._recovery_journal.load()
        write(*args)

    mixer.helper.set_cell = check_journal
    mixer.write_output('bus/0', 'mute', True)
    assert mixer.config.bus_gains['buses']['0']['mute']
    mixer.helper.set_cell = write
    mixer.shutdown_soft_mutes()
    assert not any(native(mixer, 0))
    assert mixer.read_output('bus/0')['mute']
    assert mixer._recovery_journal.load() == {}


def restart(mixer, *, cells=None, before_load=None):
    config = Config(mixer.config.path)
    config.load()
    with contextlib.redirect_stdout(io.StringIO()):
        restored = make_debug_mixer('saffirepro40', config)
    restored.helper.cells = dict(mixer.helper.cells if cells is None else cells)
    if before_load:
        before_load(restored)
    restored.attach_mute_recovery()
    return restored


def test_completed_bus_mute_resumes_without_recovery_or_hardware_writes(mixer):
    original = native(mixer, 0)
    mixer.write_output('bus/0', 'fader', ui(-6))
    mixer.write_output('bus/0', 'mute', True)

    def no_writes(restored):
        restored.helper.set_cell = lambda *args: pytest.fail('Matching saved gain must not rewrite hardware')

    restored = restart(mixer, before_load=no_writes)
    assert restored.read_output('bus/0')['level'] == pytest.approx(ui(-6))
    assert restored.read_output('bus/0')['mute']
    assert restored.mute_recovery_status()['pending'] == 0
    assert restored._bus_gains[0]['cells'][0] == original[0]


def test_independent_interrupted_channel_mute_still_requires_recovery(mixer):
    mixer.write_output('bus/0', 'fader', ui(-6))
    mixer.write(0, 'ch/00', 'mute', True)
    restored = restart(mixer)
    assert restored.mute_recovery_status()['pending'] > 0
    with pytest.raises(RuntimeError, match='Previous software mute'):
        restored.write_output('bus/0', 'fader', ui(0))
    assert native(restored, 0)[0] == 0
    restored.resolve_mute_recovery('restore')
    assert native(restored, 0)[0] == db_to_raw(-6, 'dice_db')


@pytest.mark.parametrize('level', [ui(-12), ui(0), ui(6), 0])
def test_bus_gain_survives_exit_and_repeated_restarts_without_compounding(mixer, level):
    original = native(mixer, 0)
    mixer.write_output('bus/0', 'fader', level)
    mixer.matrix_set(1, 0, db=-20, use_db=True)
    actual = native(mixer, 0)
    mixer.shutdown_soft_mutes()
    assert native(mixer, 0) == actual
    restored = restart(mixer)
    restored = restart(restored)
    assert restored.read_output('bus/0')['level'] == pytest.approx(level)
    assert native(restored, 0) == actual
    restored.write_output('bus/0', 'fader', ui(0))
    assert native(restored, 0)[0] == original[0]
    assert native(restored, 0)[1] == db_to_raw(-20, 'dice_db')


def test_saved_gain_applies_to_reset_device_live_mix(mixer):
    mixer.write_output('bus/0', 'fader', ui(-6))
    reset_cells = dict(mixer.helper.cells)
    for col in range(len(mixer.columns)):
        reset_cells[(mixer.roles['fader'][0], *mixer._coordinates(0, col))] = UNITY // 4
    restored = restart(mixer, cells=reset_cells)
    assert restored.read_output('bus/0')['level'] == pytest.approx(ui(-6))
    assert native(restored, 0) == [round(UNITY / 4 * db_to_raw(-6, 'dice_db') / UNITY)] * len(mixer.columns)


def test_closed_app_channel_edit_does_not_double_scale_unchanged_routes(mixer):
    mixer.write_output('bus/0', 'fader', ui(-6))
    before = native(mixer, 0)
    cells = dict(mixer.helper.cells)
    cells[(mixer.roles['fader'][0], *mixer._coordinates(0, 0))] = UNITY // 4
    restored = restart(mixer, cells=cells)
    assert native(restored, 0)[1:] == before[1:]
    assert native(restored, 0)[0] == round(UNITY / 4 * db_to_raw(-6, 'dice_db') / UNITY)


def test_saved_mute_loads_without_transient_unmute_after_device_reset(mixer):
    mixer.write_output('bus/0', 'fader', ui(-12))
    mixer.write_output('bus/0', 'mute', True)
    original = {key: UNITY for key in mixer.helper.cells}
    writes = []

    def track(restored):
        write = restored.helper.set_cell
        def record(*args):
            writes.append(args[-1])
            write(*args)
        restored.helper.set_cell = record

    restored = restart(mixer, cells=original, before_load=track)
    assert writes and not any(writes)
    assert restored.read_output('bus/0')['mute']
    assert restored.read_output('bus/0')['level'] == pytest.approx(ui(-12))


def test_partial_bus_write_crash_requires_explicit_recovery(mixer):
    write = mixer.helper.set_cell
    def interrupt(*args):
        write(*args)
        raise KeyboardInterrupt('process stopped mid-write')
    mixer.helper.set_cell = interrupt
    with pytest.raises(KeyboardInterrupt):
        mixer.write_output('bus/0', 'mute', True)
    restored = restart(mixer)
    assert restored.mute_recovery_status()['pending'] > 0
    assert native(restored, 0) == native(mixer, 0)


def test_bus_save_failure_rolls_back_hardware_and_saved_settings(mixer):
    mixer.write_output('bus/0', 'fader', ui(-6))
    before = native(mixer, 0)
    previous = Config(mixer.config.path)
    previous.load()
    def reject():
        raise OSError('settings unavailable')
    mixer.config.save = reject
    with pytest.raises(OSError, match='settings unavailable'):
        mixer.write_output('bus/0', 'fader', ui(-12))
    assert native(mixer, 0) == before
    assert mixer.read_output('bus/0')['level'] == pytest.approx(ui(-6))
    assert mixer.config.bus_gains == previous.bus_gains


def test_failed_channel_save_does_not_leave_false_recovery_after_restart(mixer):
    mixer.write_output('bus/0', 'fader', ui(-6))
    before = native(mixer, 0)
    def reject():
        raise OSError('settings unavailable')
    mixer.config.save = reject
    with pytest.raises(OSError, match='settings unavailable'):
        mixer.matrix_set(0, 0, db=-12, use_db=True)
    assert native(mixer, 0) == before
    restored = restart(mixer)
    assert restored.mute_recovery_status()['pending'] == 0
    assert restored.read_output('bus/0')['level'] == pytest.approx(ui(-6))


def test_saved_boost_on_incompatible_reset_levels_reports_fault_without_writes(mixer):
    mixer.write_output('bus/0', 'fader', ui(6))
    reset = dict(mixer.helper.cells)
    reset[(mixer.roles['fader'][0], *mixer._coordinates(0, 0))] = 65535
    restored = restart(mixer, cells=reset)
    assert restored.helper.cells == reset
    assert 'Could not load saved bus gains' in restored.mute_recovery_status()['fault']


def test_linked_bus_gain_and_mute_persist_per_bus(mixer):
    mixer.config.settings['stereo_buses'] = [0]
    mixer.write_linked_output('bus/0', 'fader', ui(-12))
    mixer.write_linked_output('bus/1', 'mute', True)
    mixer.write_output('bus/2', 'fader', ui(-6))
    restored = restart(mixer)
    for bus in (0, 1):
        assert restored.read_output(f'bus/{bus}')['level'] == pytest.approx(ui(-12))
        assert restored.read_output(f'bus/{bus}')['mute']
    assert restored.read_output('bus/2')['level'] == pytest.approx(ui(-6))
    assert not restored.read_output('bus/2')['mute']
    restored.write_linked_output('bus/1', 'mute', False)
    assert native(restored, 0)[0] == native(restored, 1)[0] == db_to_raw(-12, 'dice_db')


@pytest.mark.parametrize('field', ['guid', 'matrix_path', 'columns'])
def test_saved_gains_do_not_load_for_different_device_or_matrix(mixer, field):
    mixer.write_output('bus/0', 'fader', ui(-6))
    saved = deepcopy(mixer.config.bus_gains)
    if field == 'columns':
        saved[field] = ['different' + name for name in saved[field]]
    else:
        saved[field] = '0000000000000001' if field == 'guid' else '/different/matrix'
    mixer.config.bus_gains = saved
    mixer.config.save()
    before = dict(mixer.helper.cells)
    restored = restart(mixer)
    assert not restored._bus_gains
    assert restored.helper.cells == before


@pytest.mark.parametrize('field,value', [('level', True), ('level', 101), ('level', float('nan')),
                                        ('level', 10 ** 1000), ('mute', 1), ('cells', [0]),
                                        ('cells', [65536] * 18)])
def test_invalid_saved_bus_state_is_backed_up_and_not_loaded(mixer, field, value):
    mixer.write_output('bus/0', 'fader', ui(-6))
    data = json.loads(mixer.config.path.read_text())
    data['bus_gains']['buses']['0'][field] = value
    mixer.config.path.write_text(json.dumps(data))
    config = Config(mixer.config.path)
    config.load()
    assert config.bus_gains == {}
    assert mixer.config.path.with_name(mixer.config.path.name + '.bad').exists()


@pytest.mark.parametrize('control,value', [('fader', True), ('fader', -1), ('fader', 101),
                                         ('fader', float('nan')), ('mute', 1), ('bad', True)])
def test_invalid_bus_changes_do_not_write(mixer, control, value):
    before = dict(mixer.helper.cells)
    with pytest.raises(ValueError):
        mixer.write_linked_output('bus/0', control, value)
    assert mixer.helper.cells == before


def test_bus_api_description_names_and_independent_hardware_mute(mixer):
    mixer.config.names['bus:0'] = 'Speakers'
    app = Flask(__name__)
    events = []
    mixer_routes.register(app, mixer, mixer.describe(), mixer.config, events.append)
    client = app.test_client()
    description = client.get('/api/describe').json
    assert description['software_bus_gain']
    bus = next(out for out in description['outputs'] if out['id'] == 'bus/0')
    assert bus['name'] == 'Speakers'
    assert bus['controllable'] and bus['gain_scale']['max_db'] == 6
    assert client.get('/api/output?out=bus/0').json['name'] == 'Speakers'
    assert client.post('/api/output', json={'out': 'bus/0', 'control': 'fader', 'value': ui(-6)}).status_code == 200
    assert events[-1]['type'] == 'output'
    assert client.post('/api/output', json={'out': 'bus/0', 'control': 'mute', 'value': True}).status_code == 200
    assert client.get('/api/output?out=bus/0').json['mute']
    assert not client.get('/api/dice-monitoring').json['mute']
    assert client.post('/api/dice-monitoring', json={'control': 'mute', 'value': True}).status_code == 200
    assert events[-1]['type'] == 'dice-monitoring'


def test_bus_panel_pair_and_mono_names_persist_and_unlink_without_hardware_writes(mixer):
    app = Flask(__name__)
    mixer_routes.register(app, mixer, mixer.describe(), mixer.config, lambda event: None)
    client = app.test_client()
    before = dict(mixer.helper.cells)
    for out, name in [('bus/0', 'Guitar'), ('bus/1', 'Vocals'), ('bus/2', 'Headphones')]:
        assert client.post('/api/set', json={'strip': 'out:' + out, 'control': 'name', 'value': name}).status_code == 200
    assert client.post('/api/bus-stereo', json={'left': 0, 'linked': True}).status_code == 200
    for name in ('Main mix', 'Control Room Speakers'):
        assert client.post('/api/bus-pair-name', json={'left': 0, 'name': name}).status_code == 200
        for out in ('bus/0', 'bus/1'):
            assert client.get('/api/output', query_string={'out': out}).json['name'] == name
    saved = Config(mixer.config.path)
    saved.load()
    assert saved.names['bus-pair:0'] == 'Control Room Speakers'
    assert saved.names['out:bus/0'] == 'Guitar'
    assert saved.names['out:bus/1'] == 'Vocals'
    assert client.post('/api/bus-stereo', json={'left': 0, 'linked': False}).status_code == 200
    for out, name in [('bus/0', 'Guitar'), ('bus/1', 'Vocals'), ('bus/2', 'Headphones')]:
        assert client.get('/api/output', query_string={'out': out}).json['name'] == name
    assert mixer.helper.cells == before


@pytest.mark.parametrize('script', ['bus_gain_ui_test.cjs', 'dice_monitoring_ui_test.cjs', 'bus_rename_ui_test.cjs'])
def test_bus_and_monitor_ui(script):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for UI behavior checks')
    result = subprocess.run([node, str(Path(__file__).with_name(script))],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
