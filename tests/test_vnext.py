"""Offline regression tests for profile-defined FFADO hardware controls.

No dbus-python, FFADO service, physical device, or Flask is required.
"""
import contextlib
import io
import math
import unittest
from pathlib import Path
from unittest import mock

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer, fixture_names
from ffado_webmixer.device_registry import resolve_device
from ffado_webmixer.profiles.loader import load_profile


class SourceDefinedProfiles(unittest.TestCase):
    def fixture(self, name):
        with contextlib.redirect_stdout(io.StringIO()):
            mixer = make_debug_mixer(name, Config(None))
        return mixer

    def test_fixtures_are_identified_by_explicit_source_profiles(self):
        for name in ('profire2626', 'saffirepro26', 'motuultralite'):
            with self.subTest(name=name):
                mixer = self.fixture(name)
                self.assertTrue(mixer.profile['device_profile'].endswith('.xml'))
                self.assertTrue(mixer.describe()['matrix']['available'])

    def test_unknown_model_not_inferred_from_matrix_shape(self):
        unknown = {'vendor_id':0xface, 'model_id':0xbeef, 'matrices':[
            {'path':'/org/ffado/Control/DeviceManager/invalid/EAP/MatrixMixer',
             'rows':32, 'cols':32}]}
        self.assertEqual(load_profile(unknown), {})

    def test_mixer_row_col_orientation_is_source_declared(self):
        dice = self.fixture('profire2626')
        motu = self.fixture('motuultralite')
        self.assertTrue(dice.matrix['transposed'])
        self.assertFalse(motu.matrix['transposed'])
        with contextlib.redirect_stdout(io.StringIO()):
            dice.write(1, 'ch/02', 'fader', 75)
            motu.write(1, 'ch/02', 'fader', 75)
        self.assertIn((dice.roles['fader'][0], 2, 1), dice.helper.cells)
        self.assertIn((motu.roles['fader'][0], 1, 2), motu.helper.cells)

    def test_debug_never_imports_dbus_and_traces_writes(self):
        import sys
        preexisting_dbus = sys.modules.get('dbus')
        mixer = self.fixture('profire2626')
        stdout=io.StringIO()
        with contextlib.redirect_stdout(stdout):
            mixer.write(0, 'ch/00', 'fader', 65)
            mixer.router_set('Line/Out:01','')
        self.assertIs(sys.modules.get('dbus'), preexisting_dbus)
        self.assertEqual(type(mixer.helper).__module__, 'ffado_webmixer.debug_backend')
        self.assertIn('[DEBUG would call D-Bus]', stdout.getvalue())
        self.assertIn('MatrixMixer.setValue', stdout.getvalue())
        self.assertIn('CrossbarRouter.setConnectionState', stdout.getvalue())

    def test_soft_mute_restores_gain_edited_while_muted(self):
        mixer=self.fixture('profire2626')
        with contextlib.redirect_stdout(io.StringIO()):
            mixer.write(0,'ch/00','fader',75)
            mixer.write(0,'ch/00','mute',True)
            self.assertEqual(mixer._get_cell(mixer.roles['fader'][0],0,0),0)
            mixer.write(0,'ch/00','fader',60)
            self.assertEqual(mixer._get_cell(mixer.roles['fader'][0],0,0),0)
            mixer.write(0,'ch/00','mute',False)
            expected=mixer._from_ui(60,mixer.roles['fader'][1])
            self.assertAlmostEqual(mixer._get_cell(mixer.roles['fader'][0],0,0),expected,delta=1)

    def test_soft_solo_restores_other_inputs_and_user_mute(self):
        mixer=self.fixture('profire2626')
        with contextlib.redirect_stdout(io.StringIO()):
            mixer.write(0,'ch/01','mute',True)
            mixer.write(0,'ch/00','solo',True)
            self.assertEqual(mixer._get_cell(mixer.roles['fader'][0],0,2),0)
            mixer.write(0,'ch/00','solo',False)
            self.assertNotEqual(mixer._get_cell(mixer.roles['fader'][0],0,2),0)
            self.assertEqual(mixer._get_cell(mixer.roles['fader'][0],0,1),0)

    def test_stereo_bus_level_and_balance_modify_both_buses(self):
        mixer=self.fixture('profire2626')
        with contextlib.redirect_stdout(io.StringIO()):
            mixer.write_stereo_level(0,0,65)
            self.assertEqual(mixer._get_cell(mixer.roles['fader'][0],0,0),
                             mixer._get_cell(mixer.roles['fader'][0],1,0))
            mixer.write_bus_balance(0,0,-1)
            self.assertEqual(mixer._get_cell(mixer.roles['fader'][0],1,0),0)
            self.assertGreater(mixer._get_cell(mixer.roles['fader'][0],0,0),0)

    def test_router_disconnected_uses_mute_route(self):
        mixer=self.fixture('profire2626')
        with contextlib.redirect_stdout(io.StringIO()):
            mixer.router_set('Line/Out:01','')
            self.assertEqual(mixer.router_snapshot()['selected']['Line/Out:01'],'Mute:00')
            mixer.router_set('Line/Out:01','Mixer/Out:01')
            self.assertEqual(mixer.router_snapshot()['selected']['Line/Out:01'],'Mixer/Out:01')

    def test_guid_prefs_are_separate_and_stable_when_device_order_changes(self):
        import importlib
        import sys
        import tempfile
        import types
        flask = types.ModuleType('flask')
        flask.session = {}
        flask.has_request_context = lambda: True
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {'flask': flask}):
            sys.modules.pop('ffado_webmixer.device_manager', None)
            from ffado_webmixer.device_manager import DeviceManager
            original = Config(Path(tmp) / 'config.json')
            first = self.fixture('profire2626')
            second = self.fixture('saffirepro26')
            mgr = DeviceManager([first, second], original, debug=True)
            self.assertNotEqual(mgr.configs[first.guid].path, mgr.configs[second.guid].path)
            flask.session['ffado_device'] = first.guid
            mgr.config.settings['device_alias'] = 'Stage'
            mgr.config.save()
            flask.session['ffado_device'] = second.guid
            mgr.config.settings['device_alias'] = 'House'
            mgr.config.save()
            self.assertEqual([d['name'] for d in mgr.list_devices()], ['Stage', 'House'])
            again = DeviceManager([second, first], original, debug=True)
            self.assertEqual(again.configs[first.guid].settings['device_alias'], 'Stage')
            self.assertEqual(again.configs[second.guid].settings['device_alias'], 'House')
        sys.modules.pop('ffado_webmixer.device_manager', None)

    def test_profire_meter_data_is_read_from_router_not_fabricated(self):
        mixer=self.fixture('profire2626')
        with contextlib.redirect_stdout(io.StringIO()):
            data=mixer.peak_snapshot()
        self.assertTrue(data['available'])
        self.assertEqual(data['destinations']['Line/Out:01'],768)
        self.assertEqual(data['channels']['1']['destination'],'Mixer/In:02')
        self.assertTrue(data['channels']['3']['near_full_scale'])
        self.assertFalse(self.fixture('motuultralite').describe()['peak_metering'])

    def test_motu_ultralite_profile_hides_adat_aes(self):
        mixer=self.fixture('motuultralite')
        with contextlib.redirect_stdout(io.StringIO()):
            labels=[c['name'] for c in mixer.read_mix(0).values()]
            routing=mixer._dest_options()
        self.assertFalse(any('ADAT' in name or 'AES' in name for name in labels))
        self.assertFalse(any('ADAT' in dest['name'] or 'AES' in dest['name'] for dest in routing))


if __name__ == '__main__':
    unittest.main()
