/* No special browser framework needed: exercise the gesture-lock directly. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../src/ffado_webmixer/assets/static');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'index.css'), 'utf8');
const js = fs.readFileSync(path.join(root, 'index.js'), 'utf8');
const src = fs.readFileSync(path.join(root, 'editable-input.js'), 'utf8');
function node(type='text') {
  const handlers = {};
  const css = new Set();
  const input = {
    type, dataset:{}, disabled:false, readOnly:false, title:'',
    classList:{add(x){css.add(x)},remove(x){css.delete(x)},contains(x){return css.has(x)}},
    getAttribute:(x)=>x==='title'?'':null,
    addEventListener(k,fn){(handlers[k]??=[]).push(fn)},
    fire(k,arg={}){for(const fn of handlers[k]||[]) fn({preventDefault(){this.prevented=true},...arg})},
    focus(){this.fire('focus')},blur(){this.fire('blur')},select(){this.selected=true}
  };
  return input;
}
async function run() {
  const staticInput = node();
  const usernameInput = node();
  const portInput = node('number');
  const usernameTag = html.match(/<input\b[^>]*\bid="remoteAccessUsername"[^>]*>/)[0];
  usernameInput.dataset.gestureEdit = usernameTag.match(/data-gesture-edit="([^"]+)"/)?.[1];
  const portTag = html.match(/<input\b[^>]*\bid="remoteAccessPort"[^>]*>/)[0];
  portInput.dataset.gestureEdit = portTag.match(/data-gesture-edit="([^"]+)"/)?.[1];
  const window = {};
  const context = vm.createContext({
    window,document:{querySelectorAll:()=>[staticInput, usernameInput, portInput]},MouseEvent:class {constructor(t){this.type=t}},
    setTimeout,clearTimeout,
  });
  vm.runInContext(src, context);
  usernameInput.fire('click');
  usernameInput.focus();
  assert.equal(usernameInput.readOnly,false,'username supports normal click-to-edit');
  usernameInput.blur();
  assert.equal(usernameInput.readOnly,false,'username stays editable after losing focus');
  assert.equal(usernameInput.classList.contains('gesture-edit'),false,'username has no mixer editing lock');
  portInput.focus();
  assert.equal(portInput.readOnly,false,'port supports normal click-to-edit');
  const settingsTabs = css.match(/(?:^|\n)\s*\.tabs\s*\{([^}]+)\}/)[1];
  assert.match(settingsTabs,/flex-wrap:\s*wrap/,'settings tabs wrap on narrow windows');
  assert(!/overflow(?:-[xy])?:|scrollbar-width:/.test(settingsTabs),'settings tabs have no scroll container');
  assert.equal(staticInput.readOnly,true,'static fields start locked');
  staticInput.focus();assert.equal(staticInput.readOnly,true,'simple focus is not an edit gesture');
  let prevented=false;
  staticInput.fire('contextmenu',{preventDefault(){prevented=true}});
  assert(prevented);assert.equal(staticInput.readOnly,false,'right-click unlocks');
  staticInput.blur();assert.equal(staticInput.readOnly,true,'blur relocks');
  staticInput.fire('keydown',{key:'F2'});assert.equal(staticInput.readOnly,false,'keyboard shortcut unlocks');
  staticInput.blur();
  const busInput=node();window.ffadoProtectEditable(busInput);
  busInput.fire('pointerdown',{pointerType:'touch',pointerId:1,clientX:10,clientY:10});
  busInput.fire('pointermove',{pointerId:1,clientX:40,clientY:10});
  await new Promise(r=>setTimeout(r,575));
  assert.equal(busInput.readOnly,true,'touch scroll does not unlock field');
  busInput.fire('pointerdown',{pointerType:'touch',pointerId:2,clientX:10,clientY:10});
  await new Promise(r=>setTimeout(r,575));
  assert.equal(busInput.readOnly,false,'stationary long-press unlocks');
  busInput.blur();assert.equal(busInput.readOnly,true,'editing is temporary');
  assert(html.includes('<script src="/static/editable-input.js"></script>'));
  assert(js.includes('window.ffadoProtectEditable(name)'));
  assert(js.includes('window.ffadoProtectEditable(nameEl)'));
  assert(js.includes('window.ffadoProtectEditable(inputEl)'));
  assert(js.includes('window.ffadoProtectEditable(label)'));
  assert(js.includes('showBusMenu(more, entry, name, paired)'));
  assert(!js.includes("className='bus-pin'"),'no separate pin button');
  assert(!js.includes("className='bus-min'"),'no separate minimize button');
  assert(css.includes('.bus-tab { width:128px; height:29px;'));
  assert(css.includes('.bus-tab.pinned.active { background:color-mix('));
  console.log('Compact bus tabs, menu and right-click/long-press/F2 editor tests passed');
}
run().catch(e=>{console.error(e);process.exitCode=1});
