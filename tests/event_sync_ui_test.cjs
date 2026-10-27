/* Loss recovery, reconnect snapshots and out-of-order event regression tests. */
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const root = path.join(__dirname, '../src/ffado_webmixer/assets/static');
const source = fs.readFileSync(path.join(root, 'live-sync.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
assert(html.indexOf('/static/live-sync.js') < html.indexOf('/static/index.js'), 'sync helpers load before startup');

function fixture() {
  const calls = [], streams = [], timers = [];
  const info = {
    guid: 'device-a', stereo_buses: [0], stereo_bus_names: {'0': 'New stereo name'},
    mixes: [{id: 0, name: 'Renamed bus'}, {id: 1, name: 'Right'}],
    outputs: [{id: 'main', name: 'Renamed output', base_name: 'Hardware output', controllable: true}]
  };
  const context = {
    Promise, encodeURIComponent,
    ACTIVE_DEVICE: 'device-a', currentMix: 1, currentOut: 'main', CLIENT_ID: 'browser',
    row: {querySelector: () => null},
    shortFfadoLabel: name => name,
    readJson(url, device) {
      calls.push(['read', url, device]);
      return Promise.resolve(url === '/api/describe' ? info : [{id: 0, pinned: false}]);
    },
    buildOutputs() { calls.push(['outputs']); },
    markOutputs() { calls.push(['selection']); },
    loadDevices() { calls.push(['devices']); },
    loadMix(options) { assert.equal(options.throwOnError, true); calls.push(['strips']); return Promise.resolve(); },
    loadMaster(options) { assert.equal(options.throwOnError, true); calls.push(['master']); return Promise.resolve(); },
    toast(message) { calls.push(['error', message]); },
    window: {routingSyncEvent(event) { calls.push(['routing', event.type]); return Promise.resolve(); }},
    EventSource: class {
      constructor(url) { this.url = url; streams.push(this); }
    },
    setTimeout(callback, delay) { timers.push({callback, delay}); return timers.length; },
    clearTimeout() {}
  };
  vm.createContext(context);
  const index = fs.readFileSync(path.join(root, 'index.js'), 'utf8');
  vm.runInContext(index.slice(index.indexOf('function outputPartner('), index.indexOf('var outputLinkBusy')), context);
  vm.runInContext(source, context);
  return {context, calls, streams, timers, info};
}

const count = (calls, action) => calls.filter(call => call[0] === action).length;

(async () => {
  const {context, calls, streams} = fixture();
  const stream = context.startSync();
  assert.equal(stream.url, '/api/events?device=device-a');
  assert.equal(context.startSync(), stream, 'repeated startup shares the stream');
  assert.equal(streams.length, 1);
  await stream.onopen();
  assert.equal(count(calls, 'strips'), 1, 'first open closes the startup snapshot gap');
  assert.equal(count(calls, 'master'), 1);
  assert.equal(count(calls, 'routing'), 1, 'visible routing gets a snapshot');
  assert.equal(context.currentMix, 0, 'missed bus pairing selects the visible Left bus');
  assert.equal(context.MIXES[0].name, 'Renamed bus');
  assert.equal(context.OUTPUTS[0].name, 'Renamed output');
  assert.equal(context.busLayout[0].pinned, false);
  assert.equal(context.STEREO_BUS_NAMES['0'], 'New stereo name');
  assert(calls.filter(call => call[0] === 'read').every(call => call[2] === 'device-a'));

  await stream.onopen();
  assert.equal(count(calls, 'strips'), 2, 'reconnect refreshes strips');
  assert.equal(count(calls, 'outputs'), 2, 'reconnect refreshes names and bus topology');
  assert.equal(count(calls, 'routing'), 2, 'reconnect refreshes the router');
  stream.onmessage({data: JSON.stringify({type: 'resync', reason: 'overflow', device: 'device-a'})});
  await context.syncRefresh;
  assert.equal(count(calls, 'strips'), 3, 'overflow refreshes an open stream');

  stream.onmessage({data: '{bad-json'});
  await context.syncRefresh;
  assert.equal(count(calls, 'strips'), 4, 'an unreadable event also requires a snapshot');
  stream.onmessage({data: JSON.stringify({type: 'resync', device: 'device-b'})});
  assert.equal(context.syncRefresh, null, 'other-device events never refresh this mixer');

  const blocked = fixture();
  let finishFirstRead;
  let describeReads = 0;
  blocked.context.readJson = function (url) {
    if (url !== '/api/describe') return Promise.resolve([]);
    describeReads++;
    return describeReads === 1 ? new Promise(resolve => { finishFirstRead = resolve; }) : Promise.resolve(blocked.info);
  };
  const heldStream = blocked.context.startSync();
  const refreshing = heldStream.onopen();
  await Promise.resolve();
  heldStream.onmessage({data: JSON.stringify({type: 'strip', control: 'gain', strip: 'ch/00', value: 9, device: 'device-a'})});
  heldStream.onmessage({data: JSON.stringify({type: 'resync', device: 'device-a'})});
  assert.equal(describeReads, 1, 'overlapping resyncs share the active snapshot');
  finishFirstRead(blocked.info);
  await refreshing;
  assert.equal(describeReads, 2, 'events during a snapshot trigger a later snapshot');
  assert.equal(count(blocked.calls, 'strips'), 2);

  const failed = fixture();
  let fail = true;
  const realRead = failed.context.readJson;
  failed.context.readJson = function (...args) {
    if (fail) return Promise.reject(Error('network unavailable'));
    return realRead(...args);
  };
  await failed.context.startSync().onopen();
  assert.equal(failed.timers.length, 1, 'failed snapshot is retried while the stream stays open');
  assert.equal(failed.timers[0].delay, 1000);
  assert(failed.calls.some(call => call[0] === 'error' && call[1].includes('network unavailable')));
  fail = false;
  await failed.timers[0].callback();
  assert.equal(count(failed.calls, 'strips'), 1);

  const hardware = fixture();
  hardware.context.loadMix = () => Promise.reject(Error('FFADO unavailable'));
  await hardware.context.startSync().onopen();
  assert.equal(hardware.timers.length, 1, 'hardware snapshot failure also schedules recovery');
  assert(hardware.calls.some(call => call[0] === 'error' && call[1].includes('FFADO unavailable')));

  const stale = fixture();
  stale.info.guid = 'device-b';
  await stale.context.startSync().onopen();
  assert.equal(count(stale.calls, 'strips'), 0, 'a different device snapshot is never rendered');
  assert.equal(count(stale.calls, 'error'), 1);
  console.log('Event sync UI: overflow, reconnect, snapshot ordering, device isolation and retry passed');
})().catch(error => { console.error(error); process.exit(1); });
