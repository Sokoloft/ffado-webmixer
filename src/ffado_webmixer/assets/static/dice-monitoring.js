/* DICE session bus gain and independent native monitor switches. */
(function (root) {
  'use strict';
  var supported = {}, state = null, busy = false;

  function renderHardwareButtons() {
    [['diceHardwareMonitor', 'hw_monitor'], ['diceHardwareMute', 'mute'],
     ['diceAdatSpdif', 'adat_spdif']].forEach(function (item) {
      var button = document.getElementById(item[0]), control = item[1];
      if (!button) return;
      button.disabled = busy || !state;
      button.classList.toggle('active', !!state?.[control]);
      button.setAttribute('aria-pressed', state?.[control + '_partial'] ? 'mixed' : String(!!state?.[control]));
    });
  }

  function toggleHardware(control) {
    if (busy || !state) return;
    var value = !state[control], device = root.ACTIVE_DEVICE;
    busy = true;
    root.ffadoApi.cancel('dice-monitoring');
    renderHardwareButtons();
    root.ffadoApi.serial('dice-monitoring|' + (device || ''), function () {
      return root.postJson('/api/dice-monitoring', {control: control, value: value}, device);
    }).then(function (data) {
      if (device === root.ACTIVE_DEVICE) state = data;
      if (device === root.ACTIVE_DEVICE && control === 'adat_spdif')
        return root.requestSyncRefresh();
    }).catch(function (error) {
      root.toast((control === 'adat_spdif' ? 'ADAT as SPDIF' :
        'Hardware ' + (control === 'mute' ? 'mute' : 'monitor')) + ' change failed: ' + error.message);
      if (device === root.ACTIVE_DEVICE) return root.refreshDiceMonitoring();
    }).finally(function () {
      busy = false;
      renderHardwareButtons();
      if (device === root.ACTIVE_DEVICE) root.loadMaster();
    });
  }

  root.refreshDiceMonitoring = function () {
    if (!supported.hw_monitor && !supported.mute && !supported.adat_spdif) return Promise.resolve();
    var device = root.ACTIVE_DEVICE;
    return root.ffadoApi.latest('dice-monitoring', '/api/dice-monitoring', {device: device})
      .then(function (data) {
        if (!data || device !== root.ACTIVE_DEVICE) return;
        state = data;
        renderHardwareButtons();
      }).catch(function (error) {
        if (device !== root.ACTIVE_DEVICE) return;
        state = null;
        renderHardwareButtons();
        root.toast('Could not read DICE monitoring: ' + error.message);
      });
  };

  root.configureDiceMonitoring = function (info) {
    supported = info.dice_monitoring || {};
    root.DICE_BUS_GAIN = !!info.software_bus_gain;
    state = null;
    root.refreshDiceMonitoring();
  };

  root.updateDiceBusButton = function () {
    var button = document.getElementById('diceBusGain');
    if (!button) return;
    var bus = root.OUTPUTS.find(function (out) { return out.mix === root.currentMix; });
    button.disabled = !bus;
    if (!bus) return;
    button.dataset.id = bus.id;
    var name = root.outputButtonName(bus);
    if (root.STEREO_BUSES.includes(bus.mix) && root.STEREO_BUS_NAMES[String(bus.mix)])
      name = root.STEREO_BUS_NAMES[String(bus.mix)];
    button.textContent = name;
    button.title = name + ' gain and mute';
    button.classList.toggle('active', root.currentOut === bus.id);
  };

  root.buildDiceMonitoring = function (box) {
    var dim = root.OUTPUTS.find(function (out) { return out.id === 'dice/dim'; });
    box.classList.toggle('dice-columns', !!(root.DICE_BUS_GAIN && (dim || supported.hw_monitor || supported.mute || supported.adat_spdif)));
    if (!root.DICE_BUS_GAIN && !dim && !supported.hw_monitor && !supported.mute && !supported.adat_spdif) return;
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
      button.title = 'Global Dim: −87 to 0 dB from quiet to loud. Use the bottom button to turn Dim on or off.';
      button.addEventListener('click', function () { root.selectOutput(dim); });
      grid.appendChild(button);
    }
    [['hw_monitor', 'diceHardwareMonitor', 'H/W<br>Monitor', 'Use the front-panel monitor knob.'],
     ['mute', 'diceHardwareMute', 'H/W<br>Mute', 'Mute the hardware line outputs.'],
     ['adat_spdif', 'diceAdatSpdif', 'ADAT as<br>SPDIF', 'Use the optical ADAT port as SPDIF.']].forEach(function (item) {
      if (!supported[item[0]]) return;
      var button = document.createElement('button');
      button.type = 'button'; button.className = 'outbtn'; button.id = item[1];
      button.innerHTML = '<span class="olabel">' + item[2] + '</span>';
      button.title = item[3];
      button.addEventListener('click', function () { toggleHardware(item[0]); });
      grid.appendChild(button);
    });
    if (grid.children.length) box.appendChild(group);
    if (root.DICE_BUS_GAIN) {
      var buses = document.createElement('div');
      buses.className = 'outgroup dice-bus-group single-bus-group';
      var busTitle = document.createElement('div');
      busTitle.className = 'grouptitle'; busTitle.textContent = 'Bus';
      buses.appendChild(busTitle);
      var busGrid = document.createElement('div');
      busGrid.className = 'groupgrid';
      buses.appendChild(busGrid);
      var busButton = document.createElement('button');
      busButton.type = 'button'; busButton.className = 'outbtn'; busButton.id = 'diceBusGain';
      busButton.addEventListener('click', function () {
        var bus = root.OUTPUTS.find(function (out) { return out.mix === root.currentMix; });
        if (bus) root.selectOutput(bus);
      });
      busGrid.appendChild(busButton);
      box.appendChild(buses);
    }
    root.updateDiceBusButton();
    renderHardwareButtons();
  };
})(window);
