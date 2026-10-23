// Minimal browser-free regression checks for bus-scoped stereo event/selection.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');

const state = {currentMix:0, ACTIVE_DEVICE:null, CLIENT_ID:'this-browser', window:{}, row:{querySelector:() => null}};
let redraws = 0;
state.loadMix = () => {redraws++;};
state.loadMaster = () => {};
vm.createContext(state);
const syncSource = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/live-sync.js'), 'utf8');
const eventSource = syncSource.slice(syncSource.indexOf('function onSyncEvent(ev) {'), syncSource.indexOf('function refreshSyncState()'));
vm.runInContext(eventSource, state);
state.onSyncEvent({type:'stereo',mix:1,origin:'other-browser'});
assert.equal(redraws,0,'Bus 2 update must not redraw Bus 1');
state.onSyncEvent({type:'stereo',mix:0,origin:'other-browser'});
assert.equal(redraws,1,'Bus 1 update should redraw Bus 1');
state.currentMix = 1;
state.onSyncEvent({type:'stereo',mix:0,origin:'other-browser'});
assert.equal(redraws,1,'Bus 1 update must not redraw Bus 2');
state.onSyncEvent({type:'stereo',mix:1,origin:'other-browser'});
assert.equal(redraws,2,'Bus 2 update redraws Bus 2');

const iconCode = src.slice(src.indexOf('var CHAIN_LINK_SVG'), src.indexOf('var PIN_SVG'));
vm.runInContext(iconCode, state);
assert(state.CHAIN_LINK_SVG.includes('<svg'), 'Link button has an SVG');
assert(state.CHAIN_LINK_SVG.includes('stroke="currentColor"'), 'Chain link is theme-colored');
assert(!src.includes('&#x26D3;'), 'Old Unicode chains glyph is gone');
assert(src.includes("actions.push(['Unlink stereo channels'"), 'Linked strips have an unlink menu action');

const loadSource = src.slice(src.indexOf('var loadToken = 0;'), src.indexOf('window.refreshMatrixStrips = loadMix;'));
const requested = [];
state.pendingStereoLeft = 'ch/01';
state.pendingStereoMix = 0;
state.lastStripState = null;
state.loadMuteRecovery = () => {};
state.renderStrips = () => {};
state.window.ffadoApi = {
  latest(key, url, opts) {
    requested.push(url);
    assert.equal(opts.device, null);
    return Promise.resolve(url.startsWith('/api/state') ? {} : []);
  }
};
vm.runInContext(loadSource, state);
(async function main() {
  state.currentMix = 1;
  await state.loadMix();
  assert.equal(state.pendingStereoLeft, null, 'Pending Left channel cleared when switching buses');
  assert.equal(state.pendingStereoMix,1);
  assert(requested.some(url => url.includes('mix=1')));
  console.log('Bus-scoped stereo UI: independent refresh, pending selection and chain-link icon passed');
})().catch(error => {console.error(error); process.exit(1)});
