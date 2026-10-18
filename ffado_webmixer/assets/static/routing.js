/* Device-native matrix and CrossbarRouter, driven exclusively by actual FFADO controls. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const overlay = $("routingOverlay"), button = $("routingButton");
  const tabs = { bus: $("routingBusTab"), matrix: $("routingMatrixTab"), crossbar: $("routingCrossbarTab") };
  const panes = { bus: $("routingBus"), matrix: $("routingMatrix"), crossbar: $("routingCrossbar") };
  let capabilities = { bus: false, matrix: false, crossbar: false }, active = "matrix", matrix = null, selection = null;
  let loading = false;
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
    return (db > 0 ? "+" : "") + db.toFixed(1) + " dB";
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
    active = name;
    Object.keys(tabs).forEach(key => {
      panes[key].hidden = name !== key;
      tabs[key].classList.toggle("routing-active", name === key);
      tabs[key].setAttribute("aria-pressed", name === key ? "true" : "false");
    });
    refresh();
  }
  function request(url, body) {
    return fetch(url, body === undefined ? { cache: "no-store", headers:
        window.activeFfadoDevice ? {"X-FFADO-Device": window.activeFfadoDevice} : {} } :
      { method: "POST", headers: { "Content-Type": "application/json", "X-FFADO-Device": window.activeFfadoDevice || "" },
        body: JSON.stringify(body) })
      .then(async r => {
        const result = await r.json();
        if (!r.ok || result.error) throw new Error(result.error || "Hardware request failed");
        return result;
      });
  }
  function renderMatrix(data) {
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
    data.outputs.forEach(name => { th = document.createElement("th"); th.textContent = name; top.appendChild(th); });
    head.appendChild(top); table.appendChild(head);
    const body = document.createElement("tbody");
    data.inputs.forEach((name, i) => {
      const tr = document.createElement("tr"), label = document.createElement("th");
      label.textContent = name; tr.appendChild(label);
      data.outputs.forEach((outname, o) => {
        const td = document.createElement("td"), cell = document.createElement("button");
        cell.type = "button";
        const val = data.values[i][o];
        const db = isDb() ? data.db_values[i][o] : undefined;
        cell.textContent = uiDb(val, db);
        cell.classList.toggle("route-signal", val > 0);
        cell.title = name + " → " + outname;
        cell.addEventListener("click", () => {
          const previous = table.querySelector(".route-selected");
          if (previous) previous.classList.remove("route-selected");
          cell.classList.add("route-selected");
          selection = { input: i, output: o, button: cell };
          $("routingEditor").hidden = false;
          $("routingCellLabel").textContent = name + " → " + outname;
          renderEditor(data.values[i][o], isDb() ? data.db_values[i][o] : undefined);
        });
        cell.addEventListener("dblclick", () => {
          cell.click();
          if (isDb()) editDb(0); else renderEditor(100);
          message("Unity selected for this crosspoint. Press Apply to write to hardware.");
        });
        td.appendChild(cell); tr.appendChild(td);
      });
      body.appendChild(tr);
    });
    table.appendChild(body);
    message("Matrix levels are gains, not router assignments. Select a cell to edit it; Apply writes to hardware.");
  }
  // The MOTU Mk1/Mk2 has four per-bus Discrete Mix_dest selectors. Those
  // choose one hardware output per bus and never alter crosspoint gain. This
  // grid's columns are mix buses; rows are the real available destinations.
  function renderBusRouting(data) {
    const table = $("routingBusGrid");
    table.replaceChildren();
    const head = document.createElement("thead"), hr = document.createElement("tr");
    const corner = document.createElement("th"); corner.textContent = "Outputs ↓ / Buses →";
    hr.appendChild(corner);
    data.buses.forEach(bus => {
      const th = document.createElement("th"); th.scope = "col"; th.textContent = bus.name; hr.appendChild(th);
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
      "Select one output for each mix bus. Only hardware routing changes; input gains remain untouched.");
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
      const h = document.createElement("h3"); h.textContent = name; card.appendChild(h);
      destinations.forEach(dest => {
        const row = document.createElement("div"); row.className = "route-row";
        const label = document.createElement("label"); label.textContent = dest;
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
        data.sources.filter(src => src !== "" && !src.startsWith('Mute:')).forEach(src => option(select, src, src));
        if (data.sources.indexOf(data.selected[dest]) < 0 && !data.selected[dest].startsWith('Mute:')) option(select, data.selected[dest], data.selected[dest]);
        select.value = data.selected[dest].startsWith('Mute:') ? '' : data.selected[dest];
        select.addEventListener("change", () => {
          const prev = data.selected[dest], next = select.value;
          select.disabled = true;
          request("/api/router", { destination: dest, source: next }).then(() => {
            data.selected[dest] = next;
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
      meter.querySelector('.route-peak-fill').style.width = (value.level * 100).toFixed(2) + '%';
      meter.querySelector('.route-peak-hold').style.left = (state.level * 100).toFixed(2) + '%';
      meter.classList.toggle('clipping', now < state.clipUntil);
      meter.querySelector('.route-peak-db').textContent = value.db === null ? '−∞' : value.db.toFixed(1) + ' dB';
      meter.title = name + ' peak relative to FFADO full scale (not calibrated dBFS). Click to clear hold.';
    });
  });
  function refresh() {
    if (loading) return;
    loading = true;
    $("routingRefresh").disabled = true;
    message("Reading current FFADO hardware values…");
    request(active === "bus" ? "/api/bus-routing" : active === "matrix" ? "/api/matrix" : "/api/router")
      .then(active === "bus" ? renderBusRouting : active === "matrix" ? renderMatrix : renderCrossbar)
      .catch(e => message("Unable to read hardware: " + e.message))
      .finally(() => { loading = false; $("routingRefresh").disabled = false; });
  }
  function close() { overlay.hidden = true; routeMeterStates.clear(); button.focus(); }
  button.addEventListener("click", () => { overlay.hidden = false; changeTab(active); $("routingDialog").focus(); });
  $("routingClose").addEventListener("click", close);
  overlay.addEventListener("mousedown", e => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !overlay.hidden) close(); });
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
    const { input, output, button: cell } = selection;
    const payload = isDb() ? {input, output, db: editorDb} :
                           {input, output, value: editorPercent};
    $("routingApply").disabled = true;
    request("/api/matrix", payload).then(result => {
      matrix.values[input][output] = result.value;
      if (isDb()) matrix.db_values[input][output] = result.db;
      cell.textContent = uiDb(result.value, result.db);
      cell.classList.toggle("route-signal", result.value > 0);
      renderEditor(result.value, isDb() ? result.db : undefined);
      message((result.deferred ? "Saved for unmute: " : "Hardware readback: ") +
              matrix.inputs[input] + " → " + matrix.outputs[output] +
              " = " + uiDb(result.value, result.db));
    }).catch(e => message("Could not set matrix level: " + e.message))
      .finally(() => { $("routingApply").disabled = false; });
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
    if (active === "bus" && ev.type === "destination") refresh();
    if (active === "matrix" && (ev.type === "matrix" || ev.type === "strip")) refresh();
    if (active === "crossbar" && ev.type === "routing") refresh();
  };
})();
