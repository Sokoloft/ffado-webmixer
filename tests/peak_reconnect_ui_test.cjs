/* Exercise meter transport recovery with a virtual clock and no network. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require.resolve('../src/ffado_webmixer/assets/static/peak-metering.js'), 'utf8');
const GUID = 'aaaaaaaaaaaaaaaa';
const frame = (level = .25, guid = GUID) => ({guid, available:true, channels:{
  '0':{destination:'Mixer/In:01', level, db:-12, near_full_scale:false}
}});
const response = (data = frame()) => ({ok:true, status:200, json:async()=>data});
const flush = async () => { for (let i = 0; i < 8; ++i) await Promise.resolve(); };

function harness(fetcher) {
  let now = 0, nextId = 0;
  const timers = new Map(), listeners = new Map(), streams = [], requests = [];
  const bar = {style:{}}, hold = {style:{}};
  const lane = {classList:{toggle(){}, remove(){}},
    querySelector:selector=>selector === '.peak-bar' ? bar : hold};
  const meter = {hidden:true, classList:{toggle(){}}, setAttribute(){}, querySelector:()=>lane};
  const strip = {dataset:{id:'ch/00'}, querySelector:()=>meter};
  const row = {querySelectorAll:selector=>selector === '.strip' ? [strip] : [meter]};
  const document = {hidden:false,
    addEventListener:(name, fn)=>listeners.set(name, fn),
    removeEventListener:name=>listeners.delete(name), dispatchEvent(){}};
  const state = {throwOnConnect:false};
  const context = vm.createContext({document, performance:{now:()=>now},
    CustomEvent:class {},
    setTimeout(fn, delay) { const id = ++nextId; timers.set(id, {fn, at:now + delay}); return id; },
    clearTimeout:id=>timers.delete(id),
    EventSource:class {
      constructor(url) {
        if (state.throwOnConnect) throw Error('connection setup failed');
        this.url = url; this.at = now; this.closed = false; streams.push(this);
      }
      close() { this.closed = true; }
    }
  });
  vm.runInContext(source, context);
  const display = new context.FFADOPeakDisplay(row, GUID, async url => {
    requests.push({url, at:now});
    return fetcher ? fetcher() : response();
  });
  async function advance(duration) {
    const end = now + duration;
    for (let steps = 0; ; ++steps) {
      assert(steps < 10000, 'transport created a timer loop');
      const next = [...timers].filter(([, timer])=>timer.at <= end)
        .sort((a,b)=>a[1].at - b[1].at || a[0] - b[0])[0];
      if (!next) break;
      timers.delete(next[0]); now = next[1].at; next[1].fn(); await flush();
    }
    now = end; await flush();
  }
  return {display, document, streams, requests, timers, bar, meter, state, context, advance,
    message(data = frame(), stream = streams.at(-1)) { stream.onmessage({data:JSON.stringify(data)}); },
    fail(stream = streams.at(-1)) { stream.onerror(); },
    visibility(hidden) { document.hidden = hidden; listeners.get('visibilitychange')?.(); }};
}

async function run() {
  {
    const h = harness(); h.display.start(); h.message(frame(.75));
    assert.equal(h.bar.style.clipPath, 'inset(25.00% 0 0 0)');
    h.fail(); await h.advance(0);
    assert(h.streams[0].closed); assert.equal(h.requests.length, 1);
    await h.advance(999); assert.equal(h.streams.length, 1);
    await h.advance(1); assert.equal(h.streams.length, 2);
    h.message(); const count = h.requests.length;
    await h.advance(1000); assert.equal(h.requests.length, count, 'recovered SSE cancels HTTP polling');
    h.message(frame(.5), h.streams[0]); h.fail(h.streams[0]);
    assert.equal(h.bar.style.clipPath, 'inset(75.00% 0 0 0)', 'closed streams cannot repaint');
    h.display.stop(); assert.equal(h.timers.size, 0);
  }
  {
    const h = harness(); h.display.start();
    for (const delay of [1000, 2000, 4000, 8000, 16000, 30000, 30000]) {
      const count = h.streams.length;
      h.fail(); h.fail(); // Duplicate errors must not schedule extra attempts.
      await h.advance(delay - 1); assert.equal(h.streams.length, count);
      await h.advance(1); assert.equal(h.streams.length, count + 1);
    }
    h.message(); h.fail();
    const count = h.streams.length;
    await h.advance(1000); assert.equal(h.streams.length, count + 1, 'a good frame resets backoff');
    h.display.stop();
  }
  {
    const h = harness(); h.display.start();
    await h.advance(3000); assert(h.streams[0].closed, 'silent connection hits watchdog');
    assert(h.requests.length > 0);
    await h.advance(1000); assert.equal(h.streams.length, 2, 'watchdog failures reconnect too');
    h.streams[1].onmessage({data:'invalid json'});
    await h.advance(2000); assert.equal(h.streams.length, 3);
    h.display.stop();
  }
  {
    const h = harness(); h.state.throwOnConnect = true; h.display.start();
    await h.advance(0); assert.equal(h.requests.length, 1, 'constructor failure still permits polling');
    h.state.throwOnConnect = false;
    await h.advance(1000); assert.equal(h.streams.length, 1);
    h.display.stop();
  }
  for (const action of ['stop', 'hide']) {
    const h = harness(); h.display.start(); h.fail(); await h.advance(0);
    if (action === 'stop') h.display.stop(); else h.visibility(true);
    const count = h.requests.length;
    assert.equal(h.timers.size, 0);
    await h.advance(60000);
    assert.equal(h.streams.length, 1); assert.equal(h.requests.length, count);
    if (action === 'hide') {
      h.visibility(false); assert.equal(h.streams.length, 2);
      h.display.stop();
    }
  }
  for (const finish of ['resolve', 'reject']) {
    let resolve, reject;
    const h = harness(()=>new Promise((yes,no)=>{ resolve = yes; reject = no; }));
    h.display.start(); h.fail(); await h.advance(0);
    await h.advance(1000); h.message(frame(.75));
    if (finish === 'resolve') resolve(response(frame(1))); else reject(Error('old request failed'));
    await flush();
    assert.equal(h.bar.style.clipPath, 'inset(25.00% 0 0 0)');
    await h.advance(1000); assert.equal(h.requests.length, 1, 'late polls cannot restart fallback');
    h.display.stop();
  }
  {
    let resolve;
    const h = harness(()=>new Promise(yes=>{ resolve = yes; }));
    h.display.start(); h.fail(); await h.advance(0); h.visibility(true);
    resolve(response(frame(1))); await flush();
    assert(h.meter.hidden); assert.equal(h.timers.size, 0);
    h.visibility(false); assert.equal(h.streams.length, 2); h.display.stop();
  }
  for (const status of [401, 403]) {
    const h = harness(async()=>({ok:false, status}));
    h.display.start(); h.fail(); await h.advance(0);
    assert(h.display.stopped); assert.equal(h.timers.size, 0);
    await h.advance(60000); assert.equal(h.streams.length, 1);
  }
  for (const data of [{available:false, channels:{}, guid:GUID}, frame(1, 'another-device')]) {
    const h = harness(async()=>response(data));
    h.display.start(); h.fail(); await h.advance(0);
    assert(h.display.stopped); assert.equal(h.timers.size, 0);
  }
  {
    const h = harness(); h.context.EventSource = undefined; h.display.start(); await flush();
    await h.advance(1000);
    assert.equal(h.streams.length, 0); assert(h.requests.length > 1);
    assert.equal(h.display.reconnectTimer, null); h.display.stop();
  }
  console.log('Peak reconnect: recovery, capped backoff, watchdog, cancellation, stale polls and access revocation passed');
}
run().catch(error=>{ console.error(error); process.exitCode = 1; });
