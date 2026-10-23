"""Malformed recovery records must stay on disk and never restore hardware."""
import contextlib
import io
import json

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.device_manager import DeviceManager, SelectedBackend, SelectedConfig
from ffado_webmixer.server import create_app
from ffado_webmixer.soft_mute import MuteJournal
from test_soft_mute_recovery import UnreliableHelper


GUID = '0000000000000001'
MATRIX = '/test/EAP/MatrixMixer'
LEVEL = {'mix': 0, 'column': 1, 'raw': 16384}
RECORD = {'schema': 1, 'guid': GUID, 'matrix_path': MATRIX, 'levels': [LEVEL]}


@pytest.mark.parametrize('record', [
    [], None, True, 12, 'journal', {},
    *(dict(RECORD, schema=value) for value in (None, True, 1.0, '1', 2)),
    *(dict(RECORD, levels=value) for value in (None, {}, 'levels', 1)),
    *(dict(RECORD, levels=[value]) for value in (None, [], 'entry', 1, {})),
    *(dict(RECORD, levels=[dict(LEVEL, **{key: value})])
      for key in ('mix', 'column')
      for value in (None, True, '0', 0.5, -1, [], {}, float('inf'))),
    *(dict(RECORD, levels=[dict(LEVEL, raw=value)])
      for value in (None, True, '16384', [], {}, -1, float('nan'), float('inf'), 10 ** 400)),
    dict(RECORD, levels=[LEVEL, dict(LEVEL)]),
    dict(RECORD, levels=[LEVEL, {'mix': 1, 'column': 2}]),
])
def test_invalid_journal_shape_raises_value_error_and_preserves_bytes(tmp_path, record):
    journal = MuteJournal(tmp_path / 'device.json', GUID, MATRIX)
    original = json.dumps(record).encode('utf-8')
    journal.path.write_bytes(original)
    with pytest.raises(ValueError):
        journal.load()
    assert journal.path.read_bytes() == original


@pytest.mark.parametrize('levels,expected', [
    ([], {}), ([LEVEL], {(0, 1): 16384.0}),
    ([LEVEL, {'mix': 2, 'column': 3, 'raw': 8192.5}], {(0, 1): 16384.0, (2, 3): 8192.5}),
])
def test_valid_schema_one_journals_remain_readable_without_rewriting(tmp_path, levels, expected):
    journal = MuteJournal(tmp_path / 'device.json', GUID, MATRIX)
    journal.path.write_text(json.dumps(dict(RECORD, levels=levels)), encoding='utf-8')
    original = journal.path.read_bytes()
    assert journal.load() == expected
    assert journal.path.read_bytes() == original


def test_missing_journal_remains_absent(tmp_path):
    journal = MuteJournal(tmp_path / 'device.json', GUID, MATRIX)
    assert journal.load() == {}
    assert not journal.path.exists()


def test_excessively_nested_json_uses_the_recoverable_error_path(tmp_path):
    import sys
    journal = MuteJournal(tmp_path / 'device.json', GUID, MATRIX)
    depth = sys.getrecursionlimit() + 50
    original = ('[' * depth + ']' * depth).encode('utf-8')
    journal.path.write_bytes(original)
    with pytest.raises(ValueError):
        journal.load()
    assert journal.path.read_bytes() == original


@pytest.mark.parametrize('malformation', [
    'root_array', 'root_null', 'missing_levels', 'null_levels',
    'infinite_coordinate', 'overflowing_level', 'partial_record', 'invalid_encoding',
])
def test_startup_preserves_bad_journal_and_offers_safe_discard(tmp_path, malformation):
    root = Config(tmp_path / 'config.json')
    root.load()
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer('profire2626', root)
    mixer.helper = UnreliableHelper(mixer.helper)
    matrix = mixer.roles['fader'][0]
    mixer.helper.real.cells[(matrix, *mixer._coordinates(0, 0))] = 0
    path = tmp_path / 'devices' / f'{mixer.guid}.mute-recovery.json'
    path.parent.mkdir()
    record = {'schema': 1, 'guid': mixer.guid, 'matrix_path': mixer.matrix['path'],
              'levels': [{'mix': 0, 'column': 0, 'raw': 16384}]}
    if malformation == 'root_array':
        record = []
    elif malformation == 'root_null':
        record = None
    elif malformation == 'missing_levels':
        del record['levels']
    elif malformation == 'null_levels':
        record['levels'] = None
    elif malformation == 'infinite_coordinate':
        record['levels'][0]['mix'] = float('inf')
    elif malformation == 'overflowing_level':
        record['levels'][0]['raw'] = 10 ** 400
    elif malformation == 'partial_record':
        record['levels'].append(None)  # A valid first entry must never be replayed alone.
    original = b'\xff' if malformation == 'invalid_encoding' else json.dumps(record).encode('utf-8')
    path.write_bytes(original)

    # Exercise the real startup integration and HTTP boundary, without D-Bus.
    manager = DeviceManager([mixer], root)
    backend = SelectedBackend(manager)
    app = create_app(backend, backend.describe(), SelectedConfig(manager), device_manager=manager)
    app.config['TESTING'] = True
    client = app.test_client()
    response = client.get('/api/mute-recovery')
    assert response.status_code == 200
    assert response.json['corrupt'] is True
    assert 'Cannot read software-mute recovery journal' in response.json['fault']
    assert response.json['pending'] == 0 and response.json['channels'] == []
    assert path.read_bytes() == original
    with pytest.raises(RuntimeError, match='unreadable'):
        mixer.write(0, 'ch/00', 'mute', False)
    response = client.post('/api/mute-recovery', json={'action': 'restore'})
    assert response.status_code == 400
    assert 'cannot be restored safely' in response.json['error']
    assert path.read_bytes() == original and not mixer.helper.events

    response = client.post('/api/mute-recovery', json={'action': 'discard'})
    assert response.status_code == 200 and response.json['restored'] == 0
    assert not path.exists() and not mixer.helper.events
    assert mixer.helper.real.cells[(matrix, *mixer._coordinates(0, 0))] == 0
    status = client.get('/api/mute-recovery').json
    assert status['corrupt'] is False and status['fault'] is None
