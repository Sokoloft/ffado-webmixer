/* Bus tabs: large mixer threshold, stable layout, linked pair UI, and save guards. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../src/ffado_webmixer/assets/static');
const src = fs.readFileSync(path.join(root, 'index.js'), 'utf8');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'index.css'), 'utf8');
const part = src.slice(src.indexOf('var busLayout = []'), src.indexOf('// ---- output buttons (right side)'));
const callbacks = {};
const stub = {
  hidden: true, checked: false, addEventListener: (kind, cb) => callbacks[kind] = cb,
  querySelectorAll: () => [], replaceChildren: () => {}, classList: {toggle: () => {}},
};
const ctx = vm.createContext({
  document: {addEventListener: () => {}, getElementById: id => id === 'busTabs' || id === 'hideMinBuses' ? stub : {textContent: ''},
    body: {classList: {toggle: () => {}}}},
  MIXES: [], OUTPUTS: [], STEREO_BUSES: [], ACTIVE_DEVICE: 'device-1',
  window: {ffadoApi: {serial: (_key, fn) => fn()}},
  GAIN_SCALE: {}, console, Map, Set, Number,
});
vm.runInContext(part, ctx);
ctx.MIXES = Array.from({length: 8}, (_, id) => ({id, name: `Mix ${id}`}));
assert.equal(ctx.busTabsEnabled(), false, '8 or fewer buses retain sidebar grid');
ctx.MIXES.push({id: 8, name: 'Mix 8'});
assert.equal(ctx.busTabsEnabled(), true, '9 buses switch to tabs');
ctx.busLayout = [
  {id:'4', pinned: true, minimized: true},
  {id:'2', pinned: false, minimized: false},
  {id:'5', minimized: false}, // legacy entry with an omitted pin flag
];
const entries = Array.from(ctx.busEntries());
assert.equal(entries.length, 9);
assert.equal(entries[0].id, '4');
assert.equal(entries[0].pinned, true);
assert.equal(entries[0].minimized, true);
assert.equal(entries[1].id, '2');
assert.equal(entries[1].pinned, false, 'explicit user unpin preference is retained');
assert.equal(entries[2].id, '5');
assert.equal(entries[2].pinned, true, 'old layouts with no pin flag default to pinned');
assert.equal(entries[3].id, '0', 'unsaved buses are appended in numeric order');
assert.equal(entries[3].pinned, true, 'newly discovered buses default to pinned');
assert(entries.every(x => x.id === '2' || x.pinned === true), 'all other buses start pinned');
// No saved bus-tab layout: all buses should be pinned on first launch.
ctx.busLayout = [];
assert(ctx.busEntries().every(x => x.pinned), 'first-run bus tabs are pinned');
// Channel defaults are already pinned, including absent pin flags in legacy layouts.
assert(src.includes('row.appendChild(make(id, true, false));'));
assert(src.includes('row.appendChild(make(id, entry.pinned !== false, !!entry.minimized));'));
assert.equal(new Set(entries.map(x => x.id)).size, 9);
assert(html.includes('id="busTabs"'));
assert(html.includes('id="hideMinBuses"'));
assert(src.includes("postJson('/api/bus-layout', snapshot, device)"));
assert(src.includes("postJson('/api/bus-stereo', {left, linked:!linked}, device)"));
assert(src.includes('busTabs.insertBefore(tile, '));
assert(src.includes('STEREO_BUSES.includes(currentMix) && mix === currentMix + 1'),
 'active linked right bus remains visible when minimizing');
assert(css.includes('body.bus-tabs-mode #outbox .bus-group { display:none; }'));
assert(!src.includes("link.className = 'bus-seam-link'"));
assert(src.includes('tile.appendChild(makeTab(merged, group[1]))'));
assert(src.includes('showActionsMenu(q(\'.strip-more\')'));
console.log('Bus tab mode, ordering, controls, linked-pair seam, hide settings, and request guards passed');
