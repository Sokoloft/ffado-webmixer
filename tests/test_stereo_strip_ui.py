"""Regression guards for compact odd-strip stereo toggles and stereo balance."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'ffado_webmixer/assets/static/index.js').read_text()
CSS = (ROOT / 'ffado_webmixer/assets/static/index.css').read_text()
API = (ROOT / 'ffado_webmixer/api/mixer.py').read_text()

def test_stereo_control_lives_on_strip_in_both_states():
    assert '(stereo ? \'<button class="unlink"' in JS
    assert 'if (stereo) q(".unlink").addEventListener' in JS
    assert "b.className = 'unlink link-toggle';" in JS
    assert 'el.appendChild(b);' in JS
    assert "el.insertAdjacentElement('afterend', b);" not in JS
    assert ".strip .unlink { position: absolute; bottom: 3px; right: 3px;" in CSS
    assert '.pair-link {' not in CSS

def test_only_odd_channel_owns_link_toggle():
    assert "parseInt(id.split('/')[1], 10) % 2 === 0" in JS
    assert "var right = 'ch/' + String(ix + 1).padStart(2, '0');" in JS
    assert "if (!state[right] || state[left].partner === right) return;" in JS
    assert "linkStrips(left, right, Promise.resolve())" in JS

def test_minimized_strip_hides_toggle():
    assert '.strip.minimized > :not(.eye):not(.vname) { display: none; }' in CSS
    assert '#row.hide-min .strip.minimized { display: none; }' in CSS

def test_pan_is_not_hidden_for_stereo_and_uses_paired_balance():
    assert '|| stereo;' not in JS.split('q(".panrow").hidden =', 1)[1].split(';', 1)[0]
    assert "if control == 'pan' and config.pair_of(strip):" in API
    assert 'left_pan = -1 + 2 * max(0, position)' in API
    assert 'right_pan = 1 + 2 * min(0, position)' in API
