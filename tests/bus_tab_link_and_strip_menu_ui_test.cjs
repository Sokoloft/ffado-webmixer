/* Regression contract: pair menus, merged tabs and strip menu actions. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = path.join(__dirname, '../src/ffado_webmixer/assets/static');
const js = fs.readFileSync(path.join(base,'index.js'),'utf8');
const css = fs.readFileSync(path.join(base,'index.css'),'utf8');

assert(js.includes("showActionsMenu(button, 'bus:' + entry.id"));
assert(js.includes("action") || js.includes("actions.push([linked ? 'Unlink bus '"));
assert(js.includes("var linkedGroup = group.length === 2 && STEREO_BUSES.includes(Number(group[0].id))"));
assert(js.includes('tile.appendChild(makeTab(merged, group[1]))'));
assert(js.includes("var rightName = paired ?"));
assert(js.includes("(normalName + '+' + rightName)"));
assert(js.includes('STEREO_BUS_NAMES[String(mix)]'));
assert(js.includes("postJson('/api/bus-pair-name', {left, name}, device)"));
assert(js.includes("STEREO_BUS_NAMES = info.stereo_bus_names || {}"));
assert(!js.includes("link.className = 'bus-seam-link'"));
assert(css.includes('.bus-tab .bus-name { text-align:center; }'));

assert(js.includes('<button class="strip-more"'));
assert(js.includes("actions.push(['Unlink stereo channels'"));
assert(js.includes("chooseStereoChannel(id);"));
assert(js.includes("isPinned(el) ? 'Unpin' : 'Pin'"));
assert(js.includes("isMin(el) ? 'Maximize' : 'Minimize'"));
assert(js.includes("showActionsMenu(q('.strip-more'), 'strip:' + id"));
assert(!js.includes("b.className = 'unlink link-toggle pair-seam-link'"));
assert(css.includes('.strip.minimized > .strip-more { display:block;'));
assert(css.includes('.strip.minimized > :not(.strip-more):not(.vname) { display: none; }'));
console.log('Bus merged-tab and fader three-dot menu UI contracts passed');
