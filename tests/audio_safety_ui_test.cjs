/* Ensure delayed fader writes retain their original bus/GUID and preserve order. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const src = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');
const code = src.slice(src.indexOf('var CLIENT_ID'), src.indexOf('// Interrupted software mute/solo'));
const requests = [];
const ctx = vm.createContext({
  ACTIVE_DEVICE: 'aaaaaaaaaaaaaaaa', currentMix: 0, STEREO_BUSES: [], Math, Date,
  setTimeout, clearTimeout, Promise,
  fetch(url, options) {
    let done;
    const promise = new Promise(resolve => { done = () => resolve({ok: true, json: async () => ({ok: true})}); });
    requests.push({url, body: JSON.parse(options.body), device: options.headers['X-FFADO-Device'], done});
    return promise;
  },
  toast(message) { throw Error('Unexpected failed write: ' + message); },
  loadMix() { throw Error('Unexpected reload'); },
  loadMuteRecovery() {},
});
vm.runInContext(code, ctx);
const drain = () => new Promise(r => setTimeout(r, 65));
async function run() {
  ctx.sendThrottled('ch/02', 'fader', 41);
  ctx.sendThrottled('ch/02', 'fader', 42);
  ctx.sendThrottled('ch/02', 'fader', 43);
  assert.equal(requests.length, 1, 'one in-flight request per key');
  ctx.currentMix = 1;
  // A pointerup callback from an old DOM strip must retain its captured context.
  ctx.sendThrottled('ch/02', 'fader', 44, 0, 'aaaaaaaaaaaaaaaa');
  ctx.sendThrottled('ch/02', 'fader', 25);
  assert.equal(requests.length, 2, 'other bus has its own queue');
  ctx.ACTIVE_DEVICE = 'bbbbbbbbbbbbbbbb';
  ctx.sendThrottled('ch/02', 'fader', 75);
  assert.equal(requests.length, 3, 'other hardware has its own queue');
  assert.deepEqual(requests.map(r => [r.body.mix, r.device]),
    [[0, 'aaaaaaaaaaaaaaaa'], [1, 'aaaaaaaaaaaaaaaa'], [1, 'bbbbbbbbbbbbbbbb']]);
  await drain();
  assert.equal(requests.length, 3, 'slow first request blocks trailing write');
  requests[0].done();
  await drain();
  assert.equal(requests.length, 4, 'queued final fader value eventually sent');
  assert.equal(requests[3].body.value, 44, 'intermediate value coalesced');
  assert.equal(requests[3].body.mix, 0, 'old bus retained');
  assert.equal(requests[3].device, 'aaaaaaaaaaaaaaaa', 'old device retained');
  requests[1].done(); requests[2].done(); requests[3].done();
  await drain();
  assert.equal(Object.keys(ctx.queuedControlWrites).length, 0, 'no abandoned queues');
  console.log('Audio safety UI: bus/GUID affinity, ordered writes, coalescing passed');
}
run().catch(e => { console.error(e); process.exitCode = 1; });
