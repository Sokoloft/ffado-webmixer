/* DICE group selection, hardware toggle readback, failures and stale devices. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
class Element {
  constructor() {
    this.children = []; this.events = {}; this.dataset = {}; this.attributes = {};
    this.classes = new Set(); this.disabled = false;
    this.classList = {toggle: (name, on) => on ? this.classes.add(name) : this.classes.delete(name)};
  }
  appendChild(child) { this.children.push(child); return child; }
  addEventListener(type, fn) { this.events[type] = fn; }
  setAttribute(key, value) { this.attributes[key] = value; }
  click() { if (!this.disabled) this.events.click?.(); }
}
const box = new Element();
function descendants(element) { return [element, ...element.children.flatMap(descendants)]; }
let state = {hw_monitor: false}, reject = false, deferWrite;
let output, loads = 0;
const writes = [], messages = [];
const context = vm.createContext({
  document: {createElement: () => new Element(),
    getElementById: id => descendants(box).find(el => el.id === id)},
  ACTIVE_DEVICE: 'device-a', OUTPUTS: [{id: 'dice/dim', mix: null, controllable: true}],
  selectOutput: selected => { output = selected; },
  loadMaster: () => { loads++; }, toast: message => messages.push(message),
  ffadoApi: {
    latest: async () => ({...state}), cancel() {},
    serial: (key, task) => Promise.resolve().then(task),
  },
  postJson: async (url, body, device) => {
    writes.push({url, body, device});
    if (deferWrite) await new Promise(resolve => { deferWrite = resolve; });
    if (reject) throw Error('readback mismatch');
    state = {hw_monitor: body.value}; return {...state};
  },
});
context.window = context;
const base = path.join(__dirname, '../src/ffado_webmixer/assets/static');
vm.runInContext(fs.readFileSync(path.join(base, 'dice-monitoring.js'), 'utf8'), context);
const flush = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
(async () => {
  context.configureDiceMonitoring({dice_monitoring: {dim: true, mute: true, hw_monitor: true}});
  context.buildDiceMonitoring(box);
  const group = box.children[0], grid = group.children[1];
  assert.equal(group.children[0].textContent, 'Dice');
  const [dim, hardware] = grid.children;
  assert.equal(dim.textContent, 'Dim');
  assert(hardware.innerHTML.includes('H/W<br>Monitor'), 'Monitor appears on a second line');
  assert(hardware.disabled, 'toggle waits for initial hardware readback');
  await flush();
  assert(!hardware.disabled);
  dim.click();
  assert.equal(output.id, 'dice/dim');
  assert.equal(writes.length, 0, 'selecting Dim must not change its level');
  hardware.click(); hardware.click(); await flush();
  assert.equal(writes.length, 1, 'repeat clicks cannot race hardware writes');
  assert.equal(writes[0].url, '/api/dice-monitoring');
  assert.equal(writes[0].body.control, 'hw_monitor');
  assert.equal(writes[0].body.value, true);
  assert.equal(writes[0].device, 'device-a');
  assert.equal(hardware.attributes['aria-pressed'], 'true');
  assert(hardware.classes.has('active'));
  assert.equal(loads, 1, 'refresh master so line gains are replaced with H/W');
  reject = true;
  hardware.click(); await flush();
  assert.equal(hardware.attributes['aria-pressed'], 'true', 'failed toggle restores hardware readback');
  assert(messages.some(message => message.includes('readback mismatch')));
  reject = false;
  state = {hw_monitor: false, hw_monitor_partial: true};
  await context.refreshDiceMonitoring();
  assert.equal(hardware.attributes['aria-pressed'], 'mixed');
  hardware.click(); await flush();
  assert.equal(hardware.attributes['aria-pressed'], 'true', 'mixed outputs can be enabled together');
  deferWrite = true;
  hardware.click(); await flush();
  context.ACTIVE_DEVICE = 'device-b';
  const loadsBeforeSwitch = loads;
  deferWrite(); await flush();
  assert.equal(loads, loadsBeforeSwitch, 'old device completion must not refresh a different device');
  box.children = [];
  context.OUTPUTS = [];
  context.configureDiceMonitoring({}); context.buildDiceMonitoring(box);
  assert.equal(box.children.length, 0, 'other devices have no Dice group');
  console.log('DICE monitor UI: grouping, Dim selection, hardware toggle, readback and device scoping passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
