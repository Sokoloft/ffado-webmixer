"""MOTU pre-Mk3 source-derived output routing, using an offline hardware stub."""
import contextlib
import sys
import types
import unittest
from unittest.mock import MagicMock

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

from ffado_webmixer.mixer import Mixer
from ffado_webmixer.profiles.resolver import (resolve_mixer, resolve_controls, visible_columns,
                                              destination_options)
from ffado_webmixer.profiles.loader import _common
from pathlib import Path

GUID = '/org/ffado/Control/DeviceManager/0001f2000007b2ca'
PROFILE = Path(__file__).resolve().parents[1] / 'ffado_webmixer/profiles/motu/common.xml'


def setup_device():
    matrix = {'path': GUID + '/Mixer/fader', 'name': 'fader',
              'rows': 4, 'cols': 20,
              'row_names': [f'Mix {i}' for i in range(1, 5)],
              'col_names': [f'Analog {i}' for i in range(1, 9)] +
                           [f'AES/EBU {i}' for i in range(1, 3)] +
                           [f'SPDIF {i}' for i in range(1, 3)] +
                           [f'ADAT {i}' for i in range(1, 9)]}
    controls = [{'path': GUID + f'/Mixer/Mix{i}/Mix_dest',
                 'kind': 'Discrete', 'label': 'Mix dest', 'name': 'Mix_dest'} for i in range(1, 5)]
    return {'vendor_id': 0x1f2, 'device': GUID, 'guid': GUID.rsplit('/', 1)[-1],
            'controls': controls, 'matrices': [matrix], 'routers': []}


class FakeHardware:
    def __init__(self):
        self.values = {GUID + f'/Mixer/Mix{i}/Mix_dest': v
                       for i, v in enumerate((6, 2, 0, 7), start=1)}
        self.cells = {}
        self.reject_write = False

    @contextlib.contextmanager
    def transaction(self): yield

    def get_value(self, path, kind):
        assert kind == 'Discrete'
        return self.values[path]

    def set_value(self, path, kind, value):
        assert kind == 'Discrete'
        if not self.reject_write:
            self.values[path] = value

    def get_cell(self, *args):
        raise AssertionError('Changing output routing must not read a gain crosspoint')

    def set_cell(self, *args):
        raise AssertionError('Changing output routing must not write a gain crosspoint')


def make_motu():
    device = setup_device()
    profile = _common(PROFILE)
    model = resolve_mixer(device, profile)
    controls = resolve_controls(device, profile, model['matrices'], model['columns'], model['rows'])
    mixer = Mixer.__new__(Mixer)
    mixer.device, mixer.profile, mixer.model = device, profile, 3
    mixer.helper = FakeHardware()
    mixer.matrix, mixer.mixes, mixer.columns = model, model['rows'], model['columns']
    mixer.router_path = None
    mixer.roles, mixer.chan = controls['roles'], controls['channels']
    mixer.chan_specs, mixer.out_spec, mixer.outputs = (controls['channel_specs'],
                                                       controls['output_spec'], controls['outputs'])
    mixer._matrix_mutes = {}
    mixer.config = types.SimpleNamespace(save=lambda: None)
    mixer.mute_memory = {}
    return mixer


class MotuRoutingTests(unittest.TestCase):
    def test_source_paths_win_over_ambiguous_labels(self):
        m = make_motu()
        for i in range(4):
            self.assertEqual(m.outputs[f'bus/{i}']['dest']['path'],
                             GUID + f'/Mixer/Mix{i+1}/Mix_dest')
        self.assertTrue(m.describe()['bus_routing'])

    def test_ultralite_hides_nonexistent_optical_and_aes(self):
        m = make_motu()
        names = [m.columns[i] for i in m._visible_cols()]
        self.assertEqual(len(names), 10)
        self.assertFalse(any('ADAT' in n or 'AES' in n for n in names))
        option_names = [o['name'] for o in m._dest_options()]
        self.assertIn('MainOut', option_names)
        self.assertIn('SPDIF', option_names)
        self.assertFalse(any('ADAT' in n or 'AES' in n for n in option_names))
        self.assertEqual(next(o['name'] for o in m._dest_options() if o['value'] == 6), 'MainOut')

    def test_read_routes_and_change_only_destination(self):
        m = make_motu()
        original = m.bus_routing_snapshot()
        self.assertEqual([b['value'] for b in original['buses']], [6, 2, 0, 7])
        m.bus_routing_set('bus/2', 4)
        self.assertEqual(m.helper.values[GUID + '/Mixer/Mix3/Mix_dest'], 4)
        self.assertEqual(m.bus_routing_snapshot()['buses'][2]['value'], 4)

    def test_disallow_phantom_ports_bad_ids_and_failed_readback(self):
        m = make_motu()
        for value in (8, 9, 10, 11, -1, 99):
            with self.assertRaises(ValueError):
                m.bus_routing_set('bus/1', value)
        with self.assertRaises(ValueError): m.bus_routing_set('bus/5', 2)
        m.helper.reject_write = True
        with self.assertRaises(IOError): m.bus_routing_set('bus/0', 2)

    def test_model_specific_filter_does_not_hide_other_motu_models(self):
        profile = _common(PROFILE)
        self.assertIn('ADAT 1-2', [o['name'] for o in destination_options(profile, 2)])
        self.assertIn('AES/EBU', [o['name'] for o in destination_options(profile, 2)])
        self.assertEqual(len(visible_columns(profile, 2, ['AES/EBU 1', 'ADAT 1', 'SPDIF 1'])), 3)


if __name__ == '__main__': unittest.main()

class MotuApiTests(unittest.TestCase):
    def test_api_reads_and_writes_real_dest_controls(self):
        try:
            from flask import Flask
        except ImportError:
            self.skipTest("Flask not installed in the offline test environment")
        from ffado_webmixer.api.mixer import register
        mixer = make_motu()
        app = Flask('motu-api-test')
        messages = []
        register(app, mixer, mixer.describe(), types.SimpleNamespace(names={}), messages.append)
        client = app.test_client()
        response = client.get('/api/bus-routing')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json['buses']), 4)
        self.assertEqual(response.json['buses'][0]['value'], 6)
        response = client.post('/api/bus-routing', json={'bus': 'bus/1', 'value': 5})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mixer.helper.values[GUID + '/Mixer/Mix2/Mix_dest'], 5)
        self.assertEqual(messages[-1]['type'], 'destination')
        self.assertEqual(client.post('/api/bus-routing', json={'bus': 'bus/1', 'value': 10}).status_code, 400)
        self.assertEqual(mixer.helper.values[GUID + '/Mixer/Mix2/Mix_dest'], 5)

    def test_settings_inout_tab_was_removed_and_general_retains_qjackctl(self):
        page = (Path(__file__).resolve().parents[1] /
                'ffado_webmixer/assets/static/index.html').read_text()
        script = (Path(__file__).resolve().parents[1] /
                  'ffado_webmixer/assets/static/routing.js').read_text()
        self.assertNotIn('tab-inout', page)
        self.assertNotIn('pane-inout', page)
        self.assertIn('id="routingBusGrid"', page)
        self.assertIn('id="jackButtons"', page)
        self.assertIn('"/api/bus-routing"', script)
