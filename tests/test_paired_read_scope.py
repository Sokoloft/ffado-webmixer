"""Paired snapshots must avoid hardware reads for unrelated input strips."""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.demo import DemoMixer
from test_stereo_group_mute import api


@pytest.mark.parametrize('model,stereo_bus', [
    ('motuultralite', False), ('profire2626', False),
    ('saffirepro40', False), ('profire2626', True),
])
def test_scoped_snapshot_matches_full_snapshot_with_fewer_hardware_reads(model, stereo_bus):
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer(model, Config(None))
        get_cell = mixer.helper.get_cell
        reads = []
        def counted_get(path, row, col):
            reads.append((path, row, col))
            return get_cell(path, row, col)
        mixer.helper.get_cell = counted_get
        full = mixer.read_mix(2, stereo_bus=stereo_bus)
        full_count = len(reads)
        reads.clear()
        channels = ('ch/04', 'ch/01')
        scoped = mixer.read_mix(2, stereo_bus=stereo_bus, channels=channels)
    assert scoped == {channel: full[channel] for channel in channels}
    buses = (2, 3) if stereo_bus else (2,)
    expected = {(mixer.roles['fader'][0], *mixer._coordinates(bus, col))
                for bus in buses for col in (1, 4)}
    assert set(reads) == expected
    assert len(reads) == len(expected) < full_count


@pytest.mark.parametrize('control', ['fader', 'gain', 'invert', 'mute', 'solo', 'pan'])
def test_paired_api_snapshots_only_the_linked_demo_channels(control):
    mixer, config = DemoMixer(), Config(None)
    config.link('ch/04', 'ch/01', 2)
    read = mixer.read_mix
    snapshots = []
    def snapshot(mix, **kwargs):
        state = read(mix, **kwargs)
        snapshots.append((mix, set(state)))
        return state
    mixer.read_mix = snapshot
    value = True if control in ('invert', 'mute', 'solo') else .3 if control == 'pan' else 30
    for app, events in api(mixer, config, {
            'strip': 'ch/04', 'mix': 2, 'control': control, 'value': value}):
        assert app.set_value() == {'ok': True}
        assert snapshots == [(2, {'ch/04', 'ch/01'})]
        assert len(events) == 1


def test_native_paired_fader_does_not_read_a_failing_unrelated_channel():
    config = Config(None)
    config.link('ch/04', 'ch/01', 2)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer('motuultralite', config)
        get_cell = mixer.helper.get_cell
        allowed = {(mixer.roles['fader'][0], *mixer._coordinates(2, col)) for col in (1, 4)}
        reads = []
        def pair_only_get(path, row, col):
            reads.append((path, row, col))
            if (path, row, col) not in allowed:
                raise OSError('unrelated channel is unavailable')
            return get_cell(path, row, col)
        mixer.helper.get_cell = pair_only_get
        for app, events in api(mixer, config, {
                'strip': 'ch/04', 'mix': 2, 'control': 'fader', 'value': 30}):
            assert app.set_value() == {'ok': True}
            assert len(events) == 1
        assert set(reads) == allowed
        assert len(reads) == 2
        expected = mixer._from_ui(30, mixer.roles['fader'][1])
        assert all(get_cell(*cell) == expected for cell in allowed)


def test_scoped_snapshot_skips_unrelated_channel_controls():
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer('profire2626', Config(None))
        mixer.chan[1] = {'gain': {'path': '/test/channel/1/gain', 'kind': 'Discrete'}}
        mixer.chan[2] = {'gain': {'path': '/test/channel/2/gain', 'kind': 'Discrete'}}
        get_value = mixer.helper.get_value
        reads = []
        def channel_get(path, kind):
            reads.append(path)
            if path == '/test/channel/2/gain':
                raise OSError('unrelated gain control is unavailable')
            return get_value(path, kind)
        mixer.helper.get_value = channel_get
        state = mixer.read_mix(0, channels=('ch/01', 'ch/04'))
    assert set(state) == {'ch/01', 'ch/04'}
    assert '/test/channel/1/gain' in reads
    assert '/test/channel/2/gain' not in reads
