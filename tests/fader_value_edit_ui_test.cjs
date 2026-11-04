/* Native dB entry, canonical zero labels, click editing, and unity on double-click.
 * DOM events run against the actual makeFader implementation without a browser. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');
const functions = src.slice(src.indexOf('function faderHasDbScale()'), src.indexOf('// ---- a gain box:'));
const messages = [];
const changes = [];
const observers = [];
class ResizeObserver {
  constructor(callback) { this.callback = callback; observers.push(this); }
  observe(target) { this.target = target; }
  disconnect() { this.target = null; }
  resize(height) { this.target.clientHeight = height; this.callback(); }
}
const ctx = vm.createContext({
  GAIN_SCALE: {mode: 'dice_db', min_db: -60, max_db: 6},
  toast: msg => messages.push(msg), window: {ResizeObserver}, Math, Number, String, Object,
  document: {createElement: () => domNode()},
  wheelDir: event => Math.sign(-event.deltaY),
});
vm.runInContext(functions, ctx);

function domNode() {
  const events = {};
  return {
    style: {}, clientHeight: 300, value: '', textContent: '', title: '', className: '', readOnly: false, events, children: [],
    addEventListener: (type, callback) => { (events[type] ||= []).push(callback); },
    removeEventListener: (type, callback) => { events[type] = (events[type] || []).filter(fn => fn !== callback); },
    appendChild(child) { this.children.push(child); return child; },
    replaceChildren(...children) { this.children = children; },
    setAttribute() {},
    fire(type, fields = {}) {
      const ev = Object.assign({key: '', preventDefault() {}}, fields);
      for (const fn of events[type] || []) fn(ev);
    },
    select() { this.selected = true; },
    blur() { this.fire('blur'); },
    setPointerCapture() {},
  };
}
function harness(editable = () => true, getScale) {
  const track = domNode(), handle = domNode(), label = domNode(), wrap = domNode();
  track.parentNode = wrap;
  const fader = ctx.makeFader(track, handle, label, v => changes.push(v), editable, getScale);
  return {track, handle, label, wrap, fader};
}
function approx(a, b, message) { assert.ok(Math.abs(a-b) < 0.0002, `${message}: ${a} vs ${b}`); }

assert.equal(ctx.formatFaderDb(-0), '0.0 dB');
assert.equal(ctx.formatFaderDb(-0.049), '0.0 dB');
assert.equal(ctx.formatFaderDb(0.049), '0.0 dB');
assert.equal(ctx.formatFaderDb(0), '0.0 dB');
assert.equal(ctx.formatFaderDb(0.0501), '+0.1 dB');
assert.equal(ctx.formatFaderDb(-0.15), '-0.1 dB');
assert.equal(ctx.formatFaderDb(null), '−∞ dB');

const ui = harness();
assert.equal(ui.track.children[0].children.length, 23, '6 dB marks and unlabeled 3 dB half marks are rendered');
assert.equal(ui.track.children[0].children[0].textContent, '+6', 'top mark is labeled in integer dB');
assert.equal(ui.track.children[0].children[1].textContent, '', 'half marks are unlabeled');
assert.equal(ui.track.children[0].children[1].style.top, `${100 - 100*63/66}%`, 'half mark is placed at +3 dB');
assert.equal(ui.track.children[0].children[2].textContent, '0', 'unity label has no decimals');
assert.equal(ui.track.children[0].children[2].className, 'fader-mark major unity', '0 dB mark is bold');
assert.equal(ui.track.children[0].children[2].style.top, `${100 - 100*60/66}%`, 'unity mark is placed at 0 dB');
assert.equal(ui.track.children[0].children.at(-1).textContent, '-60', 'bottom mark is labeled in integer dB');
const hasDecimal = text => /\.\d/.test(text);
assert.equal(hasDecimal('+6.0'), true, 'the decimal detector rejects positive decimal labels');
assert.equal(hasDecimal('-12.5'), true, 'the decimal detector rejects negative decimal labels');
assert.equal(hasDecimal('-12'), false, 'integer labels remain valid');
assert.equal(ui.track.children[0].children.some(mark => hasDecimal(mark.textContent)), false, 'dB tick labels have no decimals');

// Actual label positions must remain readable after shrinking and growing,
// including hidden/minimized tracks that become visible again.
function checkResponsiveLabels(ui, observer, tickCount) {
  for (const height of [94, 54, 0, 54, 300]) {
    observer.resize(height);
    const marks = ui.track.children[0].children;
    assert.equal(marks.length, tickCount, 'resizing preserves every tick');
    const labels = marks.filter(mark => mark.textContent);
    assert.equal(labels.some(mark => mark.textContent === '0' && mark.className.includes('unity')), true,
      'unity is always labeled');
    for (let i = 1; i < labels.length; i++) {
      const spacing = Math.abs(parseFloat(labels[i].style.top) - parseFloat(labels[i - 1].style.top)) * height / 100;
      assert.ok(spacing >= 12, `labels need 12px separation, got ${spacing}px at height ${height}`);
    }
    assert.equal(labels.some(mark => hasDecimal(mark.textContent)), false);
    if (height === 300) assert.equal(labels.length, marks.filter(mark => mark.className.includes('major')).length,
      'growing restores all major labels');
  }
}
checkResponsiveLabels(ui, observers.at(-1), 23);
const rme = harness(() => true, () => ({mode: 'rme_db', min_db: -60, max_db: 6}));
checkResponsiveLabels(rme, observers.at(-1), 23);
rme.fader.destroy();
assert.equal(observers.at(-1).target, null, 'disposing a strip releases its observed track');
ui.fader.set(100*60/66);
assert.equal(ui.label.value, '0.0 dB');
ui.label.fire('focus');
assert.equal(ui.label.selected, true, 'focus selects displayed number for easy replacement');
ui.label.value = '+3.1 dB';
ui.label.fire('keydown', {key: 'Enter'});
approx(changes.at(-1), 100*63.1/66, '+3.1 dB is converted to the existing 0..100 transport value');
assert.equal(ui.label.value, '+3.1 dB');
assert.equal(ui.handle.style.top, `${100-changes.at(-1)}%`);
ui.label.fire('focus');
ui.label.value = '-0.0';
ui.label.fire('keydown', {key: 'Enter'});
assert.equal(ui.label.value, '0.0 dB', 'signed zero always normalized');
ui.label.fire('focus');
ui.label.value = '100 dB';
ui.label.fire('keydown', {key: 'Enter'});
assert.equal(messages.length, 1, 'invalid volume is reported');
assert.equal(ui.label.value, '0.0 dB', 'invalid entries are reverted');
ui.label.fire('focus');
ui.label.value = '-15.4';
ui.label.fire('keydown', {key: 'Escape'});
assert.equal(ui.label.value, '0.0 dB', 'Escape cancels uncommitted entry');
ui.label.fire('focus');
ui.label.value = '+2.0';
ui.label.fire('blur');
assert.equal(ui.label.value, '0.0 dB', 'leaving without Enter cancels');
ui.fader.set(30);
ui.wrap.fire('dblclick');
approx(changes.at(-1), 100*60/66, 'double-click resets to 0 dB, not mute');
assert.equal(ui.label.value, '0.0 dB');
ui.label.fire('focus');
ui.label.value = '−∞ dB';
ui.label.fire('keydown', {key: 'Enter'});
assert.equal(changes.at(-1), 0, 'silence must be explicit, not confused with unity');
assert.equal(ui.label.value, '−∞ dB');

ctx.GAIN_SCALE = {mode: 'rme_db', min_db: -60, max_db: 6};
ui.label.fire('focus');
ui.label.value = '3.1';
ui.label.fire('keydown', {key: 'Enter'});
approx(changes.at(-1), 100*63.1/66, 'RME native dB input');

let allowed = false;
const locked = harness(() => allowed);
locked.fader.set(20);
locked.wrap.fire('dblclick');
assert.equal(locked.label.value, '-46.8 dB', 'readback is still displayed but no edits are sent');
locked.label.fire('focus');
assert.equal(locked.label.readOnly, true);
allowed = true;
locked.label.fire('focus');
assert.equal(locked.label.readOnly, false);
locked.label.blur();
locked.wrap.fire('dblclick');
assert.equal(locked.label.value, '0.0 dB');

// Legacy percentage devices do not have a calibrated dB unity; do not pretend otherwise.
ctx.GAIN_SCALE = null;
const legacy = harness();
assert.equal(legacy.track.children[0].children.length, 21, 'legacy scale has no calibrated unity marker');
assert.equal(legacy.track.children[0].children[0].textContent, '0', 'legacy marks are labeled with percentages');
legacy.fader.set(35);
assert.equal(legacy.label.value, '35');
legacy.wrap.fire('dblclick');
assert.equal(legacy.label.value, '35');
legacy.label.fire('focus');
legacy.label.value = '42';
legacy.label.fire('keydown', {key: 'Enter'});
assert.equal(changes.at(-1), 42);
legacy.label.fire('focus');
legacy.label.value = '+3.1 dB';
legacy.label.fire('keydown', {key: 'Enter'});
assert.equal(legacy.label.value, '42', 'unknown dB scales reject dB typed input');

// MOTU display endpoints keep the quietest finite position separate from OFF.
// This is display interpolation; the API continues to carry native positions.
const motuScale = {mode: 'motu_db', min_db: -84, max_db: 0, native_min: 0,
  native_max: 128, min_finite_native: 1, step_native: 1, calibration: 'endpoint_interpolation'};
ctx.FADER_SCALE = motuScale;
const motu = harness();
assert.equal(motu.track.children[0].children.length, 29, 'MOTU marks are spaced by 6 dB with 3 dB half marks');
assert.equal(motu.track.children[0].children[0].className, 'fader-mark major unity');
assert.equal(motu.track.children[0].children[0].textContent, '0');
assert.equal(motu.track.children[0].children[1].textContent, '', 'MOTU half marks remain unlabeled');
assert.equal(motu.track.children[0].children.at(-1).textContent, '-84');
checkResponsiveLabels(motu, observers.at(-1), 29);
for (let raw = 0; raw <= 128; raw++) {
  const transport = 100 * raw / 128;
  motu.fader.set(transport);
  const parsed = ctx.parseFaderEntry(motu.label.value);
  assert.equal(parsed.ok, true);
  approx(parsed.value, transport, `MOTU native position ${raw} survives display and edit`);
}
motu.fader.set(100);
assert.equal(motu.label.value, '0.0 dB');
motu.label.fire('focus');
motu.label.value = '-84 dB';
motu.label.fire('keydown', {key: 'Enter'});
assert.equal(changes.at(-1), 100 / 128, '-84 is finite, not the silence sentinel');
assert.equal(motu.label.value, '-84.0 dB');
motu.wrap.fire('wheel', {deltaY: 100});
assert.equal(changes.at(-1), 0, 'the next native step below -84 is silence');
assert.equal(motu.label.value, '−∞ dB');
motu.wrap.fire('wheel', {deltaY: -100, shiftKey: true});
assert.equal(changes.at(-1), 100 / 128, 'the first step above silence is -84');
motu.wrap.fire('dblclick');
assert.equal(changes.at(-1), 100, 'MOTU unity is native maximum');
const motuWrites = changes.length;
for (const invalid of ['-85 dB', '+0.1 dB', '50%']) {
  motu.label.fire('focus');
  motu.label.value = invalid;
  motu.label.fire('keydown', {key: 'Enter'});
  assert.equal(changes.length, motuWrites, 'out-of-range MOTU edits do not write');
}

// A master fader resolves its own output scale, independently of the matrix.
ctx.FADER_SCALE = ctx.GAIN_SCALE = {mode: 'dice_db', min_db: -60, max_db: 6};
const motuMaster = harness(() => true, () => motuScale);
motuMaster.fader.set(100 / 128);
assert.equal(motuMaster.label.value, '-84.0 dB');
motuMaster.wrap.fire('dblclick');
assert.equal(changes.at(-1), 100, 'master unity follows its output descriptor');

// DICE outputs retain the original -60..+6 dB display and fractional unity.
const lineScale = {mode: 'dice_db', min_db: -60, max_db: 6};
const lineMaster = harness(() => true, () => lineScale);
lineMaster.label.fire('focus');
lineMaster.label.value = '0 dB';
lineMaster.label.fire('keydown', {key: 'Enter'});
approx(changes.at(-1), 100 * 60 / 66, 'Master 0 dB keeps its fractional percentage');
lineMaster.fader.set(changes.at(-1));
assert.equal(lineMaster.label.value, '0.0 dB', 'unity remains exact after output readback');
for (let db = -59; db <= 6; db++) {
  const transport = ctx.faderDbToUi(db, lineScale);
  lineMaster.fader.set(transport);
  assert.equal(lineMaster.label.value, ctx.formatFaderDb(db), 'the full original output range survives a refresh');
}
lineMaster.wrap.fire('dblclick');
approx(changes.at(-1), 100 * 60 / 66, 'line double-click restores exact displayed unity');

assert(src.includes('sendThrottled(id, "fader", v, stripMix, stripDevice)'), 'strip writes retain bus and GUID');
const dimScale = {mode: 'dice_dim', min_db: -87, max_db: 0,
  native_max: 88, min_finite_native: 1, step_native: 1};
const dim = harness(() => true, () => dimScale);
const dimUnity = dim.track.children[0].children.find(mark => mark.className.includes('unity'));
assert.equal(dimUnity.textContent, '0');
assert.equal(dimUnity.style.top, '0%', 'Dim unity tick is at the loud top of the track');
dim.fader.set(0);
assert.equal(dim.label.value, 'Off', 'Dim has a separate Off position at the bottom');
dim.wrap.fire('wheel', {deltaY: -100});
assert.equal(dim.label.value, '-87.0 dB', 'first step above Off activates the quietest Dim level');
dim.wrap.fire('wheel', {deltaY: -100});
assert.equal(dim.label.value, '-86.0 dB', 'raising Dim gets louder');
dim.label.fire('focus');
dim.label.value = '-12 dB';
dim.label.fire('keydown', {key: 'Enter'});
approx(changes.at(-1), 7600 / 88, 'Dim edits map negative dB into the finite range');
assert.equal(dim.label.value, '-12.0 dB');
dim.fader.set(100);
assert.equal(dim.label.value, '0.0 dB', 'top of Dim is loudest and distinct from Off');
dim.wrap.fire('wheel', {deltaY: 100});
assert.equal(dim.label.value, '-1.0 dB', 'lowering Dim gets quieter');
dim.fader.set(100 / 88);
dim.wrap.fire('wheel', {deltaY: 100});
assert.equal(dim.label.value, 'Off', 'lowering below the quietest active level disables Dim');
const dimWrites = changes.length;
for (const invalid of ['-88 dB', '+1 dB', '−∞ dB']) {
  dim.label.fire('focus'); dim.label.value = invalid;
  dim.label.fire('keydown', {key: 'Enter'});
}
assert.equal(changes.length, dimWrites, 'invalid attenuation never changes the hardware');
dim.wrap.fire('dblclick');
assert.equal(changes.at(-1), 0, 'double-click clears Dim attenuation');
dim.label.fire('focus'); dim.label.value = '0 dB';
dim.label.fire('keydown', {key: 'Enter'});
assert.equal(changes.at(-1), 100, 'typing 0 dB selects the active loudest position');
dim.label.fire('focus'); dim.label.value = 'Off';
dim.label.fire('keydown', {key: 'Enter'});
assert.equal(changes.at(-1), 0, 'typing Off explicitly disables Dim');
assert(src.includes('function () { return masterReady && !masterHardwareControlled; }'),
  'master value edits require a loaded output outside H/W mode');
console.log('Fader input UI: native dB entry, MOTU endpoints/steps, output scales, validation and unity reset passed');
