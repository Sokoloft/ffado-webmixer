/* Native DICE monitor switches. The front-panel knob's gain is never polled. */
(function (root) {
  'use strict';
  var supported = {}, state = null, busy = false;

  function renderHardwareButton() {
    var button = document.getElementById('diceHardwareMonitor');
    if (!button) return;
    button.disabled = busy || !state;
    button.classList.toggle('active', !!state?.hw_monitor);
    button.setAttribute('aria-pressed', state?.hw_monitor_partial ? 'mixed' : String(!!state?.hw_monitor));
  }

  root.refreshDiceMonitoring = function () {
    if (!supported.hw_monitor) return Promise.resolve();
    var device = root.ACTIVE_DEVICE;
    return root.ffadoApi.latest('dice-monitoring', '/api/dice-monitoring', {device: device})
      .then(function (data) {
        if (!data || device !== root.ACTIVE_DEVICE) return;
        state = data;
        renderHardwareButton();
      }).catch(function (error) {
        state = null;
        renderHardwareButton();
        root.toast('Could not read DICE monitoring: ' + error.message);
      });
  };

  root.configureDiceMonitoring = function (info) {
    supported = info.dice_monitoring || {};
    state = null;
    root.refreshDiceMonitoring();
  };

  root.buildDiceMonitoring = function (box) {
    var dim = root.OUTPUTS.find(function (out) { return out.id === 'dice/dim'; });
    if (!dim && !supported.hw_monitor) return;
    var group = document.createElement('div');
    group.className = 'outgroup dice-group';
    var title = document.createElement('div');
    title.className = 'grouptitle'; title.textContent = 'Dice';
    group.appendChild(title);
    var grid = document.createElement('div');
    grid.className = 'groupgrid dice-grid';
    group.appendChild(grid);
    if (dim) {
      var button = document.createElement('button');
      button.type = 'button'; button.className = 'outbtn'; button.dataset.id = dim.id;
      button.textContent = 'Dim';
      button.title = 'Global Dim: Off at the bottom, then −87 to 0 dB from quiet to loud.';
      button.addEventListener('click', function () { root.selectOutput(dim); });
      grid.appendChild(button);
    }
    if (supported.hw_monitor) {
      var hardware = document.createElement('button');
      hardware.type = 'button'; hardware.className = 'outbtn'; hardware.id = 'diceHardwareMonitor';
      hardware.innerHTML = '<span class="olabel">H/W<br>Monitor</span>';
      hardware.title = 'Use the front-panel monitor knob. Output gain is not displayed in H/W mode.';
      hardware.addEventListener('click', function () {
        if (busy || !state) return;
        var value = !state.hw_monitor, device = root.ACTIVE_DEVICE;
        busy = true;
        root.ffadoApi.cancel('dice-monitoring');
        renderHardwareButton();
        root.ffadoApi.serial('dice-monitoring|' + (device || ''), function () {
          return root.postJson('/api/dice-monitoring', {control: 'hw_monitor', value: value}, device);
        }).then(function (data) {
          if (device === root.ACTIVE_DEVICE) state = data;
        }).catch(function (error) {
          root.toast('Hardware monitor change failed: ' + error.message);
          return root.refreshDiceMonitoring();
        }).finally(function () {
          busy = false;
          renderHardwareButton();
          if (device === root.ACTIVE_DEVICE) root.loadMaster();
        });
      });
      grid.appendChild(hardware);
    }
    box.appendChild(group);
    renderHardwareButton();
  };
})(window);
