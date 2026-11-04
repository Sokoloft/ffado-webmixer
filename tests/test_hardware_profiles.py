"""Offline regression tests using a fake FFADO D-Bus backend.

Run: python -m unittest discover -s tests -v
These tests do NOT assert that physical hardware accepted writes.
"""
import contextlib
import math
import sys
import types
import unittest
from unittest.mock import MagicMock

# Build environments (such as CI) may lack libdbus / python-dbus.
if "dbus" not in sys.modules:
    try:
        import dbus
    except ImportError:
        dbus = types.ModuleType("dbus")
        dbus.Int32 = int
        dbus.Double = float
        dbus.String = str
        dbus.Boolean = bool
        dbus.SessionBus = MagicMock
        dbus.Interface = lambda *args: None
        dbus.exceptions = types.SimpleNamespace(DBusException=Exception)
        sys.modules["dbus"] = dbus

from ffado_webmixer.mixer import Mixer
from ffado_webmixer.profiles.resolver import resolve_mixer, resolve_controls
from ffado_webmixer.profiles.capabilities import parse_capabilities
from xml.etree import ElementTree as ET
from pathlib import Path

GUID = "/org/ffado/Control/DeviceManager/00130e04048014ef"
MATRIX = GUID + "/EAP/MatrixMixer"
ROUTER = GUID + "/EAP/Router"


def device():
    controls = []
    for i in range(1, 7):
        for role, kind in (("Volume", "Discrete"), ("Mute", "Boolean")):
            controls.append({"path": GUID + f"/EAP/Monitoring/LineOut/{role}{i}",
                             "label": f"Line Out {i} {role}", "kind": kind})
    return {"device": GUID, "guid": GUID.split("/")[-1], "vendor_id": 0x130e,
            "model_id": 0x12, "controls": controls, "routers": [{"path": ROUTER}],
            "matrices": [{"path": MATRIX, "name": "MatrixMixer", "rows": 18, "cols": 16,
                          "row_names": [f"Mixer/In:{i:02d}\n(Anlg/In:{i:02d})" for i in range(1, 19)],
                          "col_names": [f"Mixer/Out:{i:02d}\n(Line/Out:{i:02d})" for i in range(1, 17)]}]}


class Hardware:
    def __init__(self):
        self.cells = {(r, c): 16384 for r in range(18) for c in range(16)}
        self.values = {GUID + f"/EAP/Monitoring/LineOut/Volume{i}": -15 for i in range(1, 7)}
        self.boolean = {GUID + f"/EAP/Monitoring/LineOut/Mute{i}": False for i in range(1, 7)}
        self.routes = {"Line/Out:01": "Mixer/Out:01", "Mixer/In:01": "Anlg/In:01"}
    def get_cell(self, path, row, col):
        assert path == MATRIX
        return self.cells[(row, col)]
    def set_cell(self, path, row, col, value):
        assert path == MATRIX
        self.cells[(row, col)] = value
    def get_value(self, path, kind): return self.values[path]
    def set_value(self, path, kind, val): self.values[path] = val
    def get_selected(self, path, kind): return self.boolean[path]
    def select(self, path, val, kind): self.boolean[path] = val
    @contextlib.contextmanager
    def transaction(self): yield
    def router_call(self, path, method, *args):
        assert path == ROUTER
        if method == "getSourceNames": return ["Anlg/In:01", "Mixer/Out:01", "Mute:00"]
        if method == "getDestinationNames": return list(self.routes)
        if method == "getSourceForDestination": return self.routes[args[0]]
        if method == "setConnectionState":
            self.routes[args[1]] = args[0] if args[2] else ""
            return True
        raise AssertionError(method)


def make_mixer():
    d = device()
    profile = {"family": "saffire_dice", "controls": {}, "mixer_matrix":
               {"path": "/EAP/MatrixMixer", "row_role": "inputs", "coefficient": "dice_db"}}
    profile['capabilities'] = parse_capabilities(ET.parse(Path(__file__).resolve().parents[1] / 'src/ffado_webmixer/profiles/saffire_dice/saffire_pro_26_00130e_00000012.xml').getroot())
    model = resolve_mixer(d, profile)
    ctrl = resolve_controls(d, profile, model["matrices"], model["columns"], model["rows"])
    mixer = Mixer.__new__(Mixer)
    mixer.device = d
    mixer.profile = profile
    mixer.model = None
    mixer.matrix = model
    mixer.router_path = ROUTER
    mixer.helper = Hardware()
    mixer.mixes = model["rows"]
    mixer.columns = model["columns"]
    mixer.roles = ctrl["roles"]
    mixer.chan = ctrl["channels"]
    mixer.chan_specs = ctrl["channel_specs"]
    mixer.out_spec = ctrl["output_spec"]
    mixer.outputs = ctrl["outputs"]
    mixer._matrix_mutes = {}
    mixer.config = types.SimpleNamespace(save=lambda: None)
    mixer.mute_memory = {}
    return mixer


