/* Device-native matrix and CrossbarRouter, driven exclusively by actual FFADO controls. */
(function () {
  "use strict";
  const $ = id => document.getElementById(id);
  const overlay = $("routingOverlay"), button = $("routingButton");
  const tabs = { bus: $("routingBusTab"), matrix: $("routingMatrixTab"), crossbar: $("routingCrossbarTab") };
  const panes = { bus: $("routingBus"), matrix: $("routingMatrix"), crossbar: $("routingCrossbar") };
  let capabilities = { bus: false, matrix: false, crossbar: false }, active = "matrix", matrix = null, selection = null;
  let loading = false;
  function message(s) { $("routingHint").textContent = s; }
  function uiDb(v) {
    if (v === 0) return "−∞ dB";
    if (!matrix || matrix.mode !== "dice_db") return v + "%";
    return (v * .66 - 60).toFixed(1) + " dB";
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
    return fetch(url, body === undefined ? { cache: "no-store" } :
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(async r => {
        const result = await r.json();
        if (!r.ok || result.error) throw new Error(result.error || "Hardware request failed");
        return result;
      });
  }
  function renderMatrix(data) {
    matrix = data;
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
        cell.textContent = uiDb(val);
        cell.classList.toggle("route-signal", val > 0);
        cell.title = name + " → " + outname;
        cell.addEventListener("click", () => {
          const previous = table.querySelector(".route-selected");
          if (previous) previous.classList.remove("route-selected");
          cell.classList.add("route-selected");
          selection = { input: i, output: o, button: cell };
          $("routingEditor").hidden = false;
          $("routingCellLabel").textContent = name + " → " + outname;
          $("routingLevel").value = val;
          $("routingLevelLabel").textContent = uiDb(val);
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
        const select = document.createElement("select");
        select.setAttribute("aria-label", "Source for " + dest);
        option(select, "Disconnected", "");
        data.sources.filter(src => src !== "").forEach(src => option(select, src, src));
        if (data.sources.indexOf(data.selected[dest]) < 0) option(select, data.selected[dest], data.selected[dest]);
        select.value = data.selected[dest];
        select.addEventListener("change", () => {
          const prev = data.selected[dest], next = select.value;
          select.disabled = true;
          request("/api/router", { destination: dest, source: next }).then(() => {
            data.selected[dest] = next;
            message(dest + " now receives " + next);
          }).catch(e => { select.value = prev; message("Could not route " + dest + ": " + e.message); })
            .finally(() => { select.disabled = false; });
        });
        row.append(label, select); card.appendChild(row);
      });
      root.appendChild(card);
    });
    message("Each destination receives one source. Changing a selector immediately changes hardware routing.");
  }
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
  function close() { overlay.hidden = true; button.focus(); }
  button.addEventListener("click", () => { overlay.hidden = false; changeTab(active); $("routingDialog").focus(); });
  $("routingClose").addEventListener("click", close);
  overlay.addEventListener("mousedown", e => { if (e.target === overlay) close(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && !overlay.hidden) close(); });
  tabs.bus.addEventListener("click", () => changeTab("bus"));
  tabs.matrix.addEventListener("click", () => changeTab("matrix"));
  tabs.crossbar.addEventListener("click", () => changeTab("crossbar"));
  $("routingRefresh").addEventListener("click", refresh);
  $("routingLevel").addEventListener("input", () => {
    $("routingLevelLabel").textContent = uiDb(Number($("routingLevel").value));
  });
  $("routingSilence").addEventListener("click", () => {
    $("routingLevel").value = 0;
    $("routingLevelLabel").textContent = uiDb(0);
  });
  $("routingUnity").addEventListener("click", () => {
    $("routingLevel").value = matrix && matrix.mode === "dice_db" ? Math.round(60 * 100 / 66) : 100;
    $("routingLevelLabel").textContent = uiDb(Number($("routingLevel").value));
  });
  $("routingApply").addEventListener("click", () => {
    if (!selection) return;
    const { input, output, button: cell } = selection, level = Number($("routingLevel").value);
    $("routingApply").disabled = true;
    request("/api/matrix", { input, output, value: level }).then(() => {
      matrix.values[input][output] = level;
      cell.textContent = uiDb(level);
      cell.classList.toggle("route-signal", level > 0);
      message("Updated " + matrix.inputs[input] + " → " + matrix.outputs[output]);
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
