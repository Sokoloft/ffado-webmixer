/* The first-run prompt is native-desktop-only, never shown on LAN browsers. */
(function () {
  'use strict';
  const prompt = document.getElementById('desktopInstallPrompt');
  if (!prompt) return;
  const yes = document.getElementById('desktopInstallYes');
  const no = document.getElementById('desktopInstallNo');
  const message = document.getElementById('desktopInstallMessage');
  let busy = false;
  async function call(method) {
    if (!window.pywebview || !window.pywebview.api) return null;
    const fn = window.pywebview.api[method];
    return typeof fn === 'function' ? fn() : null;
  }
  async function checkFirstRun() {
    try {
      const result = await call('desktop_integration_status');
      if (result && result.prompt) { prompt.hidden = false; yes.focus(); }
    } catch (error) { console.warn('Desktop integration status unavailable:', error); }
  }
  async function act(method) {
    if (busy) return;
    busy = true;
    yes.disabled = no.disabled = true;
    message.textContent = '';
    try {
      const result = await call(method);
      if (!result || result.ok !== true) throw new Error(result && result.error || 'Could not save desktop integration preference');
      prompt.hidden = true;
    } catch (error) {
      message.textContent = error.message || String(error);
    } finally {
      busy = false;
      yes.disabled = no.disabled = false;
    }
  }
  yes.addEventListener('click', () => act('desktop_integration_install'));
  no.addEventListener('click', () => act('desktop_integration_dismiss'));
  window.addEventListener('pywebviewready', checkFirstRun);
  if (window.pywebview && window.pywebview.api) checkFirstRun();
})();
