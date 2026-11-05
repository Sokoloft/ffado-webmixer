"""Channel strip mutes survive clean software restarts on each bus."""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.device_manager import DeviceManager
from ffado_webmixer.profiles.resolver import resolve_controls


def start(path, profile, cells=None):
    settings = Config(path)
    settings.load()
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer(profile, settings)
        if profile == 'motuultralite':
            # Live MOTU discovery supplies a separate native mute matrix.
            matrix = {**mixer.device['matrices'][0], 'name': 'mute',
                      'path': mixer.device['device'] + '/Mixer/mute'}
            mixer.device['matrices'].append(matrix)
            resolved = resolve_controls(mixer.device, mixer.profile,
                                        {'fader': mixer.roles['fader'][0], 'mute': matrix['path']},
                                        mixer.columns, mixer.mixes)
            mixer.roles = resolved['roles']
            for bus in range(len(mixer.mixes)):
                for col in range(len(mixer.columns)):
                    mixer.helper.cells[matrix['path'], bus, col] = 0
        if cells is not None:
            mixer.helper.cells = dict(cells)
        DeviceManager([mixer], settings)
    return mixer


@pytest.mark.parametrize('profile', ['profire2626', 'saffirepro40', 'motuultralite'])
def test_channel_mute_recalls_per_bus_and_can_be_unmuted(tmp_path, profile):
    path = tmp_path / 'config.json'
    mixer = start(path, profile)
    original = mixer.read_mix(0)['ch/00']['fader']
    mixer.write(0, 'ch/00', 'mute', True)
    mixer.write(1, 'ch/01', 'mute', True)
    mixer.shutdown_soft_mutes()
    restored = start(path, profile)
    assert restored.read_mix(0)['ch/00']['mute']
    assert not restored.read_mix(0)['ch/01']['mute']
    assert not restored.read_mix(1)['ch/00']['mute']
    assert restored.read_mix(1)['ch/01']['mute']
    assert restored.read_mix(0)['ch/00']['fader'] == pytest.approx(original)
    assert restored.mute_recovery_status()['pending'] == 0
    restored.write(0, 'ch/00', 'mute', False)
    assert not restored.read_mix(0)['ch/00']['mute']
    assert restored.read_mix(0)['ch/00']['fader'] == pytest.approx(original)
    restored.shutdown_soft_mutes()
    again = start(path, profile)
    assert not again.read_mix(0)['ch/00']['mute']
    assert again.read_mix(1)['ch/01']['mute']


@pytest.mark.parametrize('profile', ['profire2626', 'motuultralite'])
def test_channel_mute_save_failure_rolls_back(tmp_path, profile):
    mixer = start(tmp_path / 'config.json', profile)
    before = mixer.read_mix(0)['ch/00']
    def fail():
        raise OSError('disk unavailable')
    mixer.config.save = fail
    with pytest.raises((OSError, RuntimeError), match='disk unavailable'):
        mixer.write(0, 'ch/00', 'mute', True)
    assert mixer.read_mix(0)['ch/00'] == before
    assert mixer.config.channel_mutes == {}


def test_stereo_group_mute_survives_restart(tmp_path):
    path = tmp_path / 'config.json'
    mixer = start(path, 'profire2626')
    mixer.write_group_mute((0, 1), (0, 1), True)
    mixer.shutdown_soft_mutes()
    restored = start(path, 'profire2626')
    for bus in (0, 1):
        assert all(restored.read_mix(bus)[f'ch/{col:02d}']['mute'] for col in (0, 1))
        assert not restored.read_mix(bus)['ch/02']['mute']


def test_saved_channel_level_and_bus_gain_survive_restart(tmp_path):
    path = tmp_path / 'config.json'
    mixer = start(path, 'saffirepro40')
    mixer.write_output('bus/0', 'fader', 60)
    mixer.write(0, 'ch/00', 'mute', True)
    mixer.write(0, 'ch/00', 'fader', 47)
    level = mixer.read_mix(0)['ch/00']['fader']
    mixer.shutdown_soft_mutes()
    restored = start(path, 'saffirepro40', mixer.helper.cells)
    assert restored.read_mix(0)['ch/00']['mute']
    assert restored.read_mix(0)['ch/00']['fader'] == pytest.approx(level)
    assert restored.read_output('bus/0')['level'] == 60
    restored.write(0, 'ch/00', 'mute', False)
    assert restored.read_mix(0)['ch/00']['fader'] == pytest.approx(level)


def test_other_device_layout_does_not_recall_channel_mutes(tmp_path):
    path = tmp_path / 'config.json'
    mixer = start(path, 'profire2626')
    mixer.write(0, 'ch/00', 'mute', True)
    mixer.shutdown_soft_mutes()
    mixer.config.channel_mutes['columns'][0] = 'different input'
    mixer.config.save()
    restored = start(path, 'profire2626')
    assert not restored.read_mix(0)['ch/00']['mute']
