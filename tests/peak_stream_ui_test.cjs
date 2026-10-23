/* Confirm EventSource receives live peaks, avoids duplicate HTTP polling,
 * stays per-device, and falls back if the live stream is not supported. */
const assert = require('node:assert/strict');
const PeakDisplay = require('../src/ffado_webmixer/assets/static/peak-metering.js');
const listeners = new Map();
let lastEvent;
global.document = { hidden: false,
  addEventListener:(k,f)=>listeners.set(k,f),
  removeEventListener:k=>listeners.delete(k),
  dispatchEvent:e=>{lastEvent=e} };
global.CustomEvent=class { constructor(type,init){this.type=type;this.detail=init.detail} };
const bar={style:{}}, hold={style:{}}, cls=new Set();
const lane={hidden:false,classList:{toggle:(k,v)=>v?cls.add(k):cls.delete(k),remove:k=>cls.delete(k)},
  querySelector:s=>s==='.peak-bar'?bar:s==='.peak-hold'?hold:null};
const meter={hidden:true, classList:{toggle:()=>{}}, setAttribute:()=>{},
  querySelector:s=>s.includes('data-side="left"')?lane:null};
const strip={dataset:{id:'ch/00'}, querySelector:s=>s==='.peak-meter'?meter:null};
const row={querySelectorAll:s=>s==='.strip'?[strip]:s==='.peak-meter'?[meter]:[]};
let streams=[];
global.EventSource=class {
  constructor(url){this.url=url;this.closed=false;streams.push(this)}
  close(){this.closed=true}
};
let fetched=0;
const fetcher=async () => { fetched++; return {ok:true,json:async()=>({guid:'aaaaaaaaaaaaaaaa',available:true,
  channels:{'0':{destination:'Mixer/In:01',level:.25,db:-12.04,near_full_scale:false}}})} };
async function run(){
  const d=new PeakDisplay(row,'aaaaaaaaaaaaaaaa',fetcher);
  d.start();
  assert.equal(streams.length,1);
  assert.equal(streams[0].url,'/api/peak-stream');
  assert.equal(fetched,0);
  streams[0].onmessage({data:JSON.stringify({available:true,guid:'aaaaaaaaaaaaaaaa',
    channels:{'0':{destination:'Mixer/In:01',level:.75,db:-2.5,near_full_scale:false}}})});
  assert.equal(bar.style.clipPath,'inset(25.00% 0 0 0)');
  assert.equal(lastEvent.type,'ffado-peaks');
  assert.equal(fetched,0);
  // Hidden browsers unsubscribe to prevent wasteful FireWire polling.
  document.hidden=true;
  listeners.get('visibilitychange')();
  assert(streams[0].closed);
  assert(meter.hidden);
  document.hidden=false;
  listeners.get('visibilitychange')();
  assert.equal(streams.length,2);
  // Broken stream falls back to existing JSON polling, without parallel SSE.
  streams[1].onerror();
  await new Promise(resolve=>setTimeout(resolve,35));
  assert(streams[1].closed);
  assert(fetched>=1);
  d.stop();
  assert(meter.hidden);
  // Stale frames from a previously closed stream cannot change device state.
  const before=bar.style.clipPath;
  streams[0].onmessage({data:JSON.stringify({available:true,guid:'aaaaaaaaaaaaaaaa',
    channels:{'0':{destination:'Mixer/In:01',level:1,db:0,near_full_scale:true}}})});
  assert.equal(bar.style.clipPath,before);
  const mismatch=new PeakDisplay(row,'aaaaaaaaaaaaaaaa',fetcher);
  mismatch.start();
  streams.at(-1).onmessage({data:JSON.stringify({available:true,guid:'bbbbbbbbbbbbbbbb',
    channels:{'0':{destination:'Mixer/In:01',level:1,db:0,near_full_scale:true}}})});
  assert(mismatch.stopped);
  assert(meter.hidden);
  console.log('peak SSE: shared stream path, samples, hidden tab, fallback, and GUID guard passed');
}
run().catch(e=>{console.error(e);process.exitCode=1});
