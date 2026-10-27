/* Master volume/mute writes stay ordered and bound to the original output/device. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const base = path.join(__dirname, '../src/ffado_webmixer/assets/static');
const source = fs.readFileSync(path.join(base, 'index.js'), 'utf8');
const nodes = new Map(), requests = [];
function node(id) {
  if (!nodes.has(id)) nodes.set(id, {disabled:false, handlers:{},
    classList:{contains:()=>false},
    addEventListener(type, fn) { this.handlers[type] = fn; }});
  return nodes.get(id);
}
let faderChange, reloads = 0;
const context = vm.createContext({window:{}, Promise, Math, Date, setTimeout, clearTimeout,
  ACTIVE_DEVICE:'device-a', currentOut:'line/1', OUTPUTS:[], GAIN_SCALE:null,
  document:{getElementById:node},
  makeFader(track, handle, label, change) { faderChange=change; return {}; },
  toast(message) { throw Error(message); },
  loadMaster() { reloads++; return Promise.resolve(); }, loadMuteRecovery() {},
  fetch(url, options) {
    return new Promise(resolve=>requests.push({url, body:JSON.parse(options.body),
      device:options.headers['X-FFADO-Device'],
      done:()=>resolve({ok:true,status:200,json:async()=>({ok:true})})}));
  }
});
vm.runInContext(fs.readFileSync(path.join(base,'frontend-api.js'),'utf8'),context);
vm.runInContext(source.slice(source.indexOf('var CLIENT_ID'),source.indexOf('function savePreference(')),context);
vm.runInContext(source.slice(source.indexOf('var pendingVals'),source.indexOf('// Capture bus')),context);
vm.runInContext(source.slice(source.indexOf('// ---- master (output) fader'),source.indexOf('// ---- rename the active output')),context);
context.masterReady=true;
const settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
const delay=()=>new Promise(resolve=>setTimeout(resolve,65));

(async()=>{
  faderChange(40);faderChange(41);faderChange(42);
  await settle();
  assert.equal(requests.length,1);
  await delay();await settle();
  assert.equal(requests.length,1,'slow first write blocks the newer request');
  context.currentOut='line/3';context.ACTIVE_DEVICE='device-b';
  faderChange(20);await settle();
  assert.equal(requests.length,2,'another output/device has its own write queue');
  assert.equal(requests[1].body.out,'line/3');
  assert.equal(requests[1].device,'device-b');
  requests[0].done();await settle();
  assert.equal(requests.length,3);
  assert.equal(requests[2].body.value,42,'intermediate fader position is coalesced');
  assert.equal(requests[2].body.out,'line/1','delayed write retains its original output');
  assert.equal(requests[2].device,'device-a','delayed write retains its original device');
  requests[1].done();requests[2].done();await settle();await delay();
  context.currentOut='line/1';context.ACTIVE_DEVICE='device-a';
  faderChange(10);await settle();
  const beforeMute=requests.length;
  node('masterMute').handlers.click();await settle();
  assert(node('masterMute').disabled);
  assert.equal(requests.length,beforeMute,'mute waits for the preceding volume write');
  requests.at(-1).done();await settle();
  assert.equal(requests.at(-1).body.control,'mute');
  assert.equal(requests.at(-1).body.value,true);
  requests.at(-1).done();await settle();
  assert.equal(reloads,1,'mute reads back acknowledged hardware state');
  assert(!node('masterMute').disabled);
  console.log('Master output writes: ordered volume/mute, coalescing, original output/device passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
