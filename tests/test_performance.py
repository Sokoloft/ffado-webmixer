"""Performance guards: fewer FFADO reads with unchanged live gain/mute behavior."""
import contextlib
import io
import unittest
from collections import Counter

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.gain import raw_to_ui, raw_to_db


class StereoBusReadEfficiency(unittest.TestCase):
    def mixer(self, model='profire2626'):
        with contextlib.redirect_stdout(io.StringIO()):
            return make_debug_mixer(model, Config(None))

    def capture_reads(self, mixer, **options):
        calls = []
        get_cell = mixer.helper.get_cell
        def track(*args):
            calls.append(args)
            return get_cell(*args)
        mixer.helper.get_cell = track
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                state = mixer.read_mix(0, **options)
        finally:
            mixer.helper.get_cell = get_cell
        return state, Counter(calls)

    def test_stereo_bus_reads_each_fader_coefficient_once(self):
        mixer = self.mixer()
        state, calls = self.capture_reads(mixer, stereo_bus=True)
        path = mixer.roles['fader'][0]
        for col in (int(key.split("/")[1]) for key in state):
            for bus in (0, 1):
                self.assertEqual(calls[(path, *mixer._coordinates(bus, col))], 1)
        self.assertEqual(sum(calls.values()), 2 * len(state))

    def test_rme_stereo_buses_preserve_native_balance(self):
        mixer = self.mixer('fireface400')
        path = mixer.roles['fader'][0]
        left, right = 12345, 4321
        mixer.helper.cells[(path, *mixer._coordinates(0, 0))] = left
        mixer.helper.cells[(path, *mixer._coordinates(1, 0))] = right
        state, calls = self.capture_reads(mixer, stereo_bus=True)
        first = state['ch/00']
        self.assertEqual(first['_matrix_raw'], [float(left), float(right)])
        self.assertEqual(first['fader'], raw_to_ui(left, 'rme_db'))
        self.assertEqual(first['pan'], round((right - left) / (right + left), 4))
        self.assertEqual(first['matrix_legs'], {
            'left_db': raw_to_db(left, 'rme_db'),
            'right_db': raw_to_db(right, 'rme_db')})
        self.assertEqual(calls[(path, *mixer._coordinates(0, 0))], 1)
        self.assertEqual(calls[(path, *mixer._coordinates(1, 0))], 1)

    def test_mono_bus_reads_unchanged_and_motu_supports_same_path(self):
        for model in ('profire2626', 'motuultralite'):
            with self.subTest(model=model):
                mixer = self.mixer(model)
                state, calls = self.capture_reads(mixer)
                path = mixer.roles['fader'][0]
                for col in (int(key.split("/")[1]) for key in state):
                    self.assertEqual(calls[(path, *mixer._coordinates(0, col))], 1)

    def test_muted_left_leg_reports_original_gain_and_stays_muted(self):
        mixer = self.mixer()
        path = mixer.roles['fader'][0]
        original = 8192
        mixer._matrix_mutes[(0, 0)] = original
        mixer._user_mutes.add((0, 0))
        mixer.helper.cells[(path, *mixer._coordinates(0, 0))] = 0
        mixer.helper.cells[(path, *mixer._coordinates(1, 0))] = 16384
        state, calls = self.capture_reads(mixer, stereo_bus=True)
        first = state['ch/00']
        self.assertEqual(first['_matrix_raw'], [float(original), 16384.0])
        self.assertEqual(first['fader'], raw_to_ui(16384, 'dice_db'))
        self.assertTrue(first['mute_partial'])
        self.assertIn((0, 0), mixer._matrix_mutes)
        self.assertEqual(calls[(path, *mixer._coordinates(0, 0))], 1)

    def test_external_nonzero_overrides_saved_mute_as_before(self):
        mixer = self.mixer()
        path = mixer.roles['fader'][0]
        mixer._matrix_mutes[(0, 0)] = 8192
        mixer._user_mutes.add((0, 0))
        mixer.helper.cells[(path, *mixer._coordinates(0, 0))] = 12288
        mixer.helper.cells[(path, *mixer._coordinates(1, 0))] = 0
        state, calls = self.capture_reads(mixer, stereo_bus=True)
        first = state['ch/00']
        self.assertEqual(first['_matrix_raw'], [12288.0, 0.0])
        self.assertNotIn((0, 0), mixer._matrix_mutes)
        self.assertNotIn((0, 0), mixer._user_mutes)
        self.assertFalse(first['mute'])
        self.assertEqual(calls[(path, *mixer._coordinates(0, 0))], 1)

    def test_right_leg_saved_mute_remains_live_checked(self):
        mixer = self.mixer()
        path = mixer.roles['fader'][0]
        mixer._matrix_mutes[(1, 1)] = 8192
        mixer._user_mutes.add((1, 1))
        mixer.helper.cells[(path, *mixer._coordinates(1, 1))] = 0
        state, calls = self.capture_reads(mixer, stereo_bus=True)
        self.assertEqual(state['ch/01']['_matrix_raw'][1], 8192.0)
        self.assertTrue(state['ch/01']['mute_partial'])
        self.assertEqual(calls[(path, *mixer._coordinates(1, 1))], 1)


if __name__ == '__main__':
    unittest.main()


def test_stereo_snapshot_reloads_hardware_between_requests():
    """The optimization may deduplicate a read, but never cache it across snapshots."""
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer('profire2626', Config(None))
    path = mixer.roles['fader'][0]
    left_cell = (path, *mixer._coordinates(0, 0))
    right_cell = (path, *mixer._coordinates(1, 0))
    before = mixer.read_mix(0, stereo_bus=True)['ch/00']
    # Simulate another FFADO client adjusting the device between UI refreshes.
    mixer.helper.cells[left_cell] = 4096
    mixer.helper.cells[right_cell] = 8192
    after = mixer.read_mix(0, stereo_bus=True)['ch/00']
    assert before['fader'] != after['fader']
    assert after['_matrix_raw'] == [4096.0, 8192.0]
    assert after['matrix_legs']['left_db'] == raw_to_db(4096, 'dice_db')
    assert after['matrix_legs']['right_db'] == raw_to_db(8192, 'dice_db')
