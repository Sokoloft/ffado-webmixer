"""DICE solo through the API, with simulated hardware and durable recovery."""
import contextlib
import io

import pytest

from test_stereo_group_mute import api, mixer_for


def levels(mixer):
    path = mixer.roles['fader'][0]
    with contextlib.redirect_stdout(io.StringIO()):
        return {(bus, col): mixer._get_cell(path, bus, col)
                for bus in range(len(mixer.mixes)) for col in range(len(mixer.columns))}


@pytest.mark.parametrize('model', ['saffirepro40', 'saffirepro26', 'profire2626', 'firestudio26x26'])
@pytest.mark.parametrize('stereo_bus', [False, True])
@pytest.mark.parametrize('paired', [False, True])
def test_solo_covers_linked_routes_and_restores_levels(tmp_path, model, stereo_bus, paired):
    mixer, config = mixer_for(tmp_path, model)
    mix = 2
    buses = (2, 3) if stereo_bus else (2,)
    channels = (4, 1) if paired else (4,)
    if paired:
        config.link('ch/04', 'ch/01', mix)  # arbitrary, ordered stereo inputs
    if stereo_bus:
        config.settings['stereo_buses'] = [mix]
    path = mixer.roles['fader'][0]
    # Unequal levels and disconnected crosspoints must survive the round trip.
    mixer.helper.real.cells[(path, 4, mix)] = 8192
    mixer.helper.real.cells[(path, 1, mix)] = 4096
    mixer.helper.real.cells[(path, 4, mix + 1 if stereo_bus else mix - 1)] = 0
    before = levels(mixer)
    body = {'strip': 'ch/01' if paired else 'ch/04', 'mix': mix,
            'control': 'solo', 'value': True}
    for app, events in api(mixer, config, body, mix=mix):
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        assert mixer._solos == {bus: set(channels) for bus in buses}
        assert app.state()['ch/04']['solo']
        for key, raw in levels(mixer).items():
            bus, col = key
            assert raw == (0 if bus in buses and col not in channels else before[key])
        # Neither leg of the selected input pair may be temporarily suppressed.
        assert not any(value == 0 and row in channels
                       for row, col, value in mixer.helper.events)
        assert events == [{'type': 'strip', 'mix': mix, 'strip': 'ch/04',
                           'control': 'solo', 'value': True}]
        body['value'] = False
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        assert not app.state()['ch/04']['solo']
        assert levels(mixer) == before
        assert not mixer._solos
        assert not mixer._matrix_mutes
        assert not mixer._recovery_journal.path.exists()


def test_multiple_solos_preserve_user_mutes_and_gain_edits(tmp_path):
    mixer, config = mixer_for(tmp_path)
    config.settings['stereo_buses'] = [0]
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_mute((0, 1), (3,), True)
    body = {'strip': 'ch/01', 'mix': 0, 'control': 'solo', 'value': True}
    for app, _ in api(mixer, config, body):
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
            body['strip'] = 'ch/04'
            assert app.set_value() == {'ok': True}
            mixer.write(1, 'ch/06', 'fader', 57)
            body.update(strip='ch/01', value=False)
            assert app.set_value() == {'ok': True}
        assert mixer._solos == {0: {4}, 1: {4}}
        path = mixer.roles['fader'][0]
        assert all(mixer._get_cell(path, bus, 1) == 0 for bus in (0, 1))
        with contextlib.redirect_stdout(io.StringIO()):
            body['strip'] = 'ch/04'
            assert app.set_value() == {'ok': True}
        assert mixer._user_mutes == {(0, 3), (1, 3)}
        assert set(mixer._matrix_mutes) == mixer._user_mutes
        assert all(mixer._get_cell(path, bus, 3) == 0 for bus in (0, 1))
        assert mixer._get_cell(path, 1, 6) == mixer._from_ui(57, mixer.roles['fader'][1])


