"""DICE CrossbarRouter changes must update the fader's displayed input source.

Simulated FFADO only: no physical Saffire/ProFire verification implied.
"""
import contextlib
import io
from pathlib import Path

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from test_stereo_group_mute import api


def simulated_router(model='saffirepro40'):
    config = Config(None)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer = make_debug_mixer(model, config)
    if mixer.matrix.get('transposed'):
        assert mixer._router_input_columns['Mixer/In:01'] == 0
        assert mixer._router_input_columns['Mixer/In:02'] == 1
    sources = ['Anlg/In:01', 'Mic/Lin/In:03', '1394/In:01', '1394/In:02',
               'SPDIF/In:01', 'Mixer/Out:01', 'Mute:00']
    routes = {
        'Mixer/In:01': 'Anlg/In:01',
        'Mixer/In:02': 'Mic/Lin/In:03',
        'Line/Out:01': 'Mixer/Out:01',
    }
    calls = []
    def router_call(path, method, *args):
        calls.append((method, args))
        if method == 'getSourceNames':
            return sources
        if method == 'getDestinationNames':
            return list(routes)
        if method == 'getSourceForDestination':
            return routes[args[0]]
        if method == 'setConnectionState':
            source, dest, enabled = args
            routes[dest] = source if enabled else 'Mute:00'
            return True
        raise AssertionError(method)
    mixer.helper.router_call = router_call
    return mixer, config, routes, calls


@pytest.mark.parametrize('model', ['saffirepro40', 'saffirepro26', 'profire2626'])
def test_router_select_updates_correct_input_without_reordering_columns(model):
    mixer, config, routes, calls = simulated_router(model)
    with contextlib.redirect_stdout(io.StringIO()):
        snapshot = mixer.router_snapshot()
        assert snapshot['selected']['Mixer/In:01'] == 'Anlg/In:01'
        assert mixer.read_mix(0)['ch/00']['input'] == 'Anlg/In:01'
        original_matrix = dict(mixer.helper.cells)
        mixer.router_set('Mixer/In:01', '1394/In:01')
        state = mixer.read_mix(0)
        assert state['ch/00']['input'] == '1394/In:01'
        assert state['ch/00']['name'] == '1394/In:01'
        assert state['ch/01']['input'] == 'Mic/Lin/In:03'
        assert len(state) == len(mixer._visible_cols())
        assert mixer.columns[0] == 'Anlg/In:01'  # original hardware matrix identity
        assert mixer.helper.cells == original_matrix
        # Reading a bus must not issue one CrossbarRouter request per fader.
        assert sum(method == 'getSourceForDestination' for method, _ in calls) == 5


@pytest.mark.parametrize('model', ['saffirepro40', 'profire2626'])
def test_stereo_pair_name_tracks_both_selected_sources_and_preserves_custom_names(model):
    mixer, config, routes, calls = simulated_router(model)
    config.link('ch/00', 'ch/01', 0)
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.router_set('Mixer/In:01', '1394/In:01')
        mixer.router_set('Mixer/In:02', '1394/In:02')
        for app, events in api(mixer, config, mix=0):
            state = app.state()
            assert state['ch/00']['input'] == '1394/In:01+02'
            assert state['ch/00']['name'] == '1394/In:01+02'
            assert state['ch/01']['partner_of'] == 'ch/00'
            config.names['ch/00'] = 'Vocals'
            state = app.state()
            assert state['ch/00']['name'] == 'Vocals'
            assert state['ch/00']['input'] == '1394/In:01+02'


def test_refresh_from_ffado_reads_external_changes_and_disconnection():
    mixer, config, routes, calls = simulated_router()
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.router_snapshot()
        routes['Mixer/In:01'] = 'SPDIF/In:01'   # outside ffado-webmixer
        assert mixer.read_mix(0)['ch/00']['input'] == 'Anlg/In:01'  # cached until refresh
        mixer.router_snapshot()
        assert mixer.read_mix(0)['ch/00']['input'] == 'SPDIF/In:01'
        mixer.router_set('Mixer/In:01', '')
        assert routes['Mixer/In:01'] == 'Mute:00'
        assert mixer.read_mix(0)['ch/00']['input'] == 'Disconnected'
        mixer.router_set('Mixer/In:01', '1394/In:01')
        assert mixer.read_mix(0)['ch/00']['input'] == '1394/In:01'


def test_unrelated_crossbar_output_never_renames_input():
    mixer, config, routes, calls = simulated_router()
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.router_snapshot()
        before = [entry['input'] for entry in mixer.read_mix(0).values()]
        mixer.router_set('Line/Out:01', '')
        assert before == [entry['input'] for entry in mixer.read_mix(0).values()]
        assert 'Line/Out:01' not in mixer._router_input_sources


def test_invalid_or_failed_write_preserves_previous_source_label():
    mixer, config, routes, calls = simulated_router()
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.router_snapshot()
        old = mixer.read_mix(0)['ch/00']['input']
        with pytest.raises(ValueError):
            mixer.router_set('Mixer/In:01', 'NotARealSource')
        assert mixer.read_mix(0)['ch/00']['input'] == old
        def rejection(path, method, *args):
            if method == 'setConnectionState':
                return False
            if method == 'getSourceNames':
                return ['Anlg/In:01', '1394/In:01', 'Mute:00']
            if method == 'getDestinationNames':
                return list(routes)
            if method == 'getSourceForDestination':
                return routes[args[0]]
            raise AssertionError(method)
        mixer.helper.router_call = rejection
        with pytest.raises(ValueError):
            mixer.router_set('Mixer/In:01', '1394/In:01')
        assert mixer.read_mix(0)['ch/00']['input'] == old


def test_ui_refreshes_current_and_other_browser_strips():
    root = Path(__file__).resolve().parents[1]
    routing = (root / 'src/ffado_webmixer/assets/static/routing.js').read_text()
    index = (root / 'src/ffado_webmixer/assets/static/index.js').read_text()
    assert "if (window.refreshMatrixStrips && dest.startsWith('Mixer/In:'))" in routing
    assert 'window.refreshMatrixStrips();' in routing
    sync = (root / 'src/ffado_webmixer/assets/static/live-sync.js').read_text()
    assert 'if (ev.type === "routing")' in sync
    assert "ev.origin !== CLIENT_ID" in sync
    assert "String(ev.destination || '').startsWith('Mixer/In:')" in sync
    assert "loadMix();" in sync.split('if (ev.type === "routing")', 1)[1].split('return;', 1)[0]
