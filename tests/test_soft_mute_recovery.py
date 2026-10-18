"""Regression tests for durable, hardware-verified software mute/solo.

Mock D-Bus device: no FFADO connection or actual audio hardware required.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.soft_mute import MuteJournal


class UnreliableHelper:
    """Wrap the debug helper and simulate FFADO rejecting selected writes."""
    def __init__(self, wrapped):
        self.real = wrapped
        self.fail = None
        self.ignore = False
        self.events = []

    def __getattr__(self, item):
        return getattr(self.real, item)

    def set_value(self, path, kind, value):
        self.events.append((path, value))
        if self.fail is not None and self.fail(path, kind, value):
            raise IOError('hardware refused output setValue')
        if self.ignore:
            return
        return self.real.set_value(path, kind, value)

    def set_cell(self, path, row, col, value):
        self.events.append((row, col, value))
        if self.fail is not None and self.fail(row, col, value):
            raise IOError('hardware refused setValue')
        if self.ignore:
            return
        return self.real.set_cell(path, row, col, value)


class SoftwareMuteRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'devices' / 'example.json'
        self.config = Config(self.path)
        with contextlib.redirect_stdout(io.StringIO()):
            self.mixer = make_debug_mixer('profire2626', self.config)
        self.mixer.helper = UnreliableHelper(self.mixer.helper)
        self.mixer.attach_mute_recovery()
        self.matrix = self.mixer.roles['fader'][0]

    def action(self, col=0, control='mute', state=True, mix=0):
        with contextlib.redirect_stdout(io.StringIO()):
            return self.mixer.write(mix, f'ch/{col:02d}', control, state)

    def cell(self, col=0, mix=0):
        return self.mixer._get_cell(self.matrix, mix, col)

    def test_journal_is_saved_before_hardware_is_muted(self):
        def check(row, col, value):
            if value == 0:
                self.assertTrue(self.mixer._recovery_journal.path.is_file())
                self.assertEqual(self.mixer._recovery_journal.load()[(0, 0)], 16384)
            return False
        self.mixer.helper.fail = check
        self.action()
        self.assertEqual(self.cell(), 0)
        self.assertEqual(len(self.mixer._matrix_mutes), 1)
        self.action(state=False)
        self.assertEqual(self.cell(), 16384)
        self.assertFalse(self.mixer._recovery_journal.path.exists())

    def test_interrupted_session_requires_explicit_recovery(self):
        self.action()
        with contextlib.redirect_stdout(io.StringIO()):
            other = make_debug_mixer('profire2626', self.config)
        other.helper = self.mixer.helper
        other.attach_mute_recovery()
        self.assertEqual(other.mute_recovery_status()['pending'], 1)
        self.assertEqual(self.cell(), 0, 'initialization must never restore gain automatically')
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            other.write(0, 'ch/00', 'mute', True)
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            other.matrix_set(0, 0, db=-3, use_db=True)
        result = other.resolve_mute_recovery('restore')
        self.assertEqual(result['restored'], 1)
        self.assertEqual(result['pending'], 0)
        self.assertEqual(self.cell(), 16384)
        self.assertFalse(other._recovery_journal.path.exists())

    def test_restore_respects_external_nonzero_gain(self):
        self.action()
        self.mixer.helper.real.cells[(self.matrix, 0, 0)] = 8192
        with contextlib.redirect_stdout(io.StringIO()):
            other = make_debug_mixer('profire2626', self.config)
        other.helper = self.mixer.helper
        other.attach_mute_recovery()
        outcome = other.resolve_mute_recovery('restore')
        self.assertEqual((outcome['restored'], outcome['discarded']), (0, 1))
        self.assertEqual(self.cell(), 8192)

    def test_discard_keeps_mixer_silent(self):
        self.action()
        with contextlib.redirect_stdout(io.StringIO()):
            other = make_debug_mixer('profire2626', self.config)
        other.helper = self.mixer.helper
        other.attach_mute_recovery()
        self.assertEqual(other.resolve_mute_recovery('discard')['discarded'], 1)
        self.assertEqual(self.cell(), 0)
        self.assertFalse(other._recovery_journal.path.exists())

    def test_external_nonzero_edit_cancels_suppression_without_overwriting(self):
        self.action()
        self.mixer.helper.real.cells[(self.matrix, 0, 0)] = 21000
        with contextlib.redirect_stdout(io.StringIO()):
            data = self.mixer.read_mix(0)
        self.assertEqual(self.cell(), 21000)
        self.assertFalse(data['ch/00']['mute'])
        self.assertNotIn((0, 0), self.mixer._matrix_mutes)
        self.assertFalse(self.mixer._recovery_journal.path.exists())
        self.assertIsNotNone(self.mixer.mute_recovery_status()['fault'])

    def test_failed_unmute_retains_original_level_for_retry(self):
        self.action()
        self.mixer.helper.fail = lambda r, c, value: value != 0
        with self.assertRaisesRegex(RuntimeError, 'hardware refused'):
            self.action(state=False)
        self.assertEqual(self.cell(), 0)
        self.assertEqual(self.mixer._recovery_journal.load()[(0, 0)], 16384)
        self.assertIn((0, 0), self.mixer._user_mutes)
        self.mixer.helper.fail = None
        self.action(state=False)
        self.assertEqual(self.cell(), 16384)
        self.assertFalse(self.mixer._recovery_journal.path.exists())

    def test_unacknowledged_write_rolls_back_and_preserves_journal(self):
        self.mixer.helper.ignore = True
        with self.assertRaisesRegex(RuntimeError, 'did not apply mixer value'):
            self.action()
        self.assertEqual(self.cell(), 16384)
        self.assertFalse(self.mixer._user_mutes)
        self.assertFalse(self.mixer._recovery_journal.path.exists())

    def test_solo_rollback_on_partial_failure(self):
        self.mixer.helper.fail = lambda r, c, value: value == 0 and r == 2
        with self.assertRaises(RuntimeError):
            self.action(control='solo')
        self.assertFalse(self.mixer._solos)
        self.assertEqual(self.cell(col=1), 16384)
        self.assertEqual(self.cell(col=2), 16384)
        self.assertFalse(self.mixer._recovery_journal.path.exists())

    def test_gain_edit_while_muted_is_durable_for_recovery(self):
        self.action()
        with contextlib.redirect_stdout(io.StringIO()):
            self.mixer.matrix_set(0, 0, db=-14.6, use_db=True)
        new_raw = self.mixer._matrix_mutes[(0, 0)]
        self.assertEqual(self.mixer._recovery_journal.load()[(0, 0)], new_raw)
        self.assertEqual(self.cell(), 0)
        self.mixer.shutdown_soft_mutes()
        self.assertAlmostEqual(self.cell(), new_raw, delta=1)
        self.assertFalse(self.mixer._recovery_journal.path.exists())

    def test_bus_balance_and_stereo_level_update_journal(self):
        self.action(col=0, mix=0)
        with contextlib.redirect_stdout(io.StringIO()):
            self.mixer.write_bus_balance(0, 0, -0.5)
            self.mixer.write_stereo_level(0, 0, 57.25)
        self.assertEqual(self.cell(), 0)
        self.assertEqual(self.mixer._recovery_journal.load()[(0, 0)], self.mixer._matrix_mutes[(0, 0)])

    def test_recovery_failure_keeps_entry_for_retry(self):
        self.action()
        with contextlib.redirect_stdout(io.StringIO()):
            other = make_debug_mixer('profire2626', self.config)
        other.helper = self.mixer.helper
        other.attach_mute_recovery()
        self.mixer.helper.fail = lambda r, c, value: value != 0
        failed = other.resolve_mute_recovery('restore')
        self.assertEqual(failed['failed'], 1)
        self.assertEqual(failed['pending'], 1)
        self.assertEqual(self.cell(), 0)
        self.mixer.helper.fail = None
        self.assertEqual(other.resolve_mute_recovery('restore')['restored'], 1)

    def test_corrupt_or_other_device_journal_is_not_replayed(self):
        self.action()
        guard = MuteJournal(self.path, 'other-guid', self.matrix)
        with self.assertRaisesRegex(ValueError, 'identity'):
            guard.load()
        with contextlib.redirect_stdout(io.StringIO()):
            other = make_debug_mixer('profire2626', self.config)
        other.helper = self.mixer.helper
        self.mixer._recovery_journal.path.write_text('broken json')
        other.attach_mute_recovery()
        self.assertIsNotNone(other.mute_recovery_status()['fault'])
        with self.assertRaisesRegex(RuntimeError, 'unreadable'):
            other.write(0, 'ch/00', 'mute', False)

    def test_emulated_output_mute_recovers_and_checks_readback(self):
        with contextlib.redirect_stdout(io.StringIO()):
            m = make_debug_mixer('motuultralite', self.config)
        m.helper = UnreliableHelper(m.helper)
        m.attach_mute_recovery()
        out = 'bus/0'
        fader = m._output(out)['fader']
        with contextlib.redirect_stdout(io.StringIO()):
            m.write_output(out, 'fader', 75)
        start = m.helper.get_value(fader['path'], fader['kind'])
        with contextlib.redirect_stdout(io.StringIO()):
            m.write_output(out, 'mute', True)
        self.assertEqual(m.helper.get_value(fader['path'], fader['kind']), m.out_spec['min'])
        self.assertIn(out, m.mute_memory)
        with contextlib.redirect_stdout(io.StringIO()):
            m.write_output(out, 'mute', False)
        self.assertEqual(m.helper.get_value(fader['path'], fader['kind']), start)
        self.assertNotIn(out, m.mute_memory)

    def test_emulated_output_restoration_failure_keeps_saved_level(self):
        with contextlib.redirect_stdout(io.StringIO()):
            m = make_debug_mixer('motuultralite', self.config)
        m.helper = UnreliableHelper(m.helper)
        m.attach_mute_recovery()
        out = 'bus/0'
        fader = m._output(out)['fader']
        with contextlib.redirect_stdout(io.StringIO()):
            m.write_output(out, 'fader', 75)
            m.write_output(out, 'mute', True)
        m.helper.fail = lambda path, kind, val: path == fader['path'] and val != m.out_spec['min']
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(IOError, 'hardware refused'):
                m.write_output(out, 'mute', False)
        self.assertIn(out, m.mute_memory)
        with contextlib.redirect_stdout(io.StringIO()):
            other = make_debug_mixer('motuultralite', self.config)
        other.helper = m.helper
        other.mute_memory = dict(m.mute_memory)
        other.attach_mute_recovery()
        self.assertIn(out, other.mute_recovery_status()['outputs'])
        m.helper.fail = None
        with contextlib.redirect_stdout(io.StringIO()):
            result = other.resolve_mute_recovery('restore')
        self.assertEqual(result['restored'], 1)
        self.assertEqual(result['pending'], 0)

    def test_emulated_output_external_edit_preserved(self):
        with contextlib.redirect_stdout(io.StringIO()):
            m = make_debug_mixer('motuultralite', self.config)
        m.helper = UnreliableHelper(m.helper)
        m.attach_mute_recovery()
        out = 'bus/0'
        fader = m._output(out)['fader']
        with contextlib.redirect_stdout(io.StringIO()):
            m.write_output(out, 'fader', 75)
            m.write_output(out, 'mute', True)
        m.helper.real.values[fader['path']] = 33
        with contextlib.redirect_stdout(io.StringIO()):
            m.write_output(out, 'mute', False)
        self.assertEqual(m.helper.get_value(fader['path'], fader['kind']), 33)
        self.assertNotIn(out, m.mute_memory)

    def test_debug_has_no_persistent_journal(self):
        self.mixer.attach_mute_recovery(debug=True)
        self.action()
        self.assertIsNone(self.mixer._recovery_journal.path)
        self.assertFalse((self.path.parent / (self.path.stem + '.mute-recovery.json')).exists())


if __name__ == '__main__':
    unittest.main()