class TestDICE(unittest.TestCase):
    def test_dice_orientation_source_labels(self):
        m = make_mixer()
        self.assertEqual(len(m.mixes), 16)
        self.assertEqual(len(m.columns), 18)
        self.assertEqual(m.columns[0], "Anlg/In:01")
        self.assertEqual(m.mixes[0], "Mixer/Out:01")
        self.assertTrue(m.matrix["transposed"])

    def test_gain_and_coordinates(self):
        m = make_mixer()
        state = m.read_mix(2)
        self.assertAlmostEqual(state["ch/01"]["fader"], 91, delta=1)  # unity coefficient
        m.write(2, "ch/01", "fader", 50)
        self.assertNotEqual(m.helper.cells[(1, 2)], 16384)
        self.assertEqual(m.helper.cells[(2, 1)], 16384)  # reversed coordinate untouched
        self.assertGreater(m.helper.cells[(1, 2)], 0)
        self.assertAlmostEqual(m.read_mix(2)["ch/01"]["fader"], 50, delta=0.02)

    def test_virtual_mute_restores_gain(self):
        m = make_mixer()
        m.write(0, "ch/00", "mute", True)
        self.assertEqual(m.helper.cells[(0, 0)], 0)
        self.assertTrue(m.read_mix(0)["ch/00"]["mute"])
        m.write(0, "ch/00", "mute", False)
        self.assertEqual(m.helper.cells[(0, 0)], 16384)

    def test_line_level_and_boolean_mute(self):
        m = make_mixer()
        self.assertIn("line/1", m.outputs)
        self.assertEqual(m.read_output("line/1")["level"], 62)
        m.write_output("line/1", "fader", 25)
        self.assertEqual(m.helper.values[GUID + "/EAP/Monitoring/LineOut/Volume1"], -30)
        m.write_output("line/1", "mute", True)
        self.assertTrue(m.helper.boolean[GUID + "/EAP/Monitoring/LineOut/Mute1"])
        self.assertTrue(m.read_output("line/1")["mute"])

    def test_matrix_snapshot(self):
        m = make_mixer()
        snapshot = m.matrix_snapshot()
        self.assertEqual(len(snapshot["inputs"]), 18)
        self.assertEqual(len(snapshot["outputs"]), 16)
        self.assertTrue(all(math.isfinite(v) for row in snapshot["values"] for v in row))
        with self.assertRaises(ValueError): m.matrix_set(-1, 0, 45)

    def test_router_methods(self):
        m = make_mixer()
        before = m.router_snapshot()
        self.assertEqual(before["selected"]["Line/Out:01"], "Mixer/Out:01")
        m.router_set("Line/Out:01", "Anlg/In:01")
        self.assertEqual(m.router_snapshot()["selected"]["Line/Out:01"], "Anlg/In:01")
        m.router_set("Line/Out:01", "")
        self.assertEqual(m.router_snapshot()["selected"]["Line/Out:01"], "")
        with self.assertRaises(ValueError): m.router_set("Line/Out:01", "Invalid")

    def test_unknown_matrix_not_writable(self):
        d = device()
        d["matrices"][0]["path"] = GUID + "/Unrecognized/Matrix"
        r = resolve_mixer(d, {"family": "unknown"})
        self.assertIsNone(r)

    def test_motu_orientation(self):
        d = device()
        d["matrices"] = [{"path": GUID + "/Mixer/fader", "name": "fader", "rows": 4, "cols": 20,
                          "row_names": [f"Mix {i}" for i in range(4)],
                          "col_names": [f"Analog {i}" for i in range(20)]}]
        r = resolve_mixer(d, {"family": "motu", "mixer_matrix":
                              {"path": "/Mixer/fader", "row_role": "outputs", "coefficient": "linear"},
                              "capabilities": parse_capabilities(ET.parse(Path(__file__).resolve().parents[1] / "src/ffado_webmixer/profiles/motu/motu_ultralite.xml").getroot())})
        self.assertFalse(r["transposed"])
        self.assertEqual(len(r["rows"]), 4)
        self.assertEqual(len(r["columns"]), 20)
        self.assertEqual(r["matrices"]["fader"], d["matrices"][0]["path"])


if __name__ == "__main__":
    unittest.main()

class TestSourceProfile(unittest.TestCase):
    def test_config_and_saffire_profile_select(self):
        from pathlib import Path
        from unittest.mock import patch
        from ffado_webmixer.device_registry import configured_devices, resolve_device
        from ffado_webmixer.profiles import loader
        config = Path(__file__).resolve().parent / 'fixtures' / 'ffado_configuration'
        if not config.is_file():
            self.skipTest('FFADO source configuration not included in this archive')
        definitions = configured_devices(config, '/no-user-config')
        identity = resolve_device(device(), definitions)
        self.assertEqual(identity['mixer_name'], 'Saffire_Dice')
        with patch.object(loader, 'resolve_device', lambda d: resolve_device(d, definitions)):
            profile = loader.load_profile(device())
        self.assertEqual(profile['device_name'], 'Saffire PRO 26')
        self.assertEqual(profile['device_profile'], 'saffire_pro_26_00130e_00000012.xml')
        self.assertEqual(profile['mixer_matrix']['path'], '/EAP/MatrixMixer')
        parsed = resolve_mixer(device(), profile)
        self.assertTrue(parsed['transposed'])
