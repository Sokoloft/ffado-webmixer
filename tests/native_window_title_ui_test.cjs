/* The current hardware title must reach pywebview regardless of bridge timing. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const staticDir = path.join(__dirname, '..', 'src/ffado_webmixer/assets/static');
const source = fs.readFileSync(path.join(staticDir, 'native-title.js'), 'utf8');
const index = fs.readFileSync(path.join(staticDir, 'index.js'), 'utf8');
const html = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
assert(index.includes('window.syncNativeWindowTitle(info.device)'), 'describe response syncs native title');
assert(html.includes('<script src="/static/native-title.js"></script>'), 'native title helper bundled');
assert(html.indexOf('/static/native-title.js') < html.indexOf('/static/index.js'), 'load bridge helper before main script');

function page(apiAtStart) {
  const calls = [];
  const listeners = {};
  const window = {addEventListener(name, fn) { listeners[name] = fn; }};
  const api = {set_device_title(name) { calls.push(name); return Promise.resolve({ok: true}); }};
  if (apiAtStart) window.pywebview = {api};
  const ctx = vm.createContext({window, Promise, console});
  vm.runInContext(source, ctx);
  return {window, calls, listeners, api};
}

{
  const {window, calls, listeners, api} = page(false);
  window.syncNativeWindowTitle('MOTU UltraLite');
  assert.deepEqual(calls, [], 'no native API means no native update yet');
  window.pywebview = {api};
  listeners.pywebviewready();
  assert.deepEqual(calls, ['MOTU UltraLite']);
  // A successful device switch reloads and describes the newly selected unit.
  window.syncNativeWindowTitle('Saffire PRO 40');
  assert.deepEqual(calls, ['MOTU UltraLite', 'Saffire PRO 40']);
}
{
  const {window, calls, listeners} = page(true);
  listeners.pywebviewready();
  assert.deepEqual(calls, [], 'must not set a stale title before describe arrives');
  window.syncNativeWindowTitle('Saffire PRO 40');
  assert.deepEqual(calls, ['Saffire PRO 40']);
}
{
  const {window, calls} = page(false);
  window.syncNativeWindowTitle('Saffire PRO 40');
  assert.deepEqual(calls, [], 'ordinary browsers have no native bridge');
}
console.log('Native window title follows device selection with both bridge readiness orders');
