/* Run directly with node; the app itself needs no Node.js runtime. */
const assert = require('node:assert/strict');
const PeakDisplay = require('../ffado_webmixer/assets/static/peak-metering.js');
function fakeStrip(id, partner) {
  const bar={style:{}},hold={style:{}},cls=new Set();
  const meter={hidden:true, title:'', onclick:null,
    classList:{toggle:(name,v)=>v?cls.add(name):cls.delete(name), remove:name=>cls.delete(name)},
    querySelector:sel=>sel==='.peak-bar'?bar:sel==='.peak-hold'?hold:null};
  return {dataset:{id,...(partner?{partner}:{})},
    querySelector:sel=>sel==='.peak-meter'?meter:null,
    bar, hold, meter, cls};
}
const a=fakeStrip('ch/00');
const b=fakeStrip('ch/02','ch/03');
const row={querySelectorAll:sel=>sel==='.strip'?[a,b]:[a.meter,b.meter]};
const display=new PeakDisplay(row,'test-guid');
const data={channels:{
 '00':{destination:'Mixer/In:01',level:0.8, db:-1.93,near_full_scale:false},
 '02':{destination:'Mixer/In:03',level:0.1, db:-20,near_full_scale:false},
 '03':{destination:'Mixer/In:04',level:0.95, db:-0.44,near_full_scale:true}
}};
display.render(data,1000);
assert.equal(a.meter.hidden,false);
assert.equal(b.bar.style.height,'95.00%'); // stereo displays louder side
assert(b.cls.has('clipping'));
assert(b.meter.title.includes('Mixer/In:03 / Mixer/In:04'));
data.channels['03']={...data.channels['03'],level:0.05,db:-26,near_full_scale:false};
data.channels['02']={...data.channels['02'],level:0.1,db:-20};
display.render(data,1300);
assert.equal(b.hold.style.bottom,'95.00%');
assert(b.cls.has('clipping'));
display.render(data,2700);
assert.equal(b.hold.style.bottom,'10.00%'); // hold expired
assert(b.cls.has('clipping'));              // separate clip hold
b.meter.onclick();
assert(!b.cls.has('clipping'));
display.render(data,5300);
assert(!b.cls.has('clipping'));
// Incompatible data must hide old meter; a renamed display cannot inherit a peak.
display.render({channels:{}},5500);
assert(a.meter.hidden && b.meter.hidden);
console.log('peak display: stereo, hold, clip, reset and missing-destination tests passed');
