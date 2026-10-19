"""Regression for 7+8 pairing on Bus 2 unexpectedly unhiding strips on Bus 1.

All mixer interactions are debug-only and do not require physical FFADO hardware.
"""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import types
from unittest.mock import patch

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from test_arbitrary_stereo_pairs import stub_stereo_handler, matrix_copy

ROOT = Path(__file__).resolve().parents[1]


def profire():
    with contextlib.redirect_stdout(io.StringIO()):
        return make_debug_mixer('profire2626', Config())


def state_on(mixer, config, bus):
    """Execute the real /api/state function with a selected mix."""
    flask = types.ModuleType('flask')
    flask.request = types.SimpleNamespace(args=types.SimpleNamespace(get=lambda key, fallback=0, type=int: bus))
    flask.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    class App:
        def get(self, path):
            def decorator(fn):
                if path == '/api/state': self.state = fn
                return fn
            return decorator
        def post(self, path):
            return lambda fn: fn
    with patch.dict(sys.modules, {'flask':flask}):
        spec = importlib.util.spec_from_file_location('ffado_webmixer.api._bus_scoped_test_api',
                                                     ROOT/'ffado_webmixer/api/mixer.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app = App()
        module.register(app, mixer, {}, config, lambda event: None)
        with contextlib.redirect_stdout(io.StringIO()):
            return app.state()


def test_unlink_bus_two_preserves_bus_one_partner_visibility_and_layout():
    mixer = profire()
    config = Config()
    config.settings['stereo_buses'] = [0]
    left, right = 'ch/06', 'ch/07'  # Channel 7 (Left) + Channel 8 (Right)
    config.layouts['0'] = [{'id': f'ch/{n:02}', 'pinned': True, 'minimized': False}
                           for n in range(8)]
    config.layouts['1'] = [{'id': f'ch/{n:02}', 'pinned': n != 7, 'minimized': n == 7}
                           for n in range(8)]
    bus0_original = [dict(entry) for entry in config.layouts['0']]
    bus1_original = [dict(entry) for entry in config.layouts['1']]
    handler = stub_stereo_handler(mixer, config)
    original_matrix = matrix_copy(mixer)
    # Set up the preexisting pair on Bus 1.
    assert handler({'action':'link','dragged':left,'target':right}, mix=0)['ok']
    assert state_on(mixer, config, 0)[right]['partner_of'] == left
    # User clicks Bus 2, links 7+8 there, then unlinks 7+8 on Bus 2.
    assert handler({'action':'link','dragged':left,'target':right}, mix=1)['ok']
    assert state_on(mixer, config, 1)[right]['partner_of'] == left
    assert handler({'action':'unlink','id':left}, mix=1)['ok']
    assert config.pair_of(left, 1) is None
    assert state_on(mixer, config, 1)[right].get('partner_of') is None
    assert state_on(mixer, config, 1)[left].get('partner') is None
    # Switching back must still hide the Right channel on Bus 1.
    bus0 = state_on(mixer, config, 0)
    assert bus0[left]['partner'] == right
    assert bus0[right]['partner_of'] == left
    assert config.pair_of(right, 0) == [left,right]
    assert config.layouts['0'] == bus0_original
    assert config.layouts['1'] == bus1_original
    assert matrix_copy(mixer) == original_matrix  # neither link/unlink writes routes


def test_mixed_left_right_pairings_per_bus_are_allowed():
    mixer = profire()
    config = Config()
    handler = stub_stereo_handler(mixer, config)
    assert handler({'action':'link','dragged':'ch/01','target':'ch/04'},mix=0)['ok']
    assert handler({'action':'link','dragged':'ch/04','target':'ch/06'},mix=1)['ok']
    assert config.pairs_for(0) == [['ch/01', 'ch/04']]
    assert config.pairs_for(1) == [['ch/04', 'ch/06']]
    assert state_on(mixer, config, 0)['ch/04']['partner_of'] == 'ch/01'
    assert state_on(mixer, config, 1)['ch/04']['partner'] == 'ch/06'
    # Within the same bus, a channel may not be in two pairs.
    assert handler({'action':'link','dragged':'ch/04','target':'ch/07'},mix=1)[1] == 400


def test_saved_legacy_links_are_inherited_and_unlink_overrides_only_one_bus(tmp_path):
    path = tmp_path / 'devices' / 'profire.json'
    path.parent.mkdir()
    path.write_text(json.dumps({
        'stereo': [['ch/06', 'ch/07']],
        'layouts': {'0': [{'id': 'ch/06', 'pinned': True, 'minimized': False}],
                    '1': [{'id': 'ch/06', 'pinned': True, 'minimized': False}]}
    }))
    config = Config(path)
    config.load()
    assert config.pair_of('ch/07', 0) == ['ch/06', 'ch/07']
    assert config.pair_of('ch/07', 1) == ['ch/06', 'ch/07']
    config.unlink('ch/06', mix=1)
    config.spread_unlinked('ch/06', 'ch/07', mix=1)
    config.save()
    restarted = Config(path)
    restarted.load()
    assert restarted.pairs_for(0) == [['ch/06', 'ch/07']]
    assert restarted.pairs_for(1) == []
    assert restarted.layouts['0'] == [{'id':'ch/06','pinned':True,'minimized':False}]
    assert [entry['id'] for entry in restarted.layouts['1']] == ['ch/06', 'ch/07']
    # Explicitly saving an empty bus is respected, not replaced by legacy global pair.
    assert json.loads(path.read_text())['stereo_by_mix']['1'] == []


def test_hidden_right_retains_its_individual_pin_minimize_and_position():
    mixer = profire()
    config = Config()
    config.layouts['1'] = [
        {'id':'ch/07', 'pinned':False, 'minimized':True},
        {'id':'ch/05', 'pinned':True, 'minimized':False},
        {'id':'ch/06', 'pinned':False, 'minimized':False},
    ]
    before = [dict(e) for e in config.layouts['1']]
    handler = stub_stereo_handler(mixer, config)
    handler({'action':'link','dragged':'ch/06','target':'ch/07'},mix=1)
    assert config.layouts['1'] == before  # hidden in state only, not deleted
    handler({'action':'unlink','id':'ch/07'},mix=1)
    assert config.layouts['1'] == before


def test_stereo_set_only_mirrors_on_selected_bus():
    mixer = profire()
    config = Config()
    config.link('ch/01','ch/04',0)
    commands=[]
    mixer.write = lambda mix, strip, control, value: commands.append((mix,strip,control,value))
    body = {'strip':'ch/01', 'control':'mute', 'value':True, 'mix':0}
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    flask.request = types.SimpleNamespace(get_json=lambda force=True: body)
    class App:
        def get(self, path):return lambda fn:fn
        def post(self, path):
            def decorator(fn):
                if path == '/api/set':self.set_value=fn
                return fn
            return decorator
    with patch.dict(sys.modules, {'flask':flask}):
        spec=importlib.util.spec_from_file_location('ffado_webmixer.api._bus_scoped_set_api',
                                                    ROOT/'ffado_webmixer/api/mixer.py')
        mod=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        app=App()
        mod.register(app,mixer,{},config,lambda event: None)
        assert app.set_value() == {'ok':True}
        assert [cmd[:2] for cmd in commands] == [(0,'ch/01'),(0,'ch/04')]
        commands.clear()
        body['mix'] = 1
        assert app.set_value() == {'ok':True}
        assert [cmd[:2] for cmd in commands] == [(1,'ch/01')]
