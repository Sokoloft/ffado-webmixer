// Run the actual pan value formatter from index.js without a browser.
// The displayed value must be populated from /api/state on initial render.
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const vm = require('vm');
const src = fs.readFileSync(path.join(__dirname, '../ffado_webmixer/assets/static/index.js'), 'utf8');
const panUI = src.slice(src.indexOf('  function renderPan() {'),
                        src.indexOf('  if (FEATURES.pan || STEREO_BUSES.includes(currentMix)) {'));
assert(panUI.startsWith('  function renderPan() {'));
const env = vm.createContext({
  panAvailable: true, pan: 0.5, panEl: {value: null}, panVal: {textContent: null}, data: {},
});
vm.runInContext(panUI, env);
env.renderPan();
assert.equal(env.panVal.textContent, 'R50', 'Initial positive pan must show before user gesture');
assert.equal(env.panEl.value, 50);
env.pan = -0.5;
env.renderPan();
assert.equal(env.panVal.textContent, 'L50');
env.pan = 0;
env.renderPan();
assert.equal(env.panVal.textContent, '0');
env.data.pan_partial = true;
env.renderPan();
assert.equal(env.panVal.textContent, '0*', 'Four-crosspoint balance must be identified as partial');
env.panAvailable = false;
env.renderPan();
assert.equal(env.panVal.textContent, '—', 'Disconnected routes must NOT display fake center');
assert(src.includes('panEl.disabled = !panAvailable ||'), 'Undefined pan must disable input');
assert(src.includes('if (panEl.disabled) return;'), 'Disabled pan must not send writes');
assert(src.includes('return loadMix();'), 'UI should request new state after linking');
console.log('Initial pan UI: readback labels, missing data, and cross-route warning passed');
