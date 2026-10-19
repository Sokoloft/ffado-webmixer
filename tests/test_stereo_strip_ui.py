"""Regression guards for compact odd-strip stereo toggles and stereo balance."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'ffado_webmixer/assets/static/index.js').read_text()
CSS = (ROOT / 'ffado_webmixer/assets/static/index.css').read_text()
API = (ROOT / 'ffado_webmixer/api/mixer.py').read_text()

def test_stereo_control_lives_on_strip_in_both_states():
    assert '(stereo ? \'<button class="unlink"' in JS
    assert 'q(".unlink").addEventListener("click"' in JS
    assert "b.className = 'unlink link-toggle';" in JS
    assert 'el.appendChild(b);' in JS
    assert "el.insertAdjacentElement('afterend', b);" not in JS
    assert ".strip .unlink { position: absolute; bottom: 3px; right: 3px;" in CSS
    assert '.pair-link {' not in CSS

def test_every_unpaired_channel_owns_link_toggle_and_first_is_left():
    assert "row.querySelectorAll(':scope > .strip').forEach(el =>" in JS
    assert "if (!state[id] || state[id].partner || state[id].partner_of) return;" in JS
    assert 'pendingStereoLeft = id;' in JS
    assert 'linkStrips(left, id);' in JS
    assert 'pendingStereoLeft === id' in JS
    assert "b.setAttribute('aria-pressed', String(selected));" in JS
    assert "b.className = 'unlink link-toggle';" in JS
    assert 'el.appendChild(b);' in JS
    assert "Only adjacent odd(L)/even(R)" not in JS

def test_minimized_strip_hides_toggle():
    assert '.strip.minimized > :not(.eye):not(.vname) { display: none; }' in CSS
    assert '#row.hide-min .strip.minimized { display: none; }' in CSS

def test_pan_is_not_hidden_for_stereo_and_uses_paired_balance():
    assert '|| stereo;' not in JS.split('q(".panrow").hidden =', 1)[1].split(';', 1)[0]
    assert "if control == 'pan' and config.pair_of(strip, mix):" in API
    assert 'backend.write_input_pair_balance(mix,' in API
    assert 'left_pan = -1 + 2 * max(0, position)' in API
    assert 'right_pan = 1 + 2 * min(0, position)' in API
