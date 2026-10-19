"""Arbitrary ordered L/R inputs and no surprise crosspoint writes."""
import contextlib
import io
from pathlib import Path
import sys
import types
from unittest.mock import patch
import importlib.util

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.gain import db_to_raw


def profire():
    with contextlib.redirect_stdout(io.StringIO()):
        return make_debug_mixer('profire2626', Config(None))


def edit(mixer, col, bus, db):
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.matrix_set(col, bus, db=db, use_db=True)


def stub_stereo_handler(backend, config):
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *a, **k: a[0] if a else k
    name = 'ffado_webmixer.services._pair_test_stereo'
    path = Path(__file__).parents[1] / 'ffado_webmixer/services/stereo.py'
    with patch.dict(sys.modules, {'flask': flask}):
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    events = []
    return lambda msg, mix=0: mod.change_stereo(msg, mix, backend, backend.describe(), config, events.append)


def matrix_copy(mixer):
    return dict(mixer.helper.cells)


def test_arbitrary_pair_first_clicked_is_left_and_never_rewrites_matrix():
    mixer = profire()
    config = Config(None)
    config.layouts['0'] = [dict(id=f'ch/{i:02}', pinned=True, minimized=False) for i in range(8)]
    # Channel 2 = ch/01 is the LEFT. Channel 5 = ch/04 is the RIGHT.
    edit(mixer, 1, 0, -0.4)
    edit(mixer, 4, 1, -0.4)
    edit(mixer, 1, 1, None)
    edit(mixer, 4, 0, None)
    old = matrix_copy(mixer)
    handler = stub_stereo_handler(mixer, config)
    result = handler({'action':'link','dragged':'ch/01','target':'ch/04'})
    assert result['ok'] and result['left'] == 'ch/01' and result['right'] == 'ch/04'
    assert config.pair_of('ch/04') == ['ch/01','ch/04']
    assert matrix_copy(mixer) == old
    # The hidden Right strip retains its original layout entry and position.
    assert [e['id'] for e in config.layouts['0']] == [f'ch/{i:02}' for i in range(8)]
    response = handler({'action':'unlink','id':'ch/04'})
    assert response['ok']
    assert matrix_copy(mixer) == old
    assert config.pair_of('ch/01') is None


def test_reversed_number_pair_preserves_left_right_order():
    mixer = profire()
    config = Config(None)
    handler = stub_stereo_handler(mixer, config)
    result = handler({'action':'link','dragged':'ch/07','target':'ch/02'})
    assert result['ok']
    assert config.pairs_for(0) == [['ch/07','ch/02']]
    assert handler({'action':'link','dragged':'ch/07','target':'ch/08'})[1] == 400
    assert handler({'action':'link','dragged':'ch/04','target':'ch/04'})[1] == 400
    assert config.pairs_for(0) == [['ch/07','ch/02']]


def test_link_and_unlink_preserve_custom_four_point_routing():
    mixer = profire()
    config = Config(None)
    for col in (1,4):
        for bus in (0,1): edit(mixer,col,bus,-6.4)
    old = matrix_copy(mixer)
    handler = stub_stereo_handler(mixer, config)
    assert handler({'action':'link','dragged':'ch/01','target':'ch/04'})['ok']
    assert handler({'action':'unlink','id':'ch/01'})['ok']
    assert matrix_copy(mixer) == old


def test_diagonal_input_balance_never_creates_cross_routes_and_recovers_from_endstop():
    mixer = profire()
    # Arbitrary pairing: 2 is Left, 5 is Right.
    for col in (1, 4):
        for bus in (0, 1): edit(mixer,col,bus,None)
    edit(mixer,1,0,-0.4)
    edit(mixer,4,1,-0.4)
    path=mixer.roles['fader'][0]
    original_left=mixer._get_cell(path,0,1)
    original_right=mixer._get_cell(path,1,4)
    assert original_left and original_right
    for pan in (-0.5, -1, 0, 1, 0):
        with contextlib.redirect_stdout(io.StringIO()):
            mixer.write_input_pair_balance(0,1,4,pan)
        assert mixer._get_cell(path,1,1) == 0  # Left input never gets Right output
        assert mixer._get_cell(path,0,4) == 0  # Right input never gets Left output
    assert mixer._get_cell(path,0,1) == original_left
    assert mixer._get_cell(path,1,4) == original_right


def test_empty_routes_never_open_and_user_crosspoints_untouched():
    mixer = profire()
    for col in (1,4):
        for bus in (0,1): edit(mixer,col,bus,None)
    # Right input is disconnected on its own right bus, but left's cross-route
    # is present because the user independently configured it.
    edit(mixer,1,0,-6.4)
    edit(mixer,1,1,-12)
    previous_cross = mixer._get_cell(mixer.roles['fader'][0],1,1)
    for pan in (-1, 0, 1, 0):
        with contextlib.redirect_stdout(io.StringIO()): mixer.write_input_pair_balance(0,1,4,pan)
        assert mixer._get_cell(mixer.roles['fader'][0],1,1) == previous_cross
        assert mixer._get_cell(mixer.roles['fader'][0],1,4) == 0
    # All disconnected: never introduce a route through a balance control.
    for col in (1,4):
        for bus in (0,1): edit(mixer,col,bus,None)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.write_input_pair_balance(0,1,4,0.5)
    assert mixer._get_cell(mixer.roles['fader'][0],0,1) == 0
    assert mixer._get_cell(mixer.roles['fader'][0],1,4) == 0


