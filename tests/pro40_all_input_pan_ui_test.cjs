/* Exercise actual strips and the local write/readback path with offline DOM nodes. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');

class Node {
  constructor() {
    this.dataset = {}; this.handlers = {}; this.children = {}; this.hidden = false;
    this.classList = {toggle() {}, add() {}, remove() {}};
  }
  querySelector(selector) { return this.children[selector] ||= new Node(); }
  addEventListener(type, callback) { (this.handlers[type] ||= []).push(callback); }
  emit(type, extra = {}) {
    for (const callback of this.handlers[type] || []) callback({preventDefault() {}, pointerId: 1, ...extra});
  }
  setPointerCapture() {}
}
const strips = [], faders = new Map(), writes = [], reads = [];
const state = {};
const refreshTimers = new Map();
let timerId = 0;
let holdRead = false;
const clone = data => JSON.parse(JSON.stringify(data));
const context = vm.createContext({
  Math, Date, Promise,
  setTimeout(callback, delay) {
    if (delay !== 120) return setTimeout(callback, delay);
    const id = ++timerId; refreshTimers.set(id, callback); return id;
  },
  clearTimeout(id) { if (!refreshTimers.delete(id)) clearTimeout(id); },
  currentMix: 0, ACTIVE_DEVICE: 'pro40', FEATURES: {}, GAIN_SCALE: {mode: 'dice_db'},
  STEREO_BUSES: [0], MIXES: Array.from({length: 16}, (_, id) => ({id})),
  FADER_ALLOWED: true, MUTE_ALLOWED: true,
  window: {ffadoApi: {
    latest(key, url, options) {
      assert.equal(options.device, 'pro40');
      const data = clone(state);
      if (!holdRead) return Promise.resolve(data);
      return new Promise(resolve => reads.push(() => resolve(data)));
    },
  }},
  row: {querySelectorAll() { return strips; }},
  document: {createElement() { return new Node(); }},
  shortFfadoLabel: value => value,
  setPinned() {}, setMinimized() {},
  makeFader(track, handle, label, change) { faders.set(track, change); return {set() {}}; },
  wheelDir: event => Math.sign(-event.deltaY),
  toast(message) { throw Error(message); },
  loadMuteRecovery() {}, loadMix() {}, buildOutputs() {}, markOutputs() {}, renderBusTabs() {},
  fetch(url, options) {
    const body = JSON.parse(options.body); writes.push(body);
    assert.equal(options.headers['X-FFADO-Device'], 'pro40');
    assert.equal(body.mix, 0);
    const entry = state[body.strip];
    if (body.control === 'fader') {
      entry.pan = body.value > 0 ? 0 : null;
      entry.pan_available = body.value > 0;
    } else {
      assert.equal(body.control, 'pan'); entry.pan = body.value;
    }
    return Promise.resolve({ok: true, json: async () => ({ok: true})});
  },
});
vm.runInContext(src.slice(src.indexOf('var CLIENT_ID'), src.indexOf('// Interrupted software mute/solo')), context);
vm.runInContext(src.slice(src.indexOf('function buildStrip('), src.indexOf('// ---- appearance ----')), context);
const flush = async () => {
  for (let i = 0; i < 30; i++) await Promise.resolve();
  for (const [id, callback] of refreshTimers) { refreshTimers.delete(id); callback(); }
  for (let i = 0; i < 30; i++) await Promise.resolve();
};

(async () => {
  for (let col = 0; col < 32; col++) {
    const id = 'ch/' + String(col).padStart(2, '0');
    state[id] = {name: id, input: id, fader: 0, pan: null, pan_available: false};
    const strip = context.buildStrip(id, clone(state[id]), true, false, null);
    strips.push(strip);
    assert.equal(strip.querySelector('.panrow').hidden, false, 'stereo bus shows pan on every input');
    const slider = strip.querySelector('.pan'), label = strip.querySelector('.panval');
    assert.equal(slider.disabled, true, 'silent input starts with undefined pan');
    assert.match(slider.title, /Raise this channel fader/);
    // The actual fader callback queues a POST and reads back this browser's
    // own derived pan state. No SSE echo or page reload is needed.
    faders.get(strip.querySelector('.track'))(70);
    await flush();
    assert.equal(slider.disabled, false, 'raising input ' + col + ' enables pan');
    assert.equal(label.textContent, '0');
    assert.equal(strips[col], strip, 'readback keeps the original fader DOM');
    slider.emit('pointerdown'); slider.value = '-75'; slider.emit('input');
    assert.equal(label.textContent, 'L75');
    slider.emit('pointerup'); slider.emit('change');
    await flush();
    assert.equal(writes.filter(w => w.strip === id && w.control === 'pan').length, 1);
    assert.equal(state[id].pan, -.75);
  }
  const strip = strips[7], slider = strip.querySelector('.pan'), label = strip.querySelector('.panval');
  state['ch/07'].pan = 1;
  holdRead = true;
  const draggingRead = context.refreshStripPans(0, 'pro40');
  slider.emit('pointerdown'); slider.value = '-30'; slider.emit('input');
  reads.shift()(); await draggingRead;
  assert.equal(label.textContent, 'L30', 'readback cannot overwrite an active pan gesture');
  slider.emit('pointerup');
  await new Promise(resolve => setTimeout(resolve, 65));
  await flush();
  while (reads.length) reads.shift()();
  await flush();
  const oldBusRead = context.refreshStripPans(0, 'pro40');
  context.currentMix = 2;
  reads.shift()(); await oldBusRead;
  assert.equal(label.textContent, 'L30', 'late old-bus read cannot repaint a new view');
  context.currentMix = 0;
  const oldDeviceRead = context.refreshStripPans(0, 'pro40');
  context.ACTIVE_DEVICE = 'other';
  reads.shift()(); await oldDeviceRead;
  assert.equal(label.textContent, 'L30', 'late old-device read cannot repaint a new view');
  context.ACTIVE_DEVICE = 'pro40'; holdRead = false;

  // Mono buses hide the entire pan row, including for paired input strips.
  context.STEREO_BUSES = [];
  for (const bus of [0, 1, 2, 3]) {
    context.currentMix = bus;
    for (const paired of [false, true]) {
      const data = clone(state['ch/07']);
      if (paired) data.partner = 'ch/08';
      const mono = context.buildStrip('ch/07', data, true, false, paired ? state['ch/08'] : null);
      assert.equal(mono.querySelector('.panrow').hidden, true);
      assert.equal(mono.innerHTML.includes('pan-setup'), false, 'no stereo setup button in the pan row');
    }
  }
  assert.equal(writes.length, 65, 'rendering mono buses never writes hardware');
  console.log('PRO 40: all 32 inputs enable pan on stereo buses; mono buses hide pan without setup buttons');
})().catch(error => { console.error(error); process.exitCode = 1; });
