"""Persisted preferences are validated before becoming live mixer state."""
import json
from copy import deepcopy

import pytest

from ffado_webmixer.config import Config, DEFAULT_SETTINGS


@pytest.mark.parametrize('saved', [
    None, [], 17, 'preferences',
    {'settings': None}, {'settings': []},
    {'names': []}, {'names': {'ch/00': 12}},
    {'stereo': {}}, {'stereo_by_mix': []},
    {'layouts': []}, {'layouts': {'0': None}}, {'layouts': {'0': [None]}},
    {'layouts': {'no bus': []}},
    {'layouts': {'0': [{'id': 'ch/00', 'pinned': 'false'}]}},
    {'layouts': {'0': [{'id': 'ch/00'}, {'id': 'ch/00'}]}},
    {'bus_layout': {}}, {'bus_layout': [{'id': 'unknown'}]},
    {'layout': None}, {'layout': [{'id': ''}]},
    {'mute_memory': []}, {'mute_memory': {'main': 'loud'}},
    {'mute_memory': {'main': True}},
])
def test_malformed_saved_structure_is_preserved_and_replaced_with_defaults(tmp_path, saved):
    path = tmp_path / 'config.json'
    original = json.dumps(saved).encode()
    path.write_bytes(original)
    config = Config(path)

    config.load()

    assert path.with_suffix('.json.bad').read_bytes() == original
    assert config.settings == DEFAULT_SETTINGS
    assert config.names == config.layouts == config.mute_memory == {}
    assert json.loads(path.read_text())['settings'] == DEFAULT_SETTINGS
    # The recovery output can itself be loaded without another recovery.
    Config(path).load()
    assert len(list(tmp_path.glob('*.bad*'))) == 1


@pytest.mark.parametrize('settings', [
    {'hide_minimized': 'false'}, {'desktop_integration_prompted': 0},
    {'skip_loading_screen': None}, {'_startup_preferences_migrated': 'yes'},
    {'mix': True}, {'mix': -1}, {'side_width': 10.5}, {'output': None},
    {'last_device_guid': []}, {'device_alias': {}},
    {'window_size': None}, {'window_size': {'width': True}},
    {'window_size': {'height': -1}},
    {'theme': '../light'}, {'theme': '..\\light'}, {'theme': []},
    {'accent_overrides': None}, {'accent_overrides': {'dark': 'red'}},
    {'accent_overrides': {'../custom': '#112233'}},
    {'accent_overrides': {'..\\custom': '#112233'}},
])
def test_invalid_known_setting_rejects_the_whole_snapshot(tmp_path, settings):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'settings': {'hide_minimized_buses': True, **settings},
                                'names': {'ch/00': 'Should not be applied'}}))
    config = Config(path)

    config.load()

    assert config.settings == DEFAULT_SETTINGS
    assert config.names == {}
    assert path.with_suffix('.json.bad').exists()


@pytest.mark.parametrize('buses', [
    None, {}, '0', False, True, [False], [True], [0, True],
    [-2], [1], [2.0], ['2'], [None], [{}], [[]], [0, 0],
])
def test_invalid_stereo_bus_settings_are_recovered_before_application(tmp_path, buses):
    path = tmp_path / 'config.json'
    original = json.dumps({'settings': {'stereo_buses': buses, 'theme': 'light'},
                           'names': {'ch/00': 'Should not be applied'}})
    path.write_text(original)
    config = Config(path)

    config.load()

    assert config.settings == DEFAULT_SETTINGS
    assert config.names == {}
    assert path.with_suffix('.json.bad').read_text() == original


@pytest.mark.parametrize('buses', [[], [0], [0, 4, 2]])
def test_valid_stereo_bus_settings_preserve_explicit_values(tmp_path, buses):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'settings': {'stereo_buses': buses}}))
    config = Config(path)

    config.load()
    config.save()
    reloaded = Config(path)
    reloaded.load()

    assert config.settings['stereo_buses'] == buses
    assert reloaded.settings['stereo_buses'] == buses
    assert not path.with_suffix('.json.bad').exists()


@pytest.mark.parametrize('literal', ['NaN', 'Infinity', '-Infinity', '1e999'])
def test_nonfinite_json_numbers_are_recovered_even_in_unknown_settings(tmp_path, literal):
    path = tmp_path / 'config.json'
    original = '{"settings": {"future_setting": ' + literal + '}}'
    path.write_text(original)

    Config(path).load()

    assert path.with_suffix('.json.bad').read_text() == original
    assert json.loads(path.read_text())['settings'] == DEFAULT_SETTINGS


