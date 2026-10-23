/* Unlinked buses reorder independently; linked stereo pairs remain one tile. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '../src/ffado_webmixer/assets/static');
const js = fs.readFileSync(path.join(root,'index.js'),'utf8');
const css = fs.readFileSync(path.join(root,'index.css'),'utf8');
const grouping = js.slice(js.indexOf('  // Preserve individual bus order;'), js.indexOf('  groups.forEach(group =>'));
assert(grouping.includes('if (STEREO_BUSES.includes(left) && other && !used.has(other.id)) {'),
  'unlinked even/odd buses must not share a draggable tile');
assert(!grouping.includes('if (other && !used.has(other.id)) {'),
  'pairing all adjacent buses causes pinned neighbors to lock unpinned buses');
assert(js.includes('tile.dataset.ids = group.map(e => e.id).join'),
  'linked partners must be saved as a single tile');
assert(js.includes("group.some(x => x.pinned)"), 'linked group is pinned until BOTH legs are unpinned');
assert(js.includes("busTabs.insertBefore(tile, "), 'drag gesture moves the independent tile');
assert(js.includes("document.addEventListener('pointermove', move)"), 'drag listens outside grip');
assert(js.includes("Math.hypot(e.clientX - startX, e.clientY - startY) >= 4"),
  'drag must work for touch as well as desktop pointer events');
assert(js.includes("tile.classList.remove('dragging')"), 'dragging state cleans up');
assert(js.includes("if (e.type === 'pointercancel') { renderBusTabs(); return; }"),
  'canceled drag must not persist a half-finished order');
assert(css.includes('.bus-tab.pinned .bus-grip, .bus-tab-tile.pinned .bus-grip {\n  visibility:hidden; pointer-events:none;'),
  'pinned bus handles are actually hidden');
assert(css.includes('.bus-tab:not(.pinned) .bus-grip {'), 'unpinned handles are styled explicitly');
assert(css.includes('cursor:grab'), 'unpinned grip uses the grab cursor');
assert(css.includes('cursor:grabbing'), 'actively dragging grip uses the grabbing cursor');
assert(js.includes("isMin(el) ? 'Maximize' : 'Minimize'"));
assert(js.includes("entry.minimized ? 'Maximize' : 'Minimize'"));
assert(!js.includes("isMin(el) ? 'Restore' : 'Minimize'"));
assert(!js.includes("entry.minimized ? 'Restore' : 'Minimize'"));
console.log('Independent bus drag, pinned grip visibility, touch cursor and Maximize menu contracts passed');
