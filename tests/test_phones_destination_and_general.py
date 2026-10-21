"""Source-based MOTU Phones assign and the two-column General Settings view."""
import contextlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# FFADO's D-Bus dependency is optional in our offline regression tests.
if 'dbus' not in sys.modules:
    try:
        import dbus
    except ImportError:
        dbus = types.ModuleType('dbus')
        dbus.Int32 = int
        dbus.Double = float
        dbus.String = str
        dbus.Boolean = bool
        dbus.SessionBus = MagicMock
        dbus.Interface = lambda *args: None
        dbus.exceptions = types.SimpleNamespace(DBusException=Exception)
        sys.modules['dbus'] = dbus

from ffado_webmixer.profiles.resolver import resolve_phones_assignment
from ffado_webmixer.profiles.capabilities import enabled, activate_internal_model
from ffado_webmixer.profiles.loader import _common
from ffado_webmixer.mixer import Mixer
from tests.test_motu_bus_routing import make_motu, GUID, PROFILE

PATH = GUID + '/Mixer/Control/Phones_src'
ROOT = Path(__file__).resolve().parents[1]


def with_phones():
    mixer = make_motu()
    mixer.device['controls'].append({'path': PATH, 'kind': 'Discrete', 'name': 'Phones_src'})
    mixer.helper.values[PATH] = 1
    return mixer


