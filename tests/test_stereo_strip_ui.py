"""Stereo actions must be on each strip's context menu, not floating links."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'src/ffado_webmixer/assets/static/index.js').read_text()
CSS = (ROOT / 'src/ffado_webmixer/assets/static/index.css').read_text()
API = (ROOT / 'src/ffado_webmixer/api/mixer.py').read_text()


def test_stereo_actions_on_each_strip_in_both_states():
    assert '<button class="strip-more"' in JS
    assert "q('.strip-more').addEventListener('click'" in JS
    assert "actions.push(['Unlink stereo channels', function () { unlinkStrip(id); }]);" in JS
    assert "chooseStereoChannel(id);" in JS
    assert 'showActionsMenu(q(\'.strip-more\')' in JS
    assert "'<button class=\"unlink pair-seam-link\"'" not in JS
    assert "b.className = 'unlink link-toggle pair-seam-link';" not in JS
    assert '.strip:not(.master) > .strip-more {' in CSS


def test_first_selection_still_defines_left_even_for_nonadjacent_channels():
    assert 'pendingStereoLeft = id;' in JS
    assert 'linkStrips(left, id);' in JS
    assert 'pendingStereoLeft === id' in JS
    assert "pendingStereoLeft ? 'Link as Right channel' : 'Link as Left channel'" in JS
    assert 'if (stereoLinkBusy) return;' in JS
    assert "Only adjacent odd(L)/even(R)" not in JS


def test_minimized_strip_keeps_three_dot_menu_visible():
    assert '.strip.minimized > :not(.vname):not(.strip-more) { display:none; }' in CSS
    assert '.strip.minimized > .strip-more { display:block;' in CSS
    assert '#row.hide-min .strip.minimized { display: none; }' in CSS


def test_pan_is_not_hidden_for_stereo_and_uses_paired_balance():
    assert '|| stereo;' not in JS.split('q(".panrow").hidden =', 1)[1].split(';', 1)[0]
    assert "if control == 'pan' and config.pair_of(strip, mix):" in API
    assert 'backend.write_input_pair_balance(mix,' in API
    assert 'left_pan = -1 + 2 * max(0, position)' in API
    assert 'right_pan = 1 + 2 * min(0, position)' in API
