"""Regression: a linked output pair's strip must reflect its matrix legs."""
from contextlib import nullcontext
from unittest.mock import Mock

from ffado_webmixer.mixer import Mixer


def fake_mixer(left, right):
    m = Mixer.__new__(Mixer)
    m.mixes = ['Out 1', 'Out 2']
    m.roles = {'fader': ('fake', {'type': 'dice_db'})}
    m.helper = Mock()
    m.helper.transaction.side_effect = lambda: nullcontext()
    values = {0: left, 1: right}
    m._cell_base = lambda bus, col: values[bus]
    m._to_ui = lambda raw, spec: raw
    m._from_ui = lambda ui, spec: ui
    m._require_recovery_resolved = lambda: None
    writes = []
    m._write_gain_cell = lambda bus, col, raw: writes.append((bus, col, raw))
    return m, writes


def test_linked_bus_fader_reflects_active_leg_not_average():
    m, _ = fake_mixer(100, 0)
    assert m.read_stereo_level(0, 0) == 100
    m, _ = fake_mixer(100, 100)
    assert m.read_stereo_level(0, 0) == 100


def test_linked_bus_fader_preserves_matrix_balance_on_write():
    m, writes = fake_mixer(100, 0)
    m.write_stereo_level(0, 0, 70)
    assert writes == [(0, 0, 70), (1, 0, 0)]
    m, writes = fake_mixer(100, 25)
    m.write_stereo_level(0, 0, 80)
    assert writes == [(0, 0, 80), (1, 0, 20)]


def test_silent_linked_bus_stays_disconnected():
    m, writes = fake_mixer(0, 0)
    m.write_stereo_level(0, 0, 40)
    assert writes == []  # absent L/R routes must not be created by the fader
