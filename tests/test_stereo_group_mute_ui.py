"""Guard against reverting the hardware-verified stereo mute UI behavior."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / 'src/ffado_webmixer/assets/static/index.js').read_text()
CSS = (ROOT / 'src/ffado_webmixer/assets/static/index.css').read_text()


def test_stereo_partial_state_is_visibly_distinct():
    assert "if (data.mute_partial)" in JS
    assert "el.classList.add('mute-partial')" in JS
    assert '.strip.mute-partial:not(.muted) .mute' in CSS
    assert 'Only part of this stereo route is muted' in JS


def test_strips_wait_for_acknowledgement_before_redrawing_mute():
    action = JS.split('  function toggleHardware(control, on) {', 1)[1].split('\n  soloEl.addEventListener', 1)[0]
    assert "button.disabled = true" in action
    assert "if (!r.ok || d.error) throw Error" in action
    assert '.then(() => loadMix())' in action
    assert 'loadMuteRecovery()' in action
    assert "el.classList.toggle(control === 'solo' ? 'soloed' : 'muted', on)" not in action


def test_master_mute_surfaces_hardware_errors_and_reload():
    action = JS.split('document.getElementById("masterMute").addEventListener', 1)[1].split('});', 1)[0]
    assert 'Output mute write failed' in action
    assert '.then(loadMaster)' in action
    assert '.catch(' in action


def test_external_mute_events_read_both_matrix_legs():
    sync = (ROOT / 'src/ffado_webmixer/assets/static/live-sync.js').read_text()
    assert '["fader", "pan", "mute", "solo"].includes(ev.control)' in sync
