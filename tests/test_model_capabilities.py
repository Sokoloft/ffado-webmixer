"""Per-model source capability contract. All tests are offline and make no D-Bus calls.

Optional: FFADO_SOURCE_DIR=/path/to/ffado-master python -m unittest ...
validates referenced source file provenance against an unpacked FFADO tree.
"""
import os
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from unittest.mock import patch

from ffado_webmixer.profiles.capabilities import (
    FEATURES, activate_internal_model, declared_mixer_hint, enabled,
    parse_capabilities, probe_allowed,
)
from ffado_webmixer.profiles.loader import _common, load_profile
from ffado_webmixer.profiles.resolver import resolve_mixer
from ffado_webmixer.debug_backend import fixture_names

ROOT = Path(__file__).resolve().parents[1] / 'src/ffado_webmixer/profiles'


def model_files():
    return [p for p in ROOT.glob('*/*.xml') if p.name not in ('common.xml', 'reference.xml')]


class ModelCapabilityContract(unittest.TestCase):
    def test_all_models_have_full_capability_declarations(self):
        files = model_files()
        self.assertGreaterEqual(len(files), 100)
        for path in files:
            with self.subTest(profile=str(path.relative_to(ROOT))):
                node = ET.parse(path).getroot()
                cap = parse_capabilities(node)
                self.assertEqual(set(cap['features']), FEATURES)
                self.assertTrue(cap['source'])
                if cap['status'] == 'mapped':
                    self.assertEqual(cap['features']['matrix_gain']['state'], 'mapped')
                if cap['status'] == 'identity_only':
                    self.assertFalse(any(f['state'] == 'mapped' for f in cap['features'].values()))

    def test_declared_sources_exist_in_provided_ffado_checkout(self):
        source = os.getenv('FFADO_SOURCE_DIR')
        if not source:
            self.skipTest('Set FFADO_SOURCE_DIR to validate source citations')
        source = Path(source)
        self.assertTrue((source/'configuration').is_file())
        for path in model_files():
            cap = parse_capabilities(ET.parse(path).getroot())
            for f in cap['features'].values():
                ref=f.get('source')
                if not ref or ref.startswith('ffado-webmixer:'):
                    continue
                with self.subTest(device=path.stem, source=ref):
                    self.assertTrue((source/ref).is_file(), f'{ref} is not in FFADO source')

    def test_mapped_models_match_only_exact_declared_matrix(self):
        for path in model_files():
            if path.parent.name=='motu': continue  # internal enum profile
            node = ET.parse(path).getroot()
            profile = _common(path.parent/'common.xml')
            cap = parse_capabilities(node)
            profile['capabilities'] = cap
            if cap['status']=='mapped':
                with self.subTest(model=path.stem):
                    self.assertEqual(declared_mixer_hint(profile)['path'], cap['features']['matrix_gain']['path'])
            else:
                with self.subTest(model=path.stem):
                    self.assertEqual(declared_mixer_hint(profile), {})

    def test_motu_info_model_required_and_unknown_enum_blocked(self):
        base=_common(ROOT/'motu/common.xml')
        base['capabilities']={'status':'requires_internal_model'}
        self.assertFalse(enabled(base,'matrix_gain'))
        for unsupported in (None,0,5,7,8,999):
            with self.subTest(model=unsupported), self.assertRaises(ValueError):
                activate_internal_model(base,unsupported)
        for known in (1,2,3,4,6):
            result=activate_internal_model(base,known)
            self.assertTrue(enabled(result,'matrix_gain'))
            self.assertTrue(enabled(result,'bus_destination'))
            self.assertEqual(result['internal_model_id'],known)

    def test_ultralite_lacks_adat_and_aes_and_has_native_mixer_controls(self):
        base=_common(ROOT/'motu/common.xml')
        prof=activate_internal_model({**base,'capabilities':{'status':'requires_internal_model'}},3)
        self.assertTrue(all(enabled(prof, x) for x in ('matrix_gain','matrix_pan','matrix_mute','matrix_solo','bus_destination')))
        node=ET.parse(ROOT/'motu/motu_ultralite.xml').getroot()
        self.assertEqual({x.get('feature') for x in node.findall('hardware/absent')},{'ADAT','AES/EBU'})

    def test_saffire_monitor_counts_are_per_model(self):
        for model, count in [('saffire_pro_14_00130e_00000009',4),
                             ('saffire_pro_26_00130e_00000012',6),
                             ('saffire_pro_40_00130e_00000005',10)]:
            caps=parse_capabilities(ET.parse(ROOT/'saffire_dice'/f'{model}.xml').getroot())
            self.assertEqual(int(caps['features']['monitor_line_volume']['count']), count)
            self.assertEqual(int(caps['features']['monitor_line_mute']['count']), count)
            self.assertEqual(caps['features']['matrix_gain']['path'],'/EAP/MatrixMixer')
            self.assertEqual(caps['features']['peak_metering']['state'],'optional')

    def test_unmapped_models_cannot_gain_controls_from_family(self):
        for family, filename in [('motu_mark3','all_mark3_devices_0001f2_00000001.xml'),
                                 ('rme','fireface_ufx_000a35_00000003.xml'),
                                 ('audiofire','audiofire4_001486_00000af4.xml')]:
            node=ET.parse(ROOT/family/filename).getroot()
            cap=parse_capabilities(node)
            self.assertFalse(enabled({'capabilities':cap},'matrix_gain'))
            self.assertNotIn(filename, fixture_names())
            profile=_common(ROOT/family/'common.xml')
            profile['capabilities']=cap
            # Even when a D-Bus matrix matches the family's usual path,
            # it is NOT available unless the exact model enables it.
            typical=profile.get('mixer_matrix',{}).get('path') or '/Mixer/MonitorGain'
            matrix={'path':'/org/ffado/Control/DeviceManager/0000000000000001'+typical,
                    'rows':4,'cols':8,'row_names':['A']*4,'col_names':['B']*8}
            result=resolve_mixer({'matrices':[matrix]},profile)
            self.assertIsNone(result)

    def test_loader_resolves_identity_only_model_without_writable_hint(self):
        fake={'vendor_id':0x1f2,'model_id':1,'unit_version':0x15}
        prof=load_profile(fake)
        self.assertEqual(prof['capabilities']['status'],'identity_only')
        self.assertEqual(prof['mixer_matrix'],{})

    def test_source_configuration_matches_every_exact_identity_profile(self):
        from ffado_webmixer.device_registry import parse_configuration
        definitions = parse_configuration(ROOT/'ffado_configuration')
        by_id = {(int(item['vendorid'],0), int(item['modelid'],0)):item
                 for item in definitions if 'vendorid' in item and 'modelid' in item}
        unique = set()
        for file in model_files():
            node=ET.parse(file).getroot()
            match=node.find('match')
            if match is None: continue  # MOTU's internal Info/Model overlays.
            key=(int(match.get('vendor_id'),0),int(match.get('configuration_model_id'),0))
            with self.subTest(model=file.stem):
                self.assertNotIn(key,unique)
                self.assertIn(key,by_id)
                self.assertEqual((by_id[key].get('mixer') or 'driver_only').lower(),file.parent.name)
            unique.add(key)

    def test_model_source_only_controls_are_not_enabled(self):
        cap=parse_capabilities(ET.parse(ROOT/'audiofire/audiofire8_001486_00000af8.xml').getroot())
        profile={'capabilities':cap}
        self.assertEqual(cap['features']['matrix_gain']['state'],'source_only')
        self.assertFalse(enabled(profile,'matrix_gain'))
        # FFADO provides a monitor matrix but its value scaling/axes are not
        # currently mapped by webmixer and must not inherit DICE scaling.
        self.assertEqual(declared_mixer_hint(profile),{})
        cap=parse_capabilities(ET.parse(ROOT/'phase24control/phase_x24_fw_model_version_4_000aac_00000004.xml').getroot())
        self.assertEqual(cap['features']['scalar_volume']['state'],'source_only')
        self.assertEqual(cap['features']['scalar_selector']['state'],'source_only')

    def test_debug_identity_matches_profile_instead_of_placeholder_guid(self):
        from ffado_webmixer.debug_backend import create_fixture
        for alias, vendor, model in [
            ('profire2626',0xd6c,0x10),
            ('saffirepro26',0x130e,0x12),
            ('fireface800',0xa35,1),
            ('motuultralite',0x1f2,0),
        ]:
            with self.subTest(alias=alias):
                device,profile=create_fixture(alias)
                self.assertEqual((device['vendor_id'],device['model_id']), (vendor,model))
                self.assertEqual(len(device['guid']),16)
                self.assertTrue(enabled(profile,'matrix_gain'))

    def test_motu_probe_precedes_all_model_specific_inventory(self):
        # The first D-Bus query after ConfigROM must be model ID, not a
        # guessed fader matrix from the generic MOTU generation entry.
        import sys, types
        from unittest import mock
        fake=types.ModuleType('dbus')
        fake.SessionBus=lambda:object()
        try:
            from ffado_webmixer import interrogate
        except ModuleNotFoundError as exc:
            if exc.name != 'dbus':
                raise
            # Keep this regression runnable without the optional D-Bus runtime.
            fake.Int32 = int
            fake.exceptions = types.SimpleNamespace(DBusException=Exception)
            with mock.patch.dict(sys.modules, {'dbus': fake}):
                from ffado_webmixer import interrogate
        # interrogate may already be imported with a real D-Bus module.
        with mock.patch.object(interrogate, 'dbus', fake):
            info={'device':'/org/ffado/Control/DeviceManager/0001f2000007b2ca',
                  'guid':'0001f2000007b2ca','vendor_id':0x1f2,
                  'model_id':0x0,'unit_version':0x14,
                  'controls':[],'matrices':[],'routers':[]}
            path=info['device']
            with (mock.patch.object(interrogate,'get_device_paths',return_value=[path]),
                  mock.patch.object(interrogate,'identify_device',return_value=info.copy()),
                  mock.patch.object(interrogate,'inventory_profile') as inventory,
                  mock.patch.object(interrogate,'try_call',return_value=3) as get_model):
                found=interrogate.discover()
            self.assertEqual(len(found['devices']),1)
            get_model.assert_called_once()
            self.assertEqual(get_model.call_args.args[1:],(path+'/Mixer/Info/Model','Discrete','getValue'))
            self.assertEqual(inventory.call_count,1)
            self.assertEqual(inventory.call_args.args[2]['internal_model_id'],3)
            with (mock.patch.object(interrogate,'get_device_paths',return_value=[path]),
                  mock.patch.object(interrogate,'identify_device',return_value=info.copy()),
                  mock.patch.object(interrogate,'inventory_profile') as inventory,
                  mock.patch.object(interrogate,'try_call',return_value=999)):
                found=interrogate.discover()
            inventory.assert_not_called()
            self.assertEqual(found['devices'][0]['matrices'],[])

    def test_bad_or_missing_capability_entries_rejected(self):
        node=ET.Element('device',{'name':'Unspecified'})
        with self.assertRaises(ValueError):parse_capabilities(node)
        ET.SubElement(node,'capabilities',{'schema':'2','status':'mapped'})
        with self.assertRaises(ValueError):parse_capabilities(node)

if __name__=='__main__':unittest.main()
