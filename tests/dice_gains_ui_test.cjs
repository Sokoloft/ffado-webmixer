/* DICE gain overview: hardware reads, isolated writes, failures and device scoping. */
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');

class ClassList {
  constructor() {this.set=new Set();}
  add(x) {this.set.add(x);}
  remove(x) {this.set.delete(x);}
  contains(x) {return this.set.has(x);}
  toggle(x, on) {if (on === undefined ? !this.set.has(x) : on) this.set.add(x); else this.set.delete(x);}
}
class Element {
  constructor(tag='div') {
    this.tag=tag; this.tagName=tag.toUpperCase(); this.dataset={}; this.children=[]; this.listeners={}; this.attrs={}; this.style={};
    this.classList=new ClassList();this.hidden=false;this.disabled=false;this.value='';
    this.textContent='';this._className='';
  }
  set className(x) {this._className=x;this.classList=new ClassList();x.split(/\s+/).forEach(c=>c&&this.classList.add(c));}
  get className() {return this._className;}
  appendChild(el) {this.children.push(el);el.parent=this;return el;}
  append(...els) {els.forEach(x=>this.appendChild(x));}
  replaceChildren(...els) {this.children=[];this.append(...els);}
  setAttribute(k,v) {this.attrs[k]=String(v);}
  getAttribute(k) {return this.attrs[k];}
  addEventListener(k,fn) {(this.listeners[k] ||= []).push(fn);}
  emit(k,e={}) {e.preventDefault ||= (()=>{e.prevented=true;});for(const fn of this.listeners[k]||[]) fn(e);}
  click() {this.emit('click');}
  focus() { this.emit('focus'); }
  select() {}
  blur() { this.emit('blur'); }
  setPointerCapture(x) {this.pointerCapture=x;}
  querySelectorAll(q) {
    if (!q.startsWith('.')) throw Error('Unrecognized selector '+q);
    const className=q.slice(1), result=[];
    const walk = el => {for(const child of el.children) {if(child.classList.contains(className))result.push(child);walk(child);}};
    walk(this);return result;
  }
  querySelector(q) {return this.querySelectorAll(q)[0] || null;}
}
const ids = [...fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.html'), 'utf8').matchAll(/id="([^"]+)"/g)].map(match => match[1]);
const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
elements.routingKnob.appendChild(Object.assign(new Element('span'), {className:'routing-knob-needle'}));
elements.routingOverlay.hidden = true;
const scale = {mode:'dice_db', min_db:-60, max_db:6};
let outputs = [
  {id:'bus/0', name:'Main', controllable:true},
  {id:'bus/1', name:'Right', controllable:true},
  {id:'bus/2', name:'Cue', controllable:true},
  {id:'line/0', name:'Line 1', controllable:true},
  {id:'line/1', name:'Line 2', controllable:true},
  {id:'spdif/0', name:'SPDIF', controllable:false}
];
const states = Object.fromEntries(outputs.map(out => [out.id, {name:out.name, level:50, mute:false}]));
states['line/1'].hardware_controlled = true;
let held = null, fail = false, reloads = 0, quantize = true;
const reads = [], writes = [];
const read = async (url, device) => {
  reads.push({url, device});
  const id = new URL(url, 'http://local').searchParams.get('out');
  return {...states[id]};
};
const root = {
  activeFfadoDevice:'a', OUTPUTS:outputs, GAIN_SCALE:scale,
  canonicalOutput:id => id === 'bus/1' ? 'bus/0' : id,
  hasFaderDbScale:s => !!s,
  faderUiToDb:(v,s) => v <= 0 ? null : s.min_db + v * (s.max_db-s.min_db)/100,
  faderDbToUi:(v,s) => (v-s.min_db)*100/(s.max_db-s.min_db),
  formatFaderDb:db => db === null ? '−∞ dB' : db.toFixed(1)+' dB',
  readJson:read,
  ffadoApi:{request:(url, options) => read(url, options.device)},
  writeOutput:async (id, control, level, device) => {
    writes.push({id, control, level, device});
    if (held) await new Promise(resolve => held.push(resolve));
    if (fail) throw Error('readback mismatch');
    states[id].level = quantize ? Math.round(level) : level;
  },
  loadMaster:() => reloads++, refreshMatrixStrips:() => reloads++
};
const ctx = vm.createContext({window:root, document:{getElementById:id=>elements[id], createElement:tag=>new Element(tag), addEventListener(){}, querySelectorAll:()=>[]}, setTimeout, clearTimeout, GAIN_SCALE:scale, shortFfadoLabel:s=>s});
const indexSource = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');
vm.runInContext(indexSource.slice(indexSource.indexOf('function faderHasDbScale()'), indexSource.indexOf('// ---- a gain box:')), ctx);
for (const name of ['hasFaderDbScale','faderUiToDb','faderDbToUi','formatFaderDb']) root[name] = ctx[name];
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/editable-input.js'), 'utf8'), ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/routing.js'), 'utf8'), ctx);
const flush = async () => {for (let i=0;i<80;i++) await Promise.resolve();};
const cards = () => elements.routingGainGroups.querySelectorAll('.routing-gain-card');
// Extend the tiny DOM's selector support for the busy lock.
const originalQuery = Element.prototype.querySelectorAll;
Element.prototype.querySelectorAll = function(q) {
  if (q !== 'input, button') return originalQuery.call(this,q);
  return this.children.flatMap(child => [...(['input','button'].includes(child.tag)?[child]:[]), ...child.querySelectorAll(q)]);
};
(async () => {
  root.configureRouting({software_bus_gain:true});
  assert.equal(elements.routingGainsTab.hidden,false);
  assert.equal(elements.routerbox.hidden,false);
  elements.routingButton.click(); await flush();
  assert.equal(elements.routingGains.hidden,false);
  assert.equal(cards().length,4,'all controllable buses/outputs; linked pair appears once');
  assert.equal(writes.length,0,'opening the overview never changes hardware');
  assert(!reads.some(x=>x.url.includes('bus%2F1')));
  assert.equal(cards()[3].children[3].textContent,'H/W');
  assert(cards()[3].children[1].disabled);
  const first = cards()[0];
  first.children[1].value=-13.668; first.children[1].emit('input');
  root.routingSyncEvent({type:'output'}); await flush();
  assert.equal(cards()[0], first,'sync cannot replace an active fader');
  assert.equal(writes.length,0,'slider previews do not write until release');
  held=[];first.children[1].emit('change');await flush();
  assert.equal(writes.length,1);assert(first.children[1].disabled);
  assert.equal(writes[0].id,'bus/0');assert.equal(writes[0].control,'fader');assert.equal(writes[0].device,'a');
  elements.routingMatrixTab.click();assert.equal(elements.routingGains.hidden,false);
  held.shift()();held=null;await flush();
  assert(Math.abs(Number(cards()[0].children[1].value) + 13.8)<1e-10,'display uses quantized readback in dB');
  assert(reloads>=2);
  // Numeric dB conversion and output isolation.
  cards()[2].children[2].emit('contextmenu');cards()[2].children[2].value='-12';cards()[2].children[2].emit('change');await flush();
  assert.equal(writes.at(-1).id,'line/0');
  assert(Math.abs(writes.at(-1).level - 100*48/66)<1e-8);
  const count=writes.length;
  cards()[2].children[2].emit('contextmenu');cards()[2].children[2].value='99';cards()[2].children[2].emit('change');await flush();
  assert.equal(writes.length,count,'invalid numeric values are rejected');
  fail=true;cards()[0].children[4].click();await flush();
  assert(Math.abs(Number(cards()[0].children[1].value) + 13.8)<1e-10,'failed write restores readback');
  assert.match(elements.routingHint.textContent,/readback mismatch/);
  fail=false;
  cards()[1].children[4].click();await flush();
  assert.equal(writes.at(-1).level,0,'silence sets only the selected bus');
  // Unity must round-trip without losing fractional API percentage precision.
  quantize=false;
  for (const index of [0, 2]) {
    let card=cards()[index];
    const numeric=card.children[2];
    assert.equal(numeric.readOnly,true,'numeric gain starts locked');
    numeric.click(); numeric.focus();
    assert.equal(numeric.readOnly,true,'left click does not unlock gain');
    numeric.emit('contextmenu');assert.equal(numeric.readOnly,false);
    numeric.value='0';numeric.emit('change');await flush();
    assert(Math.abs(writes.at(-1).level - 100*60/66)<1e-10);
    assert.equal(cards()[index].children[2].value,'0.0');
    assert.equal(cards()[index].children[3].textContent,'0.0 dB');
    card=cards()[index];card.children[1].value='0';card.children[1].emit('input');card.children[1].emit('change');await flush();
    assert.equal(cards()[index].children[3].textContent,'0.0 dB','slider zero is exactly unity');
    cards()[index].children[5].click();await flush();
    assert.equal(cards()[index].children[3].textContent,'0.0 dB','unity preset is exact');
    const field=cards()[index].children[2];field.emit('keydown',{key:'F2'});
    assert.equal(field.readOnly,false,'keyboard editing remains available');
    field.blur();assert.equal(field.readOnly,true,'blur locks editing again');
  }
  // Pending writes retain the old device and cannot repaint the new device.
  held=[];cards()[0].children[5].click();await flush();
  root.activeFfadoDevice='b';root.configureRouting({software_bus_gain:true});
  elements.routingGainsTab.click();await flush();
  const newCard=cards()[0], before=reloads;
  held.shift()();held=null;await flush();
  assert.equal(writes.at(-1).device,'a');assert.equal(cards()[0],newCard);assert.equal(reloads,before);
  root.configureRouting({matrix:{available:true},fader:{writable:true}});
  assert.equal(elements.routingGainsTab.hidden,true,'other devices do not show DICE gains');
  // Dim retains its attenuation level while its independent switch is Off.
  outputs.push({id:'dice/dim', name:'Dim', controllable:true,
    gainScale:{mode:'dice_dim', min_db:-87, max_db:0, native_max:88, min_finite_native:1, step_native:1}});
  states['dice/dim'] = {name:'Dim', level:50, mute:true, dim_active:false};
  root.configureRouting({software_bus_gain:true});
  elements.routingGainsTab.click();await flush();
  assert.equal(cards().at(-1).children[3].textContent,'-44.0 dB · Off');
  states['dice/dim'].mute=false;states['dice/dim'].dim_active=true;
  elements.routingRefresh.click();await flush();
  assert.equal(cards().at(-1).children[3].textContent,'-44.0 dB · On');
  console.log('DICE gains UI: overview, links, preview, isolated writes, readback, failures and device scoping passed');
})().catch(error => {console.error(error);process.exitCode=1;});