def test_late_validation_failure_cannot_mutate_existing_live_state(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'settings': {'theme': 'light'},
                                'names': {'ch/01': 'New name'},
                                'layout': [None]}))
    config = Config(path)
    config.settings['theme'] = 'nordic'
    config.names['ch/00'] = 'Existing name'
    config.layouts['0'] = [{'id': 'ch/00'}]
    config.mute_memory['main'] = 200
    before = deepcopy((config.settings, config.names, config.layouts, config.mute_memory))

    config.load()

    assert (config.settings, config.names, config.layouts, config.mute_memory) == before
    assert json.loads(path.read_text())['names'] == {'ch/00': 'Existing name'}


def test_each_recovery_keeps_earlier_backups(tmp_path):
    path = tmp_path / 'config.json'
    backup = path.with_suffix('.json.bad')
    second_backup = path.with_suffix('.json.bad.1')
    backup.write_text('first broken file')
    second_backup.write_text('second broken file')
    path.write_bytes(b'\xffinvalid UTF-8')

    Config(path).load()

    assert backup.read_text() == 'first broken file'
    assert second_backup.read_text() == 'second broken file'
    assert path.with_suffix('.json.bad.2').read_bytes() == b'\xffinvalid UTF-8'


def test_valid_legacy_preferences_and_unknown_settings_migrate_without_loss(tmp_path):
    source = tmp_path / 'legacy.json'
    path = tmp_path / 'devices' / 'config.json'
    saved = {
        'settings': {'theme': 'custom-theme', 'mix': '2', 'side_width': '240',
                     'window_size': {'width': 1400},
                     'future_setting': {'list': ['custom', None, 2.5]},
                     '_startup_preferences_migrated': True},
        'names': {'ch/00': 'Vocal'},
        'stereo': [['ch/00', 'ch/01'], ['ch/00', 'ch/02'], ['bad']],
        'stereo_by_mix': {'1': [], '2': [['ch/02', 'ch/03']]},
        'layout': [{'id': 'ch/00', 'pinned': False, 'custom_layout_flag': True}],
        'layouts': {'2': [{'id': 'ch/02', 'minimized': True}]},
        'bus_layout': [{'id': '2', 'pinned': False}],
        'mute_memory': {'main': 123.5},
    }
    source.write_text(json.dumps(saved))
    original = source.read_bytes()
    config = Config(path)
    memory = config.mute_memory

    config.load(migrate_from=source)

    assert source.read_bytes() == original
    assert config.settings['theme'] == 'custom-theme'
    assert config.settings['mix'] == 2
    assert config.settings['side_width'] == 240
    assert config.settings['window_size'] == {'width': 1400, 'height': 800}
    assert config.settings['future_setting'] == saved['settings']['future_setting']
    assert config.settings['_startup_preferences_migrated'] is True
    assert config.pairs_for(0) == [['ch/00', 'ch/01']]
    assert config.pairs_for(1) == []
    assert config.pairs_for(2) == [['ch/02', 'ch/03']]
    assert config.layout_for(0) == saved['layout']
    assert config.layout_for(2) == saved['layouts']['2']
    assert config.bus_layout == saved['bus_layout']
    assert memory is config.mute_memory and memory == {'main': 123.5}
    loaded = Config(path)
    loaded.load()
    assert loaded.settings == config.settings
    assert loaded.layout_for(0) == config.layout_for(0)
    assert loaded.mute_memory == config.mute_memory


def test_invalid_migration_source_is_left_untouched(tmp_path):
    source = tmp_path / 'legacy.json'
    source.write_text('{"settings": null}')
    path = tmp_path / 'new' / 'config.json'
    config = Config(path)

    config.load(migrate_from=source)

    assert source.read_text() == '{"settings": null}'
    assert not path.exists()
    assert config.settings == DEFAULT_SETTINGS


def test_existing_config_takes_precedence_over_migration_source(tmp_path):
    source = tmp_path / 'legacy.json'
    source.write_text('{"settings": {"theme": "light"}}')
    path = tmp_path / 'config.json'
    path.write_text('{"settings": {"theme": "nordic"}}')
    config = Config(path)

    config.load(migrate_from=source)

    assert config.settings['theme'] == 'nordic'
    assert not path.with_suffix('.json.bad').exists()
