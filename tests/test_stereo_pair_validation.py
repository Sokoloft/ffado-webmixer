"""Pair validation must never corrupt other pairs, routes, or saved layouts."""
import contextlib
import importlib.util
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import types
from unittest.mock import patch

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from test_arbitrary_stereo_pairs import matrix_copy

ROOT = Path(__file__).parents[1]


def profire():
    with contextlib.redirect_stdout(io.StringIO()):
        return make_debug_mixer('profire2626', Config())


def handler(mixer, config):
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *a, **k: a[0] if a else k
    with patch.dict(sys.modules, {'flask': flask}):
        spec = importlib.util.spec_from_file_location(
            'ffado_webmixer.services._pair_validation',
            ROOT / 'src/ffado_webmixer/services/stereo.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    events = []
    return lambda msg, mix=0: mod.change_stereo(
        msg, mix, mixer, mixer.describe(), config, events.append), events


@pytest.mark.parametrize('payload,bus', [
    (None, 0), ([], 0), ('link', 0), ({'action':'unknown'}, 0),
    ({'action':'link','dragged':'ch/01','target':'ch/04'}, -1),
    ({'action':'link','dragged':'ch/01','target':'ch/04'}, 999),
    ({'action':'link','dragged':'ch/01','target':'ch/04'}, True),
    ({'action':'link','dragged':'ch/01','target':'ch/01'}, 0),
    ({'action':'link','dragged':'ch/01','target':''}, 0),
    ({'action':'link','dragged':23,'target':'ch/04'}, 0),
    ({'action':'link','dragged':'ch/01','target':None}, 0),
    ({'action':'link','dragged':'ch/01','target':'ch/98'}, 0),
    ({'action':'unlink'}, 0),
    ({'action':'unlink','id':12}, 0),
    ({'action':'unlink','id':'ch/01'}, 0),
])
def test_invalid_requests_leave_all_bus_pair_layout_and_routing_state_unchanged(payload, bus):
    mixer, config = profire(), Config()
    config.link('ch/06','ch/07',mix=1)
    config.layouts['0'] = [{'id':'ch/01','pinned':False,'minimized':True}]
    initial_pairs = {str(i): config.pairs_for(i) for i in (0, 1)}
    initial_layouts = json.dumps(config.layouts, sort_keys=True)
    cells = matrix_copy(mixer)
    call, events = handler(mixer, config)
    response = call(payload, mix=bus)
    assert response[1] == 400
    assert {str(i): config.pairs_for(i) for i in (0,1)} == initial_pairs
    assert json.dumps(config.layouts,sort_keys=True) == initial_layouts
    assert matrix_copy(mixer) == cells
    assert not events


def test_pair_conflicts_report_existing_partner_and_do_not_change_state():
    mixer, config = profire(), Config()
    call, events = handler(mixer, config)
    assert call({'action':'link','dragged':'ch/01','target':'ch/04'})['ok']
    saved = json.dumps(config.stereo_by_mix,sort_keys=True)
    cells = matrix_copy(mixer)
    for a,b in [('ch/01','ch/06'),('ch/05','ch/04'),('ch/04','ch/01')]:
        error, status = call({'action':'link','dragged':a,'target':b})
        assert status == 400
        assert 'already linked' in error['error']
    assert json.dumps(config.stereo_by_mix,sort_keys=True) == saved
    assert len(events) == 1
    assert matrix_copy(mixer) == cells


def test_simultaneous_tabs_cannot_assign_same_channel_to_different_pairs(tmp_path):
    mixer = profire()
    config = Config(tmp_path/'device.json')
    config.save()
    original_read = mixer.read_mix
    barrier = threading.Barrier(2)

    def competing_read(mix):
        result = original_read(mix)
        barrier.wait(timeout=5)
        return result

    mixer.read_mix = competing_read
    call, events = handler(mixer,config)
    before = matrix_copy(mixer)
    with ThreadPoolExecutor(max_workers=2) as executor:
        tasks = [executor.submit(call,{'action':'link','dragged':'ch/01','target':target})
                 for target in ('ch/04','ch/06')]
        outcomes = [task.result(timeout=10) for task in tasks]
    assert sorted(isinstance(result, tuple) for result in outcomes) == [False, True]
    assert len(config.pairs_for(0)) == 1
    assert config.pairs_for(0)[0][0] == 'ch/01'
    assert len(events) == 1
    assert matrix_copy(mixer) == before
    persisted = Config(tmp_path/'device.json')
    persisted.load()
    assert persisted.pairs_for(0) == config.pairs_for(0)


def test_malformed_saved_links_are_sanitized_without_losing_valid_lr_order(tmp_path):
    file = tmp_path/'device.json'
    file.write_text(json.dumps({
        'stereo': [['ch/07','ch/02'], ['ch/07','ch/01'], ['ch/03','ch/03'],
                   ['ch/04',None], 'not a pair', ['ch/05'], ['', 'ch/06']],
        'stereo_by_mix': {'1': [['ch/01','ch/04'], ['ch/05','ch/04'], [],
                                ['ch/05','ch/06']], '2': 'invalid', 'bad': [['ch/00','ch/01']]}
    }))
    config=Config(file)
    config.load()
    assert config.pairs_for(0) == [['ch/07','ch/02']]
    assert config.pairs_for(1) == [['ch/01','ch/04'], ['ch/05','ch/06']]
    assert config.pairs_for(2) == []
    assert 'bad' not in config.stereo_by_mix
    config.save()
    reload=Config(file)
    reload.load()
    assert reload.pairs_for(0)==config.pairs_for(0)
    assert reload.pairs_for(1)==config.pairs_for(1)


def test_config_api_link_rejects_duplicate_or_invalid_pairs_directly():
    c=Config()
    c.link('ch/07','ch/02',1)
    for left,right in [('ch/02','ch/03'), ('ch/03','ch/07'), ('ch/01','ch/01'), (None,'ch/03')]:
        with pytest.raises(ValueError):
            c.link(left,right,1)
    assert c.pairs_for(1)==[['ch/07','ch/02']]
    with pytest.raises(ValueError):
        c.unlink('ch/00',1)
    assert c.pairs_for(0)==[]


@pytest.mark.parametrize('action', ['link','unlink'])
def test_save_failure_rolls_back_config_without_broadcast_or_hardware_change(action):
    mixer, config=profire(), Config()
    config.layouts['0'] = [{'id': 'ch/01', 'pinned': True, 'minimized': False}]
    if action=='unlink':
        config.link('ch/01','ch/04',0)
    saved_pairs = json.dumps(config.stereo_by_mix,sort_keys=True)
    saved_layouts = json.dumps(config.layouts,sort_keys=True)
    cells = matrix_copy(mixer)
    config.save = lambda: (_ for _ in ()).throw(OSError('Disk full'))
    call, events=handler(mixer,config)
    payload = ({'action':'link','dragged':'ch/01','target':'ch/04'} if action == 'link'
               else {'action':'unlink','id':'ch/01'})
    result=call(payload)
    assert result[1] == 500
    assert 'Disk full' in result[0]['error']
    assert json.dumps(config.stereo_by_mix,sort_keys=True) == saved_pairs
    assert json.dumps(config.layouts,sort_keys=True) == saved_layouts
    assert matrix_copy(mixer) == cells
    assert not events


def test_failed_backend_read_leaves_stereo_config_untouched():
    mixer, config=profire(),Config()
    mixer.read_mix = lambda mix: (_ for _ in ()).throw(ValueError('Disconnected'))
    call, events=handler(mixer,config)
    assert call({'action':'link','dragged':'ch/01','target':'ch/04'})[1] == 400
    assert config.stereo_by_mix == {}
    assert not events


def test_stereo_http_route_rejects_malformed_bus_before_handler():
    """Exercise the route's request parser without depending on Flask in CI."""
    mixer, config = profire(), Config()
    change, _ = handler(mixer, config)
    flask = types.ModuleType('flask')
    flask.jsonify = lambda *a, **k: a[0] if a else k
    raw = {'mix':'0', 'msg':None}
    flask.request = types.SimpleNamespace(
        args=types.SimpleNamespace(get=lambda key, default: raw.get(key,default)),
        get_json=lambda force=False: raw['msg'])
    services = types.ModuleType('ffado_webmixer.services.stereo')
    services.change_stereo = lambda msg, mix, *rest: change(msg,mix)
    class App:
        def post(self, route):
            def decorate(fn):
                self.stereo = fn
                return fn
            return decorate
    with patch.dict(sys.modules, {'flask':flask,'ffado_webmixer.services.stereo':services}):
        spec = importlib.util.spec_from_file_location(
            'ffado_webmixer.api._pair_http_test',
            ROOT / 'src/ffado_webmixer/api/stereo.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app = App()
        module.register(app,mixer,mixer.describe(),config,lambda ev:None)
        raw['msg']={'action':'link','dragged':'ch/01','target':'ch/04'}
        for raw_mix in ('-1','garbage','1x','1.5','9999999999999'):
            raw['mix']=raw_mix
            assert app.stereo()[1] == 400
            assert config.stereo_by_mix == {}
        raw['mix']='0'
        assert app.stereo()['ok']
        assert config.pairs_for(0) == [['ch/01','ch/04']]
        raw['msg']={'action':'link','dragged':'ch/01','target':'ch/06'}
        assert app.stereo()[1] == 400
        assert config.pairs_for(0) == [['ch/01','ch/04']]
        raw['mix']='1'
        assert app.stereo()['ok']
        assert config.pairs_for(1) == [['ch/01','ch/06']]
        raw['mix']='0'
        raw['msg']={'action':'unlink','id':'ch/04'}
        assert app.stereo()['ok']
        assert config.pairs_for(0) == []
        assert config.pairs_for(1) == [['ch/01','ch/06']]
