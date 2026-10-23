/* Exercise credential setup, failed saves and read-only access through the form. */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(path.join(__dirname, '../src/ffado_webmixer/assets/static/remote-access.js'), 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    value: '', checked: false, disabled: true, required: false, textContent: '', handlers: {},
    classList: {toggle() {}}, focus() {this.focused = true;}, reportValidity() {return true;},
    addEventListener(event, handler) {this.handlers[event] = handler;}
  });
  return elements.get(id);
}
const requests = [];
let saved = {enabled: false, username: '', configured: false, can_manage: true,
             listening: false, restart_required: false};
let saveError = null;
const window = {ffadoApi: {async request(url, options = {}) {
  requests.push({url, options});
  if (options.body) {
    if (saveError) throw Error(saveError);
    saved = {...saved, enabled: options.body.enabled, username: options.body.username,
             configured: true, restart_required: options.body.enabled};
  }
  return saved;
}}};
vm.runInNewContext(source, {window, document: {getElementById: element}});
const enabled = element('remoteAccessEnabled');
const username = element('remoteAccessUsername');
const password = element('remoteAccessPassword');
const confirm = element('remoteAccessConfirm');
const fields = element('remoteAccessFields');
const message = element('remoteAccessMessage');
const submit = () => element('remoteAccessForm').handlers.submit({preventDefault() {}});
(async () => {
  await window.ffadoRemoteAccess.load();
  assert.equal(fields.disabled, false);
  assert.equal(password.required, false);
  enabled.checked = true;
  enabled.handlers.change();
  assert.equal(password.required, true, 'initial setup requires a password');
  assert.equal(username.required, true);
  username.value = 'studio';
  password.value = 'a long password for the mixer';
  confirm.value = 'a typo';
  await submit();
  assert.equal(requests.length, 1, 'mismatched passwords never reach the server');
  assert.match(message.textContent, /do not match/);
  assert.equal(confirm.focused, true);
  confirm.value = password.value;
  await submit();
  assert.equal(requests.at(-1).url, '/api/remote-access');
  assert.deepEqual({...requests.at(-1).options.body}, {
    enabled: true, username: 'studio', password: 'a long password for the mixer'
  });
  assert.equal(requests.at(-1).options.device, undefined, 'credentials are application-wide');
  assert.match(message.textContent, /Saved.*Restart/);
  assert.equal(password.value, '');
  assert.equal(confirm.value, '');
  assert.equal(password.required, false, 'blank password preserves existing credentials');

  enabled.checked = false;
  await submit();
  assert.equal(requests.at(-1).options.body.password, '');
  assert.equal(requests.at(-1).options.body.enabled, false);
  assert.equal(enabled.checked, false);
  saveError = 'disk full';
  enabled.checked = true;
  password.value = confirm.value = 'a replacement password';
  await submit();
  assert.match(message.textContent, /Could not save.*disk full/);
  assert.equal(fields.disabled, false, 'failed save allows retry');
  assert.equal(password.value, '', 'password is cleared even on a failed request');
  assert.equal(confirm.value, '');

  saveError = null;
  saved = {...saved, can_manage: false};
  await window.ffadoRemoteAccess.load();
  assert.equal(fields.disabled, true);
  assert.match(message.textContent, /local app/);
  const count = requests.length;
  await submit();
  assert.equal(requests.length, count, 'read-only clients cannot submit credentials');
  password.value = confirm.value = 'unsaved secret';
  window.ffadoRemoteAccess.clear();
  assert.equal(password.value, '');
  assert.equal(confirm.value, '');
  console.log('Remote access form: setup, confirmation, persistence failures and local-only management passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
