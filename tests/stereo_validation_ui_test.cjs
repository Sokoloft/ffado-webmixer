// Behavioral checks for rejected requests, busy controls, bus switching.
const fs = require('fs');
const vm = require('vm');
const assert = require('node:assert/strict');
const path = require('path');
const src = fs.readFileSync(path.join(__dirname, '../ffado_webmixer/assets/static/index.js'), 'utf8');
const block = src.slice(src.indexOf('var CHAIN_LINK_SVG'), src.indexOf('var PIN_SVG')) + '\n' +
  src.slice(src.indexOf('var pendingStereoLeft = null;'), src.indexOf('function startDrag(el, e)')) + '\n' +
  src.slice(src.indexOf('// Each mono strip gets its own link button'), src.indexOf('var loadToken ='));
const ids = ['ch/00','ch/01','ch/02','ch/03','ch/04','ch/05','ch/06','ch/07'];
const cls = () => {
  const values = new Set();
  return {toggle(key, value) { if (value) values.add(key); else values.delete(key); },
    remove(key) {values.delete(key);}, contains(key) { return values.has(key); }};
};
const strips = ids.map(id => ({dataset:{id}, classList:cls(), buttons:[], appendChild(b) {this.buttons.push(b);}}));
const row = {querySelectorAll(selector) {
  if (selector === ':scope > .strip') return strips;
  if (selector === '.strip.stereo-pending') return strips.filter(s => s.classList.contains('stereo-pending'));
  if (selector === '.strip > .link-toggle' || selector === '.strip .link-toggle, .strip.stereo .unlink') return strips.flatMap(s=>s.buttons);
  throw Error('Unexpected selector: ' + selector);
}};
let reply; const submitted=[], toasts=[]; let refreshes=0;
const ctx=vm.createContext({
  currentMix:0, lastStripMix:0, pendingStereoMix:0,
  lastStripState:Object.fromEntries(ids.map(id=>[id,{}])), row,
  toast(m) { toasts.push(m); }, loadMix() { refreshes++; return Promise.resolve(); },
  post(url, body) { submitted.push({url,body}); return new Promise(resolve=>{reply=resolve;}); },
  document:{createElement() {return {classList:cls(), attributes:{}, addEventListener(name,fn){this[name]=fn;},
    setAttribute(key,value){this.attributes[key]=value;},remove(){for (const s of strips) s.buttons=s.buttons.filter(b=>b!==this);}};}}
});
vm.runInContext(block,ctx);
const click = id => strips.find(s=>s.dataset.id===id).buttons[0].click();
const flush = async()=>{for (let i=0;i<5;i++) await new Promise(resolve=>setImmediate(resolve));};
(async()=>{
  ctx.renderLinkButtons(ctx.lastStripState);
  // First click is Left; second is Right. While waiting, all buttons are disabled.
  click('ch/01'); click('ch/04');
  assert.equal(submitted.length,1);
  assert.equal(ctx.stereoLinkBusy,true);
  assert(strips.every(s=>s.buttons[0].disabled));
  click('ch/02'); click('ch/03');
  assert.equal(submitted.length,1,'race prevention must not send another link');
  reply({ok:false,json:async()=>({error:'ch/01 already linked elsewhere'})});
  await flush();
  assert.equal(ctx.stereoLinkBusy,false);
  assert.equal(ctx.pendingStereoLeft,null);
  assert(toasts.some(v=>v.includes('already linked elsewhere')));
  assert.equal(refreshes,1,'rejected link refreshes server state');
  assert(strips.every(s=>!s.buttons[0].disabled));
  // Mark channel 3 as paired by another client, reject it before sending.
  ctx.lastStripState['ch/03'].partner_of='ch/02';
  click('ch/03');
  assert.equal(submitted.length,1);
  assert.equal(ctx.pendingStereoLeft,null);
  // Simulate old bus still displayed after user selects a new bus.
  ctx.currentMix=1;
  click('ch/01');
  assert.equal(ctx.pendingStereoLeft,null);
  ctx.currentMix=0;
  click('ch/07'); click('ch/02');
  assert.equal(submitted.length,2);
  assert.equal(submitted[1].body.dragged,'ch/07');
  assert.equal(submitted[1].body.target,'ch/02');
  // Switch bus during an in-flight request: late completion must not clear
  // the new bus state or re-render the wrong bus.
  ctx.currentMix=1;
  ctx.pendingStereoMix=1;
  reply({ok:true,json:async()=>({ok:true})});
  await flush();
  assert.equal(ctx.currentMix,1);
  assert.equal(refreshes,2,'rejected stale UI refresh only; late link did not refresh new bus');
  ctx.currentMix=0;
  // Unlink must handle non-200 HTTP status and restore enabled controls.
  const p=ctx.unlinkStrip('ch/01');
  assert(ctx.stereoLinkBusy);
  assert.equal(submitted.length,3);
  reply({ok:false,json:async()=>({error:'This channel is not linked on this bus'})});
  await p;
  assert.equal(ctx.stereoLinkBusy,false);
  assert(toasts.some(t=>t.includes("Couldn't unlink:")));
  console.log('Stereo validation UI: busy lock, conflict/error recovery, stale bus, arbitrary order passed');
})().catch(err=>{console.error(err);process.exit(1)});
