// ---- live sync: changes made on other pages arrive here ----
function stripEl(id) {                          // a stereo strip answers to both of its channels
  return row.querySelector('.strip[data-id="' + id + '"], .strip[data-partner="' + id + '"]');
}

function applyLayout() {                         // order / pinned / minimized changed on another page
  if (row.querySelector(".dragging")) return;    // don't yank a strip out of the user's hand
  var mix = currentMix, device = ACTIVE_DEVICE;
  return window.ffadoApi.latest('sync-layout', '/api/layout?mix=' + mix, {device}).then(function (layout) {
    if (!layout || mix !== currentMix || device !== ACTIVE_DEVICE || row.querySelector('.dragging')) return;
    var current = Array.prototype.slice.call(row.querySelectorAll(':scope > .strip')), byId = {}, used = [], ordered = [];
    current.forEach(function (c) {
      byId[c.dataset.id] = c;
      if (c.dataset.partner) byId[c.dataset.partner] = c;
    });
    layout.forEach(function (entry) {
      var el = byId[entry.id];
      if (!el || used.indexOf(el) >= 0) return;
      used.push(el);
      ordered.push(el);
      setPinned(el, entry.pinned !== false);
      setMinimized(el, !!entry.minimized);
    });
    current.forEach(function (c) { if (used.indexOf(c) < 0) ordered.push(c); });   // not in the layout: keep at the end
    if (ordered.some(function (el, i) { return el !== current[i]; })) {
      ordered.forEach(function (el) { row.appendChild(el); });
    }
    if (lastStripState) renderLinkButtons(lastStripState);
  }).catch(function (error) { toast('Could not sync layout: ' + error.message); });
}

function onSyncEvent(ev) {
  if (ev.device && ACTIVE_DEVICE && ev.device !== ACTIVE_DEVICE) return;
  if (ev.type === 'resync') { requestSyncRefresh(); return; }
  if (window.routingSyncEvent) window.routingSyncEvent(ev);
  // Matrix writes change derived fader and pan values, including our own writes.
  // Always re-read the affected bus; a single crosspoint can change both.
  if (ev.type === "matrix") {
    if (ev.output === currentMix ||
        (STEREO_BUSES.includes(currentMix) && ev.output === currentMix + 1)) loadMix();
    return;
  }
  if (ev.type === "routing") {
    // A router source assigned to Mixer/In changes the hardware input name
    // beneath a fader. Refresh other browser windows; our own write already
    // refreshes the strips after verified readback in routing.js.
    if (ev.origin !== CLIENT_ID && String(ev.destination || '').startsWith('Mixer/In:'))
      loadMix();
    return;
  }
  if (ev.origin === CLIENT_ID) return;           // our own non-matrix change coming back
  var el;
  if (ev.type === "strip") {
    var shared = ev.control === "gain" || ev.control === "invert";    // belong to the channel, not to one bus
    if (!shared && ev.mix !== currentMix) return;
    // Another client's posted fader/pan value is not necessarily the native
    // FFADO readback, especially with a linked stereo bus or linked inputs.
    // Re-derive both controls from actual coefficients rather than replaying
    // the optimistic command value as though it were hardware state.
    if (["fader", "pan", "mute", "solo"].includes(ev.control)) { loadMix(); return; }
    el = stripEl(ev.strip);
    if (el) el._apply(ev.control, ev.value, ev.strip);
  } else if (ev.type === "name") {
    if (ev.strip.indexOf("out:") === 0) { applyOutputName(ev.strip.slice(4), ev.value); return; }
    el = stripEl(ev.strip);
    if (el) el._apply("name", ev.value, ev.strip);
  } else if (ev.type === "output") {
    if (ev.out !== currentOut) return;
    if (ev.control === "fader") masterFader.set(ev.value); else loadMaster();   // Main/Phones mute can move the level
  } else if (ev.type === 'bus-name') {
    var named = MIXES.find(x => x.id === ev.mix);
    if (named) named.name = ev.name;
    renderBusTabs();
  } else if (ev.type === 'bus-pair-name') {
    STEREO_BUS_NAMES[String(ev.left)] = ev.name;
    renderBusTabs();
  } else if (ev.type === 'bus-layout') {
    readJson('/api/bus-layout').then(function (items) {
      if (Array.isArray(items)) { busLayout = items; renderBusTabs(); }
    }).catch(function (error) { toast('Could not sync bus tabs: ' + error.message); });
  } else if (ev.type === "layout") {
    if (ev.mix === currentMix) applyLayout();     // another bus's arrangement doesn't concern this page
  } else if (ev.type === "bus-stereo") {
    requestSyncRefresh();
  } else if (ev.type === "stereo") {
    if (ev.mix !== undefined && ev.mix !== currentMix) return;
    if (!row.querySelector(".dragging")) loadMix();   // only this bus's pairs changed
  }
}

