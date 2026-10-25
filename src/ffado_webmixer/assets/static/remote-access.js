/* Global application credentials, deliberately separate from mixer preferences. */
(function () {
  'use strict';
  const form = document.getElementById('remoteAccessForm');
  const fields = document.getElementById('remoteAccessFields');
  const enabled = document.getElementById('remoteAccessEnabled');
  const username = document.getElementById('remoteAccessUsername');
  const password = document.getElementById('remoteAccessPassword');
  const confirm = document.getElementById('remoteAccessConfirm');
  const port = document.getElementById('remoteAccessPort');
  const message = document.getElementById('remoteAccessMessage');
  let status = null;
  let busy = false;

  function clear() { password.value = ''; confirm.value = ''; }
  function tell(text, error = false) {
    message.textContent = text;
    message.classList.toggle('err', error);
  }
  function requirements() {
    username.required = enabled.checked;
    password.required = enabled.checked && !(status && status.configured);
    confirm.required = password.required || Boolean(password.value);
  }
  function render(data, saved = false) {
    status = data;
    enabled.checked = data.enabled;
    username.value = data.username;
    port.value = data.port === 5000 ? '' : String(data.port);
    fields.disabled = !data.can_manage;
    clear();
    requirements();
    if (!data.can_manage) {
      tell('Manage remote access from the local app or localhost browser, outside demo/debug mode.');
    } else if (data.restart_required) {
      const changes = [];
      if (data.port !== data.listening_port) changes.push(`use port ${data.port}`);
      if (data.enabled && !data.listening) changes.push('enable LAN access');
      if (!data.enabled && data.listening) changes.push('close the LAN listener');
      tell((saved ? 'Saved. ' : '') + (!data.enabled ? 'Remote requests are blocked. ' : '') +
        'Restart the app to ' + changes.join(' and ') + '.' +
        (data.enabled && !data.listening ? ' Remove any localhost --host override.' : ''));
    } else {
      tell((saved ? 'Saved. ' : '') + (data.enabled
        ? 'Remote access is enabled. Credential changes apply to new requests immediately.'
        : 'Remote access is disabled.'));
    }
  }
  async function load() {
    if (busy) return;
    busy = true;
    fields.disabled = true;
    clear();
    tell('Loading remote access settings…');
    try {
      render(await window.ffadoApi.request('/api/remote-access'));
    } catch (error) {
      tell('Could not load remote access settings: ' + error.message, true);
    } finally { busy = false; }
  }
  enabled.addEventListener('change', requirements);
  password.addEventListener('input', requirements);
  form.addEventListener('submit', async function (event) {
    event.preventDefault();
    if (busy || !status || !status.can_manage) return;
    if (password.value !== confirm.value) {
      tell('Passwords do not match.', true);
      confirm.focus();
      return;
    }
    if (!form.reportValidity()) return;
    const body = {enabled: enabled.checked, username: username.value, password: password.value,
                  port: port.value.trim()};
    busy = true;
    fields.disabled = true;
    clear();
    tell('Saving remote access settings…');
    try {
      render(await window.ffadoApi.request('/api/remote-access', {body}), true);
    } catch (error) {
      fields.disabled = false;
      tell('Could not save remote access settings: ' + error.message, true);
    } finally {
      requirements();
      busy = false;
    }
  });
  window.ffadoRemoteAccess = {load, clear};
})();
