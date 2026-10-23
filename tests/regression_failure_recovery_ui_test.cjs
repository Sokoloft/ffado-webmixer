/* Release regression: failed saves do not block later saves, and canceled reads
 * cannot repaint a newer selection even when transport ignores AbortController.
 * This is deliberately an offline JS test: no browser, Flask or device needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/frontend-api.js'), 'utf8');
const queue = [];
const defer = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return {promise, resolve, reject};
};
const ctx = vm.createContext({
  window: {}, Promise, AbortController, Map,
  fetch(url, init) {
    const d = defer();
    queue.push({url, init, ...d});
    return d.promise;
  },
});
vm.runInContext(source, ctx);
const api = ctx.window.ffadoApi;
const ok = data => ({ok: true, status: 200, json: async () => data});
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

(async () => {
  // A read canceled by closing a panel may still finish on the network.
  const obsolete = api.latest('routing', '/api/router-old', {device: 'GUID-A'});
  const oldRequest = queue.at(-1);
  api.cancel('routing');
  assert.equal(oldRequest.init.signal.aborted, true);
  oldRequest.resolve(ok({source: 'OLD'})); // simulate an abort-ignoring transport
  assert.equal(await obsolete, null, 'canceled read must not update the routing view');

  // A response from an old device is obsolete even when it returns *after*
  // a new device's successful response.
  const wrongDevice = api.latest('routing', '/api/router-a', {device: 'GUID-A'});
  const a = queue.at(-1);
  const rightDevice = api.latest('routing', '/api/router-b', {device: 'GUID-B'});
  const b = queue.at(-1);
  b.resolve(ok({source: 'RIGHT'}));
  assert.equal((await rightDevice).source, 'RIGHT');
  a.reject(Error('late network failure'));
  assert.equal(await wrongDevice, null, 'old errors must not replace the newer view');
  assert.equal(b.init.headers['X-FFADO-Device'], 'GUID-B');

  // The failed first POST is not aborted, and its failure must not prevent
  // the next saved preference on that serial key from reaching the server.
  const first = api.serial('settings|GUID-A|theme', () =>
    api.request('/api/settings', {body: {theme: 'light'}, device: 'GUID-A'}));
  await flush();
  const firstPost = queue.at(-1);
  assert.equal(firstPost.url, '/api/settings');
  assert.equal(firstPost.init.signal, undefined, 'writes must not be abortable GETs');
  const second = api.serial('settings|GUID-A|theme', () =>
    api.request('/api/settings', {body: {theme: 'nordic'}, device: 'GUID-A'}));
  // Independent layout saves should not be delayed behind a theme write.
  const layout = api.serial('layout|GUID-B|0', () =>
    api.request('/api/layout?mix=0', {body: [], device: 'GUID-B'}));
  await flush();
  const layoutPost = queue.at(-1);
  assert.equal(layoutPost.url, '/api/layout?mix=0');
  assert.equal(queue.filter(r => r.url === '/api/settings').length, 1);
  firstPost.resolve({ok: false, status: 500, json: async () => ({error: 'Disk full'})});
  await assert.rejects(first, /Disk full/);
  await flush();
  const retryPost = queue.at(-1);
  assert.equal(retryPost.url, '/api/settings');
  assert.equal(JSON.parse(retryPost.init.body).theme, 'nordic');
  retryPost.resolve(ok({ok: true}));
  layoutPost.resolve(ok({ok: true}));
  assert.equal((await second).ok, true);
  assert.equal((await layout).ok, true);
  console.log('Release frontend regressions: late read, cancellation, save retry and independent queues passed');
})().catch(e => { console.error(e); process.exitCode = 1; });
