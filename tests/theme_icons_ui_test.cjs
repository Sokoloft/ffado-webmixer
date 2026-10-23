const assert = require('node:assert/strict');
const fs = require('fs');
const vm = require('node:vm');
const path = require('node:path');
const js = fs.readFileSync(path.join(__dirname, '..', 'src/ffado_webmixer/assets/static/themes.js'), 'utf8');
function run(protocol, search) {
  const calls = [];
  const icon = {href:'../icon.svg'};
  const style = {
    values: {},
    setProperty(key, value) { this.values[key] = value; },
    getPropertyValue(key) { return this.values[key] || ''; },
  };
  const document = {
    documentElement: {dataset: {}, style},
    getElementById(id) { return id === 'themeStylesheet' ? {dataset: {base: '/themes/'}, href:''} : null; },
    querySelector(sel) { return sel === 'link[rel="icon"]' ? icon : null; },
  };
  const listeners = {};
  const window = {
    addEventListener(name, fn) { listeners[name] = fn; },
    pywebview: {api: {set_theme_icon(theme, accent) { calls.push([theme, accent]); return Promise.resolve({ok:true}); }}},
  };
  const context = vm.createContext({document, window, location:{protocol, search},
    URLSearchParams, Promise, localStorage:{getItem(){return null;},setItem(){}}, console});
  vm.runInContext(js, context);
  return {context, icon, calls, listeners};
}
{
  const {context,icon,calls,listeners} = run('http:', '');
  vm.runInContext('setMixerTheme("gruvbox"); setMixerAccent("#1234ab");', context);
  assert.equal(icon.href, '/favicon.svg?theme=gruvbox&accent=%231234ab');
  assert.deepEqual(calls.at(-1), ['gruvbox', '#1234ab']);
  vm.runInContext('setMixerTheme("light"); setMixerAccent(null);', context);
  assert.equal(icon.href, '/favicon.svg?theme=light');
  assert.deepEqual(calls.at(-1), ['light', null]);
  listeners.pywebviewready();
  assert.deepEqual(calls.at(-1), ['light', null]);
}
{
  const {icon} = run('file:', '?theme=gruvbox&accent=%23ffffee&icon_url=file%3A%2F%2F%2Ftmp%2Ftest-icon.svg');
  assert.equal(icon.href, 'file:///tmp/test-icon.svg');
}
console.log('Theme icon UI: browser favicon, accents, Qt bridge, local splash icon OK');
