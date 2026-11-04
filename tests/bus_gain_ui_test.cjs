/* Production bus selection and output writes retain the selected bus/device. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const shortFfadoLabel = require('../src/ffado_webmixer/assets/static/labels.js');
const source = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');
const nodes = new Map(), writes = [], pending = [];
let change, getScale, caption;
function node(id) {
  if (!nodes.has(id)) {
    const classes = new Set();
    nodes.set(id, {dataset: {}, events: {}, value: '', hidden: false,
      classList: {toggle: (key, on) => on ? classes.add(key) : classes.delete(key), contains: key => classes.has(key)},
      addEventListener(type, fn) { this.events[type] = fn; },
      querySelector: child => node(id + child),
    });
  }
  return nodes.get(id);
}
const scale = {mode: 'dice_db', min_db: -60, max_db: 6};
const context = vm.createContext({
  DICE_BUS_GAIN: true, currentMix: 0, currentOut: 'line/1', ACTIVE_DEVICE: 'device-a',
  shortFfadoLabel,
  OUTPUTS: [
    {id: 'bus/0', mix: 0, name: 'Mix 1', baseName: 'Mix 1', controllable: true, gainScale: scale},
    {id: 'bus/1', mix: 1, name: 'Mix 2', baseName: 'Mix 2', controllable: true, gainScale: scale},
    {id: 'line/1', mix: null, name: 'Line Out 1', baseName: 'Line Out 1', controllable: true},
    {id: 'dice/dim', mix: null, name: 'Dim', baseName: 'Dim', controllable: true},
  ],
  STEREO_BUSES: [], STEREO_BUS_NAMES: {}, OUTPUT_PAIRS: [], STEREO_OUTPUTS: [],
  controlWriteRevision: 0, pendingStereoLeft: null, GAIN_SCALE: scale,
  document: {getElementById: node},
  makeFader(track, handle, label, callback, canEdit, scaleCallback) {
    change = callback; getScale = scaleCallback;
    return {set: v => { label.value = v; }};
  },
  throttled(key, value, task) { pending.push(() => task(value)); },
  postJson(url, body, device) { writes.push({...body, device}); return Promise.resolve(); },
  markOutputs() {}, saveViewSelection() {}, loadMix() {}, loadMuteRecovery() {},
  showMasterName(name) { caption = name; }, masterHardwareName: node('hardwareName'),
  masterName: node('masterName'),
  toast(message) { throw Error(message); },
  ffadoApi: {cancel() {}, serial: (key, task) => task(), latest: async (key, url) => ({name: url.includes('bus%2F0') ? 'Mixer/Out:01' : 'Mixer/Out:02', level: 100 * 60 / 66, mute: false})},
});
context.window = context;
vm.runInContext(source.slice(source.indexOf('function outputPartner('), source.indexOf('var outputLinkBusy')), context);
vm.runInContext(source.slice(source.indexOf('// ---- master (output) fader'), source.indexOf('// ---- rename the active output')), context);
vm.runInContext(source.slice(source.indexOf('function applyMasterState('), source.indexOf('// ---- Bus tabs')), context);
vm.runInContext(source.slice(source.indexOf('function selectOutput('), source.indexOf('function buildOutputs(')), context);
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
(async () => {
  context.selectOutput(context.OUTPUTS[0]); await flush();
  assert.equal(context.currentMix, 0); assert.equal(context.currentOut, 'bus/0');
  assert.equal(caption, 'Bus 1', 'unnamed buses use the compact name instead of the FFADO identifier');
  assert.equal(node('hardwareName').textContent, 'Bus 1');
  assert.equal(getScale().max_db, 6); assert.equal(getScale().min_db, -60);
  change(100 * 60 / 66);
  context.selectOutput(context.OUTPUTS[1]); await flush();
  assert.equal(context.currentMix, 1); assert.equal(context.currentOut, 'bus/1');
  assert.equal(caption, 'Bus 2');
  assert.equal(node('hardwareName').textContent, 'Bus 2');
  pending.shift()(); await flush();
  assert.equal(writes[0].out, 'bus/0', 'delayed gain retains its original bus');
  assert.equal(writes[0].device, 'device-a');
  node('masterMute').events.click(); await flush();
  assert.equal(writes[1].out, 'bus/1', 'mute targets the selected bus');
  assert.equal(writes[1].control, 'mute'); assert.equal(writes[1].value, true);
  context.STEREO_BUSES = [0];
  context.selectOutput(context.OUTPUTS[1]); await flush();
  assert.equal(context.currentOut, 'bus/0', 'linked bus gain canonicalizes to its Left leg');
  assert.equal(context.currentMix, 0);
  assert.equal(context.outputPartner('bus/0').id, 'bus/1');
  assert.equal(node('masterName').maxLength, 32, 'linked bus panel accepts the same name length as the bus tab');
  assert.equal(node('hardwareName').textContent, 'Bus 1+2', 'short bus labels do not force a second line');
  context.applyMasterState({name: 'Mixer/Out:01+02', level: 90, mute: false});
  assert.equal(caption, 'Bus 1+2');
  context.applyMasterState({name: 'Headphones', level: 90, mute: false});
  assert.equal(caption, 'Headphones', 'custom bus names remain intact');
  context.OUTPUTS.push({id: 'bus/2', mix: 2, name: 'Bus 3', baseName: 'Mixer/Out:03', controllable: true, gainScale: scale});
  context.selectOutput(context.OUTPUTS.at(-1)); await flush();
  assert.equal(node('hardwareName').textContent, 'Bus 3', 'mono bus labels stay on one line');
  assert.equal(node('masterName').maxLength, 16);
  context.selectOutput(context.OUTPUTS[3]); await flush();
  assert.equal(context.currentOut, 'dice/dim', 'Dim remains independently selectable');
  assert(writes.every(write => write.out.startsWith('bus/')), 'bus controls never write hardware outputs');
  context.OUTPUTS.push({id: 'line/2', mix: null, name: 'Line Out 2', baseName: 'Line Out 2', controllable: true});
  context.OUTPUT_PAIRS = [['line/1', 'line/2']];
  context.STEREO_OUTPUTS = ['line/1'];
  context.selectOutput(context.OUTPUTS[2]); await flush();
  assert.equal(node('hardwareName').textContent, 'Line Out\n1\u00a0+\u00a02',
    'stereo hardware labels use one shared prefix and keep numbers together for wrapping');
  context.DICE_BUS_GAIN = false;
  await context.loadMaster();
  assert.equal(node('hardwareName').textContent, 'Line Out\n1\u00a0+\u00a02',
    'master label formatting also applies outside DICE bus mode');
  console.log('Bus gain UI: selection, names, scale, mute, stereo and delayed write scoping passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
