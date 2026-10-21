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
    assert 'const right = el.dataset.partner ? channelKey(el.dataset.partner) : null;' in METERS
    assert "{side: 'left', channel: left}" in METERS
    assert "lanes.push({side: 'right', channel: right})" in METERS
    assert '.peak-meter.stereo-meter' in CSS
    assert '.peak-lane.clipping .peak-clip' in CSS


def test_no_artificial_post_fader_or_unmapped_channels():
    assert 'const item = channel === null ? null : channels[channel];' in METERS
    assert 'if (!validSample(item)) { lane.hidden = true; return; }' in METERS
    assert "not post-fader" in METERS
    assert 'router destination' in METERS.lower()
    assert '.peak-meter[hidden] { display:none; }' in CSS
    assert 'return Number.isSafeInteger(index) ? String(index) : null;' in METERS
    assert "MIXER_INPUT.fullmatch(router_destination)" in BACKEND
    assert "'full_scale': 4096" in BACKEND
    assert "calibrated_dbfs': False" in BACKEND


def test_no_hidden_meter_overlaid_on_master():
    assert '<div class="track" id="masterTrack"' in (ROOT / 'ffado_webmixer/assets/static/index.html').read_text()
    assert "const meter = el.querySelector('.peak-meter')" in METERS
    assert 'if (!meter) return;' in METERS


def test_full_height_gradient_is_clipped_not_scaled_with_signal_height():
    """Colors must reflect absolute position on the meter's full 0..1 track."""
    ROUTING_CSS = (ROOT / 'ffado_webmixer/assets/static/routing.css').read_text()
    ROUTING_JS = (ROOT / 'ffado_webmixer/assets/static/routing.js').read_text()
    assert '.peak-bar { position:absolute; inset:0; height:100%;' in CSS
    assert 'clip-path:inset(100% 0 0 0)' in CSS
    assert '#43b581 89%' in CSS and '#e05454 97%' in CSS
    assert "lane.querySelector('.peak-bar').style.clipPath" in METERS
    assert "lane.querySelector('.peak-bar').style.height" not in METERS
    assert '.route-peak-fill { position:absolute; inset:0; height:100%; width:100%;' in ROUTING_CSS
    assert 'clip-path:inset(0 100% 0 0)' in ROUTING_CSS
    assert '#43b581 89%' in ROUTING_CSS and '#e05454 97%' in ROUTING_CSS
    assert "meter.querySelector('.route-peak-fill').style.clipPath" in ROUTING_JS
    assert "meter.querySelector('.route-peak-fill').style.width" not in ROUTING_JS
    # Real raw hardware peak and warning/hold timing stay unchanged.
    assert 'if (item.near_full_scale) state.clipUntil = now + CLIP_HOLD_MS;' in METERS
    assert 'state.held * 100' in METERS
