/* Offline DOM + polling regression. Node is not required by the app runtime. */
const assert = require('node:assert/strict');
const PeakDisplay = require('../ffado_webmixer/assets/static/peak-metering.js');
function fakeLane(side) {
  const bar={style:{}}, hold={style:{}}, cls=new Set();
  return {side,hidden:false,title:'',bar,hold,cls,
    classList:{toggle:(name,v)=>v?cls.add(name):cls.delete(name),remove:name=>cls.delete(name)},
    querySelector:sel=>sel==='.peak-bar'?bar:sel==='.peak-hold'?hold:null};
}
function fakeStrip(id, partner) {
  const lanes = {left: fakeLane('left')};
  if (partner) lanes.right=fakeLane('right');
  const cls=new Set();
  const meter={hidden:true, title:'', onclick:null, label:'',
    classList:{toggle:(name,v)=>v?cls.add(name):cls.delete(name)},
    setAttribute:(attr,text)=>{if(attr==='aria-label') meter.label=text},
    querySelector:sel=>{const match=sel.match(/^\.peak-lane\[data-side="(left|right)"\]$/);return match?lanes[match[1]]:null;}};
  return {dataset:{id,...(partner?{partner}:{})}, lanes, meter, cls,
    querySelector:sel=>sel==='.peak-meter'?meter:null};
}
function makeRow(...strips) { return {querySelectorAll:sel=>sel==='.strip'?strips:
  sel==='.peak-meter'?strips.map(x=>x.meter):[]}; }
function peak(destination, level, near=false) {
  return {destination,level, db:level?20*Math.log10(level):null,near_full_scale:near};
}
const mono=fakeStrip('ch/00');
const stereo=fakeStrip('ch/01','ch/04'); // arbitrary pair Left=2, Right=5
const noReading=fakeStrip('ch/09');
const row=makeRow(mono,stereo,noReading);
const display=new PeakDisplay(row,'unit-a');
let channels={
  '00':peak('Mixer/In:01',0.8),
  '01':peak('Mixer/In:02',0.10),
  '04':peak('Mixer/In:05',0.95,true),
};
display.render({channels},1000);
assert.equal(mono.meter.hidden,false);
assert.equal(stereo.meter.hidden,false);
assert.equal(noReading.meter.hidden,true);
assert.equal(mono.lanes.left.bar.style.height,'80.00%');
assert.equal(stereo.lanes.left.bar.style.height,'10.00%');
assert.equal(stereo.lanes.right.bar.style.height,'95.00%');
assert(stereo.lanes.right.cls.has('clipping'));
assert(!stereo.lanes.left.cls.has('clipping'));
assert(stereo.meter.title.includes('Left · Mixer/In:02'));
assert(stereo.meter.title.includes('Right · Mixer/In:05'));
assert(stereo.meter.title.includes('not post-fader'));
assert(stereo.meter.label.includes('not measured post-fader'));

// Individual stereo peak/clip holds do not merge the channels.
channels={...channels, '01':peak('Mixer/In:02',0.50),'04':peak('Mixer/In:05',0.05)};
display.render({channels},1300);
assert.equal(stereo.lanes.left.hold.style.bottom,'50.00%');
assert.equal(stereo.lanes.right.hold.style.bottom,'95.00%');
assert(stereo.lanes.right.cls.has('clipping'));
display.render({channels},2700);
assert.equal(stereo.lanes.right.hold.style.bottom,'5.00%');
assert(stereo.lanes.right.cls.has('clipping'));
stereo.meter.onclick();
assert(!stereo.lanes.right.cls.has('clipping'));
assert.equal(stereo.lanes.left.hold.style.bottom,'0%');
assert.equal(stereo.lanes.right.hold.style.bottom,'0%');
display.render({channels},5300);
assert(!stereo.lanes.right.cls.has('clipping'));

// Missing Right never silently copies Left or shows an artificial stereo peak.
delete channels['04'];
display.render({channels},5400);
assert(!stereo.meter.hidden);
assert(stereo.lanes.right.hidden);
assert(!stereo.lanes.left.hidden);
assert(!stereo.meter.title.includes('Mixer/In:05'));
assert(!Array.from(display.states.keys()).some(k=>k.includes('Mixer/In:05')));
// When the hardware has no mapped channel data, all meters disappear.
display.render({channels:{}},5500);
assert(mono.meter.hidden && stereo.meter.hidden && noReading.meter.hidden);

// Stereo directions follow user-selected Left/Right, not numeric input order.
const reverse=fakeStrip('ch/07','ch/02');
const other=new PeakDisplay(makeRow(reverse),'unit-a');
other.render({channels:{'07':peak('Mixer/In:08',0.25),'02':peak('Mixer/In:03',0.75)}},123);
assert.equal(reverse.lanes.left.bar.style.height,'25.00%');
assert.equal(reverse.lanes.right.bar.style.height,'75.00%');

// Unsupported device: the live API must not conjure fake strip levels.
const globalDocument=global.document;
const globalPerformance=global.performance;
const globalCustomEvent=global.CustomEvent;
const listeners=new Map();
global.document={hidden:false,
  addEventListener:(name,fn)=>listeners.set(name,fn),
  removeEventListener:name=>listeners.delete(name),
  dispatchEvent:()=>{}};
global.performance={now:()=>1200};
global.CustomEvent=class { constructor(name,props){this.type=name;this.detail=props.detail;} };
async function liveTests() {
  let fetchCalls=0;
  const unsupported=new PeakDisplay(row,'unit-a',async () => {
    ++fetchCalls;
    return {ok:true,json:async()=>({available:false,channels:{},guid:'unit-a'})};
  });
  unsupported.start();
  await new Promise(setImmediate);
  assert.equal(fetchCalls,1);
  assert(unsupported.stopped);
  assert(mono.meter.hidden && stereo.meter.hidden);
  // A response from an earlier poll (or changed device) must never render.
  let resolveOld;
  const stale=new PeakDisplay(row,'unit-a',() => new Promise(r=>resolveOld=r));
  stale.start(); stale.stop();
  resolveOld({ok:true,json:async()=>({available:true,guid:'unit-a',channels:{'00':peak('Mixer/In:01',1)}})});
  await new Promise(setImmediate);
  assert(mono.meter.hidden);
  let wrong;
  const mismatched=new PeakDisplay(row,'unit-a',async()=>({ok:true,json:async()=>({available:true,guid:'unit-b',channels:{'00':peak('Mixer/In:01',1)}})}));
  mismatched.start();
  await new Promise(setImmediate);
  assert(mono.meter.hidden);
  mismatched.stop();
  global.document=globalDocument;
  global.performance=globalPerformance;
  global.CustomEvent=globalCustomEvent;
}
liveTests().then(()=>console.log('peak display: mono and independent stereo lanes, arbitrary pairs, holds, absent data, device isolation passed'))
  .catch(err=>{console.error(err);process.exitCode=1;});
