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
const ctx = vm.createContext({
  GAIN_SCALE: {mode: 'dice_db', min_db: -60, max_db: 6},
  toast: msg => messages.push(msg), window: {}, Math, Number, String, Object,
  wheelDir: event => Math.sign(-event.deltaY),
});
vm.runInContext(functions, ctx);

function domNode() {
  const events = {};
  return {
    style: {}, value: '', readOnly: false, events,
    addEventListener: (type, callback) => { (events[type] ||= []).push(callback); },
    removeEventListener: (type, callback) => { events[type] = (events[type] || []).filter(fn => fn !== callback); },
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

assert(src.includes('sendThrottled(id, "fader", v, stripMix, stripDevice)'), 'strip writes retain bus and GUID');
assert(src.includes('function () { return masterReady; }'), 'master value edits require loaded output');
console.log('Fader input UI: native dB entry, MOTU endpoints/steps, output scales, validation and unity reset passed');
