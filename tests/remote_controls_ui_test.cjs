/* Remote events read authoritative state without replacing strips/meters. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const base = path.join(__dirname, '../src/ffado_webmixer/assets/static');
const index = fs.readFileSync(path.join(base, 'index.js'), 'utf8');
const sync = fs.readFileSync(path.join(base, 'live-sync.js'), 'utf8');
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

function fixture() {
  const reads = [], applied = [], outputs = [], errors = [];
  let rebuilds = 0;
  const strips = [
    {dataset:{id:'ch/00'}, meter:{}},
    {dataset:{id:'ch/01', partner:'ch/02'}, meter:{}}
  ];
  strips.forEach(el => { el._apply = (...args) => applied.push([el, ...args]); });
  const context = vm.createContext({
    Promise, Object, Array, encodeURIComponent,
    ACTIVE_DEVICE:'unit-a', currentMix:0, currentOut:'main', CLIENT_ID:'local',
    STEREO_BUSES:[0], loadToken:1, masterToken:1, masterReady:true,
    controlWriteRevision:0, queuedControlWrites:{}, pendingOutputWrites:{}, pendingVals:{},
    lastStripMix:0, lastStripState:null, window:{},
    row:{querySelectorAll() { return strips; }},
    canonicalOutput:out => out,
    readJson(url, device) {
      return new Promise((resolve, reject) => reads.push({url,device,resolve,reject}));
    },
    loadMix() { rebuilds++; return Promise.resolve(); },
    applyMasterState:state => outputs.push(state),
    toast:message => errors.push(message),
  });
  vm.runInContext(index.slice(index.indexOf('function applyStripState('), index.indexOf('function loadMix(')), context);
  vm.runInContext(sync, context);
  return {context,reads,applied,outputs,errors,strips,rebuilds:() => rebuilds};
}
const state = level => ({
  'ch/00':{fader:level,pan:.25,mute:false,solo:false},
  'ch/01':{fader:level + 10,pan:-.5,partner:'ch/02',pair_mismatch:true,pair_faders:[level,level+10]},
  'ch/02':{partner_of:'ch/01'}
});
const event = (c, changes = {}) => c.onSyncEvent({type:'strip',control:'fader',strip:'ch/00',
  mix:0,device:'unit-a',origin:'remote',value:99,...changes});

(async () => {
  const f = fixture(), c = f.context;
  const meter = f.strips[0].meter;
  event(c);
  assert.equal(f.reads.length, 1);
  assert.equal(f.reads[0].url, '/api/state?mix=0');
  assert.equal(f.reads[0].device, 'unit-a');
  for (let i = 0; i < 20; i++) event(c);
  assert.equal(f.reads.length, 1, 'burst shares one hardware read');
  f.reads[0].resolve(state(30));
  await settle();
  assert.equal(f.reads.length, 2, 'burst requests exactly one follow-up');
  assert.equal(f.applied[0][2].fader, 30, 'use hardware state, not optimistic event value 99');
  assert.equal(f.applied[1][2].pan, -.5, 'stereo derived pan is updated too');
  f.reads[1].resolve(state(45));
  await c.controlRefreshes.strips.promise;
  assert.equal(f.applied.at(-2)[2].fader, 45);
  assert.equal(f.strips[0].meter, meter, 'meter identity survives updates');
  assert.equal(f.rebuilds(), 0);
  assert.equal(c.lastStripState['ch/00'].fader, 45);
  event(c, {origin:'local'});
  event(c, {mix:3});
  event(c, {device:'unit-b'});
  assert.equal(f.reads.length, 2, 'own/other-bus/other-device events do not read');

  for (const control of ['pan', 'mute', 'solo']) {
    event(c, {control});
    f.reads.at(-1).resolve(state(50));
    await c.controlRefreshes.strips.promise;
  }
  event(c, {type:'matrix',origin:'local',output:1});
  f.reads.at(-1).resolve(state(55));
  await c.controlRefreshes.strips.promise;
  assert.equal(f.rebuilds(), 0, 'derived matrix updates also preserve strips');

  event(c);
  c.currentMix = 2;
  const before = f.applied.length;
  f.reads.at(-1).resolve(state(60));
  await c.controlRefreshes.strips.promise;
  assert.equal(f.applied.length, before, 'old-bus snapshot is discarded');
  c.currentMix = 0;
  event(c);
  c.loadToken++;
  f.reads.at(-1).resolve(state(60));
  await c.controlRefreshes.strips.promise;
  assert.equal(f.applied.length, before, 'structural reload invalidates older reads');

  event(c);
  c.controlWriteRevision++;
  f.reads.at(-1).resolve(state(60));
  await settle();
  assert.equal(f.applied.length, before, 'local edit invalidates earlier snapshot');
  f.reads.at(-1).resolve(state(65));
  await c.controlRefreshes.strips.promise;
  c.queuedControlWrites['unit-a|0|ch/00|fader'] = {};
  event(c);
  delete c.queuedControlWrites['unit-a|0|ch/00|fader'];
  f.reads.at(-1).resolve(state(65));
  await c.controlRefreshes.strips.promise;
  assert(f.applied.at(-2)[4].includes('unit-a|0|ch/00|fader'), 'protect writes active when the read began');

  event(c);
  const changed = state(70);
  delete changed['ch/01'].partner;
  f.reads.at(-1).resolve(changed);
  await c.controlRefreshes.strips.promise;
  assert.equal(f.rebuilds(), 1, 'topology change requires a full rebuild');

  const master = {type:'output',out:'main'};
  event(c, master);
  for (let i = 0; i < 10; i++) event(c, master);
  f.reads.at(-1).resolve({level:22});
  await settle();
  f.reads.at(-1).resolve({level:44});
  await c.controlRefreshes.master.promise;
  assert.deepEqual(f.outputs, [{level:22},{level:44}]);
  c.pendingOutputWrites['unit-a|main'] = 1;
  event(c, master);
  delete c.pendingOutputWrites['unit-a|main'];
  f.reads.at(-1).resolve({level:2});
  await c.controlRefreshes.master.promise;
  assert.equal(f.outputs.length, 2, 'local output writes protect the displayed value');
  event(c, master);
  c.currentOut = 'phones';
  f.reads.at(-1).resolve({level:2});
  await c.controlRefreshes.master.promise;
  assert.equal(f.outputs.length, 2, 'old output response is discarded');

  event(c);
  f.reads.at(-1).reject(Error('hardware unavailable'));
  await c.controlRefreshes.strips.promise;
  assert(f.errors[0].includes('hardware unavailable'));
  assert.equal(f.rebuilds(), 1, 'failed refresh preserves current controls');
  event(c);
  f.reads.at(-1).resolve(state(75));
  await c.controlRefreshes.strips.promise;
  assert.equal(f.applied.at(-2)[2].fader, 75, 'next event recovers after a read error');
  console.log('Remote controls: in-place readback, coalescing, local edits, topology, stale views and errors passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
