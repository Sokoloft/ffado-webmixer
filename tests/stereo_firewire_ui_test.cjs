/* Native routing.js L/R helper: no writes without an explicit, confirmed click. */
const fs=require('node:fs'), path=require('node:path'), vm=require('node:vm'), assert=require('node:assert/strict');
class Classes { constructor(){this.v=new Set();} add(x){this.v.add(x);} remove(x){this.v.delete(x);} contains(x){return this.v.has(x);} toggle(x,on){if(on===undefined?!this.v.has(x):on)this.v.add(x);else this.v.delete(x);} }
class Node { constructor(){this.children=[];this.listeners={};this.classList=new Classes();this.style={};this.attrs={};this.value='';this.hidden=false;this.disabled=false;this.dataset={};this.textContent='';}
  set className(s){this.classList=new Classes();s.split(/\s+/).forEach(x=>x&&this.classList.add(x));} appendChild(e){this.children.push(e);return e;} append(...es){es.forEach(e=>this.appendChild(e));} replaceChildren(...es){this.children=[];this.append(...es);}
  setAttribute(k,v){this.attrs[k]=String(v);} addEventListener(k,f){(this.listeners[k]??=[]).push(f);} click(){(this.listeners.click||[]).forEach(f=>f({preventDefault(){}}));} focus(){} querySelectorAll(q){let result=[];const walk=e=>{for(const x of e.children){if(x.classList.contains(q.slice(1)))result.push(x);walk(x);}};walk(this);return result;} querySelector(q){return this.querySelectorAll(q)[0]||null;}
}
const names='routerbox routingOverlay routingButton routingBusTab routingMatrixTab routingCrossbarTab routingBus routingMatrix routingCrossbar routingHint routingGrid routingEditor routingDb routingDbLabel routingKnob routingPreset routingPresetLabel routingRefresh routingClose routingDialog routingCellLabel routingLevel routingLevelLabel routingApply routingSilence routingUnity routingBusGrid routingPhonesAssignment routingPhonesSelect routingDestinations routingStereoFirewire routingStereoSource routingStereoBus routingStereoApply'.split(' ');
const nodes=Object.fromEntries(names.map(n=>[n,new Node()]));nodes.routingOverlay.hidden=true;
const needle=new Node();needle.className='routing-knob-needle';nodes.routingKnob.appendChild(needle);
const posts=[];let yes=true;let stripRefresh=0;
const matrix={mode:'dice_db',gain_scale:{min_db:-60,max_db:6},inputs:['Mixer/In:01','Mixer/In:02'],outputs:['Mixer/Out:01','Mixer/Out:02'],values:[[99,0],[0,99]],db_values:[[-0.4,null],[null,-0.4]]};
const helper={available:true,pairs:[{left_source:'1394/In:01',right_source:'1394/In:02',left_input:0,right_input:1,label:'Firewire 1+2'}],buses:[{left:0,label:'Bus 1+2'}]};
const fetchFake=(url,opts)=>{
  if(opts?.method==='POST') {posts.push({url,opts,body:JSON.parse(opts.body)});return Promise.resolve({ok:true,json:async()=>({ok:true,pair:'Firewire 1+2',bus:0})});}
  return Promise.resolve({ok:true,json:async()=>url==='/api/stereo-firewire'?helper:matrix});
};
const ctx=vm.createContext({document:{getElementById:id=>nodes[id],createElement:()=>new Node(),addEventListener(){}},
 window:{activeFfadoDevice:'0011223344556677',confirm(){return yes;},refreshMatrixStrips(){stripRefresh++;}},fetch:fetchFake,
 shortFfadoLabel:s=>s,performance:{now:()=>0},setTimeout(){return 1;},clearTimeout(){}});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/ffado_webmixer/assets/static/routing.js'),'utf8'),ctx);
const flush=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
(async()=>{
 ctx.window.configureRouting({matrix:{available:true},fader:{writable:true}});
 nodes.routingButton.click();await flush();
 assert.equal(nodes.routingStereoFirewire.hidden,false);
 assert.equal(nodes.routingStereoSource.children[0].textContent,'Firewire 1+2');
 assert.equal(nodes.routingStereoBus.children[0].textContent,'Bus 1+2');
 assert.equal(posts.length,0,'loading/linking must not rewrite matrix');
 nodes.routingStereoSource.value='1394/In:01'; nodes.routingStereoBus.value='0';
 yes=false;nodes.routingStereoApply.click();await flush();
 assert.equal(posts.length,0,'cancelled confirmation leaves hardware alone');
 yes=true;nodes.routingStereoApply.click();await flush();
 assert.equal(posts.length,1);
 assert.equal(posts[0].url,'/api/stereo-firewire');
 assert.equal(posts[0].body.left_source,'1394/In:01');
 assert.equal(posts[0].body.bus,0);
 assert.equal(posts[0].opts.headers['X-FFADO-Device'],'0011223344556677');
 assert.equal(stripRefresh,1);
 assert.equal(nodes.routingStereoApply.disabled,false);
 console.log('Stereo FireWire UI helper: explicit confirmation, source/bus mapping, hardware refresh passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
