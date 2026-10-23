/* Device-native matrix and CrossbarRouter, driven exclusively by actual FFADO controls. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const overlay = $("routingOverlay"), button = $("routingButton");
  const tabs = { bus: $("routingBusTab"), matrix: $("routingMatrixTab"), crossbar: $("routingCrossbarTab") };
  const panes = { bus: $("routingBus"), matrix: $("routingMatrix"), crossbar: $("routingCrossbar") };
  let capabilities = { bus: false, matrix: false, crossbar: false }, active = "matrix", matrix = null, selection = null;
  let loading = false, phonesWriteBusy = false;
  let refreshEpoch = 0, refreshController = null;
  let inlineGesture = null, matrixWriteBusy = false, matrixRefreshPending = false;
  let stereoPlaybackBusy = false;
  let matrixWriteError = null, matrixWriteEpoch = 0;
  const routeMeterStates = new Map();
  function message(s) { $("routingHint").textContent = s; }
  let editorDb = null, editorPercent = 0;
  function isDb() { return !!(matrix && matrix.gain_scale && ["dice_db", "rme_db"].includes(matrix.mode)); }
  function scale() { return matrix.gain_scale; }
  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }
  function dbToUi(db) {
    if (db === null) return 0;
    return clamp((db - scale().min_db) * 100 / (scale().max_db - scale().min_db), 0, 100);
  }
  function uiToDb(ui) { return ui <= 0 ? null : scale().min_db + ui * (scale().max_db - scale().min_db) / 100; }
  function formatDb(db) {
    if (db === null) return "−∞ dB";
    const rounded = Math.round(db * 10) / 10;
    return (rounded > 0 ? "+" : "") + rounded.toFixed(1) + " dB";
  }
  function uiDb(v, db) { return isDb() ? formatDb(db) : Number(v).toFixed(0) + "%"; }
  function updateEditor() {
    const percent = isDb() ? dbToUi(editorDb) : editorPercent;
    $("routingLevel").value = percent;
    $("routingLevelLabel").textContent = isDb() ? formatDb(editorDb) : Math.round(percent) + "%";
    $("routingDb").value = isDb() && editorDb !== null ? editorDb.toFixed(1) : "";
    $("routingDb").placeholder = editorDb === null ? "−∞" : "";
    const knob = $("routingKnob");
    knob.querySelector('.routing-knob-needle').style.transform = 'rotate(' + (-135+270*percent/100) + 'deg)';
    knob.setAttribute('aria-valuenow', String(isDb() && editorDb !== null ? editorDb.toFixed(1) : percent.toFixed(1)));
    knob.setAttribute('aria-valuetext', isDb() ? (editorDb === null ? 'minus infinity' : formatDb(editorDb)) : Math.round(percent) + ' percent');
  }
  function editDb(db) {
    if (!isDb()) return;
    editorDb = db === null ? null : Math.round(clamp(db, scale().min_db, scale().max_db) * 10) / 10;
    // -60 is the FFADO silence sentinel. Do not pretend it is a finite level.
    if (editorDb !== null && editorDb <= scale().min_db) editorDb = null;
    updateEditor();
  }
  function renderEditor(percent, db) {
    editorPercent = percent;
    if (isDb()) editorDb = db === undefined ? uiToDb(percent) : db;
    updateEditor();
  }
  function nudgeDb(steps) {
    if (!isDb()) return;
    editDb((editorDb === null ? scale().min_db : editorDb) + steps);
  }
  function changeTab(name) {
    if (!capabilities[name]) return;
    if (name !== 'matrix' && inlineGesture) {
      if (inlineGesture.pointer != null) cancelMatrixGesture();
      else commitMatrixGesture();
    }
    if (matrixWriteBusy && name !== active) return;
    active = name;
    Object.keys(tabs).forEach(key => {
      panes[key].hidden = name !== key;
      tabs[key].classList.toggle("routing-active", name === key);
      tabs[key].setAttribute("aria-pressed", name === key ? "true" : "false");
    });
    refresh();
  }
  function request(url, body, signal) {
    if (window.ffadoApi) return window.ffadoApi.request(url, {
      body, device: window.activeFfadoDevice, signal
    });
    // Standalone routing test harnesses can run without frontend-api.js.
    return fetch(url, body === undefined ? {cache: 'no-store', signal, headers:
        window.activeFfadoDevice ? {'X-FFADO-Device': window.activeFfadoDevice} : {}} :
      {method: 'POST', signal, headers: {'Content-Type': 'application/json',
          'X-FFADO-Device': window.activeFfadoDevice || ''}, body: JSON.stringify(body)})
      .then(async r => {
        const result = await r.json();
        if (!r.ok || result.error) throw new Error(result.error || 'Hardware request failed');
        return result;
      });
  }
  function stopPendingRefresh() {
    refreshEpoch++;
    if (refreshController) refreshController.abort();
    refreshController = null;
    loading = false;
  }
  // Each crosspoint is a real rotary control. Its pointer/wheel/keyboard
  // preview stays local until release (or an idle pause), then ONE FFADO write
  // is made and the value is replaced by verified hardware readback.
  function cellLevel(value, db) {
    return isDb() ? dbToUi(db) : clamp(Number(value), 0, 100);
  }
  function paintMatrixCell(cell, value, db) {
    const percent = cellLevel(value, db);
    cell.querySelector('.matrix-cell-value').textContent = uiDb(value, db);
    cell.querySelector('.matrix-cell-needle').style.transform =
      'rotate(' + (-135 + 270 * percent / 100) + 'deg)';
    cell.classList.toggle('route-signal', Number(value) > 0);
    cell.setAttribute('aria-valuemin', isDb() ? String(scale().min_db) : '0');
    cell.setAttribute('aria-valuemax', isDb() ? String(scale().max_db) : '100');
    cell.setAttribute('aria-valuenow', String(isDb() ? (db === null ? scale().min_db : db) : value));
    cell.setAttribute('aria-valuetext', isDb() ? (db === null ? 'minus infinity' : formatDb(db)) : uiDb(value, db));
  }
  // Display the currently routed source, not the immutable FFADO matrix ID.
  // `inputs` stays untouched, because indexes and writes refer to that array.
  function matrixInputLabel(i) {
    return matrix.input_labels && matrix.input_labels[i] !== undefined
      ? matrix.input_labels[i] : matrix.inputs[i];
  }
  // Group names are hardware router namespace identifiers, not user-facing
  // labels. Keep the raw destination for FFADO reads/writes and meter keys.
  const ROUTER_GROUP_TITLES = Object.freeze({
    "1394/out": "Firewire", "1394/in": "Firewire",
    "adat/out": "ADAT", "adat/in": "ADAT",
    "line/out": "Line Out", "line/in": "Line In",
    "loop": "Loop", "mixer/in": "Mixer Inputs", "mixer/out": "Mixer Outputs",
    "anlg/out": "Analog Out", "anlg/in": "Analog",
    "spdif/out": "SPDIF", "spdif/in": "SPDIF",
    "aes/out": "AES", "aes/in": "AES",
  });
  function routerGroupTitle(rawName) {
    return ROUTER_GROUP_TITLES[String(rawName).trim().toLowerCase()] || rawName;
  }
  function routedDestinationLabel(destination, selected) {
    const id = shortFfadoLabel(destination);
    // A CrossbarRouter mixer-input destination has a stable identity, while
    // its source can change. Show BOTH, especially if it is disconnected.
    if (!destination.startsWith('Mixer/In:')) return id;
    const source = selected && selected[destination];
    return id + ' ← ' + shortFfadoLabel(
      !source || source.startsWith('Mute:') ? 'Disconnected' : source);
  }
  function selectMatrixCell(i, o, cell) {
    const old = $('routingGrid').querySelector('.route-selected');
    if (old && old !== cell) old.classList.remove('route-selected');
    cell.classList.add('route-selected');
    selection = { input: i, output: o, button: cell };
    $('routingEditor').hidden = false;
    $('routingCellLabel').textContent = shortFfadoLabel(matrixInputLabel(i)) + ' → ' + shortFfadoLabel(matrix.outputs[o]);
    renderEditor(matrix.values[i][o], isDb() ? matrix.db_values[i][o] : undefined);
  }
  function previewMatrixCell(gesture, level) {
    if (isDb()) {
      const db = level <= scale().min_db ? null : Math.round(clamp(level, scale().min_db, scale().max_db) * 10) / 10;
      gesture.db = db;
      // A preview is not the hardware value: only the visible knob and the
      // selected detailed editor change until the write succeeds.
      paintMatrixCell(gesture.cell, db === null ? 0 : dbToUi(db), db);
      renderEditor(dbToUi(db), db);
    } else {
      gesture.percent = Math.round(clamp(level, 0, 100) * 100) / 100;
      paintMatrixCell(gesture.cell, gesture.percent);
      renderEditor(gesture.percent);
    }
    gesture.changed = true;
  }
  function clearGestureTimer() {
    if (inlineGesture && inlineGesture.timer !== null) {
      clearTimeout(inlineGesture.timer);
      inlineGesture.timer = null;
    }
  }
  function undoMatrixPreview(gesture) {
    if (!matrix || !gesture) return;
    paintMatrixCell(gesture.cell, matrix.values[gesture.input][gesture.output],
      isDb() ? matrix.db_values[gesture.input][gesture.output] : undefined);
    if (selection && selection.button === gesture.cell) {
      renderEditor(matrix.values[gesture.input][gesture.output],
        isDb() ? matrix.db_values[gesture.input][gesture.output] : undefined);
    }
  }
  function finishMatrixWrite() {
    matrixWriteBusy = false;
    $('routingApply').disabled = false;
    $('routingRefresh').disabled = loading;
    if (matrixRefreshPending && !loading) {
      matrixRefreshPending = false;
      if (!overlay.hidden && active === 'matrix') refresh();
    }
  }
  function writeMatrixValue(input, output, cell, payload) {
    if (matrixWriteBusy) return Promise.resolve(false);
    matrixWriteBusy = true;
    matrixWriteEpoch++;
    $('routingApply').disabled = true;
    $('routingRefresh').disabled = true;
    // Disable ALL crosspoint knobs until the hardware confirms this write;
    // otherwise another user's gesture could be overwritten by a stale read.
    $('routingGrid').querySelectorAll('.matrix-cell-control').forEach(b => { b.disabled = true; });
    return request('/api/matrix', payload).then(result => {
      matrixWriteError = null;
      matrix.values[input][output] = result.value;
      if (isDb()) matrix.db_values[input][output] = result.db;
      paintMatrixCell(cell, result.value, isDb() ? result.db : undefined);
      if (selection && selection.button === cell) {
        renderEditor(result.value, isDb() ? result.db : undefined);
      }
      if (typeof window.refreshMatrixStrips === "function") window.refreshMatrixStrips();
      message((result.deferred ? 'Saved for unmute: ' : 'Hardware readback: ') +
        matrix.inputs[input] + ' → ' + matrix.outputs[output] +
        ' = ' + uiDb(result.value, result.db));
      return true;
    }).catch(error => {
      paintMatrixCell(cell, matrix.values[input][output],
        isDb() ? matrix.db_values[input][output] : undefined);
      if (selection && selection.button === cell) {
        renderEditor(matrix.values[input][output],
          isDb() ? matrix.db_values[input][output] : undefined);
      }
      matrixWriteError = 'Could not set matrix level: ' + error.message;
      message(matrixWriteError);
      // Hardware may have changed even if readback failed. Reload it.
      matrixRefreshPending = true;
      return false;
    }).finally(() => {
      $('routingGrid').querySelectorAll('.matrix-cell-control').forEach(b => { b.disabled = false; });
      finishMatrixWrite();
    });
  }
  function commitMatrixGesture() {
    if (!inlineGesture || matrixWriteBusy) return;
    const gesture = inlineGesture;
    clearGestureTimer();
    inlineGesture = null;
    if (!gesture.changed) return;
    const payload = isDb()
      ? { input: gesture.input, output: gesture.output, db: gesture.db }
      : { input: gesture.input, output: gesture.output, value: gesture.percent };
    writeMatrixValue(gesture.input, gesture.output, gesture.cell, payload);
  }
  function cancelMatrixGesture() {
    const gesture = inlineGesture;
    clearGestureTimer();
    inlineGesture = null;
    undoMatrixPreview(gesture);
  }
  function beginMatrixGesture(i, o, cell) {
    if (matrixWriteBusy) return null;
    if (inlineGesture && inlineGesture.cell !== cell) commitMatrixGesture();
    if (matrixWriteBusy) return null;
    selectMatrixCell(i, o, cell);
    if (!inlineGesture) {
      inlineGesture = { input:i, output:o, cell, timer:null, changed:false,
        db: isDb() ? matrix.db_values[i][o] : null, percent:matrix.values[i][o] };
    }
    return inlineGesture;
  }
  function scheduleMatrixGesture() {
    clearGestureTimer();
    if (inlineGesture) inlineGesture.timer = setTimeout(commitMatrixGesture, 320);
  }
  function installMatrixKnob(cell, i, o) {
    cell.addEventListener('click', () => {
      if (!matrixWriteBusy && !inlineGesture) selectMatrixCell(i, o, cell);
    });
    cell.addEventListener('dblclick', () => {
      if (matrixWriteBusy) return;
      if (inlineGesture) cancelMatrixGesture();
      selectMatrixCell(i, o, cell);
      if (isDb()) editDb(0); else renderEditor(100);
      message('Unity selected for this crosspoint. Press Apply to write to hardware.');
    });
    cell.addEventListener('pointerdown', e => {
      if (e.button !== undefined && e.button !== 0) return;
      const gesture = beginMatrixGesture(i, o, cell);
      if (!gesture) return;
      clearGestureTimer();
      e.preventDefault();
      gesture.startY = e.clientY;
      gesture.startLevel = isDb()
        ? (gesture.db === null ? scale().min_db : gesture.db) : gesture.percent;
      gesture.pointer = e.pointerId;
      cell.setPointerCapture(e.pointerId);
    });
    cell.addEventListener('pointermove', e => {
      const gesture = inlineGesture;
      if (!gesture || gesture.cell !== cell || gesture.pointer !== e.pointerId) return;
      const delta = gesture.startY - e.clientY;
      if (Math.abs(delta) < 2 && !gesture.changed) return;
      previewMatrixCell(gesture, gesture.startLevel + delta * (isDb() ? 0.1 : 0.5));
    });
    cell.addEventListener('pointerup', e => {
      if (!inlineGesture || inlineGesture.cell !== cell || inlineGesture.pointer !== e.pointerId) return;
      inlineGesture.pointer = null;
      commitMatrixGesture();
    });
    cell.addEventListener('pointercancel', e => {
      if (inlineGesture && inlineGesture.cell === cell && inlineGesture.pointer === e.pointerId) cancelMatrixGesture();
    });
    cell.addEventListener('wheel', e => {
      if (matrixWriteBusy) return;
      const gesture = beginMatrixGesture(i, o, cell);
      if (!gesture) return;
      e.preventDefault();
      const step = isDb() ? (e.shiftKey ? 1 : 0.1) : (e.shiftKey ? 5 : 1);
      const current = isDb() ? (gesture.db === null ? scale().min_db : gesture.db) : gesture.percent;
      previewMatrixCell(gesture, current + (e.deltaY < 0 ? step : -step));
      scheduleMatrixGesture();
    }, { passive: false });
    cell.addEventListener('keydown', e => {
      let direction = 0, preset = null;
      if (e.key === 'ArrowUp' || e.key === 'ArrowRight') direction = 1;
      else if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') direction = -1;
      else if (e.key === 'Home' || e.key.toLowerCase() === 'm') preset = 'mute';
      else if (e.key === 'End') preset = 'max';
      else if (e.key === '0') preset = 'unity';
      else return; // Enter/Space open the detailed editor through click.
      e.preventDefault();
      const gesture = beginMatrixGesture(i, o, cell);
      if (!gesture) return;
      const current = isDb() ? (gesture.db === null ? scale().min_db : gesture.db) : gesture.percent;
      const step = isDb() ? (e.shiftKey ? 1 : 0.1) : (e.shiftKey ? 5 : 1);
      const next = preset === 'mute' ? (isDb() ? scale().min_db : 0)
        : preset === 'max' ? (isDb() ? scale().max_db : 100)
        : preset === 'unity' ? (isDb() ? 0 : 100)
        : current + direction * step;
      previewMatrixCell(gesture, next);
      scheduleMatrixGesture();
    });
  }
  function renderMatrix(data) {
    const previous = selection ? {input: selection.input, output: selection.output,
      focused: document.activeElement === selection.button} : null;
    cancelMatrixGesture();
    matrix = data;
    const dbMode = isDb();
    $("routingDb").hidden = !dbMode;
    $("routingDbLabel").hidden = !dbMode;
    $("routingKnob").hidden = !dbMode;
    $("routingDb").min = dbMode ? scale().min_db : -60;
    $("routingDb").max = dbMode ? scale().max_db : 6;
    $("routingKnob").setAttribute("aria-valuemin", dbMode ? scale().min_db : -60);
    $("routingKnob").setAttribute("aria-valuemax", dbMode ? scale().max_db : 6);
    $("routingPreset").hidden = !dbMode;
    $("routingPresetLabel").hidden = !dbMode;
    $("routingPreset").value = "";
    selection = null;
    $("routingEditor").hidden = true;
    const table = $("routingGrid");
    table.replaceChildren();
    const head = document.createElement("thead"), top = document.createElement("tr");
    let th = document.createElement("th"); th.textContent = "Inputs ↓ / Outputs →"; top.appendChild(th);
    data.outputs.forEach(name => { th = document.createElement("th"); th.textContent = shortFfadoLabel(name); th.title = name; top.appendChild(th); });
    head.appendChild(top); table.appendChild(head);
    const body = document.createElement("tbody"), cellButtons = [];
    data.inputs.forEach((name, i) => {
      cellButtons[i] = [];
      const tr = document.createElement("tr"), label = document.createElement("th");
      const displayName = matrixInputLabel(i);
      label.textContent = shortFfadoLabel(displayName);
      label.title = name + (displayName !== name ? ' ← ' + displayName : '');
      tr.appendChild(label);
      data.outputs.forEach((outname, o) => {
        const td = document.createElement("td"), cell = document.createElement("button");
        cell.type = "button";
        cell.className = "matrix-cell-control";
        cell.setAttribute('role', 'slider');
        cell.setAttribute('aria-label', shortFfadoLabel(displayName) + ' to ' + shortFfadoLabel(outname) + ' mixer volume');
        cell.title = shortFfadoLabel(displayName) + ' → ' + shortFfadoLabel(outname) +
          ': drag up/down, scroll, or use arrow keys; click for exact dB';
        const dial = document.createElement('span'), needle = document.createElement('span');
        dial.className = 'matrix-cell-dial';
        needle.className = 'matrix-cell-needle';
        dial.appendChild(needle);
        const valueLabel = document.createElement('span');
        valueLabel.className = 'matrix-cell-value';
        cell.append(dial, valueLabel);
        const val = data.values[i][o];
        const db = isDb() ? data.db_values[i][o] : undefined;
        paintMatrixCell(cell, val, db);
        installMatrixKnob(cell, i, o);
        cellButtons[i][o] = cell;
        td.appendChild(cell); tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    if (previous && cellButtons[previous.input] && cellButtons[previous.input][previous.output]) {
      const cell = cellButtons[previous.input][previous.output];
      selectMatrixCell(previous.input, previous.output, cell);
      if (previous.focused) cell.focus();
    }
    message(matrixWriteError || "Drag a matrix knob to adjust, scroll or use arrow keys; changes write on release/pause. Click for precise editing and presets.");
  }
  // The MOTU Mk1/Mk2 has four per-bus Discrete Mix_dest selectors. Those
  // choose one hardware output per bus and never alter crosspoint gain. This
  // grid's columns are mix buses; rows are the real available destinations.
  function renderBusRouting(data) {
    const phones = $("routingPhonesAssignment");
    const select = $("routingPhonesSelect");
    select.replaceChildren();
    phones.hidden = !data.phones;
    if (data.phones) {
      data.phones.options.forEach(dest => {
        const opt = document.createElement('option');
        opt.textContent = dest.name;
        opt.value = String(dest.value);
        opt.disabled = dest.name.startsWith('Unavailable');
        select.appendChild(opt);
      });
      select.value = String(data.phones.value);
      // Unsupported hardware value is shown as read-only until the user
      // deliberately chooses one of the known valid destinations.
      const current = data.phones.options.find(dest => dest.value === data.phones.value);
      if (current && current.name.startsWith('Unavailable')) {
        select.title = 'Hardware has an unsupported Phones assignment; select a supported destination.';
      } else select.title = 'Choose the hardware source for the Phones output.';
      select.disabled = phonesWriteBusy;
    }
    const table = $("routingBusGrid");
    table.replaceChildren();
    const head = document.createElement("thead"), hr = document.createElement("tr");
    const corner = document.createElement("th"); corner.textContent = "Outputs ↓ / Buses →";
    hr.appendChild(corner);
    data.buses.forEach(bus => {
      const th = document.createElement("th"); th.scope = "col"; th.textContent = shortFfadoLabel(bus.name); hr.appendChild(th);
    });
    head.appendChild(hr); table.appendChild(head);
    const body = document.createElement("tbody");
    data.destinations.forEach(destination => {
      const row = document.createElement("tr"), label = document.createElement("th");
      label.scope = "row"; label.textContent = destination.name; row.appendChild(label);
      data.buses.forEach(bus => {
        const td = document.createElement("td"), button = document.createElement("button");
        button.type = "button";
        button.className = "bus-route-cell";
        const chosen = bus.value === destination.value;
        button.classList.toggle("route-assigned", chosen);
        button.textContent = chosen ? "●" : "○";
        button.setAttribute("aria-pressed", chosen ? "true" : "false");
        button.setAttribute("aria-label", bus.name + " → " + destination.name + (chosen ? " (selected)" : ""));
        button.title = bus.name + " → " + destination.name;
        button.addEventListener("click", () => {
          if (chosen) return;
          // Prevent double writes to a shared bus while FFADO is working.
          table.querySelectorAll("button").forEach(b => { b.disabled = true; });
          message("Assigning " + bus.name + " to " + destination.name + "…");
          request("/api/bus-routing", { bus: bus.id, value: destination.value })
            .then(() => request("/api/bus-routing"))
            .then(renderBusRouting)
            .catch(e => message("Routing failed: " + e.message))
            .finally(() => table.querySelectorAll("button").forEach(b => { b.disabled = false; }));
        });
        td.appendChild(button); row.appendChild(td);
      });
      body.appendChild(row);
    });
    // If the hardware reports an assignment not supported by this model,
    // display it as a warning, never as a selectable phantom ADAT output.
    const allowed = new Set(data.destinations.map(dest => dest.value));
    const unknown = data.buses.filter(bus => !allowed.has(bus.value));
    table.appendChild(body);
    message(unknown.length ?
      "Hardware reported an unsupported destination on " + unknown.map(b => b.name).join(", ") + ". Choose a valid row to correct it." :
      "Select one output for each mix bus. Only hardware routing changes; mixer volume levels remain untouched.");
  }
  function refreshStereoFirewire() {
    if (!$('routingStereoFirewire')) return Promise.resolve();
    // The helper only appears when the Crossbar Router positively identifies
    // a unique left/right FireWire source assignment for two mixer inputs.
    return request('/api/stereo-firewire').then(data => {
      const block = $('routingStereoFirewire');
      if (!data.available || !data.pairs?.length || !data.buses?.length) {
        block.hidden = true;
        return;
      }
      const sources = $('routingStereoSource'), buses = $('routingStereoBus');
      const oldSource = sources.value, oldBus = buses.value;
      sources.replaceChildren(); buses.replaceChildren();
      data.pairs.forEach(pair => option(sources, pair.label, pair.left_source));
      data.buses.forEach(bus => option(buses, bus.label, String(bus.left)));
      if (data.pairs.some(pair => pair.left_source === oldSource)) sources.value = oldSource;
      if (data.buses.some(bus => String(bus.left) === oldBus)) buses.value = oldBus;
      block.hidden = false;
    }).catch(() => { $('routingStereoFirewire').hidden = true; });
  }
  function option(select, text, value) {
    const opt = document.createElement("option"); opt.textContent = text; opt.value = value; select.appendChild(opt);
  }
  function renderCrossbar(data) {
    routeMeterStates.clear();
    const root = $("routingDestinations"); root.replaceChildren();
    const groups = new Map();
    data.destinations.forEach(destination => {
      const groupName = destination.split(":")[0];
      if (!groups.has(groupName)) groups.set(groupName, []);
      groups.get(groupName).push(destination);
    });
    groups.forEach((destinations, name) => {
      const card = document.createElement("section"); card.className = "route-group";
      const h = document.createElement("h3"); h.textContent = routerGroupTitle(name);
      h.title = name; card.appendChild(h);
      destinations.forEach(dest => {
        const row = document.createElement("div"); row.className = "route-row";
        const label = document.createElement("label");
        label.textContent = routedDestinationLabel(dest, data.selected);
        label.title = dest;
        // Each hardware router destination has its own FFADO peak reading.
        // These may not correspond to a mixer input strip on every DICE model.
        const meter = document.createElement('button');
        meter.type = 'button';
        meter.className = 'route-peak'; meter.hidden = true;
        meter.dataset.destination = dest;
        meter.setAttribute('aria-label', 'Clear peak and warning hold for ' + dest);
        meter.title = dest + ': reset peak and near-full-scale hold';
        meter.innerHTML = '<span class="route-peak-fill"></span><span class="route-peak-hold"></span><span class="route-peak-clip"></span><span class="route-peak-db"></span>';
        meter.addEventListener('click', () => {
          routeMeterStates.delete(dest);
          meter.classList.remove('clipping');
        });
        const select = document.createElement("select");
        select.setAttribute("aria-label", "Source for " + dest);
        option(select, "Disconnected", "");
        data.sources.filter(src => src !== "" && !src.startsWith('Mute:')).forEach(src => option(select, shortFfadoLabel(src), src));
        if (data.sources.indexOf(data.selected[dest]) < 0 && !data.selected[dest].startsWith('Mute:'))
          option(select, shortFfadoLabel(data.selected[dest]), data.selected[dest]);
        select.value = data.selected[dest].startsWith('Mute:') ? '' : data.selected[dest];
        select.addEventListener("change", () => {
          const prev = data.selected[dest], next = select.value;
          select.disabled = true;
          request("/api/router", { destination: dest, source: next }).then(() => {
            data.selected[dest] = next;
            label.textContent = routedDestinationLabel(dest, data.selected);
            // A Mixer/In destination is the source feeding a channel fader.
            // Reload the strips from the verified server-side router mapping.
            if (window.refreshMatrixStrips && dest.startsWith('Mixer/In:'))
              window.refreshMatrixStrips();
            message(dest + " now receives " + (next || 'Disconnected'));
          }).catch(e => { select.value = prev; message("Could not route " + dest + ": " + e.message); })
            .finally(() => { select.disabled = false; });
        });
        row.append(label, meter, select); card.appendChild(row);
      });
      root.appendChild(card);
    });
    message("Each destination receives one source. Changing a selector immediately changes hardware routing.");
  }
  // The main mixer polls FFADO once; share that response rather than creating
  // a second hardware polling loop when the Crossbar tab is open.
  document.addEventListener('ffado-peaks', e => {
    if (overlay.hidden || active !== 'crossbar') return;
    const peaks = e.detail && e.detail.destination_levels || {};
    const now = performance.now();
    panes.crossbar.querySelectorAll('.route-peak').forEach(meter => {
      const name = meter.dataset.destination;
      const value = peaks[name];
      meter.hidden = !value;
      if (!value) { routeMeterStates.delete(name); return; }
      let state = routeMeterStates.get(name);
      if (!state) {
        state = {level:value.level,until:0,clipUntil:0};
        routeMeterStates.set(name,state);
      }
      if (value.level >= state.level || now >= state.until) {
        state.level = value.level; state.until = now + 1600;
      }
      if (value.near_full_scale) state.clipUntil = now + 4000;
      // Clip a full-track gradient so yellow/red remain at the top of
      // the absolute FFADO scale, even for low router readings.
      meter.querySelector('.route-peak-fill').style.clipPath =
        `inset(0 ${((1 - value.level) * 100).toFixed(2)}% 0 0)`;
      meter.querySelector('.route-peak-hold').style.left = (state.level * 100).toFixed(2) + '%';
      meter.classList.toggle('clipping', now < state.clipUntil);
      meter.querySelector('.route-peak-db').textContent = value.db === null ? '−∞' : value.db.toFixed(1) + ' dB';
      meter.title = name + ' peak relative to FFADO full scale (not calibrated dBFS). Click to clear hold.';
    });
  });
  function refresh(throwOnError = false) {
    if (active === 'matrix' && (matrixWriteBusy || inlineGesture)) {
      matrixRefreshPending = true;
      return;
    }
    // New refreshes supersede old GETs, including a tab switch mid-request.
    // They do NOT cancel in-flight routing/matrix POSTs.
    stopPendingRefresh();
    const requestedTab = active, readEpoch = matrixWriteEpoch, epoch = refreshEpoch;
    refreshController = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const controller = refreshController;
    loading = true;
    $('routingRefresh').disabled = true;
    message('Reading current FFADO hardware values…');
    return request(requestedTab === 'bus' ? '/api/bus-routing' : requestedTab === 'matrix' ? '/api/matrix' : '/api/router',
      undefined, controller ? controller.signal : undefined)
      .then(data => {
        if (epoch !== refreshEpoch || overlay.hidden || active !== requestedTab) return;
        if (requestedTab === 'matrix' && (matrixWriteBusy || inlineGesture || readEpoch !== matrixWriteEpoch)) {
          // Never replace the live knob DOM with a read started before an edit.
          matrixRefreshPending = true;
          return;
        }
        if (requestedTab === 'bus') renderBusRouting(data);
        else if (requestedTab === 'matrix') { renderMatrix(data); refreshStereoFirewire(); }
        else {
          renderCrossbar(data);
          // Refresh the fader source labels after a router snapshot, including
          // changes made by a separate FFADO client while this page was open.
          if (window.refreshMatrixStrips) window.refreshMatrixStrips();
        }
      })
      .catch(e => {
        if (epoch === refreshEpoch && e.name !== 'AbortError') message('Unable to read hardware: ' + e.message);
        if (epoch === refreshEpoch && e.name !== 'AbortError' && throwOnError === true) throw e;
      })
      .finally(() => {
        if (epoch !== refreshEpoch) return;
        loading = false;
        refreshController = null;
        $('routingRefresh').disabled = matrixWriteBusy;
        if (matrixRefreshPending && !matrixWriteBusy && !inlineGesture && active === 'matrix') {
          matrixRefreshPending = false;
          refresh();
        }
      });
  }
  function close() {
    if (inlineGesture) {
      if (inlineGesture.pointer != null) cancelMatrixGesture();
      else commitMatrixGesture();
    }
    stopPendingRefresh();
    overlay.hidden = true; routeMeterStates.clear(); button.focus();
  }
  button.addEventListener("click", () => { overlay.hidden = false; changeTab(active); $("routingDialog").focus(); });
  $("routingClose").addEventListener("click", close);
  overlay.addEventListener("mousedown", e => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !overlay.hidden) close(); });
  if ($('routingStereoApply')) $('routingStereoApply').addEventListener('click', () => {
    if (stereoPlaybackBusy || matrixWriteBusy || inlineGesture) return;
    const source = $('routingStereoSource').value;
    const bus = Number($('routingStereoBus').value);
    const busText = $('routingStereoBus').selectedOptions?.[0]?.textContent || 'the selected buses';
    if (!Number.isInteger(bus) || !source) return;
    if (!window.confirm('Patch ' + source + ' and its Right channel into ' + busText +
        '? This sets both diagonal mixer volumes to 0 dB and the two cross-routes to silence. ' +
        'It can make audio louder. Lower monitor volume first.')) return;
    stereoPlaybackBusy = true;
    const apply = $('routingStereoApply'); apply.disabled = true;
    message('Applying stereo FireWire routing…');
    request('/api/stereo-firewire', {left_source: source, bus: bus})
      .then(result => {
        if (typeof window.refreshMatrixStrips === 'function') window.refreshMatrixStrips();
        // Refresh the hardware readback before announcing the completed
        // patch, so the normal matrix-refresh hint doesn't hide the result.
        matrixWriteEpoch++;
        return Promise.resolve(refresh()).then(() => message(
          result.pair + ' routed to ' + busText + ' with independent Left/Right outputs. ' +
          'Assign Mixer Output buses to your physical outputs separately in Crossbar Router.'));
      })
      .catch(error => { message('Stereo routing failed: ' + error.message); refresh(); })
      .finally(() => { stereoPlaybackBusy = false; apply.disabled = false; });
  });
  $("routingPhonesSelect").addEventListener("change", () => {
    if (phonesWriteBusy) return;
    const select = $("routingPhonesSelect");
    const value = Number(select.value);
    if (!Number.isInteger(value)) return;
    phonesWriteBusy = true;
    select.disabled = true;
    message('Changing Phones destination…');
    request('/api/phones-assignment', {value})
      .then(() => request('/api/bus-routing'))
      .then(data => {
        phonesWriteBusy = false;
        if (active === 'bus') renderBusRouting(data);
      })
      .catch(e => {
        const error = 'Phones assignment failed: ' + e.message;
        // Re-read the hardware; never leave a failed selection displayed.
        return request('/api/bus-routing').then(data => {
          phonesWriteBusy = false;
          if (active === 'bus') renderBusRouting(data);
          message(error);
        }).catch(() => message(error));
      })
      .finally(() => { phonesWriteBusy = false; select.disabled = false; });
  });
  tabs.bus.addEventListener("click", () => changeTab("bus"));
  tabs.matrix.addEventListener("click", () => changeTab("matrix"));
  tabs.crossbar.addEventListener("click", () => changeTab("crossbar"));
  $("routingRefresh").addEventListener("click", refresh);
  const knob=$('routingKnob');
  knob.addEventListener('pointerdown', e => {
    if (!isDb()) return;
    e.preventDefault();
    knob.setPointerCapture(e.pointerId);
    const initialY=e.clientY, initialDb=editorDb === null ? scale().min_db : editorDb;
    const move=ev => editDb(initialDb+(initialY-ev.clientY)*0.1);
    const done=() => { knob.removeEventListener('pointermove',move);
                      knob.removeEventListener('pointerup',done); knob.removeEventListener('pointercancel',done); };
    knob.addEventListener('pointermove',move);
    knob.addEventListener('pointerup',done);
    knob.addEventListener('pointercancel',done);
  });
  knob.addEventListener('wheel', e => {
    if (!isDb()) return;
    e.preventDefault(); nudgeDb(e.deltaY<0 ? (e.shiftKey?1:0.1) : (e.shiftKey?-1:-0.1));
  }, {passive:false});
  knob.addEventListener('keydown', e => {
    if (!isDb()) return;
    const step = e.shiftKey ? 1 : 0.1;
    if (e.key==='ArrowUp'||e.key==='ArrowRight') nudgeDb(step);
    else if (e.key==='ArrowDown'||e.key==='ArrowLeft') nudgeDb(-step);
    else if (e.key==='0'||e.key==='Home') editDb(0);
    else if (e.key==='m'||e.key==='M'||e.key==='End') editDb(null);
    else return;
    e.preventDefault();
  });
  $("routingLevel").addEventListener("input", () => {
    const percent = Number($("routingLevel").value);
    renderEditor(percent, isDb() ? uiToDb(percent) : undefined);
  });
  $("routingDb").addEventListener("input", () => {
    if (!isDb() || $("routingDb").value === "") return;
    const db = Number($("routingDb").value);
    if (Number.isFinite(db) && db >= scale().min_db && db <= scale().max_db) {
      editorDb = db; editorPercent = dbToUi(db);
      $("routingLevel").value = editorPercent;
      $("routingLevelLabel").textContent = formatDb(db);
      knob.querySelector('.routing-knob-needle').style.transform = 'rotate(' + (-135+270*editorPercent/100) + 'deg)';
    }
  });
  $("routingDb").addEventListener("keydown", e => {
    if (e.key === 'Enter') { e.preventDefault(); $("routingApply").click(); }
  });
  $("routingDb").addEventListener("wheel", e => {
    if (!isDb()) return;
    e.preventDefault(); nudgeDb(e.deltaY < 0 ? (e.shiftKey ? 1 : 0.1) : (e.shiftKey ? -1 : -0.1));
  }, {passive:false});
  $("routingPreset").addEventListener('change', () => {
    const preset = $("routingPreset").value;
    if (preset === '') return;
    editDb(preset === 'silence' ? null : Number(preset));
    $("routingPreset").value = "";
  });
  $("routingSilence").addEventListener("click", () => isDb() ? editDb(null) : renderEditor(0));
  $("routingUnity").addEventListener("click", () => isDb() ? editDb(0) : renderEditor(100));
  $("routingApply").addEventListener("click", () => {
    if (!selection) return;
    if (isDb() && $("routingDb").value !== "") {
      const entered = Number($("routingDb").value);
      if (!Number.isFinite(entered) || entered < scale().min_db || entered > scale().max_db) {
        message("Enter a valid dB value from " + scale().min_db + " to +" + scale().max_db + ", or use −∞.");
        return;
      }
      editorDb = entered <= scale().min_db ? null : entered;
    } else if (isDb() && editorDb !== null && $("routingDb").value === "") {
      message("Enter a dB value or use the −∞ preset."); return;
    }
    if (inlineGesture) {
      // The detailed editor's Apply is authoritative over a pending wheel
      // preview. Drop the staged gesture, then commit its exact value below.
      clearGestureTimer(); inlineGesture = null;
    }
    const { input, output, button: cell } = selection;
    const payload = isDb() ? { input, output, db: editorDb } :
      { input, output, value: editorPercent };
    writeMatrixValue(input, output, cell, payload);
  });
  window.configureRouting = function (info) {
    capabilities = { bus: !!info.bus_routing,
                     // When bus destinations exist, MOTU uses the main strips to
                     // set crosspoint gains; the In/Out button is routing only.
                     matrix: !info.bus_routing && !!(info.matrix && info.matrix.available && info.fader && info.fader.writable),
                     crossbar: !!info.router };
    $("routerbox").hidden = !capabilities.bus && !capabilities.matrix && !capabilities.crossbar;
    Object.keys(tabs).forEach(key => { tabs[key].hidden = !capabilities[key]; });
    active = capabilities.bus ? "bus" : capabilities.crossbar ? "crossbar" : "matrix";
  };
  window.routingSyncEvent = function (ev) {
    if (overlay.hidden) return;
    if (ev.type === 'resync') return refresh(true);
    if (active === "bus" && ev.type === "destination") return refresh();
    if (active === "matrix" && (ev.type === "matrix" || ev.type === "strip" || ev.type === "routing")) return refresh();
    if (active === "crossbar" && ev.type === "routing") return refresh();
  };
})();
