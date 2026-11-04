/* Exercise the actual routing.js matrix UI with a lightweight DOM, no npm deps. */
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
    this.tag=tag; this.children=[]; this.listeners={}; this.attrs={}; this.style={};
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
  focus() {}
  setPointerCapture(x) {this.pointerCapture=x;}
  querySelectorAll(q) {
    if (!q.startsWith('.')) throw Error('Unrecognized selector '+q);
    const className=q.slice(1), result=[];
    const walk = el => {for(const child of el.children) {if(child.classList.contains(className))result.push(child);walk(child);}};
    walk(this);return result;
  }
  querySelector(q) {return this.querySelectorAll(q)[0] || null;}
}
const ids='routerbox routingOverlay routingButton routingBusTab routingMatrixTab routingCrossbarTab routingBus routingMatrix routingCrossbar routingHint routingGrid routingEditor routingDb routingDbLabel routingKnob routingPreset routingPresetLabel routingRefresh routingClose routingDialog routingCellLabel routingLevel routingLevelLabel routingApply routingSilence routingUnity routingBusGrid routingPhonesAssignment routingPhonesSelect routingDestinations'.split(' ');
const elements=Object.fromEntries(ids.map(id=>[id,new Element()]));
elements.routingKnob.appendChild(Object.assign(new Element('span'),{className:'routing-knob-needle'}));
elements.routingGrid.className='grid';
elements.routingOverlay.hidden=true;
let nextTimer=0;const timers=new Map();
const setTimeoutFake=fn=>{const t=++nextTimer;timers.set(t,fn);return t;};
const clearTimeoutFake=t=>timers.delete(t);
const flushTimers=()=>{for(const [id,fn] of [...timers]){if(timers.delete(id))fn();}};
let matrix={mode:'dice_db',gain_scale:{min_db:-60,max_db:6},inputs:['In 1','In 2'],outputs:['Out 1','Out 2'],values:[[99,0],[0,99]],db_values:[[-0.4,null],[null,-0.4]]};
const posts=[];let fail=false, held=null, heldReads=null, refreshStrips=0;
const fetchFake=(url, options)=>{
  if (!options || options.method !== 'POST') {
    const snapshot=JSON.parse(JSON.stringify(matrix));
    if (heldReads) return new Promise(resolve=>heldReads.push(()=>resolve({ok:true,json:async()=>snapshot})));
    return Promise.resolve({ok:true,json:async()=>snapshot});
  }
  const payload=JSON.parse(options.body);posts.push(payload);
  return new Promise(resolve=>{
    const answer=()=>{
      if (fail) {fail=false;resolve({ok:false,json:async()=>({error:'Hardware write failed'})});return;}
      if (matrix.mode === 'percent') {
        matrix.values[payload.input][payload.output]=payload.value;
        resolve({ok:true,json:async()=>({value:payload.value})});
        return;
      }
      matrix.db_values[payload.input][payload.output]=payload.db;
      const gain=payload.db===null?0:Math.max(1,Math.round((payload.db+60)*100/66));
      matrix.values[payload.input][payload.output]=gain;
      resolve({ok:true,json:async()=>({value:gain,db:payload.db})});
    };
    if (held) held.push(answer);else answer();
  });
};
const ctx=vm.createContext({document:{getElementById:id=>elements[id],createElement:tag=>new Element(tag),addEventListener(){}},
  window:{activeFfadoDevice:'0011223344556677',refreshMatrixStrips:()=>refreshStrips++},
  fetch:fetchFake,setTimeout:setTimeoutFake,clearTimeout:clearTimeoutFake,performance:{now:()=>10}});
