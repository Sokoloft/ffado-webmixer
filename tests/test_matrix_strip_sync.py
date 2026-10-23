"""Regression: a linked output pair's fader must work from absolute silence."""
from contextlib import nullcontext
from unittest.mock import Mock

from ffado_webmixer.mixer import Mixer


def fake_mixer(left, right):
    m = Mixer.__new__(Mixer)
    m.mixes = ['Out 1', 'Out 2']
    m.columns = ['Input 1']
    m.matrix = {'mode': 'dice_db'}
    m.roles = {'fader': ('fake', {'type': 'dice_db'})}
    m.helper = Mock()
    m.helper.transaction.side_effect = lambda: nullcontext()
    values = {0: left, 1: right}
    m._cell_base = lambda bus, col: values[bus]
    m._to_ui = lambda raw, spec: raw
    m._from_ui = lambda ui, spec: ui
    m._require_recovery_resolved = lambda: None
    writes = []
    def do_write(bus, col, raw):
        writes.append((bus, col, raw))
        values[bus] = raw
    m._write_gain_cell = do_write
    return m, values, writes


def test_linked_bus_fader_reflects_active_leg_not_average():
    m, _, _ = fake_mixer(100, 0)
    assert m.read_stereo_level(0, 0) == 100
    m, _, _ = fake_mixer(100, 100)
    assert m.read_stereo_level(0, 0) == 100


def test_linked_bus_fader_preserves_matrix_balance_on_write():
    m, _, writes = fake_mixer(100, 0)
    m.write_stereo_level(0, 0, 70)
    assert writes == [(0, 0, 70)]
    m, values, writes = fake_mixer(100, 25)
    m.write_stereo_level(0, 0, 80)
    assert values == {0: 80, 1: 20}


def test_silent_mono_channel_can_be_raised_in_stereo_bus():
    m, values, writes = fake_mixer(0, 0)
    m.write_stereo_level(0, 0, 40)
    assert values == {0: 40, 1: 40}
    assert writes == [(0, 0, 40), (1, 0, 40)]


def test_fader_can_be_lowered_to_infinity_and_raised_again_without_losing_pan():
    m, values, writes = fake_mixer(100, 25)
    m.write_stereo_level(0, 0, 0)
    assert values == {0: 0, 1: 0}
    m.write_stereo_level(0, 0, 80)
    assert values == {0: 80, 1: 20}


def test_silence_readback_sentinel_does_not_lose_saved_pan():
    m, values, _ = fake_mixer(100, 25)
    m.write_stereo_level(0, 0, 0)
    # Some DICE versions return the native silence sentinel 16 for zero.
    values[0] = 16
    values[1] = 16
    m.write_stereo_level(0, 0, 75)
    assert values == {0: 75, 1: 19}
