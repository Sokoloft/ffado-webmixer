"""Guard source-backed channel peak elements and identity assumptions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'ffado_webmixer/assets/static/index.js').read_text()
CSS = (ROOT / 'ffado_webmixer/assets/static/index.css').read_text()
METERS = (ROOT / 'ffado_webmixer/assets/static/peak-metering.js').read_text()
BACKEND = (ROOT / 'ffado_webmixer/peak_metering.py').read_text()


def test_stereo_lanes_created_in_user_selected_left_right_order():
    assert 'data-side="left"' in JS
    assert 'data-side="right"' in JS
    assert 'el.dataset.partner = pid' in JS
    assert 'const right = el.dataset.partner ? el.dataset.partner.split' in METERS
    assert "{side: 'left', channel: left}" in METERS
    assert "lanes.push({side: 'right', channel: right})" in METERS
    assert '.peak-meter.stereo-meter' in CSS
    assert '.peak-lane.clipping .peak-clip' in CSS


def test_no_artificial_post_fader_or_unmapped_channels():
    assert 'const item = channels[channel]' in METERS
    assert 'if (!validSample(item)) { lane.hidden = true; return; }' in METERS
    assert "not post-fader" in METERS
    assert 'router destination' in METERS.lower()
    assert "MIXER_INPUT.fullmatch(router_destination)" in BACKEND
    assert "'full_scale': 4096" in BACKEND
    assert "calibrated_dbfs': False" in BACKEND


def test_no_hidden_meter_overlaid_on_master():
    assert '<div class="track" id="masterTrack"' in (ROOT / 'ffado_webmixer/assets/static/index.html').read_text()
    assert "const meter = el.querySelector('.peak-meter')" in METERS
    assert 'if (!meter) return;' in METERS
