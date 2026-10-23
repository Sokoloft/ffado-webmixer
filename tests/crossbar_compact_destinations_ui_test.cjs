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
// Use exactly the five group names shown by the real PRO 40 screenshot.
let selected={
  '1394/Out:01':'Anlg/In:01',
  'ADAT/Out:01':'Mute:00',
  'Line/Out:01':'Mixer/Out:01',
  'Line/Out:02':'Mute:00',
  'Loop:01':'Mute:00',
  'Mixer/In:01':'Anlg/In:01',
  'Mixer/In:09':'Mute:00',
};
const readRouter=()=>({
  sources:['Anlg/In:01','1394/In:01','Mixer/Out:01','Mute:00'],
  destinations:Object.keys(selected),selected:{...selected}
});
const fetchFake=(url,opts)=>Promise.resolve({ok:true,json:async()=>{
  if(url==='/api/router'){
    if(opts && opts.method==='POST'){
      const payload=JSON.parse(opts.body);
      selected[payload.destination]=payload.source||'Mute:00';
      return {ok:true};
    }
    return readRouter();
  }
  return {inputs:['Mixer/In:01'],input_labels:['Analog 1'],outputs:['Mixer/Out:01'],
          mode:'dice_db',gain_scale:{min_db:-60,max_db:6},values:[[90]],db_values:[[-0.4]]};
}});
const ctx=vm.createContext({document:{getElementById:id=>nodes[id],createElement:tag=>new Element(tag),addEventListener(){}},
  window:{activeFfadoDevice:'0011223344556677',refreshMatrixStrips(){}},fetch:fetchFake,
  performance:{now:()=>0},shortFfadoLabel,setTimeout(){return 1;},clearTimeout(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ffado_webmixer/assets/static/routing.js'),'utf8'),ctx);
const flush=async()=>{for(let n=0;n<18;n++)await Promise.resolve();};
(async()=>{
  ctx.window.configureRouting({router:true,matrix:{available:true},fader:{writable:true}});
  nodes.routingButton.click(); await flush();
  const cards=nodes.routingDestinations.children;
  assert.equal(cards.length,5,'five distinct hardware router groups');
  assert.deepEqual(cards.map(card=>card.children[0].textContent),
    ['Firewire','ADAT','Line Out','Loop','Mixer Inputs']);
  const [firewire,adat,line,loop,mixer]=cards;
  assert.equal(firewire.children[1].children[0].textContent,'Firewire 1');
  assert.equal(adat.children[1].children[0].textContent,'ADAT 1');
  assert.equal(line.children[1].children[0].textContent,'Line Out 1');
  assert.equal(line.children[2].children[0].textContent,'Line Out 2');
  assert.equal(loop.children[1].children[0].textContent,'Loop 1');
  assert.equal(mixer.children[1].children[0].textContent,'In 1 ← Analog 1');
  assert.equal(mixer.children[2].children[0].textContent,'In 9 ← Disconnected');
  // Names must never replace hardware IDs in the form or meter destinations.
  assert.equal(firewire.children[1].children[1].dataset.destination,'1394/Out:01');
  assert.equal(line.children[1].children[1].dataset.destination,'Line/Out:01');
  assert.equal(line.children[2].children[2].children[0].value,'');
  assert.equal(line.children[1].children[2].value,'Mixer/Out:01');
  assert.equal(line.children[1].children[2].children[2].value,'1394/In:01');
  assert.equal(line.children[1].children[2].children[2].textContent,'Firewire 1');
  assert.equal(line.children[1].children[0].title,'Line/Out:01');
  assert.equal(cards[0].children[0].title,'1394/Out');
  // Selecting a newly displayed name still transmits the original FFADO ID.
  line.children[1].children[2].value='1394/In:01';
  line.children[1].children[2].emit('change'); await flush();
  assert.equal(selected['Line/Out:01'],'1394/In:01');
  assert.equal(line.children[1].children[0].textContent,'Line Out 1');
  console.log('Crossbar compact titles, rows, and raw routing IDs passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