function refreshSyncState() {
  var device = ACTIVE_DEVICE;
  return Promise.all([
    readJson('/api/describe', device),
    readJson('/api/bus-layout', device)
  ]).then(function (data) {
    if (device !== ACTIVE_DEVICE) return;
    var info = data[0];
    if (device && info.guid !== device) throw Error('Selected mixer changed; reload this page');
    STEREO_BUSES = info.stereo_buses || [];
    STEREO_BUS_NAMES = info.stereo_bus_names || {};
    MIXES = (info.mixes || []).map(function (mix) {
      return Object.assign({}, mix, {name: shortFfadoLabel(mix.name)});
    });
    OUTPUTS = (info.outputs || []).map(function (out) {
      return {id: out.id, name: shortFfadoLabel(out.name), baseName: out.base_name || out.name,
              mix: out.mix == null ? null : out.mix, controllable: out.controllable,
              destination: !!out.destination};
    });
    busLayout = Array.isArray(data[1]) ? data[1] : [];
    // A missed stereo-link event can turn the selected Right bus into the
    // hidden half of a pair. Keep the current view on its visible Left bus.
    if (currentMix % 2 && STEREO_BUSES.includes(currentMix - 1)) currentMix--;
    buildOutputs();
    markOutputs();
    loadDevices();
    return Promise.all([
      loadMix({throwOnError: true}), loadMaster({throwOnError: true}),
      window.routingSyncEvent ? window.routingSyncEvent({type: 'resync', device: device}) : null
    ]);
  });
}

var syncSource = null, syncRefresh = null, syncAgain = false, syncRetry = null;
function requestSyncRefresh() {
  syncAgain = true;
  if (syncRefresh) return syncRefresh;
  clearTimeout(syncRetry);
  syncRetry = null;
  function refresh() {
    syncAgain = false;
    return Promise.resolve().then(refreshSyncState).then(function () {
      // Changes arriving while a snapshot is read may be newer than it.
      // Re-read after those changes instead of replaying stale deltas over it.
      if (syncAgain) return refresh();
    });
  }
  syncRefresh = refresh().catch(function (error) {
    toast('Could not synchronize mixer: ' + error.message);
    syncRetry = setTimeout(requestSyncRefresh, 1000);
  }).finally(function () { syncRefresh = null; });
  return syncRefresh;
}

function startSync() {
  if (syncSource) return syncSource;
  var url = '/api/events' + (ACTIVE_DEVICE ? '?device=' + encodeURIComponent(ACTIVE_DEVICE) : '');
  syncSource = new EventSource(url);
  syncSource.onmessage = function (message) {
    var event;
    try { event = JSON.parse(message.data); }
    catch (error) { requestSyncRefresh(); return; }
    if (!event || typeof event !== 'object') { requestSyncRefresh(); return; }
    if (event.device && ACTIVE_DEVICE && event.device !== ACTIVE_DEVICE) return;
    if (event.type === 'resync') { requestSyncRefresh(); return; }
    if (syncRefresh) { syncAgain = true; return; }
    try { onSyncEvent(event); }
    catch (error) { requestSyncRefresh(); }
  };
  // Initial connection closes the gap between startup reads and subscription;
  // subsequent connections recover every view affected by missed events.
  syncSource.onopen = requestSyncRefresh;
  return syncSource;
}
