/* Offline DOM + polling regression. Node is not required by the app runtime. */
const assert = require('node:assert/strict');
const PeakDisplay = require('../src/ffado_webmixer/assets/static/peak-metering.js');
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
  '0':peak('Mixer/In:01',0.8),
  '1':peak('Mixer/In:02',0.10),
  '4':peak('Mixer/In:05',0.95,true),
};
display.render({channels},1000);
assert.equal(mono.meter.hidden,false);
assert.equal(stereo.meter.hidden,false);
assert.equal(noReading.meter.hidden,true);
assert.equal(mono.lanes.left.bar.style.clipPath,'inset(20.00% 0 0 0)');
assert.equal(stereo.lanes.left.bar.style.clipPath,'inset(90.00% 0 0 0)');
assert.equal(stereo.lanes.right.bar.style.clipPath,'inset(5.00% 0 0 0)');
assert(stereo.lanes.right.cls.has('clipping'));
assert(!stereo.lanes.left.cls.has('clipping'));
assert(stereo.meter.title.includes('Left · Mixer/In:02'));
assert(stereo.meter.title.includes('Right · Mixer/In:05'));
assert(stereo.meter.title.includes('not post-fader'));
assert(stereo.meter.label.includes('not measured post-fader'));

// Individual stereo peak/clip holds do not merge the channels.
channels={...channels, '1':peak('Mixer/In:02',0.50),'4':peak('Mixer/In:05',0.05)};
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

// Full-scale color coordinates: the visible fill changes but the gradient
// remains fixed to the ENTIRE lane. A half-scale reading must not inherit
// its own red/yellow top; the CSS positions those bands near track top.
for (const [level, expectedClip] of [[0,'100.00'],[0.5,'50.00'],
  [0.89,'11.00'],[0.93,'7.00'],[0.99,'1.00'],[1,'0.00']]) {
  display.render({channels:{'0':peak('Mixer/In:01',level)}},5000+level);
  assert.equal(mono.lanes.left.bar.style.clipPath,
    `inset(${expectedClip}% 0 0 0)`, `wrong full-track clipping at ${level}`);
}

// Missing Right never silently copies Left or shows an artificial stereo peak.
delete channels['4'];
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
other.render({channels:{'7':peak('Mixer/In:08',0.25),'2':peak('Mixer/In:03',0.75)}},123);
assert.equal(reverse.lanes.left.bar.style.clipPath,'inset(75.00% 0 0 0)');
assert.equal(reverse.lanes.right.bar.style.clipPath,'inset(25.00% 0 0 0)');

// Real API contract: /api/state uses padded "ch/00" ... "ch/17" strip IDs,
// whereas /api/peaks.channels JSON keys are decimal "0" ... "17".
// The previous UI regression test inadvertently padded both sides, allowing
// channels 0-9 to stay hidden on real DICE devices (as seen on Saffire PRO 26).
const allStrips=Array.from({length:18},(_,i)=>fakeStrip(`ch/${String(i).padStart(2,'0')}`));
const allRows=makeRow(...allStrips);
const allDisplay=new PeakDisplay(allRows,'unit-a');
const allChannels=Object.fromEntries(Array.from({length:18},(_,i)=>[
  String(i), peak(`Mixer/In:${String(i+1).padStart(2,'0')}`,(i+1)/20)
]));
allDisplay.render({channels:allChannels},1500);
allStrips.forEach((strip,i)=>{
  assert.equal(strip.meter.hidden,false,`strip ${i} (index ${String(i).padStart(2,'0')}) should be metered`);
  assert.equal(strip.lanes.left.bar.style.clipPath,`inset(${(100-(i+1)*5).toFixed(2)}% 0 0 0)`,`channel ${i} mapped incorrectly`);
});
// A missing destination must still leave only that strip unmetered, never
// borrow the peak of another channel or a similarly named router source.
delete allChannels['5'];
allDisplay.render({channels:allChannels},1700);
assert(allStrips[5].meter.hidden);
assert(!allStrips[4].meter.hidden && !allStrips[6].meter.hidden);
const invalid=fakeStrip('ch/not-a-number');
new PeakDisplay(makeRow(invalid),'unit-a').render({channels:allChannels},1900);
assert(invalid.meter.hidden);
// Explicit cross-language fixture generated by the actual Python backend.
// This runs from the Python unittest below as well as standalone with node.
if (process.env.FFADO_BACKEND_PEAK_JSON) {
  const backend = JSON.parse(process.env.FFADO_BACKEND_PEAK_JSON);
  const strips=Array.from({length:18},(_,i)=>fakeStrip(`ch/${String(i).padStart(2,'0')}`));
  new PeakDisplay(makeRow(...strips),backend.guid).render(backend,2000);
  strips.forEach((strip,i)=>{
    const item=backend.channels[String(i)];
    assert.equal(strip.meter.hidden,!item,`backend/UI disagrees at channel ${i}`);
    if (item) assert.equal(strip.lanes.left.bar.style.clipPath,`inset(${((1-item.level)*100).toFixed(2)}% 0 0 0)`);
  });
}

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
  resolveOld({ok:true,json:async()=>({available:true,guid:'unit-a',channels:{'0':peak('Mixer/In:01',1)}})});
  await new Promise(setImmediate);
  assert(mono.meter.hidden);
  let wrong;
  const mismatched=new PeakDisplay(row,'unit-a',async()=>({ok:true,json:async()=>({available:true,guid:'unit-b',channels:{'0':peak('Mixer/In:01',1)}})}));
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