def test_external_matrix_edits_invalidate_cached_balance_reference():
    mixer = profire()
    edit(mixer,1,0,-0.4)
    edit(mixer,4,1,-0.4)
    with contextlib.redirect_stdout(io.StringIO()): mixer.write_input_pair_balance(0,1,4,-1)
    # An external edit must override the stored Right-side restore value.
    edit(mixer,1,0,-15)
    with contextlib.redirect_stdout(io.StringIO()): mixer.write_input_pair_balance(0,1,4,0)
    assert mixer._get_cell(mixer.roles['fader'][0],1,4) == 0
    mixer.forget_input_pair_balance('ch/01','ch/04')
    assert mixer._input_pair_balance_cache == {}


def test_input_pair_pan_ui_readback_uses_ordered_diagonal_not_four_cell_sum():
    # Two differently numbered channels, both cross routes active.
    from test_matrix_live_strip_sync import state_handler
    mixer = profire()
    config = Config(None)
    config.settings['stereo_buses'] = [0]
    config.stereo=[['ch/04','ch/01']]
    for col in (1, 4):
        for bus in (0,1): edit(mixer,col,bus,None)
    edit(mixer,4,0,-3)
    edit(mixer,1,1,-20)
    edit(mixer,4,1,-3)
    edit(mixer,1,0,-3)
    # Summing four cells would show centered pan, but the ordered diagonal
    # clearly has a stronger Left source than Right source.
    with contextlib.redirect_stdout(io.StringIO()): state=state_handler(mixer, config)()
    assert state['ch/04']['partner']=='ch/01'
    assert state['ch/04']['pan'] < -0.4
    assert state['ch/01']['partner_of']=='ch/04'


def test_invalid_balance_and_nonadjacent_hardware_bus_rejected():
    mixer = profire()
    for args in [(0,1,1,0), (1,1,4,0), (0,1,4,float('nan')), (0,1,4,2)]:
        with pytest.raises(ValueError): mixer.write_input_pair_balance(*args)


def test_api_pair_pan_uses_ordered_diagonal_writes():
    """Exercise /api/set, not just the lower-level matrix method."""
    mixer = profire()
    config = Config(None)
    config.stereo = [['ch/01', 'ch/04']]
    config.settings['stereo_buses'] = [0]
    for col in (1,4):
        for bus in (0,1): edit(mixer,col,bus,None)
    edit(mixer,1,0,-0.4)
    edit(mixer,4,1,-0.4)
    called = []
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *a, **k: a[0] if a else k
    flask.request = types.SimpleNamespace(get_json=lambda force=True: {
        'strip':'ch/01', 'control':'pan', 'value':-1, 'mix':0})
    class App:
        routes = {}
        def get(self, path):
            def decorator(fn): return fn
            return decorator
        def post(self, path):
            def decorator(fn):
                self.routes[path] = fn
                return fn
            return decorator
    path=Path(__file__).parents[1]/'ffado_webmixer/api/mixer.py'
    with patch.dict(sys.modules, {'flask':flask}):
        spec=importlib.util.spec_from_file_location('ffado_webmixer.api._any_pair_api',path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app=App()
        module.register(app,mixer,mixer.describe(),config,called.append)
        with contextlib.redirect_stdout(io.StringIO()): result=app.routes['/api/set']()
    assert result == {'ok':True}
    assert called[-1]['control']=='pan'
    assert mixer._get_cell(mixer.roles['fader'][0],1,4)==0  # Right diagonal muted
    assert mixer._get_cell(mixer.roles['fader'][0],1,1)==0  # Left cross-route remains off
    assert mixer._get_cell(mixer.roles['fader'][0],0,4)==0  # Right cross-route remains off


def test_reversed_input_order_api_state_is_still_first_click_left():
    from test_matrix_live_strip_sync import state_handler
    mixer=profire()
    config=Config(None)
    config.settings['stereo_buses']=[0]
    config.stereo=[['ch/07','ch/02']]
    for col in (2,7):
        for bus in (0,1): edit(mixer,col,bus,None)
    edit(mixer,7,0,-0.4)
    edit(mixer,2,1,-0.4)
    with contextlib.redirect_stdout(io.StringIO()): data=state_handler(mixer,config)()
    assert data['ch/07']['partner']=='ch/02'
    assert data['ch/07']['pan']==0
    assert data['ch/02']['partner_of']=='ch/07'


def test_balance_partial_failure_rolls_back_both_crosspoints():
    mixer=profire()
    edit(mixer,1,0,-0.4)
    edit(mixer,4,1,-12)
    path=mixer.roles['fader'][0]
    original=(mixer._get_cell(path,0,1),mixer._get_cell(path,1,4))
    base=mixer._write_gain_cell
    tripped=[False]
    def fail_second_after_writing(bus,col,raw):
        base(bus,col,raw)
        if bus == 1 and col == 4 and not tripped[0]:
            tripped[0]=True
            raise IOError('Simulated FFADO readback failure')
    mixer._write_gain_cell=fail_second_after_writing
    with contextlib.redirect_stdout(io.StringIO()):
        with pytest.raises(IOError,match='Simulated'):
            mixer.write_input_pair_balance(0,1,4,0.5)
    assert (mixer._get_cell(path,0,1),mixer._get_cell(path,1,4)) == original
    assert not getattr(mixer,'_input_pair_balance_cache',{})
