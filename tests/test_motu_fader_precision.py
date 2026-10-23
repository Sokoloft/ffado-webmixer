"""MOTU control round trips use native integer steps without percentage loss."""
import contextlib
import io

import pytest

from ffado_webmixer.config import Config
from ffado_webmixer.debug_backend import create_fixture, TraceHelper
from ffado_webmixer.gain import has_db_scale, motu_display_scale
from ffado_webmixer.mixer import Mixer


@pytest.fixture(params=[
    'motu_model_1.xml', 'motu_model_2.xml', 'motu_ultralite.xml',
    'motu_model_4.xml', 'motu_model_6.xml',
])
def mixer(request):
    device, profile = create_fixture(request.param)
    # Debug topology omits optional scalar controls. Add only the exact output
    # paths authorized by this particular pre-mk3 model's capabilities.
    feature = profile['capabilities']['features']['output_level']
    for suffix in feature.get('extra_paths', '').split(','):
        if suffix:
            device['controls'].append({'path': device['device'] + suffix,
                                       'kind': 'Discrete', 'label': suffix})

    class OfflineMixer(Mixer):
        def _find_profile(self):
            return profile

    with contextlib.redirect_stdout(io.StringIO()):
        return OfflineMixer(Config(None), device=device, helper=TraceHelper(device))


def test_matrix_and_strip_read_write_preserve_every_native_position(mixer):
    path = mixer.roles['fader'][0]
    with contextlib.redirect_stdout(io.StringIO()):
        for raw in range(129):
            mixer.helper.set_cell(path, 0, 0, raw)
            level = mixer.read_mix(0)['ch/00']['fader']
            mixer.write(0, 'ch/00', 'fader', level)
            assert mixer.helper.cells[path, 0, 0] == raw
            matrix_level = mixer.matrix_snapshot()['values'][0][0]
            mixer.matrix_set(0, 0, matrix_level)
            assert mixer.helper.cells[path, 0, 0] == raw


def test_output_read_write_preserves_every_native_position(mixer):
    with contextlib.redirect_stdout(io.StringIO()):
        for out_id, out in mixer.outputs.items():
            if not out['fader']:
                continue
            path = out['fader']['path']
            for raw in range(129):
                mixer.helper.values[path] = raw
                level = mixer.read_output(out_id)['level']
                mixer.write_output(out_id, 'fader', level)
                assert mixer.helper.values[path] == raw, (out_id, raw, level)


def test_display_metadata_does_not_enable_unverified_native_db_writes(mixer):
    with contextlib.redirect_stdout(io.StringIO()):
        info = mixer.describe()
    assert info['fader_scale'] == motu_display_scale() == {
        'mode': 'motu_db', 'min_db': -84, 'max_db': 0,
        'native_min': 0, 'native_max': 128, 'min_finite_native': 1,
        'step_native': 1, 'calibration': 'endpoint_interpolation',
    }
    assert info['gain_scale'] is None
    assert info['matrix']['mode'] == 'linear'
    assert not has_db_scale('motu_db')
    for output in info['outputs']:
        if output['controllable']:
            assert output['gain_scale'] == info['fader_scale']
    with pytest.raises(ValueError, match='does not support dB'):
        mixer.matrix_set(0, 0, db=-42, use_db=True)


def test_motu_display_scale_requires_a_verified_pre_mk3_model(mixer):
    spec = mixer.roles['fader'][1]
    assert mixer._fader_display_scale(spec, 'matrix_gain') is not None
    for unverified in (None, 5, 7, 8):
        mixer.profile['internal_model_id'] = unverified
        assert mixer._fader_display_scale(spec, 'matrix_gain') is None


def test_motu_gain_control_has_device_specific_label():
    device, profile = create_fixture('motuultralite')
    device['controls'].append({'path': device['device'] + '/Mixer/Control/Ana1_trimgain',
                               'kind': 'Discrete', 'label': 'Trim gain'})

    class OfflineMixer(Mixer):
        def _find_profile(self):
            return profile

    with contextlib.redirect_stdout(io.StringIO()):
        mixer = OfflineMixer(Config(None), device=device, helper=TraceHelper(device))
        assert mixer.describe()['features']['gain']['label'] == 'Gain'
