/* Keep the native pywebview title in sync after a device switch/reload.
 * Updating document.title alone does not update the Qt window title. */
(function () {
  'use strict';
  let selectedDevice = null;

  function updateNativeTitle() {
    const bridge = window.pywebview?.api;
    if (!selectedDevice || typeof bridge?.set_device_title !== 'function') return;
    Promise.resolve(bridge.set_device_title(selectedDevice)).catch(error => {
      console.warn('Could not update the native window title:', error);
    });
  }

  window.syncNativeWindowTitle = function (device) {
    selectedDevice = typeof device === 'string' ? device.trim() : '';
    updateNativeTitle();
  };
  // On some starts the mixer description arrives before pywebview's API;
  // on others the API is ready first. Both orders must update the title.
  window.addEventListener('pywebviewready', updateNativeTitle);
})();
