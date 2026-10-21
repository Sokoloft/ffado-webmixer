/* Hardware-backed MOTU Phones assignment in the real In/Out panel. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
class Classes {
  constructor(){ this.values = new Set(); }
  add(x){this.values.add(x);} remove(x){this.values.delete(x);}
  toggle(x, b){ b ? this.add(x) : this.remove(x); }
  contains(x){return this.values.has(x);}
}
class Element {
  constructor(tag='div'){
    this.tag=tag;this.children=[];this.events={};this.classList=new Classes();
    this.hidden=false;this.disabled=false;this.value='';this.textContent='';this.style={};
  }
  appendChild(el){this.children.push(el);return el;}
  replaceChildren(...els){this.children=els;}
  addEventListener(event,fn){(this.events[event] ||= []).push(fn);}
  emit(event){for(const fn of this.events[event]||[])fn({preventDefault(){}});}
  click(){this.emit('click');}
  focus(){}
  setAttribute(k,v){this[k]=v;}
  querySelectorAll(q){return q==='button' ? this.children.flatMap(x=>x.querySelectorAll(q)).concat(this.tag==='button'?[this]:[]) : [];}
}
const ids='routerbox routingOverlay routingButton routingBusTab routingMatrixTab routingCrossbarTab routingBus routingMatrix routingCrossbar routingHint routingGrid routingEditor routingDb routingDbLabel routingKnob routingPreset routingPresetLabel routingRefresh routingClose routingDialog routingCellLabel routingLevel routingLevelLabel routingApply routingSilence routingUnity routingBusGrid routingPhonesAssignment routingPhonesSelect routingDestinations'.split(' ');
const els=Object.fromEntries(ids.map(id=>[id,new Element()]));
els.routingOverlay.hidden=true;
let value=1, hasPhones=true, shouldFail=false;
const writes=[];
const snapshot=()=>({kind:'motu_mix_dest',destinations:[{name:'Disabled',value:0},{name:'Phones',value:1},{name:'MainOut',value:6}],buses:[{id:'bus/0',name:'Mix 1',value:6},{id:'bus/1',name:'Mix 2',value:1}],...(hasPhones?{phones:{value,options:[{name:'Disabled',value:0},{name:'Phones',value:1},{name:'MainOut',value:6}]}}:{})});
const fetchFake=(url, init={})=>{
  if (init.method === 'POST') {
    const body=JSON.parse(init.body);writes.push({url,body});
    if(shouldFail){shouldFail=false;return Promise.resolve({ok:false,json:async()=>({error:'FFADO readback mismatch'})});}
    value=body.value;
    return Promise.resolve({ok:true,json:async()=>({ok:true,value})});
  }
  assert.equal(url,'/api/bus-routing');
  return Promise.resolve({ok:true,json:async()=>snapshot()});
};
const context=vm.createContext({document:{getElementById:id=>els[id],createElement:tag=>new Element(tag),addEventListener(){}},window:{activeFfadoDevice:'0001f2000007b2ca'},fetch:fetchFake,performance:{now:()=>0}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../ffado_webmixer/assets/static/routing.js'),'utf8'),context);
const flush=async()=>{for(let i=0;i<25;i++) await Promise.resolve();};
(async()=>{
  context.window.configureRouting({bus_routing:true,matrix:{available:true},fader:{writable:true}});
  els.routingButton.click();await flush();
  assert.equal(els.routingPhonesAssignment.hidden,false);
  assert.equal(els.routingPhonesSelect.value,'1');
  assert.equal(els.routingPhonesSelect.children.length,3);
  els.routingPhonesSelect.value='6';
  els.routingPhonesSelect.emit('change');await flush();
  assert.equal(writes.length,1);
  assert.equal(writes[0].url,'/api/phones-assignment');
  assert.equal(writes[0].body.value,6);
  assert.equal(els.routingPhonesSelect.value,'6');
  assert.equal(els.routingPhonesSelect.disabled,false);
  assert.equal(snapshot().buses[0].value,6,'Phones selection must not rewrite mix-bus routing');
  shouldFail=true;
  els.routingPhonesSelect.value='0';els.routingPhonesSelect.emit('change');await flush();
  assert.equal(value,6,'failed write must preserve hardware state');
  assert.equal(els.routingPhonesSelect.value,'6','failed write must restore hardware readback');
  hasPhones=false;
  els.routingRefresh.click();await flush();
  assert.equal(els.routingPhonesAssignment.hidden,true,'no endpoint means no Phones dropdown');
  console.log('MOTU Phones UI: select, FFADO readback, failed write and missing endpoint passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
