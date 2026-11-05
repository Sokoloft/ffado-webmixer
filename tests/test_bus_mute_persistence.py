"""Native bus mute recall uses the GUID-specific settings after each restart."""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.device_manager import DeviceManager
from ffado_webmixer.profiles.resolver import match_outputs


def backend(config):
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer('motuultralite', config)
    # The generic debug fixture omits native mute controls. Supply the
    # source-mapped MOTU controls that live discovery reports.
    for number in range(1, 5):
        mixer.device['controls'].append({
            'path': mixer.device['device'] + f'/Mixer/Mix{number}/Mix_mute',
            'kind': 'Discrete'})
    mixer.outputs = match_outputs(mixer.device, mixer.mixes, mixer.profile)
    return mixer


def start(path):
    settings = Config(path)
    settings.load()
    mixer = backend(settings)
    DeviceManager([mixer], settings)
    return mixer


@pytest.mark.parametrize('muted', [True, False])
def test_native_bus_mute_survives_restart(tmp_path, muted):
    path = tmp_path / 'config.json'
    mixer = start(path)
    mixer.write_output('bus/0', 'mute', not muted)
    mixer.write_output('bus/0', 'mute', muted)
    saved = Config(mixer.config.path)
    saved.load()
    assert saved.bus_mutes == {'bus/0': muted}
    # Simulate a fresh device state with the opposite mute value.
    settings = Config(path)
    settings.load()
    restored = backend(settings)
    restored._write_scalar(restored.outputs['bus/0']['mute'], not muted)
    DeviceManager([restored], settings)
    assert restored.read_output('bus/0')['mute'] is muted
    assert restored.read_output('bus/1')['mute'] is False
    restored.shutdown_soft_mutes()
    assert restored.read_output('bus/0')['mute'] is muted
    assert start(path).read_output('bus/0')['mute'] is muted


def test_failed_bus_mute_save_restores_hardware_and_preferences(tmp_path):
    mixer = start(tmp_path / 'config.json')
    mixer.write_output('bus/0', 'mute', True)
    def fail():
        raise OSError('settings unavailable')
    mixer.config.save = fail
    with pytest.raises(OSError, match='settings unavailable'):
        mixer.write_output('bus/0', 'mute', False)
    assert mixer.read_output('bus/0')['mute'] is True
    saved = Config(mixer.config.path)
    saved.load()
    assert mixer.config.bus_mutes == saved.bus_mutes == {'bus/0': True}


def test_rejected_hardware_mute_is_not_saved(tmp_path):
    mixer = start(tmp_path / 'config.json')
    mixer._write_scalar = lambda *args: None
    with pytest.raises(OSError, match='acknowledge'):
        mixer.write_output('bus/0', 'mute', True)
    assert mixer.config.bus_mutes == {}


def test_failed_recall_reports_fault_and_keeps_saved_mute(tmp_path):
    path = tmp_path / 'config.json'
    mixer = start(path)
    mixer.write_output('bus/0', 'mute', True)
    settings = Config(path)
    settings.load()
    restored = backend(settings)
    restored._write_scalar = lambda *args: None
    DeviceManager([restored], settings)
    assert 'Could not load saved bus mutes' in restored.mute_recovery_status()['fault']
    assert restored.config.bus_mutes == {'bus/0': True}