class MotuPhonesDestination(unittest.TestCase):
    def test_exact_control_required_not_guessed(self):
        m = make_motu()
        self.assertNotIn('phones', m.bus_routing_snapshot())
        self.assertFalse(m.describe()['phones_assignment'])
        with self.assertRaisesRegex(ValueError, 'not supported'):
            m.write_phones_assignment(2)
        m.device['controls'].append({'path': GUID + '/Mixer/Control/Other_src', 'kind': 'Discrete'})
        self.assertIsNone(resolve_phones_assignment(m.device, m.profile))
        m.device['controls'].append({'path': PATH, 'kind': 'Text'})
        self.assertIsNone(resolve_phones_assignment(m.device, m.profile))
        m.device['controls'][-1]['kind'] = 'Discrete'
        self.assertEqual(resolve_phones_assignment(m.device, m.profile)['path'], PATH)
        m.profile['family'] = 'saffire_dice'
        self.assertIsNone(resolve_phones_assignment(m.device, m.profile))

    def test_real_discovery_probes_model_declared_phones_selector(self):
        """Regression: declared phones_source_path must enter D-Bus inventory.

        Prior builds parsed this field in the XML profile but only inventoried
        path/extra_paths.  The UI silently hid a control that FFADO exported.
        """
        from ffado_webmixer import interrogate
        for model in (1, 2, 3, 4, 6):
            m = make_motu()
            m.profile = activate_internal_model(
                {**_common(PROFILE), 'capabilities': {'status': 'requires_internal_model'}}, model)
            device = {**m.device, 'controls': [], 'matrices': [], 'routers': []}
            touched = []
            def inspect(_bus, path):
                touched.append(path)
                if path == PATH:
                    return {interrogate.NS + 'Discrete'}, []
                raise dbus.exceptions.DBusException('not exposed')
            with (patch.object(interrogate, 'introspect', side_effect=inspect),
                  patch.object(interrogate, 'try_call', return_value='Phones source')):
                interrogate.inventory_profile(object(), device, m.profile)
            self.assertIn(PATH, touched, f'model {model} did not probe Phones_src')
            self.assertEqual(resolve_phones_assignment(device, m.profile)['path'], PATH)
            self.assertTrue(any(c['kind'] == 'Discrete' for c in device['controls']))

    def test_phones_probe_needs_supported_model_and_live_discrete(self):
        from ffado_webmixer import interrogate
        m = make_motu()
        touched = []
        def inspect(_bus, path):
            touched.append(path)
            if path == PATH:
                return {interrogate.NS + 'Text'}, []  # wrong FFADO interface
            raise dbus.exceptions.DBusException('not exposed')
        device = {**m.device, 'controls': [], 'matrices': [], 'routers': []}
        with (patch.object(interrogate, 'introspect', side_effect=inspect),
              patch.object(interrogate, 'try_call', return_value='Phones source')):
            interrogate.inventory_profile(object(), device, m.profile)
        self.assertIn(PATH, touched)
        self.assertIsNone(resolve_phones_assignment(device, m.profile))
        m.profile = {**m.profile, 'family': 'saffire_dice'}
        touched.clear()
        with patch.object(interrogate, 'introspect', side_effect=inspect):
            interrogate.inventory_profile(object(), device, m.profile)
        self.assertNotIn(PATH, touched)

    def test_proper_source_profile_and_value_hardware_readback(self):
        m = with_phones()
        self.assertTrue(m.describe()['phones_assignment'])
        original = m.bus_routing_snapshot()
        self.assertEqual(original['phones']['value'], 1)
        self.assertIn('MainOut', [option['name'] for option in original['phones']['options']])
        self.assertNotIn('ADAT 1-2', [option['name'] for option in original['phones']['options']])
        self.assertNotIn('AES/EBU', [option['name'] for option in original['phones']['options']])
        before = {k: v for k, v in m.helper.values.items() if k != PATH}
        m.write_phones_assignment(6)
        self.assertEqual(m.helper.values[PATH], 6)
        self.assertEqual(m.bus_routing_snapshot()['phones']['value'], 6)
        self.assertEqual(before, {k: v for k, v in m.helper.values.items() if k != PATH})

    def test_invalid_values_and_failed_write_do_not_invent_routes(self):
        m = with_phones()
        for value in (-2, 8, 9, 10, 11, 128, 2.5, '6', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                m.write_phones_assignment(value)
        m.helper.reject_write = True
        with self.assertRaises(IOError):
            m.write_phones_assignment(6)
        self.assertEqual(m.helper.values[PATH], 1)

    def test_other_motu_models_must_also_observe_live_endpoint(self):
        base = _common(PROFILE)
        for model in (1, 2, 3, 4, 6):
            profile = activate_internal_model({**base, 'capabilities': {'status': 'requires_internal_model'}}, model)
            self.assertTrue(enabled(profile, 'bus_destination'))
            self.assertEqual(profile['capabilities']['features']['bus_destination']['phones_source_path'],
                             '/Mixer/Control/Phones_src')
            self.assertIsNone(resolve_phones_assignment({'device': GUID, 'controls': []}, profile))

    def test_api_write_validation_and_destination_event(self):
        try:
            from flask import Flask
        except ImportError:
            self.skipTest('Flask is not installed in the offline environment')
        from ffado_webmixer.api.mixer import register
        m = with_phones()
        app = Flask('test-phones')
        emitted = []
        register(app, m, m.describe(), types.SimpleNamespace(names={}), emitted.append)
        client = app.test_client()
        for value in ('6', 6.0, True, -1, 8):
            self.assertEqual(client.post('/api/phones-assignment', json={'value': value}).status_code, 400)
        self.assertEqual(client.post('/api/phones-assignment', json={'value': 6}).status_code, 200)
        self.assertEqual(emitted[-1], {'type': 'destination', 'out': 'phones', 'value': 6})
        self.assertEqual(client.get('/api/bus-routing').json['phones']['value'], 6)


class GeneralSettingsLayout(unittest.TestCase):
    def test_checkbox_layout_keeps_exact_user_order_and_ids(self):
        html = (ROOT / 'ffado_webmixer/assets/static/index.html').read_text()
        css = (ROOT / 'ffado_webmixer/assets/static/index.css').read_text()
        a = html.index('<div class="general-options"')
        b = html.index('<div class="field device-alias-field">', a)
        options = html[a:b]
        self.assertLess(options.index('id="skipLoadingScreen"'), options.index('id="hideMin"'))
        self.assertLess(options.index('id="hideMin"'), options.index('id="enableQjackctl"'))
        self.assertEqual(options.count('general-option-column'), 2)
        self.assertEqual(options.count('general-option-check'), 3)
        self.assertEqual(options.count('general-option-copy'), 3)
        self.assertIn('grid-template-columns: repeat(2, minmax(0, 1fr))', css)
        self.assertIn('text-align: center', css)
        self.assertIn('@media (max-width: 480px)', css)
        self.assertIn('grid-template-columns: minmax(0, 1fr)', css)
        for key in ('hideMin', 'skipLoadingScreen', 'enableQjackctl'):
            self.assertEqual(options.count('id="'+key+'"'), 1)
        self.assertEqual(options.count('id="minCount"'), 1)


if __name__ == '__main__':
    unittest.main()
