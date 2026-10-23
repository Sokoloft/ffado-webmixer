/* Browser-level test: Crossbar Router and matrix labels use the same live sources. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const shortFfadoLabel = require('../src/ffado_webmixer/assets/static/labels.js');
class ClassList {
  constructor() {this.set=new Set();}
  add(x) {this.set.add(x);} remove(x) {this.set.delete(x);}
  contains(x) {return this.set.has(x);}
  toggle(x,on) {if(on===undefined?!this.set.has(x):on)this.set.add(x);else this.set.delete(x);}
}
class Element {
  constructor(tag='div') {this.tag=tag;this.children=[];this.listeners={};this.attrs={};this.style={};this.dataset={};
    this.classList=new ClassList();this.hidden=false;this.disabled=false;this.value='';this.textContent='';this._className='';}
  set className(x){this._className=x;this.classList=new ClassList();x.split(/\s+/).forEach(c=>c&&this.classList.add(c));}
  get className(){return this._className;}
  appendChild(el){this.children.push(el);el.parent=this;return el;}
  append(...els){els.forEach(x=>this.appendChild(x));}
  replaceChildren(...els){this.children=[];this.append(...els);}
  setAttribute(k,v){this.attrs[k]=String(v);} getAttribute(k){return this.attrs[k];}
  addEventListener(k,fn){(this.listeners[k] ||= []).push(fn);}
  emit(k,e={}){for(const fn of this.listeners[k]||[])fn(e);} click(){this.emit('click');} focus(){}
  querySelectorAll(q){const cls=q.slice(1),out=[];const rec=el=>{for(const child of el.children){if(child.classList.contains(cls))out.push(child);rec(child);}};rec(this);return out;}
  querySelector(q){return this.querySelectorAll(q)[0]||null;}
}
const ids='routerbox routingOverlay routingButton routingBusTab routingMatrixTab routingCrossbarTab routingBus routingMatrix routingCrossbar routingHint routingGrid routingEditor routingDb routingDbLabel routingKnob routingPreset routingPresetLabel routingRefresh routingClose routingDialog routingCellLabel routingLevel routingLevelLabel routingApply routingSilence routingUnity routingBusGrid routingPhonesAssignment routingPhonesSelect routingDestinations'.split(' ');
const nodes=Object.fromEntries(ids.map(id=>[id,new Element()]));
nodes.routingKnob.appendChild(Object.assign(new Element('span'),{className:'routing-knob-needle'}));
nodes.routingOverlay.hidden=true;
let selected={'Mixer/In:01':'1394/In:01','Mixer/In:09':'Mute:00','Line/Out:01':'Mixer/Out:01'};
const fixedInputs=Array.from({length:9},(_,i)=>`Anlg/In:${String(i+1).padStart(2,'0')}`);
const readMatrix=()=>({inputs:fixedInputs,input_labels:fixedInputs.map((x,i)=>i===0?selected['Mixer/In:01']:
  i===8?(selected['Mixer/In:09'].startsWith('Mute:')?'Disconnected':selected['Mixer/In:09']):x),
  outputs:['Mixer/Out:01'],mode:'dice_db',gain_scale:{min_db:-60,max_db:6},
  values:fixedInputs.map(()=>[90]),db_values:fixedInputs.map(()=>[-0.4])});
const readRouter=()=>({sources:['1394/In:01','SPDIF/In:01','Mixer/Out:01','Mute:00'],
  destinations:['Mixer/In:01','Mixer/In:09','Line/Out:01'],selected:{...selected}});
const fetchFake=(url,opts)=>Promise.resolve({ok:true,json:async()=>{
  if(url==='/api/router'){
    if(opts && opts.method==='POST'){
      const payload=JSON.parse(opts.body);selected[payload.destination]=payload.source||'Mute:00';return {ok:true};
    }
    return readRouter();
  }
  return readMatrix();
}});
const ctx=vm.createContext({document:{getElementById:id=>nodes[id],createElement:tag=>new Element(tag),addEventListener(){}},
  window:{activeFfadoDevice:'0011223344556677',refreshMatrixStrips(){}},fetch:fetchFake,
  performance:{now:()=>0},shortFfadoLabel,setTimeout(){return 1;},clearTimeout(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ffado_webmixer/assets/static/routing.js'),'utf8'),ctx);
const flush=async()=>{for(let n=0;n<18;n++)await Promise.resolve();};
(async()=>{
  ctx.window.configureRouting({router:true,matrix:{available:true},fader:{writable:true}});
  nodes.routingButton.click();await flush();
  assert.equal(nodes.routingDestinations.children.length,2,'crossbar destinations are grouped by hardware type; '+nodes.routingHint.textContent);
  const mixerRows=nodes.routingDestinations.children[0].children.slice(1);
  assert.equal(mixerRows[0].children[0].textContent,'In 1 ← Firewire 1');
  assert.equal(mixerRows[1].children[0].textContent,'In 9 ← Disconnected');
  assert.equal(mixerRows[1].children[2].children[0].textContent,'Disconnected');
  // The displayed options are shortened, but their actual FFADO values remain untouched.
  assert.equal(mixerRows[0].children[2].children[1].textContent,'Firewire 1');
  assert.equal(mixerRows[0].children[2].children[1].value,'1394/In:01');
  nodes.routingMatrixTab.click();await flush();
  const rows=nodes.routingGrid.children[1].children;
  assert.equal(rows[0].children[0].textContent,'Firewire 1');
  assert.equal(rows[8].children[0].textContent,'Disconnected');
  assert.match(rows[8].children[1].children[0].getAttribute('aria-label'),/^Disconnected to Bus 1/);
  rows[8].children[1].children[0].click();
  assert.equal(nodes.routingCellLabel.textContent,'Disconnected → Bus 1');
  selected['Mixer/In:09']='SPDIF/In:01';
  ctx.window.routingSyncEvent({type:'routing',destination:'Mixer/In:09'});await flush();
  const newRows=nodes.routingGrid.children[1].children;
  assert.equal(newRows[8].children[0].textContent,'SPDIF 1');
  assert.equal(newRows[0].children[0].textContent,'Firewire 1');
  nodes.routingCrossbarTab.click();await flush();
  const updatedRows=nodes.routingDestinations.children[0].children.slice(1);
  assert.equal(updatedRows[1].children[0].textContent,'In 9 ← SPDIF 1');
  // Set to disconnected through the actual UI: displayed names change, hardware values stay raw.
  updatedRows[1].children[2].value='';updatedRows[1].children[2].emit('change');await flush();
  assert.equal(updatedRows[1].children[0].textContent,'In 9 ← Disconnected');
  assert.equal(selected['Mixer/In:09'],'Mute:00');
  console.log('Global router/matrix labels: disconnected, source changes, SSE, exact FFADO IDs passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
