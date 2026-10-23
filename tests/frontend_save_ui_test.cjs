/* Executable assertions for theme save acknowledgement and latest-edit rollback. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const src = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/index.js'), 'utf8');
const saveFn = src.slice(src.indexOf('function savePreference('), src.indexOf('function send('));
const themeFn = src.slice(src.indexOf('var confirmedTheme = null;'), src.indexOf('// Accent overrides'));
const requests = [], notices = [], handlers = {};
let theme = 'dark';
function deferred() { let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject}; }
const themeSelect={value:'dark',addEventListener(event,func){handlers[event]=func;}};
const tails=new Map();
const ffadoApi={serial(key, fn){const previous=tails.get(key)||Promise.resolve();const next=previous.catch(()=>{}).then(fn);tails.set(key,next);return next;}};
const ctx=vm.createContext({themeSelect,ACTIVE_DEVICE:'GUID',window:{ffadoApi},Promise,
  postJson(url,body,device){const d=deferred();requests.push({url,body,device,...d});return d.promise;},
  applyTheme(name){theme=name;themeSelect.value=name;},
  toast(message){notices.push(message);}
});
vm.runInContext(saveFn+'\n'+themeFn,ctx);
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
(async()=>{
  ctx.confirmedTheme='dark';
  themeSelect.value='light';handlers.change();await flush();
  assert.equal(theme,'light','appearance may be previewed while saving');
  assert.equal(requests.length,1);
  assert.equal(requests[0].device,'GUID');
  requests[0].reject(Error('disk full'));await flush();
  assert.equal(theme,'dark','failed save restores confirmed theme');
  assert.match(notices.at(-1),/Could not save theme: disk full/);

  themeSelect.value='gruvbox';handlers.change();await flush();
  themeSelect.value='nordic';handlers.change();await flush();
  assert.equal(requests.length,2,'same setting serializes consecutive edits');
  requests[1].reject(Error('busy'));await flush();
  assert.equal(theme,'nordic','old failed request must not revert newer preview');
  assert.equal(requests.length,3,'pending newer request is issued');
  requests[2].resolve({ok:true});await flush();
  assert.equal(ctx.confirmedTheme,'nordic');
  assert.match(notices.at(-1),/Saved theme/);
  assert.equal(theme,'nordic');
  console.log('Frontend saves: server confirmation, failed-save rollback, and rapid-edits ordering passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
