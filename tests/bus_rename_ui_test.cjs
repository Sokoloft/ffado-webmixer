/* The master-panel name edits the selected bus or linked bus pair. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');
const inputs = new Map(), posts = [], errors = [], saved = new Map();
function input(id) {
  if (!inputs.has(id)) inputs.set(id, {value: '', defaultValue: '', events: {}, dataset: {},
    addEventListener(kind, fn) { this.events[kind] = fn; }, select() {}, blur() {}});
  return inputs.get(id);
}
let fail = false, release = null, defer = false, rebuilds = 0;
const queues = new Map();
const context = vm.createContext({
  currentOut: 'bus/0', currentMix: 0, ACTIVE_DEVICE: 'device-a', DICE_BUS_GAIN: true,
  OUTPUTS: [0, 1, 2].map(mix => ({id: `bus/${mix}`, mix, name: `Bus ${mix+1}`, customName: false})),
  STEREO_BUSES: [0], STEREO_BUS_NAMES: {'0': 'Old stereo'}, OUTPUT_PAIRS: [], STEREO_OUTPUTS: [],
  document: {getElementById: input, activeElement: null}, masterEl: {querySelector: () => ({})},
  buildOutputs() { rebuilds++; }, markOutputs() {}, renderBusTabs() {}, busTabsEnabled: () => false,
  busOutput: id => context.OUTPUTS.find(out => out.mix === Number(id)),
  loadMaster() {
    const out = context.OUTPUTS.find(out => out.id === context.canonicalOutput(context.currentOut));
    context.showMasterName(context.outputButtonName(out));
    return Promise.resolve();
  },
  toast: message => errors.push(message),
  ffadoApi: {serial(key, task) {
    const job = (queues.get(key) || Promise.resolve()).catch(() => {}).then(task);
    queues.set(key, job); return job;
  }},
  async postJson(url, body, device) {
    posts.push({url, body, device});
    if (defer) { defer = false; await new Promise(resolve => { release = resolve; }); }
    if (fail) throw Error('save failed');
    saved.set(url === '/api/bus-pair-name' ? `bus-pair:${body.left}` : body.strip, body.name || body.value);
    return {ok: true};
  },
});
context.window = context;
vm.runInContext(source.slice(source.indexOf('function outputPartner('), source.indexOf('var outputLinkBusy')), context);
vm.runInContext(source.slice(source.indexOf('// ---- rename the active output'), source.indexOf('function applyMasterState(')), context);
vm.runInContext(source.slice(source.indexOf('function changeBusName('), source.indexOf('function toggleBusLink(')), context);
const flush = async () => { for (let i=0; i<30; i++) await Promise.resolve(); };
const name = input('masterName');
function rename(value) { name.value = value; name.events.change(); }
(async () => {
  context.showMasterName('Old stereo');
  rename('Main mix'); await flush();
  assert.equal(posts.at(-1).url, '/api/bus-pair-name');
  assert.equal(posts.at(-1).body.left, 0); assert.equal(posts.at(-1).device, 'device-a');
  assert.equal(saved.get('bus-pair:0'), 'Main mix');
  assert.equal(context.STEREO_BUS_NAMES['0'], 'Main mix');
  assert.equal(context.outputButtonName(context.OUTPUTS[0]), 'Main mix');
  assert.equal(name.value, 'Main mix');
  assert.equal(context.OUTPUTS[0].name, 'Bus 1'); assert.equal(context.OUTPUTS[1].name, 'Bus 2');
  assert(rebuilds > 0, 'pair rename refreshes all bus buttons and tabs');
  fail = true;
  rename('Rejected'); await flush();
  assert.equal(name.value, 'Main mix'); assert.equal(context.STEREO_BUS_NAMES['0'], 'Main mix');
  assert(errors.some(message => message.includes('save failed')));
  fail = false;
  context.currentOut = 'bus/2'; context.loadMaster();
  rename('Headphones'); await flush();
  assert.equal(posts.at(-1).url, '/api/set');
  assert.equal(posts.at(-1).body.strip, 'out:bus/2');
  assert.equal(saved.get('out:bus/2'), 'Headphones');
  assert.equal(context.OUTPUTS[2].name, 'Headphones');
  assert.equal(name.value, 'Headphones');
  assert.equal(context.STEREO_BUS_NAMES['0'], 'Main mix', 'mono rename preserves pair names');
  context.currentOut = 'bus/0'; context.loadMaster();
  defer = true; rename('Pending pair'); await flush();
  context.currentOut = 'bus/2'; context.loadMaster();
  fail = true; release(); await flush();
  assert.equal(name.value, 'Headphones', 'an old bus rename failure must not overwrite the newly selected bus');
  fail = false;
  context.currentOut = 'bus/0'; context.loadMaster();
  defer = true; rename('Old device rename'); await flush();
  context.ACTIVE_DEVICE = 'device-b'; context.STEREO_BUS_NAMES = {'0':'Other device'};
  context.showMasterName('Other device'); release(); await flush();
  assert.equal(posts.at(-1).device, 'device-a');
  assert.equal(name.value, 'Other device'); assert.equal(context.STEREO_BUS_NAMES['0'], 'Other device');
  context.CLIENT_ID = 'this-client';
  context.row = {querySelector: () => null};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/live-sync.js'), 'utf8'), context);
  context.onSyncEvent({type:'bus-pair-name', left:0, name:'Remote mix', origin:'other-client'});
  assert.equal(name.value, 'Remote mix', 'pair renames from another browser update the selected bus panel');
  console.log('Bus panel rename: stereo pair, mono, persistence targets, failures and selection/device scoping passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
