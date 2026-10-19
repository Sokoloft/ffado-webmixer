"""Matrix/strip synchronization on mocked ProFire hardware (no FireWire required).

The snapshots reported by rusk911 include diagonal input routing, two
cross-routes at different levels, and a four-crosspoint stereo block.
"""
import contextlib
import importlib.util
import io
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import make_debug_mixer
from ffado_webmixer.gain import db_to_raw, raw_to_ui


def profire():
    with contextlib.redirect_stdout(io.StringIO()):
        return make_debug_mixer('profire2626', Config(None))


def crosspoint(mixer, channel, bus, db):
    with contextlib.redirect_stdout(io.StringIO()):
        mixer.matrix_set(channel, bus, db=db, use_db=True)


def state_handler(mixer, config):
    """Import only the real API handlers with a tiny Flask request stub."""
    request = types.SimpleNamespace(args=types.SimpleNamespace(get=lambda *args, **kwargs: 0))
    flask = types.ModuleType('flask')
    flask.request = request
    flask.jsonify = lambda *args, **kwargs: args[0] if args else kwargs
    class App:
        def __init__(self): self.routes = {}
        def get(self, path):
            def register(fn): self.routes['GET', path] = fn; return fn
            return register
        def post(self, path):
            def register(fn): self.routes['POST', path] = fn; return fn
            return register
    # The module's import uses a relative path for the pair naming utility.
    # Load under its package without mutating the user's actual Flask install.
    name = 'ffado_webmixer.api._matrix_sync_test_api'
    filename = Path(__file__).parents[1]/'ffado_webmixer/api/mixer.py'
    with patch.dict(sys.modules, {'flask': flask}):
        from ffado_webmixer.services import stereo as stereo_module
        # services.stereo is allowed to be imported by any earlier test; it
        # only needs the stub at first import.
        spec = importlib.util.spec_from_file_location(name, filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app = App()
        module.register(app, mixer, {}, config, lambda event: None)
    return app.routes['GET', '/api/state']


def test_diagonal_stereo_matrix_fader_and_centered_pair():
    mixer = profire()
    config = Config(None)
    config.settings['stereo_buses'] = [0]
    config.stereo = [['ch/00', 'ch/01']]
    for ch in (0, 1):
        for bus in (0, 1): crosspoint(mixer, ch, bus, None)
    crosspoint(mixer, 0, 0, -0.4)
    crosspoint(mixer, 1, 1, -0.4)
    with contextlib.redirect_stdout(io.StringIO()):
        data = state_handler(mixer, config)()
    first, second = data['ch/00'], data['ch/01']
    assert first['pan'] == 0
    assert first['fader'] == pytest.approx(raw_to_ui(db_to_raw(-0.4, 'dice_db'),'dice_db'), abs=0.001)
    assert first['matrix_legs']['right_db'] is None
    assert second['matrix_legs']['left_db'] is None
    assert first['pair_mismatch'] is False
    assert '_matrix_raw' not in first


def test_four_active_stereo_crosspoints_are_read_without_changing_routing():
    mixer = profire()
    config = Config(None)
    config.settings['stereo_buses'] = [0]
    config.stereo = [['ch/00', 'ch/01']]
    for ch in (0, 1):
        for bus in (0, 1): crosspoint(mixer, ch, bus, -6.4)
    before = dict(mixer.helper.cells)
    with contextlib.redirect_stdout(io.StringIO()):
        data = state_handler(mixer, config)()
    assert before == mixer.helper.cells  # reading must never recross-route anything
    assert data['ch/00']['pan'] == 0
    assert data['ch/00']['pair_mismatch'] is False
    assert data['ch/00']['matrix_legs']['left_db'] == pytest.approx(-6.4, abs=0.05)
    assert data['ch/01']['matrix_legs']['right_db'] == pytest.approx(-6.4, abs=0.05)


def test_direct_matrix_edit_updates_volume_and_pan_from_same_coefficients():
    mixer = profire()
    config = Config(None)
    config.settings['stereo_buses'] = [0]
    crosspoint(mixer, 3, 0, -3.7)
    crosspoint(mixer, 3, 1, -50.1)
    with contextlib.redirect_stdout(io.StringIO()):
        data = state_handler(mixer, config)()
    state = data['ch/03']
    assert state['fader'] == pytest.approx(raw_to_ui(db_to_raw(-3.7,'dice_db'), 'dice_db'), abs=0.01)
    assert state['pan'] < -0.98
    assert state['matrix_legs']['left_db'] == pytest.approx(-3.7, abs=0.05)
    assert state['matrix_legs']['right_db'] == pytest.approx(-50.1, abs=0.2)
    crosspoint(mixer, 3, 1, -3.7)
    with contextlib.redirect_stdout(io.StringIO()):
        updated = state_handler(mixer, config)()['ch/03']
    assert updated['pan'] == 0
    assert updated['fader'] == pytest.approx(state['fader'], abs=0.01)


def test_linked_inputs_with_unequal_levels_report_max_and_weighted_pan():
    mixer = profire()
    config = Config(None)
    config.settings['stereo_buses'] = [0]
    config.stereo = [['ch/00', 'ch/01']]
    for ch in (0, 1):
        for bus in (0, 1): crosspoint(mixer, ch, bus, None)
    crosspoint(mixer, 0, 0, -0.4)
    crosspoint(mixer, 1, 1, -20)
    with contextlib.redirect_stdout(io.StringIO()):
        data = state_handler(mixer, config)()
    first = data['ch/00']
    assert first['pair_mismatch']
    assert first['pair_faders'][0] > first['pair_faders'][1]
    assert first['fader'] == first['pair_faders'][0]
    assert first['pan'] < -0.5  # channel 1 contributes more output than channel 2


def test_unlinked_output_and_motu_read_state_do_not_assume_stereo():
    config = Config(None)
    for model in ('profire2626', 'motuultralite'):
        mixer = profire() if model == 'profire2626' else make_debug_mixer(model, config)
        with contextlib.redirect_stdout(io.StringIO()):
            data = state_handler(mixer, config)()
        assert '_matrix_raw' not in data['ch/00']
        assert 'matrix_legs' not in data['ch/00']


def test_linked_input_unequal_gain_on_unpaired_bus_is_not_hidden():
    mixer = profire()
    config = Config(None)
    config.stereo = [['ch/00', 'ch/01']]
    crosspoint(mixer, 0, 0, -0.4)
    crosspoint(mixer, 1, 0, -12)
    with contextlib.redirect_stdout(io.StringIO()):
        data = state_handler(mixer, config)()
    assert data['ch/00']['pair_mismatch']
    assert data['ch/00']['fader'] == max(data['ch/00']['pair_faders'])


def test_browser_refresh_and_mismatch_cue_remain_connected():
    root = Path(__file__).parents[1]/'ffado_webmixer/assets/static'
    routing = (root/'routing.js').read_text()
    index = (root/'index.js').read_text()
    assert 'window.refreshMatrixStrips === "function"' in routing
    assert 'window.refreshMatrixStrips = loadMix' in index
    assert 'if (ev.type === "matrix")' in index
    assert 'data.pair_mismatch' in index
    assert 'valueLabel.textContent = "MAX "' in index
