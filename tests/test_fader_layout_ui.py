"""Measure real browser geometry while remote refreshes hide/show peak meters."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_remote_control_refresh_ordering():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for event ordering checks')
    result = subprocess.run(
        [node, str(ROOT / 'tests/remote_controls_ui_test.cjs')],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_fader_tracks_stay_fixed_when_peak_meters_change():
    if importlib.util.find_spec('PyQt6') is None or importlib.util.find_spec('PyQt6.QtWebEngineWidgets') is None:
        pytest.skip('Qt WebEngine is required for browser layout checks')
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(ROOT)],
        env={**os.environ, 'QT_QPA_PLATFORM': 'offscreen',
             'QTWEBENGINE_DISABLE_SANDBOX': '1',
             'QTWEBENGINE_CHROMIUM_FLAGS': '--no-sandbox --disable-gpu --disable-dev-shm-usage'},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def browser_check(root):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    assets = root / 'src/ffado_webmixer/assets/static'
    css = (assets / 'index.css').read_text()
    source = (assets / 'index.js').read_text()
    load_master = source[source.index('function applyMasterState('):source.index('// ---- Bus tabs')]
    strip_helpers = source[source.index('function faderHasDbScale()'):source.index('// ---- appearance ----')]
    strip_state = source[source.index('function applyStripState('):source.index('function loadMix(')]
    # Use the production master refresh, with only its network and display
    # dependencies stubbed. The browser still lays out the real stylesheet.
    script = r"""
    const failures = [];
    const check = (ok, message) => { if (!ok) failures.push(message); };
    for (const kind of ['mono', 'stereo', 'master']) {
      for (const width of [88, 100, 108, 112, 124]) {
        const strip = document.createElement('div');
        strip.className = 'strip ' + (kind === 'mono' ? '' : kind);
        strip.style.cssText = `width:${width}px;height:400px;flex:none`;
        strip.innerHTML = '<div class="faderwrap"><div class="track"><div class="handle"></div></div>' +
          '<button class="peak-meter" hidden></button></div>';
        document.body.appendChild(strip);
        const wrap = strip.querySelector('.faderwrap');
        let track = strip.querySelector('.track');
        let meter = strip.querySelector('.peak-meter');
        const x = track.getBoundingClientRect().x;
        for (const state of ['mono', 'stereo', 'hidden', 'stereo', 'mono', 'hidden']) {
          meter.classList.toggle('stereo-meter', state === 'stereo');
          meter.hidden = state === 'hidden';
          const rect = track.getBoundingClientRect();
          check(Math.abs(rect.x - x) < 0.01, `${kind}/${width}/${state}: track moved sideways`);
          check(rect.height > 100, `${kind}/${width}: track lost its height`);
          if (!meter.hidden) {
            const peakRect = meter.getBoundingClientRect();
            check(Math.abs(peakRect.height - (wrap.clientHeight - 26)) < 1, 'meter height changed');
            check(peakRect.left >= rect.right + 17, 'meter overlaps the fader handle');
          }
        }
        // Channel refreshes currently recreate strips with hidden meters.
        const rebuilt = strip.cloneNode(true);
        strip.replaceWith(rebuilt);
        track = rebuilt.querySelector('.track');
        meter = rebuilt.querySelector('.peak-meter');
        check(Math.abs(track.getBoundingClientRect().x - x) < 0.01, 'rebuilding moved the track');
        meter.hidden = false;
        check(Math.abs(track.getBoundingClientRect().x - x) < 0.01, 'first peak after rebuild moved the track');
        rebuilt.remove();
      }
    }
    var currentOut = 'main', ACTIVE_DEVICE = 'unit-a', masterToken = 0;
    var masterReady = false, masterHardwareControlled = false;
    var OUTPUTS = [{id:'main', controllable:true, baseName:'Main'},
                   {id:'phones', controllable:true, baseName:'Phones'}];
    var masterEl = document.getElementById('master');
    var masterHardwareName = {textContent:''}, masterFader = {set() {}};
    var canonicalOutput = out => out, partner = null, outputPartner = () => partner;
    var showMasterName = () => {}, toast = message => failures.push(message);
    window.ffadoApi = {cancel() {}, latest() { return Promise.resolve({name:'Main',level:50,mute:false}); }};
    const meter = masterEl.querySelector('.peak-meter');
    loadMaster();
    check(meter.hidden, 'initial load must hide unverified output peaks');
    meter.hidden = false;
    loadMaster();
    check(!meter.hidden, 'same-output remote refresh hid the meter');
    partner = {id:'right'};
    loadMaster();
    check(meter.hidden, 'pair change must invalidate previous peaks');
    meter.hidden = false;
    loadMaster();
    check(!meter.hidden, 'same-pair remote refresh hid the meter');
    currentOut = 'phones';
    loadMaster();
    check(meter.hidden, 'output switch must invalidate previous peaks');

    // Exercise production strip controls in a real DOM: applying readback
    // must preserve meter nodes, holds and visibility without sending writes.
    var currentMix = 0, lastStripMix = 0, lastStripState = null;
    var GAIN_SCALE = {mode:'dice_db',min_db:-60,max_db:6}, FADER_SCALE = null;
    var FEATURES = {software_solo:true}, FADER_ALLOWED = true, MUTE_ALLOWED = true;
    var STEREO_BUSES = [0], queuedControlWrites = {}, writes = 0;
    var sendThrottled = () => { writes++; }, send = sendThrottled;
    var shortFfadoLabel = name => name, vertical = name => name;
    var setPinned = () => {}, setMinimized = () => {};
    var row = document.createElement('div');
    document.body.appendChild(row);
    var state = {
      'ch/00':{name:'Mono',input:'Input 1',fader:40,pan:.25},
      'ch/01':{name:'Stereo',input:'Input 2',fader:50,pan:-.5,partner:'ch/02'},
      'ch/02':{name:'Right',input:'Input 3',partner_of:'ch/01'}
    };
    const mono = buildStrip('ch/00',state['ch/00'],true,false);
    const stereo = buildStrip('ch/01',state['ch/01'],true,false,state['ch/02']);
    row.append(mono,stereo);
    const peak = stereo.querySelector('.peak-meter');
    peak.hidden = false;
    const hold = peak.querySelector('.peak-hold');
    hold.style.bottom = '80%';
    const label = stereo.querySelector('.fval');
    const originalTitle = label.title;
    state['ch/00'] = {...state['ch/00'],fader:60,pan:null,pan_available:false};
    state['ch/01'] = {...state['ch/01'],fader:70,pan:.5,mute:true,solo:true,
      mute_partial:true,pair_mismatch:true,pair_faders:[60,70]};
    check(applyStripState(state,[]), 'same topology should update in place');
    check(row.children[1] === stereo && stereo.querySelector('.peak-meter') === peak, 'strip/meter replaced');
    check(!peak.hidden && hold.style.bottom === '80%', 'peak display/hold reset');
    check(label.value.startsWith('MAX ') && label.classList.contains('level-mismatch'), 'stereo mismatch missing');
    check(stereo.querySelector('.panval').textContent === 'R50', 'derived stereo pan not applied');
    check(mono.querySelector('.pan').disabled, 'undefined pan must remain disabled');
    check(stereo.classList.contains('muted') && stereo.classList.contains('soloed') &&
      stereo.classList.contains('mute-partial'), 'mute/solo status not applied');
    state['ch/01'] = {...state['ch/01'],pair_mismatch:false,mute_partial:false,mute:false,solo:false};
    applyStripState(state,[]);
    check(!label.value.startsWith('MAX ') && label.title === originalTitle &&
      !label.classList.contains('level-mismatch'), 'stereo mismatch did not clear');
    check(!stereo.classList.contains('mute-partial') &&
      !stereo.querySelector('.mute').title.includes('Only part'), 'partial mute did not clear');
    const position = stereo.querySelector('.handle').style.top;
    queuedControlWrites['unit-a|0|ch/01|fader'] = {};
    state['ch/01'].fader = 10;
    applyStripState(state,[]);
    check(stereo.querySelector('.handle').style.top === position, 'pending local edit overwritten');
    delete queuedControlWrites['unit-a|0|ch/01|fader'];
    applyStripState(state,['unit-a|0|ch/01|pan']);
    check(stereo.querySelector('.handle').style.top === position, 'read-start local edit overwritten');
    label.dispatchEvent(new Event('focus'));
    label.value = '-12';
    applyStripState(state,[]);
    check(label.value === '-12' && stereo.querySelector('.handle').style.top === position,
      'active numeric edit overwritten');
    label.dispatchEvent(new Event('blur'));
    applyStripState(state,[]);
    check(stereo.querySelector('.handle').style.top === '90%', 'fader did not update after editing');
    const handle = stereo.querySelector('.handle');
    handle.setPointerCapture = () => {};
    handle.dispatchEvent(new PointerEvent('pointerdown',{pointerId:1}));
    state['ch/01'].fader = 80;
    applyStripState(state,[]);
    check(handle.style.top === '90%', 'local pointer drag overwritten');
    handle.dispatchEvent(new PointerEvent('pointerup',{pointerId:1}));
    applyStripState(state,[]);
    check(handle.style.top === '20%', 'remote updates did not resume after dragging');
    check(writes === 0, 'remote readback caused a hardware write');
    mono.destroyFader(); stereo.destroyFader();
    return failures;
    """
    app = QApplication(['fader-layout-check'])
    view = QWebEngineView()
    view.resize(1000, 800)
    view.show()
    passed = False

    def labels_checked(failures):
        nonlocal passed
        passed = failures == []
        print('Fader label layout:', failures, flush=True)
        app.quit()

    def checked(failures):
        if failures:
            labels_checked(failures)
            return
        # Exercise wrapping and shared track geometry after observer/frame work.
        setup = r"""
        window.labelFailures = [];
        const row = document.createElement('div'); row.id = 'row';
        row.style.cssText = 'position:fixed;inset:0 auto auto 0;width:700px;height:650px;box-sizing:border-box';
        document.body.appendChild(row);
        for (const kind of ['', 'stereo', '']) {
          const strip = document.createElement('div'); strip.className = 'strip ' + kind;
          strip.innerHTML = '<textarea class="name" rows="1">Short</textarea>' +
            '<div class="faderwrap"><div class="track"></div></div><div class="inname">Input</div>';
          row.appendChild(strip);
        }
        const strips = Array.from(row.children);
        const label = strips[0].querySelector('.name');
        const hardware = strips[1].querySelector('.inname');
        const masterLabel = document.getElementById('masterName');
        const track = strip => strip.querySelector('.track').getBoundingClientRect();
        function check(ok, message) { if (!ok) window.labelFailures.push(message); }
        function aligned() {
          const first = track(strips[0]);
          for (const strip of strips.slice(1)) {
            const rect = track(strip);
            check(Math.abs(rect.top - first.top) < 1 && Math.abs(rect.height - first.height) < 1,
              'mono/stereo tracks must align when one label wraps');
          }
        }
        """
        scenarios = r"""
        setTimeout(() => {
          const initial = track(strips[0]).height;
          const masterInitial = masterLabel.getBoundingClientRect().height;
          masterLabel.value = 'Long output name';
          masterLabel.dispatchEvent(new Event('input', {bubbles:true}));
          check(label.readOnly, 'wrapped names must remain protected from accidental edits');
          label.dispatchEvent(new KeyboardEvent('keydown', {key:'F2', bubbles:true}));
          check(!label.readOnly, 'F2 must allow editing wrapped names');
          label.blur();
          check(label.readOnly, 'blur must protect wrapped names again');
          label.value = 'LongUnbrokenName';
          label.dispatchEvent(new Event('input', {bubbles:true}));
          hardware.textContent = 'Hardware input with a long descriptive name';
          setTimeout(() => {
            aligned();
            check(masterLabel.getBoundingClientRect().height > masterInitial,
              'master label must expand for wrapped text');
            check(masterLabel.clientHeight >= masterLabel.scrollHeight, 'master label must show all text');
            const expanded = track(strips[0]).height;
            check(expanded < initial, 'wrapping labels must shrink every track');
            check(label.clientHeight >= label.scrollHeight, 'name must show all wrapped text');
            check(hardware.clientHeight >= hardware.scrollHeight, 'hardware input must show all text');
            row.querySelectorAll('.strip').forEach(strip => { strip.style.width = '88px'; });
            window.dispatchEvent(new Event('resize'));
            setTimeout(() => {
              aligned();
              check(track(strips[0]).height <= expanded, 'narrowing strips must reserve wrapped height');
              label.value = 'Short'; hardware.textContent = 'Input';
              label.dispatchEvent(new Event('input', {bubbles:true}));
              setTimeout(() => {
                aligned();
                check(track(strips[0]).height > expanded, 'short labels must restore track height');
                label.value = 'LongUnbrokenName';
                label.dispatchEvent(new Event('input', {bubbles:true}));
                setTimeout(() => {
                  const before = track(strips[1]).height;
                  strips[0].classList.add('minimized');
                  setTimeout(() => {
                    check(track(strips[1]).height > before, 'minimized labels must release shared space');
                    window.labelChecksDone = true;
                  }, 80);
                }, 80);
              }, 80);
            }, 80);
          }, 80);
        }, 80);
        """
        view.page().runJavaScript(setup + (assets / 'fader-labels.js').read_text() +
                                  (assets / 'editable-input.js').read_text() + scenarios)
        QTimer.singleShot(1200, lambda: view.page().runJavaScript(
            'window.labelChecksDone ? window.labelFailures : ["label checks did not complete"]', labels_checked))

    def loaded(ok):
        if not ok:
            app.quit()
            return
        view.page().runJavaScript('(function () {' + load_master + strip_helpers + strip_state + script + '})()', checked)

    view.loadFinished.connect(loaded)
    view.setHtml('<style>' + css + '</style>'
                 '<div id="masterbox"><div id="master" class="strip master">'
                 '<textarea id="masterName" class="mname" rows="1">Main</textarea>'
                 '<div class="faderwrap"><div class="track"></div>'
                 '<button class="peak-meter" hidden></button></div>'
                 '<input id="masterVal"><button id="masterMute"></button></div></div>')
    QTimer.singleShot(15000, app.quit)
    app.exec()
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(browser_check(Path(sys.argv[1])))
