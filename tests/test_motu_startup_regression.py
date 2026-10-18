"""Offline regression for FFADO pre-mk3 MOTU model identification.

The ConfigROM only identifies the generation. FFADO's /Mixer/Info/Model
value must survive discovery and subsequent mixer initialization.
"""
import sys
import types
import unittest
from unittest.mock import patch
from pathlib import Path

# CI/dev machines do not need libdbus installed to run these tests.
try:
    import dbus
except ImportError:
    dbus = types.ModuleType('dbus')
    dbus.Int32 = int
    dbus.exceptions = types.SimpleNamespace(DBusException=Exception)
    sys.modules['dbus'] = dbus

from ffado_webmixer import interrogate
from ffado_webmixer.mixer import Mixer
from ffado_webmixer.profiles.loader import load_profile

GUID = '0001f2000007b2ca'
BASE = '/org/ffado/Control/DeviceManager/' + GUID


class ReadOnlyHelper:
    def get_value(self, path, kind):
        if path == BASE + '/Mixer/Info/Model' and kind == 'Discrete':
            return 3
        if path == BASE + '/Mixer/Info/SampleRate' and kind == 'Discrete':
            return 48000
        raise AssertionError(f'Unrecognized read: {kind} {path}')


class MotuStartupRegression(unittest.TestCase):
    def identity(self):
        return {'device': BASE, 'guid': GUID, 'vendor_id': 0x1f2,
                'model_id': 0, 'unit_version': 0x14,
                'model_name': 'MOTU UltraLite', 'controls': [],
                'matrices': [], 'routers': []}

    def discover_fake(self, model=3, metadata_introspection=True):
        seen = []

        def fake_introspect(bus, path):
            seen.append(path)
            if not metadata_introspection and path.endswith('/Mixer/Info/Model'):
                raise dbus.exceptions.DBusException('No introspection')
            if path.endswith(('/Mixer/Info/Model', '/Mixer/Info/SampleRate')):
                return {interrogate.NS + 'Discrete'}, []
            if path.endswith(('/Mixer/fader', '/Mixer/mute', '/Mixer/pan', '/Mixer/solo')):
                return {interrogate.NS + 'MatrixMixer'}, []
            raise dbus.exceptions.DBusException('Not exported')

        def fake_call(bus, path, kind, method, *args, default=None):
            if path == BASE + '/Mixer/Info/Model' and method == 'getValue':
                return model
            if path == BASE + '/Mixer/Info/SampleRate' and method == 'getValue':
                return 48000
            if method == 'getRowCount': return 4
            if method == 'getColCount': return 20
            if method == 'getRowName': return f'Mix {args[0]+1}'
            if method == 'getColName': return f'Analog {args[0]+1}'
            if method == 'getLabel': return path.rsplit('/', 1)[-1]
            if method == 'getName': return path.rsplit('/', 1)[-1]
            return default

        with (patch.object(interrogate.dbus, 'SessionBus', lambda: object(), create=True),
              patch.object(interrogate.dbus, 'Int32', int, create=True),
              patch.object(interrogate, 'get_device_paths', return_value=[BASE]),
              patch.object(interrogate, 'identify_device', return_value=self.identity()),
              patch.object(interrogate, 'introspect', side_effect=fake_introspect),
              patch.object(interrogate, 'try_call', side_effect=fake_call)):
            devices = interrogate.discover()['devices']
        return devices[0], seen

    def test_model_metadata_path_is_the_actual_ffado_path(self):
        profile = load_profile(self.identity())
        self.assertEqual(profile['model_element'], 'Mixer/Info/Model')
        self.assertEqual(profile['rate_element'], 'Mixer/Info/SampleRate')

    def test_ultralite_loads_from_actual_discovery_inventory(self):
        device, seen = self.discover_fake()
        self.assertEqual(device['internal_model_id'], 3)
        self.assertIn(BASE + '/Mixer/Info/Model', seen)
        self.assertIn(BASE + '/Mixer/Info/SampleRate', seen)
        self.assertNotIn(BASE + '/Info/Model', seen)
        self.assertTrue(any(c['path'] == BASE + '/Mixer/Info/Model' and c['kind'] == 'Discrete'
                            for c in device['controls']))
        self.assertTrue(any(m['path'] == BASE + '/Mixer/fader' for m in device['matrices']))
        mixer = Mixer(config=types.SimpleNamespace(mute_memory={}),
                      device=device, helper=ReadOnlyHelper())
        self.assertEqual(mixer.model, 3)
        self.assertEqual(mixer.profile['device_name'], 'MOTU Ultralite')
        self.assertEqual(mixer.matrix['matrices']['fader'], BASE + '/Mixer/fader')
        self.assertEqual(mixer._info(mixer.profile['rate_element']), 48000)

    def test_verified_model_survives_nonessential_introspection_failure(self):
        device, _ = self.discover_fake(metadata_introspection=False)
        self.assertEqual(device['internal_model_id'], 3)
        self.assertFalse(any(c['path'].endswith('/Info/Model') for c in device['controls']))
        mixer = Mixer(config=types.SimpleNamespace(mute_memory={}),
                      device=device, helper=ReadOnlyHelper())
        self.assertEqual(mixer.model, 3)

    def test_unknown_internal_model_is_not_assigned_ultralite_controls(self):
        device, seen = self.discover_fake(model=999)
        self.assertNotIn('internal_model_id', device)
        self.assertEqual(device['matrices'], [])
        self.assertNotIn(BASE + '/Mixer/fader', seen)


if __name__ == '__main__':
    unittest.main()