const js=fs.readFileSync(path.join(__dirname,'../src/ffado_webmixer/assets/static/routing.js'),'utf8');
ctx.shortFfadoLabel = text => text; // UI label helper; tests target matrix interactions.
vm.runInContext(js,ctx);
const flush=async()=>{for(let i=0;i<24;i++)await Promise.resolve();};
const cells=()=>elements.routingGrid.querySelectorAll('.matrix-cell-control');
const value=c=>c.querySelector('.matrix-cell-value').textContent;
const event=(x={})=>({preventDefault(){this.prevented=true;}, ...x});
(async()=>{
  ctx.window.configureRouting({matrix:{available:true},fader:{writable:true}});
  elements.routingButton.click();await flush();
  assert.equal(cells().length,4,'all hardware crosspoints should render inline knobs');
  assert.equal(value(cells()[0]),'-0.4 dB');
  assert.equal(cells()[0].getAttribute('role'),'slider');
  assert.match(cells()[0].getAttribute('aria-label'), /mixer volume/i);
  assert.doesNotMatch(cells()[0].getAttribute('aria-label'), /gain/i);
  assert.equal(cells()[0].getAttribute('aria-valuetext'),'-0.4 dB');
  assert.match(cells()[0].title,/drag/);
  // Clicking the knob keeps precise editing accessible.
  cells()[0].click();assert.equal(elements.routingEditor.hidden,false);
  assert.match(elements.routingCellLabel.textContent,/In 1.*Out 1/);
  // Drag up by 14px: preview +1.4 dB, with no network traffic until release.
  let first=cells()[0];
  first.emit('pointerdown',event({button:0,clientY:100,pointerId:7}));
  first.emit('pointermove',event({clientY:86,pointerId:7}));
  assert.equal(posts.length,0);
  assert.equal(value(first),'+1.0 dB');
  first.emit('pointerup',event({clientY:86,pointerId:7}));await flush();
  assert.equal(posts.length,1,'one drag emits one POST');
  assert.equal(posts[0].input,0);assert.equal(posts[0].output,0);assert.equal(posts[0].db,1);
  assert.equal(value(first),'+1.0 dB');assert.equal(refreshStrips,1);
  // Multiple wheel ticks become a single write on idle.
  first.emit('wheel',event({deltaY:1}));first.emit('wheel',event({deltaY:1}));
  assert.equal(posts.length,1);
  assert.equal(value(first),'+0.8 dB');
  flushTimers();await flush();
  assert.equal(posts.length,2);assert.equal(posts[1].db,0.8);
  // Keyboard fine/coarse increments and accessible value.
  first.emit('keydown',event({key:'ArrowUp',shiftKey:true}));
  assert.equal(value(first),'+1.8 dB');
  flushTimers();await flush();
  assert.equal(posts.length,3);assert.equal(posts[2].db,1.8);
  // Pointer cancellation never reaches the hardware.
  first.emit('pointerdown',event({button:0,clientY:100,pointerId:9}));
  first.emit('pointermove',event({clientY:50,pointerId:9}));
  first.emit('pointercancel',event({pointerId:9}));
  assert.equal(posts.length,3);assert.equal(value(first),'+1.8 dB');
  // A failed write rolls back preview, enables controls, and requests a reload.
  fail=true;first.emit('keydown',event({key:'m'}));flushTimers();await flush();
  assert.equal(posts.length,4);assert.equal(value(first),'+1.8 dB');
  await new Promise(resolve=>setImmediate(resolve));
  assert.match(elements.routingHint.textContent,/Could not set matrix level/);
  first=cells()[0];
  assert.equal(first.disabled,false);
  // Matrix controls must not write repeatedly while the device is busy.
  held=[];
  first.emit('keydown',event({key:'0'}));flushTimers();await flush();
  assert.equal(first.disabled,true);
  first.emit('keydown',event({key:'ArrowUp'}));
  assert.equal(posts.length,5);
  held.shift()();held=null;await flush();
  assert.equal(first.disabled,false);
  // A silent crosspoint can be activated with a keyboard preset, without
  // changing any other crosspoint (no implicit stereo-to-mono routing).
  const other=cells()[1];other.emit('keydown',event({key:'0'}));flushTimers();await flush();
  assert.equal(posts.length,6);assert.equal(posts[5].input,0);assert.equal(posts[5].output,1);
  assert.equal(matrix.db_values[1][0],null);
  assert.equal(matrix.db_values[1][1],-0.4);
  // Generic (non-dB) writable matrices get the same rotary interaction, in %.
  matrix={mode:'percent',inputs:['In 1'],outputs:['Out 1'],values:[[50]]};
  elements.routingRefresh.click();await flush();
  const percentCell=cells()[0];
  assert.equal(cells().length,1);
  assert.equal(value(percentCell),'50%');
  assert.equal(elements.routingKnob.hidden,true,'non-dB mode keeps the dedicated dB knob hidden');
  percentCell.emit('wheel',event({deltaY:-1}));flushTimers();await flush();
  assert.equal(posts.length,7);assert.equal(posts[6].value,51);
  assert.equal(value(percentCell),'51%');
  assert.equal(percentCell.getAttribute('aria-valuenow'),'51');
  // A GET that started before a rotary write must NOT overwrite readback.
  heldReads=[];
  elements.routingRefresh.click(); await flush();
  percentCell.emit('keydown',event({key:'ArrowUp'})); flushTimers(); await flush();
  assert.equal(posts.length,8);
  assert.equal(value(percentCell),'52%');
  assert.equal(cells()[0],percentCell,'pending old read must not replace editing knob');
  const releaseOldRead=heldReads.shift(); heldReads=null; releaseOldRead();await flush();
  assert.equal(value(cells()[0]),'52%','stale GET cannot replace new hardware value');
  // Double-click only stages unity, without a hardware write.
  const postCount=posts.length;
  cells()[0].emit('dblclick');
  assert.equal(posts.length,postCount);
  assert.equal(elements.routingLevel.value,100);
  // Ctrl-click toggles membership without staging a level change.
  matrix={mode:'dice_db',gain_scale:{min_db:-60,max_db:6},inputs:['In 1','In 2'],outputs:['Out 1','Out 2'],values:[[80,70],[60,50]],db_values:[[-10,-20],[-30,-40]]};
  elements.routingRefresh.click();await flush();
  let group=cells();const beforeGroup=posts.length;
  group[0].click();
  group[1].emit('pointerdown',event({button:0,ctrlKey:true,clientY:100,pointerId:20}));
  group[1].emit('click',event({ctrlKey:true}));
  assert.equal(posts.length,beforeGroup);
  assert.equal(group.filter(c=>c.classList.contains('route-selected')).length,2);
  assert.match(elements.routingCellLabel.textContent,/2 entries/);
  group[0].emit('wheel',event({deltaY:-1,shiftKey:true}));
  assert.equal(value(group[0]),'-9.0 dB');assert.equal(value(group[1]),'-19.0 dB');
  flushTimers();await flush();
  assert.equal(posts.length,beforeGroup+2);
  assert.equal(matrix.db_values[1][0],-30,'unselected crosspoints are untouched');
  // A canceled group drag restores every preview and writes nothing.
  group[0].emit('pointerdown',event({button:0,clientY:100,pointerId:21}));
  group[0].emit('pointermove',event({clientY:80,pointerId:21}));
  assert.equal(value(group[1]),'-17.0 dB');
  group[0].emit('pointercancel',event({pointerId:21}));
  assert.equal(value(group[0]),'-9.0 dB');assert.equal(value(group[1]),'-19.0 dB');
  assert.equal(posts.length,beforeGroup+2);
  // Exact Apply writes all selected entries, with one busy lock for the batch.
  elements.routingDb.value='-12';held=[];
  elements.routingApply.click();await flush();
  assert.equal(held.length,1);assert.equal(group[0].disabled,true);
  held.shift()();await flush();
  assert.equal(held.length,1);assert.equal(group[0].disabled,true);
  held.shift()();held=null;await flush();
  assert.equal(group[0].disabled,false);
  assert.equal(matrix.db_values[0][0],-12);assert.equal(matrix.db_values[0][1],-12);
  // Refresh preserves group membership, and Ctrl-click can remove an entry.
  elements.routingRefresh.click();await flush();group=cells();
  assert.equal(group.filter(c=>c.classList.contains('route-selected')).length,2);
  group[1].emit('click',event({ctrlKey:true}));
  assert.equal(group.filter(c=>c.classList.contains('route-selected')).length,1);
  // A touch long press adds a crosspoint; its trailing click cannot undo it.
  const touchDown=(cell,id)=>cell.emit('pointerdown',event({button:0,pointerType:'touch',clientX:50,clientY:100,pointerId:id}));
  const touchUp=(cell,id)=>cell.emit('pointerup',event({pointerId:id}));
  touchDown(group[2],30);
  group[2].emit('pointermove',event({clientX:52,clientY:101,pointerId:30}));
  flushTimers();touchUp(group[2],30);group[2].click();
  assert.equal(group[2].classList.contains('route-selected'),true);
  assert.equal(group[0].classList.contains('route-selected'),true);
  touchDown(group[2],31);flushTimers();touchUp(group[2],31);group[2].click();
  assert.equal(group[2].classList.contains('route-selected'),false,'long press toggles off too');
  // Short taps select immediately; movement cancels long press and drags.
  touchDown(group[3],32);touchUp(group[3],32);group[3].click();
  assert.equal(group.filter(c=>c.classList.contains('route-selected')).length,1);
  assert.equal(group[3].classList.contains('route-selected'),true);
  touchDown(group[3],33);
  group[3].emit('pointermove',event({clientX:50,clientY:80,pointerId:33}));
  flushTimers();assert.equal(value(group[3]),'-38.0 dB');
  group[3].emit('pointercancel',event({pointerId:33}));
  assert.equal(value(group[3]),'-40.0 dB');
  touchDown(group[0],34);elements.routingClose.click();flushTimers();
  assert.equal(group[0].classList.contains('route-selected'),false,'closing cancels long press');
  elements.routingButton.click();await flush();group=cells();
  // Percent matrices also support group adjustments and exact Apply.
  matrix={mode:'percent',inputs:['In 1'],outputs:['Out 1','Out 2'],values:[[25,50]]};
  elements.routingRefresh.click();await flush();group=cells();
  group[0].click();group[1].emit('click',event({ctrlKey:true}));
  group[0].emit('keydown',event({key:'ArrowUp'}));flushTimers();await flush();
  assert.deepEqual(matrix.values,[[26,51]]);
  elements.routingLevel.value=60;elements.routingLevel.emit('input');elements.routingApply.click();await flush();
  assert.deepEqual(matrix.values,[[60,60]]);
  // A later failure keeps earlier verified writes and reloads the rest.
  held=[];elements.routingLevel.value=70;elements.routingLevel.emit('input');elements.routingApply.click();await flush();
  held.shift()();await flush();fail=true;held.shift()();held=null;await flush();
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(matrix.values,[[70,60]]);
  assert.equal(value(cells()[0]),'70%');assert.equal(value(cells()[1]),'60%');
  assert.match(elements.routingHint.textContent,/Could not set matrix level/);
  console.log('Matrix-cell rotary UI: drag, wheel debounce, keyboard, readback, rollback, selection, isolated writes passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
