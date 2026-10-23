// Browser-free behavioral test of the actual link-button state machine.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');
const icon = src.slice(src.indexOf('var CHAIN_LINK_SVG'), src.indexOf('var PIN_SVG'));
const logic = src.slice(src.indexOf('// Link buttons are available on every mono channel.'),
                        src.indexOf('function unlinkStrip('));
const render = src.slice(src.indexOf('// Link state is highlighted on the strip;'),
                         src.indexOf('var loadToken ='));
class ClassList {
  constructor() { this.set = new Set(); }
  add(x) { this.set.add(x); }
  remove(x) { this.set.delete(x); }
  contains(x) { return this.set.has(x); }
  toggle(x, on) { if (on) this.add(x); else this.remove(x); }
}
const ids = ['ch/00', 'ch/01', 'ch/02', 'ch/03', 'ch/04', 'ch/05', 'ch/06', 'ch/07'];
const strips = ids.map(id => ({ dataset: {id}, classList: new ClassList(), buttons: [] }));
const row = {
  querySelectorAll(selector) {
    if (selector === ':scope > .strip') return strips;
    if (selector === '.strip .strip-more') return strips.flatMap(s => s.buttons);
    if (selector === '.strip.stereo-pending') return strips.filter(s => s.classList.contains('stereo-pending'));
    if (selector === '.strip > .link-toggle') return strips.flatMap(s => s.buttons);
    throw new Error('Unexpected selector: ' + selector);
  }
};
const submitted = [];
let refreshCount = 0;
const context = vm.createContext({
  currentMix: 0, lastStripMix: 0, pendingStereoMix: 0, lastStripState: Object.fromEntries(ids.map(id => [id, {}])),
  row, toast() {}, loadMix() { refreshCount++; return Promise.resolve(); },
  post(url, body) { submitted.push({url, body}); return Promise.resolve({ok: true, json: () => Promise.resolve({ok: true})}); },
  document: { createElement() {
    return {classList:new ClassList(), attributes:{}, addEventListener(name, f) { this[name] = f; },
      setAttribute(name, value) { this.attributes[name] = value; }, remove() {
        for (const s of strips) s.buttons = s.buttons.filter(b => b !== this);
      }};
  }}
});
for (const s of strips) s.appendChild = b => s.buttons.push(b);
vm.runInContext(icon + '\n' + logic + '\n' + render, context);
const click = id => context.chooseStereoChannel(id);
(async function main() {
  context.renderLinkButtons(context.lastStripState);
  assert(strips.every(s => s.buttons.length === 0), 'no obsolete overlay buttons');
  click('ch/01');
  assert.strictEqual(context.pendingStereoLeft, 'ch/01');
  assert(strips[1].classList.contains('stereo-pending'));
  click('ch/01');
  assert.strictEqual(context.pendingStereoLeft, null, 'click twice to cancel');
  click('ch/01');
  click('ch/04');
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(JSON.stringify(submitted[0].body), JSON.stringify({action:'link', dragged:'ch/01', target:'ch/04'}));
  assert.strictEqual(context.pendingStereoLeft, null);
  assert(refreshCount >= 1);
  // Reverse number order is valid; first remains Left even when numerically larger.
  click('ch/07');
  click('ch/02');
  await new Promise(resolve => setImmediate(resolve));
  assert.strictEqual(JSON.stringify(submitted[1].body), JSON.stringify({action:'link', dragged:'ch/07', target:'ch/02'}));
  assert(strips.every(s => s.buttons.length === 0));
  console.log('Stereo pair UI: action state machine; first-click Left; cancellation; 2→5 and 8→3 passed');
})().catch(e => {console.error(e);process.exit(1)});
