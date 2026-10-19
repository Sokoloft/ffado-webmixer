"""Only digital mixer *labels* change; preamp and API identifiers remain."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / 'ffado_webmixer/assets/static/index.html').read_text()
JS = (ROOT / 'ffado_webmixer/assets/static/index.js').read_text()
ROUTING = (ROOT / 'ffado_webmixer/assets/static/routing.js').read_text()


def test_matrix_precise_editor_and_presets_are_volume_labeled():
    for text in ('>Volume</label>', 'Mixer volume knob', 'Selected mixer volume',
                 'Mixer volume in dB', 'mixer volume preset', 'Input volume into each mixer output'):
        assert text in HTML
    assert 'Matrix gain knob' not in HTML
    assert 'Matrix gain in dB' not in HTML
    assert 'to ' + "' + outname + ' mixer volume'" in ROUTING


def test_strip_and_master_describe_digital_volume():
    assert 'title=\"Digital mixer volume\"' in JS
    assert 'title="Output volume"' in HTML
    assert 'title="Digital mixer volume"' in JS  # frontend template string


def test_distinct_preamp_gain_remains_a_gain_control():
    assert 'INPUT GAIN' in JS
    assert 'Hardware input gain/trim, separate from digital mixer volume' in JS
    assert 'FEATURES.gain' in JS
    assert 'send(chId, "gain", gain)' in JS
    assert 'control === "gain"' in JS
    assert 'data.gain' in JS


def test_router_instructions_and_mute_recovery_use_volume_not_preamp_gain():
    assert 'mixer volume levels remain untouched' in ROUTING
    assert 'saved mixer volume levels' in JS
    assert 'mixer volume level(s) could not be restored' in JS