@pytest.mark.parametrize('unsolo', [False, True])
def test_partial_failure_restores_both_buses_and_journal(tmp_path, unsolo):
    mixer, config = mixer_for(tmp_path)
    config.settings['stereo_buses'] = [0]
    body = {'strip': 'ch/01', 'mix': 0, 'control': 'solo', 'value': True}
    for app, events in api(mixer, config, body):
        with contextlib.redirect_stdout(io.StringIO()):
            if unsolo:
                assert app.set_value() == {'ok': True}
                body['value'] = False
        before = levels(mixer)
        saved = dict(mixer._matrix_mutes)
        solos = {bus: set(cols) for bus, cols in mixer._solos.items()}
        # Fail late, on the right bus, after earlier writes have succeeded.
        mixer.helper.fail = lambda row, col, value: (row, col) == (4, 1) and (
            value != 0 if unsolo else value == 0)
        with contextlib.redirect_stdout(io.StringIO()):
            result, status = app.set_value()
        assert status == 500
        assert 'hardware refused' in result['error']
        assert levels(mixer) == before
        assert mixer._solos == solos
        assert mixer._matrix_mutes == saved
        assert mixer._recovery_journal.load() == saved
        assert len(events) == int(unsolo)
        mixer.helper.fail = None
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}


def test_motu_solo_uses_native_controls(tmp_path):
    mixer, config = mixer_for(tmp_path, 'motuultralite')
    # The minimal debug fixture only inventories the fader matrix. Supply the
    # native solo endpoint that a real Ultralite advertises separately.
    path = mixer.device['device'] + '/Mixer/solo'
    mixer.roles['solo'] = (path, {'type': 'toggle', 'writable': True})
    for col in range(len(mixer.columns)):
        mixer.helper.real.cells[(path, 0, col)] = 0
    config.link('ch/04', 'ch/01', 0)
    before = levels(mixer)
    for app, _ in api(mixer, config, {
            'strip': 'ch/04', 'mix': 0, 'control': 'solo', 'value': True}):
        with contextlib.redirect_stdout(io.StringIO()):
            assert app.set_value() == {'ok': True}
        assert app.state()['ch/04']['solo']
    assert levels(mixer) == before
    assert not mixer._matrix_mutes
    assert not mixer._solos


def test_failed_unsolo_journals_levels_before_rollback_silences_them(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_solo((0, 1), (1, 4), True)
    saved = dict(mixer._matrix_mutes)
    def fail(row, col, value):
        if value == 0:
            assert mixer._recovery_journal.load() == saved
        return (row, col) == (6, 1) and value != 0
    mixer.helper.fail = fail
    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(RuntimeError, match='hardware refused'):
            mixer.write_group_solo((0, 1), (1, 4), False)
    assert mixer._solos == {0: {1, 4}, 1: {1, 4}}
    assert mixer._recovery_journal.load() == saved


def test_failed_rollback_keeps_all_original_levels_recoverable(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_solo((0, 1), (1,), True)
    saved = dict(mixer._matrix_mutes)
    mixer.helper.fail = lambda row, col, value: (
        (row, col) == (6, 1) and value != 0 or (row, col) == (0, 0) and value == 0)
    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(RuntimeError, match='incomplete rollback'):
            mixer.write_group_solo((0, 1), (1,), False)
    assert mixer._recovery_journal.load() == saved
    mixer.helper.fail = None
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.shutdown_soft_mutes()
    assert all(raw == 16384 for raw in levels(mixer).values())
    assert not mixer._recovery_journal.path.exists()


def test_solo_accepts_native_silence_readback_and_requires_recovery(tmp_path):
    mixer, _ = mixer_for(tmp_path)
    original = mixer.helper.set_cell
    mixer.helper.set_cell = lambda path, row, col, value: original(
        path, row, col, 16 if value == 0 else value)
    before = levels(mixer)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_group_solo((0, 1), (4, 1), True)
    assert mixer.read_mix(0, stereo_bus=True)['ch/04']['solo']
    assert levels(mixer)[0, 0] == 16
    # An interrupted solo must retain the same explicit recovery guard as mute.
    mixer.attach_mute_recovery()
    assert mixer.mute_recovery_status()['pending']
    with pytest.raises(RuntimeError, match='interrupted'):
        mixer.write_group_solo((0, 1), (4, 1), False)
    with contextlib.redirect_stdout(io.StringIO()):
        assert mixer.resolve_mute_recovery('restore')['pending'] == 0
    assert levels(mixer) == before


@pytest.mark.parametrize('buses,channels,value', [
    ((), (1,), True), ((0,), (), True), ((-1,), (1,), True),
    ((0,), (999,), True), ((0,), (1,), 1),
])
def test_invalid_solo_is_rejected_without_writes(tmp_path, buses, channels, value):
    mixer, _ = mixer_for(tmp_path)
    with pytest.raises(ValueError):
        mixer.write_group_solo(buses, channels, value)
    assert not mixer.helper.events
    assert not mixer._solos
    assert not mixer._matrix_mutes
