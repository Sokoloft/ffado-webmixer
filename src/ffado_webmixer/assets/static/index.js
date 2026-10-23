var row = document.getElementById("row");
var FEATURES = {};
var FADER_ALLOWED = true;
var MUTE_ALLOWED = true;
var OUTPUTS = [];
var MIXES = [];
var GAIN_SCALE = null;
var STEREO_BUSES = [];
var STEREO_BUS_NAMES = {};
var ACTIVE_DEVICE = null;
var currentMix = 0;       // which bus the channel strips show
var currentOut = "";      // which output the master fader controls (Main, Phones or a bus)

function fmtGain(v) { return (v >= 0 ? "+" : "") + v; }

// ---- server calls ----
var CLIENT_ID = Math.random().toString(36).slice(2) + Date.now().toString(36);
function post(url, body, device = ACTIVE_DEVICE) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Client-Id": CLIENT_ID,
                                 "X-FFADO-Device": device || "" },
                      body: JSON.stringify(body) });
}
// Device-specific reads must never silently return another unit when two
// tabs of the same browser share a session cookie and one changes devices.
function deviceFetch(url) {
  return fetch(url, {cache: "no-store", headers: ACTIVE_DEVICE ? {"X-FFADO-Device": ACTIVE_DEVICE} : {}});
}

// One error contract for HTTP failures, JSON errors, and application-level
// {error: ...} responses. The native mixer writes still use post()/send().
function postJson(url, body, device = ACTIVE_DEVICE) {
  return window.ffadoApi.request(url, {body, device, clientId: CLIENT_ID});
}
function readJson(url, device = ACTIVE_DEVICE) {
  return window.ffadoApi.request(url, {device});
}
function savePreference(key, body, confirmed, rejected, notify = false) {
  var device = ACTIVE_DEVICE;
  return window.ffadoApi.serial('settings|' + (device || '') + '|' + key, function () {
    return postJson('/api/settings', body, device);
  }).then(function (data) {
    if (confirmed) confirmed(data);
    if (notify) toast('Saved ' + key + '.');
    return data;
  }).catch(function (error) {
    if (rejected) rejected();
    toast('Could not save ' + key + ': ' + error.message);
    return null;
  });
}

function send(strip, control, value, mix = currentMix, device = ACTIVE_DEVICE) {
  return post("/api/set", { strip: strip, control: control, value: value, mix: mix }, device)
    .then(function (r) { return r.json().then(function (d) { if (!r.ok || d.error) throw Error(d.error || "FFADO rejected the change"); }); })
    .catch(function (e) {
      toast("Mixer change failed: " + e.message);
      // Never refresh a newly selected bus because an old bus's write failed.
      if (mix === currentMix && device === ACTIVE_DEVICE) { loadMuteRecovery(); loadMix(); }
    });
}
// Other UI controls retain their existing 50 ms leading/trailing throttle.
var pendingVals = {}, sendTimers = {};
function throttled(key, value, fn) {
  if (sendTimers[key]) { pendingVals[key] = value; return; }
  fn(value);
  sendTimers[key] = setTimeout(function () {
    sendTimers[key] = null;
    if (key in pendingVals) { var v = pendingVals[key]; delete pendingVals[key]; fn(v); }
  }, 50);
}
// Capture bus and GUID at the user gesture, not at the timer callback.
// Serialize writes to each control: a slow first D-Bus request must not
// overtake the latest fader position and leave the hardware at a stale level.
var queuedControlWrites = Object.create(null);
function sendThrottled(strip, control, value, mix = currentMix, device = ACTIVE_DEVICE) {
  var key = [device || "", mix, strip, control].join("|");
  var state = queuedControlWrites[key];
  if (!state) state = queuedControlWrites[key] = { busy: false, timer: null, next: undefined, started: 0 };
  state.next = value;
  function pump() {
    if (state.busy || state.timer || state.next === undefined) return;
    var delay = Math.max(0, 50 - (Date.now() - state.started));
    if (delay) {
      state.timer = setTimeout(function () { state.timer = null; pump(); }, delay);
      return;
    }
    var next = state.next;
    state.next = undefined;
    state.busy = true;
    state.started = Date.now();
    Promise.resolve(send(strip, control, next, mix, device)).finally(function () {
      state.busy = false;
      if (state.next !== undefined) pump();
      else delete queuedControlWrites[key];
    });
  }
  pump();
}

// Interrupted software mute/solo is journaled per FireWire GUID. No automatic
// restoration: recovering nonzero gains after a reboot could be dangerously loud.
function loadMuteRecovery() {
  window.ffadoApi.latest('mute-recovery', '/api/mute-recovery', {device: ACTIVE_DEVICE}).then(data => {
    if (!data) return;
    var bar = document.getElementById('muteRecovery');
    var message = document.getElementById('muteRecoveryText');
    bar.hidden = !data.pending && !data.fault;
    if (data.pending) {
      message.textContent = data.pending + ' channel/output level(s) were saved by an interrupted mute/solo session. ' +
        'Restoring may raise output volume. Lower monitor levels before choosing Restore; ' +
        'Keep current levels only forgets saved mixer volume levels.';
    } else if (data.fault) {
      message.textContent = data.fault + (data.corrupt ?
        ' The journal cannot be safely restored. Keep current levels discards the unreadable record.' :
        ' Keep current levels dismisses this warning without writing to the hardware.');
    }
    bar.querySelector('.mute-recovery-actions').hidden = !data.pending && !data.fault && !data.corrupt;
    document.getElementById('muteRestore').hidden = !data.pending || !!data.corrupt;
  }).catch(e => console.warn('Could not check mute recovery:', e));
}
function muteRecoveryAction(action) {
  if (action === 'restore' && !window.confirm('Restore previously muted channel levels? ' +
      'This may make the speakers louder. Lower your monitoring volume first.')) return;
  post('/api/mute-recovery', {action: action}).then(r => r.json().then(data => {
    if (!r.ok || data.error) throw Error(data.error || 'Recovery failed');
    if (data.failed) toast(data.failed + ' mixer volume level(s) could not be restored. Try again after checking FFADO.');
    loadMuteRecovery();
    loadMix();
  })).catch(e => toast('Recovery failed: ' + e.message));
}
document.getElementById('muteRestore').addEventListener('click', () => muteRecoveryAction('restore'));
document.getElementById('muteDiscard').addEventListener('click', () => muteRecoveryAction('discard'));

// ---- mouse wheel: one notch = one step. Returns +1 (wheel up), -1 (wheel down) or 0 (not enough yet;
// trackpads send many small deltas, so they are accumulated). Shift+wheel arrives as deltaX in browsers.
function wheelDir(e, acc) {
  var d = e.deltaY !== 0 ? e.deltaY : e.deltaX;
  if (e.deltaMode === 1) d *= 33;
  else if (e.deltaMode === 2) d *= 400;
  else d *= window.devicePixelRatio || 1;       // pixel deltas shrink on scaled / zoomed displays; undo that
  acc.v += d;
  if (Math.abs(acc.v) < 60) return 0;
  acc.v = 0;
  return d < 0 ? 1 : -1;
}

// ---- layout = DOM order + each strip's pinned / minimized flags ----
var layoutRevisions = Object.create(null);
function isPinned(el) { return el.classList.contains("pinned"); }
function isMin(el) { return el.classList.contains("minimized"); }
function saveLayout() {
  var layout = Array.prototype.map.call(row.querySelectorAll(":scope > .strip"), function (s) {
    return { id: s.dataset.id, pinned: isPinned(s), minimized: isMin(s) };
  });
  var mix = currentMix, device = ACTIVE_DEVICE;
  var key = 'layout|' + (device || '') + '|' + mix;
  var revision = layoutRevisions[key] = (layoutRevisions[key] || 0) + 1;
  return window.ffadoApi.serial(key, function () {
    return postJson('/api/layout?mix=' + mix, layout, device);
  }).catch(function (error) {
    toast('Could not save channel layout: ' + error.message);
    // Read the server's confirmed layout. Do not overwrite another bus or
    // interrupt a newer drag/resize gesture.
    if (revision === layoutRevisions[key] && mix === currentMix &&
        device === ACTIVE_DEVICE && !row.querySelector('.dragging')) applyLayout();
    return null;
  });
}

var toastTimer = null;
function toast(message) {
  var t = document.getElementById("toast");
  t.textContent = message;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { t.hidden = true; }, 3500);
}

var EYE_OPEN = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/>' +
  '<circle cx="12" cy="12" r="3"/></svg>';
var EYE_SHUT = EYE_OPEN.replace("</svg>", '<path d="M3 3l18 18"/></svg>');
var CHAIN_LINK_SVG = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>' +
  '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
var PIN_SVG = '<svg viewBox="0 0 24 24" width="14" height="14"><path fill="currentColor" ' +
  'd="M9 3h6l-1 6 3 3v2h-4v7l-1 1-1-1v-7H7v-2l3-3z"/></svg>';

function vertical(text) { return Array.from(text).join("\n"); }
function updateMinCount() {
  var n = row.querySelectorAll(".strip.minimized").length;
  document.getElementById("minCount").textContent = n ? "(" + n + ")" : "";
}
function setMinimized(el, min) {
  el.classList.toggle("minimized", min);
  var btn = el.querySelector(".strip-more");
  if (btn) btn.title = min ? "Channel actions (minimized)" : "Channel actions";
  el.querySelector(".vname").textContent = vertical(el.querySelector(".name").value);
  updateMinCount();
}
function setPinned(el, pinned) {
  el.classList.toggle("pinned", pinned);
  var btn = el.querySelector(".strip-more");
  if (btn) btn.setAttribute('aria-label', pinned ? 'Channel actions (pinned)' : 'Channel actions');
  el.querySelector(".grip").title = pinned ? "" : "Drag to move";
}

// ---- drag: only unpinned strips can be picked up, but they can be dropped anywhere,
// including between pinned strips (which keep their relative order and shift over).
function place(el, over, after) {
  if (over) row.insertBefore(el, after ? over.nextSibling : over);
  else row.appendChild(el);
}
// Link buttons are available on every mono channel. First click picks Left,
// second click picks Right, regardless of number or saved strip order.
var pendingStereoLeft = null;
var pendingStereoMix = null;
var stereoLinkBusy = false;
// Disable all pair controls while a mutation is in flight. A quick second
// click or an unlink from another strip must never submit a competing action.
function setStereoLinkBusy(busy) {
  stereoLinkBusy = busy;
  row.querySelectorAll('.strip .strip-more').forEach(function (button) {
    button.disabled = busy;
  });
}
function stereoResponse(r) {
  return r.json().then(function (res) {
    if (!r.ok || res.error) throw Error(res.error || 'Stereo operation rejected');
    return res;
  });
}
function linkStrips(left, right) {
  if (stereoLinkBusy) return Promise.resolve();
  var bus = currentMix;
  pendingStereoLeft = null;
  setStereoLinkBusy(true);
  return post("/api/stereo?mix=" + bus, {action:"link", dragged:left, target:right})
    .then(stereoResponse)
    .catch(function (error) { toast("Couldn't link: " + error.message); })
    .then(function () { if (bus === currentMix) return loadMix(); })
    .finally(function () { setStereoLinkBusy(false); });
}
function chooseStereoChannel(id) {
  if (stereoLinkBusy) return;
  // The old bus remains on screen briefly during a bus change. Do not let
  // the user accidentally create a pair on a different bus in that window.
  if (lastStripMix !== null && lastStripMix !== currentMix) return;
  if (!lastStripState || !lastStripState[id] ||
      lastStripState[id].partner || lastStripState[id].partner_of) {
    pendingStereoLeft = null;
    toast('Channel is already paired or unavailable. Refreshing mixer.');
    loadMix();
    return;
  }
  if (pendingStereoMix !== currentMix) {
    pendingStereoLeft = null;
    pendingStereoMix = currentMix;
  }
  if (pendingStereoLeft === id) {
    pendingStereoLeft = null;
  } else if (pendingStereoLeft === null) {
    pendingStereoLeft = id;
    var number = parseInt(id.split('/')[1], 10);
    toast('Left: ' + (Number.isNaN(number) ? id : number + 1) + '. Choose the Right channel.');
  } else {
    var left = pendingStereoLeft;
    if (!lastStripState[left] || lastStripState[left].partner || lastStripState[left].partner_of) {
      pendingStereoLeft = null;
      toast('Left channel is no longer available. Select it again.');
      loadMix();
      return;
    }
    linkStrips(left, id);
  }
  if (lastStripState) renderLinkButtons(lastStripState);
}
function unlinkStrip(id) {
  if (stereoLinkBusy) return Promise.resolve();
  var bus = currentMix;
  setStereoLinkBusy(true);
  return post("/api/stereo?mix=" + bus, {action:"unlink", id: id})
    .then(stereoResponse)
    .catch(function (error) { toast("Couldn't unlink: " + error.message); })
    .then(function () { if (bus === currentMix) return loadMix(); })
    .finally(function () { setStereoLinkBusy(false); });
}

function startDrag(el, e) {
  if (isPinned(el)) return;
  e.preventDefault();
  el.classList.add("dragging");
  function move(ev) {
    var t = document.elementFromPoint(ev.clientX, ev.clientY);
    if (!t) return;
    var over = t.closest(".strip");
    if (over && over !== el && over.parentNode === row) {
      var r = over.getBoundingClientRect(), frac = (ev.clientX - r.left) / r.width;
      place(el, over, frac > 0.5);
    } else {
      if (!over && t === row) {
        var last = row.lastElementChild;
        if (last && ev.clientX > last.getBoundingClientRect().right) place(el, null, true);
      }
    }
  }
  function up() {
    document.removeEventListener("pointermove", move);
    document.removeEventListener("pointerup", up);
    document.removeEventListener("pointercancel", up);
    el.classList.remove("dragging");
    saveLayout();  // dragging only reorders; linking uses bottom-right buttons
  }
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", up);
  document.addEventListener("pointercancel", up);
}

// ---- fader: preserve the existing 0..100 API, but edit native dB where available ----
function faderHasDbScale() {
  return !!(GAIN_SCALE && (GAIN_SCALE.mode === "dice_db" || GAIN_SCALE.mode === "rme_db"));
}
function formatFaderDb(db) {
  if (db === null) return "−∞ dB";
  // Decide the sign *after* rounding. Values near unity must display 0.0,
  // never -0.0 or +0.0 (including negative zero).
  var rounded = Math.round(db * 10) / 10;
  return (rounded > 0 ? "+" : "") + rounded.toFixed(1) + " dB";
}
function faderUiToDb(ui) {
  return ui <= 0 ? null : GAIN_SCALE.min_db + ui * (GAIN_SCALE.max_db - GAIN_SCALE.min_db) / 100;
}
function parseFaderEntry(text) {
  var input = String(text).trim().replace(/−/g, "-");
  if (faderHasDbScale() && (/^-∞(?:\s*dB)?$/i.test(input) || /^-inf(?:inity)?(?:\s*dB)?$/i.test(input))) {
    return {ok: true, value: 0};
  }
  var match = /^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(dB|%)?$/i.exec(input);
  if (!match) return {ok: false};
  var entered = Number(match[1]);
  if (!Number.isFinite(entered)) return {ok: false};
  if (faderHasDbScale()) {
    if (match[2] === "%" || entered < GAIN_SCALE.min_db || entered > GAIN_SCALE.max_db) return {ok: false};
    return {ok: true, value: entered <= GAIN_SCALE.min_db ? 0 :
      100 * (entered - GAIN_SCALE.min_db) / (GAIN_SCALE.max_db - GAIN_SCALE.min_db)};
  }
  // Devices without a declared dB scale still use the historical percent/0..100 editor.
  if ((match[2] && match[2].toLowerCase() === "db") || entered < 0 || entered > 100) return {ok: false};
  return {ok: true, value: entered};
}
function makeFader(track, handle, label, onChange, canEdit = function () { return true; }) {
  var value = 0, dragging = false, editing = false;
  function render() {
    handle.style.top = (100 - value) + "%";
    if (!editing) label.value = faderHasDbScale() ? formatFaderDb(faderUiToDb(value)) :
      (value === 0 ? "−∞" : String(value));
  }
  function setValue(v) {
    if (!canEdit()) return;
    var precise = faderHasDbScale();
    value = Math.min(100, Math.max(0, precise ? Math.round(v * 10000) / 10000 : Math.round(v)));
    render();
    onChange(value);
  }
  label.addEventListener("focus", function () {
    if (label.dataset?.gestureEdit === "locked") return;
    label.readOnly = !canEdit();
    if (label.readOnly) { label.blur(); return; }
    editing = true;
    label.select();
  });
  label.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { e.preventDefault(); editing = false; label.blur(); render(); }
    else if (e.key === "Enter") {
      e.preventDefault();
      if (!canEdit()) { editing = false; label.blur(); render(); return; }
      var parsed = parseFaderEntry(label.value);
      editing = false;
      if (parsed.ok) setValue(parsed.value);
      else toast(faderHasDbScale() ?
        "Invalid volume: enter " + GAIN_SCALE.min_db + " to +" + GAIN_SCALE.max_db + " dB, or −∞." :
        "Invalid volume: enter a value from 0 to 100.");
      label.blur();
      render();
    }
  });
  // Leaving the box without Enter cancels an unfinished entry.
  label.addEventListener("blur", function () { editing = false; render(); });
  if (window.ffadoProtectEditable) window.ffadoProtectEditable(label);
  handle.addEventListener("pointerdown", function (e) {
    if (!canEdit()) return;
    handle.setPointerCapture(e.pointerId);
    dragging = true;
    function move(ev) {
      var rect = track.getBoundingClientRect();
      setValue(100 * (1 - (ev.clientY - rect.top) / rect.height));
    }
    function up() {
      dragging = false;
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
    }
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
    e.preventDefault();
  });
  // Double-clicking the handle or the fader track restores unity (0 dB),
  // *not* the silent end of the slider. Legacy percent devices have no calibrated unity.
  track.parentNode.addEventListener("dblclick", function (e) {
    if (!canEdit() || !faderHasDbScale()) return;
    e.preventDefault();
    setValue(100 * (0 - GAIN_SCALE.min_db) / (GAIN_SCALE.max_db - GAIN_SCALE.min_db));
  });
  // wheel over the fader: 2 per notch, 1 with Shift held
  var acc = { v: 0 };
  track.parentNode.addEventListener("wheel", function (e) {
    if (!canEdit()) return;
    e.preventDefault();
    var dir = wheelDir(e, acc);
    if (dir) setValue(value + dir * (GAIN_SCALE ? (e.shiftKey ? 0.15 : 0.75) : (e.shiftKey ? 1 : 2)));
  }, { passive: false });
  return { set: function (v) {
    if (dragging) return;
    value = Math.min(100, Math.max(0, faderHasDbScale() ? Number(v) : Math.round(v)));
    render();
  } };
}

// ---- a gain box: shown as +20, typed as 20 or +20; Up/Down arrows and the mouse wheel nudge it ----
function bindGain(inputEl, chId, initial, mix, device) {
  var gmin = FEATURES.gain.min, gmax = FEATURES.gain.max, gain = initial, acc = { v: 0 };
  var missing = function () { return gain === undefined || gain === null; };
  inputEl.disabled = !FEATURES.gain.writable;
  inputEl.value = missing() ? "" : fmtGain(gain);
  inputEl.classList.toggle("na", missing());
  function commit(v, rapid) {
    if (isNaN(v) || missing()) { inputEl.value = missing() ? "" : fmtGain(gain); return; }
    gain = Math.max(gmin, Math.min(gmax, v));
    inputEl.value = fmtGain(gain);
    sendThrottled(chId, "gain", gain, mix, device);
  }
  inputEl.addEventListener("wheel", function (e) {            // wheel over the box: +/-1 per notch
    if (inputEl.disabled || missing()) return;
    e.preventDefault();
    var dir = wheelDir(e, acc);
    if (dir) commit(gain + dir, true);
  }, { passive: false });
  inputEl.addEventListener("focus", function () { if (inputEl.dataset?.gestureEdit !== "locked") inputEl.select(); });
  if (window.ffadoProtectEditable) window.ffadoProtectEditable(inputEl);
  inputEl.addEventListener("change", function () { commit(parseInt(inputEl.value.replace(/[^\d-]/g, ""), 10)); });
  inputEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") inputEl.blur();
    else if (e.key === "ArrowUp" && !missing()) { e.preventDefault(); commit(gain + 1); }
    else if (e.key === "ArrowDown" && !missing()) { e.preventDefault(); commit(gain - 1); }
  });
  return { set: function (v) { if (document.activeElement !== inputEl) { gain = v; inputEl.value = fmtGain(v); } } };
}

// ---- build one channel strip. `partner` (the right channel's data) makes it a stereo strip ----
function buildStrip(id, data, pinned, minimized, partner) {
  // Keep old DOM gestures on the bus/device that rendered this strip.
  var stripMix = currentMix, stripDevice = ACTIVE_DEVICE;
  var stereo = !!partner, pid = stereo ? data.partner : null;
  var el = document.createElement("div");
  el.className = "strip" + (stereo ? " stereo" : "") + (data.mute ? " muted" : "") + (data.solo ? " soloed" : "");
  el.dataset.id = id;
  if (stereo) {
    el.dataset.partner = pid;
    el.title = 'Stereo inputs — Left: ' + (data.input || id) + ', Right: ' + (partner.input || pid);
  }
  el.innerHTML =
    '<div class="grip">::::</div>' +
    '<button class="strip-more" type="button" title="Channel actions" aria-label="Channel actions" aria-haspopup="menu">⋮</button>' +
    '<div class="vname"></div>' +
    '<div class="gaininv"><div class="gainrow" title="Hardware input gain/trim, separate from digital mixer volume"><div class="cap">INPUT GAIN</div>' +
      '<div class="gainboxes"><input class="gain" type="text" inputmode="numeric" autocomplete="off" spellcheck="false" aria-label="Hardware input gain"></div></div>' +
      '<button class="invert" title="Polarity (invert)">\u00D8</button></div>' +
    '<div class="panrow"><div class="caprow"><span>PAN</span><span class="panval">0</span></div>' +
      '<input class="pan" type="range" min="-100" max="100" step="1" value="0" title="Double-click to center"></div>' +

    '<input class="name" maxlength="16" spellcheck="false" title="Rename">' +
    '<button class="btn solo">Solo</button>' +
    '<input class="fval" type="text" inputmode="decimal" autocomplete="off" spellcheck="false" aria-label="Digital mixer volume" title="Right-click or long-press to edit volume; Enter applies, Escape cancels">' +
    '<div class="faderwrap"><div class="track" title="Digital mixer volume"><div class="handle"></div></div>' +
      '<button type="button" class="peak-meter" hidden title="FFADO router destination peak (not post-fader)" aria-label="Clear peak holds">' +
        '<span class="peak-lane" data-side="left"><span class="peak-bar"></span><span class="peak-hold"></span><span class="peak-clip"></span></span>' +
        (stereo ? '<span class="peak-lane" data-side="right"><span class="peak-bar"></span><span class="peak-hold"></span><span class="peak-clip"></span></span>' : '') +
      '</button></div>' +
    '<button class="btn mute">Mute</button>' +
    '<div class="inname" title="Hardware input"></div>';

  var q = function (sel) { return el.querySelector(sel); };
  var nameEl = q(".name"), invertEl = q(".invert");
  var panEl = q(".pan"), panVal = q(".panval"), soloEl = q(".solo");
  // Do not turn an unavailable hardware balance (null) into fake center.
  var panAvailable = data.pan !== null && data.pan !== undefined &&
    Number.isFinite(Number(data.pan)) && data.pan_available !== false;
  var pan = panAvailable ? Number(data.pan) : 0;
  var missing = function (v) { return v === undefined || v === null; };

  // which controls this device offers (and which this particular channel has)
  var matrixPairNeedsBus = stereo && GAIN_SCALE &&
    ["dice_db", "rme_db"].includes(GAIN_SCALE.mode) && !STEREO_BUSES.includes(currentMix);
  // A linked DICE input has no native per-channel pan. Display the
  // requirement instead of dispatching partial/nonexistent hardware writes.
  q(".panrow").hidden = !FEATURES.pan && !STEREO_BUSES.includes(currentMix) && !stereo;
  if (stereo) invertEl.title = "Polarity of both channels";
  soloEl.hidden = !FEATURES.solo && !(FEATURES.software_solo);
  q(".mute").hidden = !MUTE_ALLOWED;
  q(".faderwrap").classList.toggle("read-only", !FADER_ALLOWED);
  q(".gainrow").hidden = !FEATURES.gain;
  invertEl.hidden = !FEATURES.invert;
  q(".gaininv").hidden = !FEATURES.gain && !FEATURES.invert;
  q(".gainrow").classList.toggle("na", missing(data.gain) && (!stereo || missing(partner.gain)));
  invertEl.classList.toggle("na", missing(data.invert) && (!stereo || missing(partner.invert)));
  q(".inname").textContent = shortFfadoLabel(data.input || "");

  // rename (the label above the solo button): Enter saves, Esc reverts. A stereo pair is named under its left channel.
  nameEl.value = shortFfadoLabel(data.name);
  var lastName = nameEl.value;
  nameEl.addEventListener("change", function () {
    var n = nameEl.value.trim() || lastName;
    var previous = lastName, mix = stripMix, device = stripDevice;
    nameEl.value = n;
    q('.vname').textContent = vertical(n);
    window.ffadoApi.serial('name|' + (device || '') + '|' + id, function () {
      return postJson('/api/set', {strip: id, control: 'name', value: n, mix}, device);
    })
      .then(function () { lastName = n; })
      .catch(function (error) {
        toast('Could not rename channel: ' + error.message);
        if (nameEl.value === n) {
          nameEl.value = previous;
          q('.vname').textContent = vertical(previous);
        }
      });
  });
  if (window.ffadoProtectEditable) window.ffadoProtectEditable(nameEl);
  nameEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") nameEl.blur();
    if (e.key === "Escape") { nameEl.value = lastName; nameEl.blur(); }
  });

  // gain: one box. On a stereo strip the server applies it to both channels.
  var gain1 = null;
  if (FEATURES.gain) gain1 = bindGain(q(".gain"), id, missing(data.gain) && stereo ? partner.gain : data.gain, stripMix, stripDevice);

  // polarity: one button (on a stereo strip it flips both channels, again done by the server)
  invertEl.classList.toggle("on", !!data.invert);
  invertEl.disabled = !!FEATURES.invert && !FEATURES.invert.writable;
  invertEl.addEventListener("click", function () { send(id, "invert", invertEl.classList.toggle("on")); });

  // Pan for mono strips and stereo-pair balance (handled as L/R by the API).
  function renderPan() {
    if (!panAvailable) {
      panEl.value = 0;  // slider needs a numeric coordinate; never show center
      panVal.textContent = "—";
      return;
    }
    var p = Math.round(pan * 100);
    panEl.value = p;
    panVal.textContent = (p === 0 ? "0" : (p < 0 ? "L" + (-p) : "R" + p)) +
      (data.pan_partial ? "*" : "");
  }
  if (FEATURES.pan || STEREO_BUSES.includes(currentMix) || stereo) {
    panEl.disabled = matrixPairNeedsBus || !panAvailable ||
      (!STEREO_BUSES.includes(currentMix) && !matrixPairNeedsBus && !FEATURES.pan?.writable);
    if (matrixPairNeedsBus) {
      panEl.title = "Link the output buses as a stereo pair to enable input balance";
      panVal.title = panEl.title;
      panVal.textContent = "—";
    } else if (data.pan_note) {
      panEl.title = data.pan_note;
      panVal.title = data.pan_note;
    } else if (!panAvailable) {
      panEl.title = "No active matrix route for this channel. Connect it in In/Out before adjusting balance.";
      panVal.title = panEl.title;
    }
    // Pan is a two-matrix-cell FFADO transaction, often over a relatively
    // slow FireWire D-Bus link. Preview drag locally; commit the final value
    // on release. Wheel/keyboard steps are grouped to avoid stale writes.
    var panCommitTimer = null, panChanged = false, panDragging = false;
    function commitPan() {
      clearTimeout(panCommitTimer);
      if (!panChanged || panEl.disabled) return;
      panChanged = false;
      send(id, "pan", pan);
    }
    function queuePanCommit() {
      clearTimeout(panCommitTimer);
      if (!panDragging) panCommitTimer = setTimeout(commitPan, 180);
    }
    panEl.addEventListener("input", function () {
      if (panEl.disabled) return;
      pan = parseInt(panEl.value, 10) / 100;
      panChanged = true;
      renderPan();
      queuePanCommit();
    });
    panEl.addEventListener("change", commitPan);
    panEl.addEventListener("dblclick", function () {
      if (panEl.disabled) return;
      pan = 0; panChanged = true; renderPan(); commitPan();
    });
    var panAcc = { v: 0 };
    panEl.addEventListener("wheel", function (e) {              // wheel over the bar: 5 per notch, 1 with Shift
      if (panEl.disabled) return;
      e.preventDefault();
      var dir = wheelDir(e, panAcc);
      if (!dir) return;
      var now = Math.round(pan * 100), next = Math.max(-100, Math.min(100, now + dir * (e.shiftKey ? 1 : 5)));
      if ((now < 0 && next > 0) || (now > 0 && next < 0)) next = 0;   // stop at center when crossing it
      pan = next / 100;
      panChanged = true;
      renderPan();
      queuePanCommit();
    }, { passive: false });
    panEl.addEventListener("pointerdown", function (e) {
      panDragging = true;
      if (panEl.setPointerCapture) panEl.setPointerCapture(e.pointerId);
    });
    panEl.addEventListener("pointerup", function () { panDragging = false; commitPan(); });
    panEl.addEventListener("pointercancel", function () { panDragging = false; commitPan(); });
    panEl.addEventListener("lostpointercapture", function () { panDragging = false; commitPan(); });
  }

  // Fader and mute: linked inputs and stereo buses are applied across all matrix legs by the API.
  var fader = makeFader(q(".track"), q(".handle"), q(".fval"), function (v) { if (FADER_ALLOWED) sendThrottled(id, "fader", v, stripMix, stripDevice); },
    function () { return FADER_ALLOWED && stripMix === currentMix && stripDevice === ACTIVE_DEVICE; });
  function toggleHardware(control, on) {
    // Never optimistically show both stereo legs muted before FFADO has
    // acknowledged every write. Read the entire state back on success.
    var button = control === 'mute' ? q('.mute') : soloEl;
    if (button.disabled) return;
    button.disabled = true;
    var targetMix = currentMix;
    post('/api/set', { strip:id, control:control, value:on, mix:targetMix })
      .then(r => r.json().then(d => { if (!r.ok || d.error) throw Error(d.error || 'Hardware write failed'); }))
      .then(() => loadMix())
      .catch(e => { toast(control + ': ' + e.message); loadMuteRecovery(); loadMix(); })
      .finally(() => { button.disabled = false; });
  }
  soloEl.addEventListener("click", function () { toggleHardware('solo', !el.classList.contains('soloed')); });
  if (data.mute_partial) {
    q(".mute").title = 'Only part of this stereo route is muted. Click to mute both channels/bus legs.';
    el.classList.add('mute-partial');
  }
  q(".mute").addEventListener("click", function () { if (MUTE_ALLOWED) toggleHardware('mute', !el.classList.contains('muted')); });
  // One menu per strip, independent of its link state or whether it is minimized.
  // The first unlinked channel selected becomes Left, the second becomes Right.
  q('.strip-more').addEventListener('click', function (event) {
    event.stopPropagation();
    var actions = [];
    if (stereo) {
      actions.push(['Unlink stereo channels', function () { unlinkStrip(id); }]);
    } else {
      var label = pendingStereoLeft === id ? 'Cancel Left selection' :
        (pendingStereoLeft ? 'Link as Right channel' : 'Link as Left channel');
      actions.push([label, function () { chooseStereoChannel(id); }]);
    }
    actions.push([isPinned(el) ? 'Unpin' : 'Pin', function () {
      setPinned(el, !isPinned(el)); saveLayout();
    }]);
    actions.push([isMin(el) ? 'Maximize' : 'Minimize', function () {
      setMinimized(el, !isMin(el)); saveLayout();
    }]);
    showActionsMenu(q('.strip-more'), 'strip:' + id, 'Channel actions', actions);
  });

  q(".grip").addEventListener("pointerdown", function (e) { startDrag(el, e); });
  q(".vname").addEventListener("pointerdown", function (e) { startDrag(el, e); });

  el._apply = function (control, value, stripId) {  // remote change: update the display only, send nothing
    if (control === "fader") fader.set(value);
    else if (control === "mute") el.classList.toggle("muted", !!value);
    else if (control === "solo") el.classList.toggle("soloed", !!value);
    else if (control === "invert") invertEl.classList.toggle("on", !!value);
    else if (control === "gain") { if (gain1) gain1.set(value); }
    else if (control === "pan") {
      if (!panDragging) {
        panAvailable = value !== null && value !== undefined && Number.isFinite(Number(value));
        pan = panAvailable ? Number(value) : 0;
        panEl.disabled = matrixPairNeedsBus || !panAvailable ||
          (!STEREO_BUSES.includes(currentMix) && !matrixPairNeedsBus && !FEATURES.pan?.writable);
        renderPan();
      }
    }
    else if (control === "name") {
      if (stripId && stripId !== id) return;          // the right channel's own name isn't shown on a stereo strip
      if (document.activeElement !== nameEl) { nameEl.value = shortFfadoLabel(value); lastName = nameEl.value; q(".vname").textContent = vertical(nameEl.value); }
    }
  };

  setPinned(el, pinned);
  setMinimized(el, !!minimized);
  renderPan();
  fader.set(Number.isFinite(data.fader) ? data.fader : 0);
  if (stereo && data.pair_mismatch) {
    // The label represents the louder linked input. Do not imply both
    // crosspoint gains match when one was edited independently in the matrix.
    var valueLabel = q(".fval");
    valueLabel.value = "MAX " + valueLabel.value;
    valueLabel.classList.add("level-mismatch");
    if (Array.isArray(data.pair_faders)) {
      var labelFor = function (v) {
        if (!faderHasDbScale()) return String(Math.round(v));
        return formatFaderDb(faderUiToDb(v));
      };
      valueLabel.title = "Linked inputs differ: left " + labelFor(data.pair_faders[0]) +
        ", right " + labelFor(data.pair_faders[1]) + ". The fader shows the louder input.";
    }
  }
  return el;
}

// ---- appearance ----
var themeSelect = document.getElementById("themeSelect");
var THEMES = AVAILABLE_THEMES;
readJson('/api/themes').then(names => {
  THEMES.splice(0, THEMES.length, ...names);
  themeSelect.replaceChildren(...names.map(name => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name.replace(/[-_]/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    return option;
  }));
  applyTheme(document.documentElement.dataset.theme || "dark");
}).catch(function (error) { toast('Could not load themes: ' + error.message); });
function applyTheme(name) {
  if (THEMES.length && THEMES.indexOf(name) === -1) name = "dark";
  name = setMixerTheme(name);
  themeSelect.value = name;
  if (typeof updateAccent === "function") updateAccent();
}
var confirmedTheme = null;
themeSelect.addEventListener("change", function () {
  var requested = themeSelect.value;
  applyTheme(requested);
  savePreference('theme', {theme: requested}, function () {
    confirmedTheme = requested;
  }, function () {
    if (themeSelect.value === requested && confirmedTheme) applyTheme(confirmedTheme);
  }, true);
});

// Accent overrides are stored per theme in the existing settings JSON.
var accentOverrides = {};
var confirmedAccents = {};
var accentButton = document.getElementById("accentButton");
var accentEditor = document.getElementById("accentEditor");
var accentHex = document.getElementById("accentHex");
var accentCurrent = document.getElementById("accentCurrent");
var accentError = document.getElementById("accentError");
function updateAccent() {
  setMixerAccent(accentOverrides[themeSelect.value] || null);
  var current = getComputedStyle(document.documentElement).getPropertyValue("--accent-color").trim();
  if (accentCurrent) accentCurrent.textContent = current.toUpperCase();
  if (accentButton) accentButton.style.backgroundColor = current;
  if (accentHex) accentHex.value = current.toUpperCase();
  if (accentError) accentError.textContent = "";
}
function saveAccent() {
  var requested = Object.assign({}, accentOverrides);
  return savePreference('accent colors', {accent_overrides: requested}, function () {
    confirmedAccents = Object.assign({}, requested);
  }, function () {
    if (JSON.stringify(accentOverrides) === JSON.stringify(requested)) {
      accentOverrides = Object.assign({}, confirmedAccents);
      updateAccent();
    }
  }, true);
}
accentButton.addEventListener("click", function () {
  accentEditor.hidden = !accentEditor.hidden;
  if (!accentEditor.hidden) { updateAccent(); accentHex.focus(); accentHex.select(); }
});
document.getElementById("accentApply").addEventListener("click", function () {
  var value = accentHex.value.trim();
  if (!/^#[0-9a-fA-F]{6}$/.test(value)) {
    accentError.textContent = "Enter a six-digit HTML color, such as #3DAEE9.";
    return;
  }
  accentOverrides[themeSelect.value] = value.toLowerCase();
  updateAccent();
  accentEditor.hidden = true;
  saveAccent();
});
accentHex.addEventListener("keydown", function (e) {
  if (e.key === "Enter") document.getElementById("accentApply").click();
});
document.getElementById("accentReset").addEventListener("click", function () {
  delete accentOverrides[themeSelect.value];
  updateAccent();
  accentEditor.hidden = true;
  saveAccent();
});

// Initialize the theme only after accent controls and state are ready.
try { applyTheme(localStorage.getItem("ffado-theme") || "dark"); } catch (_) { applyTheme("dark"); }

// ---- settings dialog (cog, top right) ----
var gear = document.getElementById("gear"), overlay = document.getElementById("overlay");
var dialog = document.getElementById("dialog");
var hideBox = document.getElementById("hideMin");
var qjackctlEnabled = false;
var TABS = ["general", "theme", "about"], currentTab = "general";
var jackEnableBox = document.getElementById("enableQjackctl");
function setQjackctlEnabled(enabled) {
  qjackctlEnabled = !!enabled;
  jackEnableBox.checked = qjackctlEnabled;
  var tab = document.getElementById("tab-qjackctl");
  var pane = document.getElementById("pane-qjackctl");
  tab.hidden = !qjackctlEnabled;
  pane.hidden = !qjackctlEnabled;
  if (!qjackctlEnabled) {
    pane.classList.add("off");
    tab.classList.remove("active");
    tab.setAttribute("aria-selected", "false");
    tab.tabIndex = -1;
  }
  TABS = qjackctlEnabled ? ["general", "qjackctl", "theme", "about"] : ["general", "theme", "about"];
  if (!qjackctlEnabled && currentTab === "qjackctl") showTab("general");
}
function showTab(name) {
  if (name === "qjackctl" && !qjackctlEnabled) name = "general";
  currentTab = name;
  TABS.forEach(function (t) {
    var on = t === name, tab = document.getElementById("tab-" + t);
    tab.classList.toggle("active", on);
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
    document.getElementById("pane-" + t).classList.toggle("off", !on);
  });
  if (name === "about") loadAbout();
  if (name === "qjackctl") checkJackStatus();
}
Array.prototype.forEach.call(document.querySelectorAll(".tab"), function (tab) {
  tab.addEventListener("click", function () { showTab(tab.dataset.tab); });
  tab.addEventListener("keydown", function (e) {   // Left / Right / Home / End move between tabs
    var i = TABS.indexOf(tab.dataset.tab), to = null;
    if (e.key === "ArrowRight") to = TABS[(i + 1) % TABS.length];
    else if (e.key === "ArrowLeft") to = TABS[(i + TABS.length - 1) % TABS.length];
    else if (e.key === "Home") to = TABS[0];
    else if (e.key === "End") to = TABS[TABS.length - 1];
    if (to) { e.preventDefault(); showTab(to); document.getElementById("tab-" + to).focus(); }
  });
});
// QjackCtl's Graph and Patchbay windows (they open on the computer running ffado-webmixer)
var JACK_HINT = "Opens the window in QjackCtl on the computer running ffado-webmixer.";
var jackMsg = document.getElementById("jackMsg");
var jackButtons = document.getElementById("jackButtons");
var jackRefresh = document.getElementById("jackRefresh");
function checkJackStatus() {
  if (!qjackctlEnabled) return;
  jackRefresh.hidden = true;
  showJackMessage("Checking QjackCtl...", false);
  readJson('/api/qjackctl/status').then(function (status) {
    if (!qjackctlEnabled) return;
    jackButtons.hidden = !status.running;
    jackRefresh.hidden = !!status.running;
    showJackMessage(status.running ? JACK_HINT : "QjackCtl not running. Launch it and check again.", !status.running);
  }).catch(function () {
    if (!qjackctlEnabled) return;
    jackButtons.hidden = true;
    jackRefresh.hidden = false;
    showJackMessage("Unable to check QjackCtl status. Try again.", true);
  });
}
jackRefresh.addEventListener("click", checkJackStatus);
jackEnableBox.addEventListener("change", function () {
  var newValue = jackEnableBox.checked;
  setQjackctlEnabled(newValue);
  savePreference('QjackCtl', { enable_qjackctl: newValue }, function () {
    confirmedQjackctl = newValue;
  }, function () {
    if (qjackctlEnabled === newValue) setQjackctlEnabled(confirmedQjackctl);
  }, true);
});
function showJackMessage(text, isError) {
  jackMsg.textContent = text;
  jackMsg.classList.toggle("err", !!isError);
}
Array.prototype.forEach.call(document.querySelectorAll(".dlgbtn[data-window]"), function (btn) {
  btn.addEventListener("click", function () {
    var label = btn.textContent;
    btn.disabled = true;
    showJackMessage("Asking QjackCtl to open the " + label + "...", false);
    postJson('/api/qjackctl', { window: btn.dataset.window }).then(function (d) {
      if (d.error) showJackMessage(d.error, true);
      else showJackMessage("Asked QjackCtl to open the " + label + ". If nothing opens, turn on Setup > Misc > Other > " +
                           "Enable D-Bus interface in QjackCtl.", false);
    }).catch(function (error) {
      showJackMessage('Could not open QjackCtl window: ' + error.message, true);
    }).then(function () { btn.disabled = false; });
  });
});

// URL shown in About and encoded in the offline QR code must always match.
var mixerPageUrl = "";
var qrDialog = document.getElementById("qrDialog");
var qrCodeEl = document.getElementById("qrCode");
var qrErrorEl = document.getElementById("qrError");
var aboutShowQR = document.getElementById("aboutShowQR");
function renderMixerQR(url) {
  qrCodeEl.replaceChildren();
  qrErrorEl.hidden = true;
  if (!url) throw Error("The mixer web page URL is unavailable.");
  var qr = new FFADOQRCode.Code(0, FFADOQRCode.Ecc.M);
  qr.addData(url);
  qr.make();
  var count = qr.getModuleCount();
  var quiet = 4;
  var size = count + quiet * 2;
  // Build a single SVG path; fill the whole canvas white for reliable scanning
  // against the dark and light application themes.
  var path = [];
  for (var y = 0; y < count; y++) {
    for (var x = 0; x < count; x++) {
      if (qr.isDark(y, x)) path.push("M" + (x + quiet) + " " + (y + quiet) + "h1v1h-1z");
    }
  }
  var ns = "http://www.w3.org/2000/svg";
  var svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 " + size + " " + size);
  svg.setAttribute("shape-rendering", "crispEdges");
  var bg = document.createElementNS(ns, "rect");
  bg.setAttribute("width", size);
  bg.setAttribute("height", size);
  bg.setAttribute("fill", "#fff");
  svg.appendChild(bg);
  var dots = document.createElementNS(ns, "path");
  dots.setAttribute("d", path.join(""));
  dots.setAttribute("fill", "#000");
  svg.appendChild(dots);
  qrCodeEl.appendChild(svg);
}
function openMixerQR() {
  showTab("about");
  dialog.hidden = true;
  qrDialog.hidden = false;
  qrCodeEl.replaceChildren();
  try { renderMixerQR(mixerPageUrl); }
  catch (error) { qrErrorEl.textContent = "Could not create QR code: " + error.message; qrErrorEl.hidden = false; }
  document.getElementById("qrClose").focus();
}
function closeMixerQR() {
  if (qrDialog.hidden) return;
  qrDialog.hidden = true;
  dialog.hidden = false;
  // The settings dialog was not closed; return to its previous About tab.
  aboutShowQR.focus();
}
aboutShowQR.addEventListener("click", openMixerQR);
document.getElementById("qrClose").addEventListener("click", closeMixerQR);

function loadAbout() {
  readJson('/api/about').then(function (a) {
    document.getElementById("aboutName").textContent = a.name;
    document.getElementById("aboutVersion").textContent = a.version ? "Version " + a.version : "";
    document.getElementById("aboutMode").textContent = a.mode || "-";
    document.getElementById("aboutDevice").textContent = a.device || "-";
    document.getElementById("aboutAddress").textContent = a.address || "-";
    var openMixer = document.getElementById("aboutOpenMixer");
    // Use the exact same server URL for the browser button and QR code.
    mixerPageUrl = /^https?:\/\/[^/]+/i.test(a.address || "")
      ? (a.address.endsWith("/") ? a.address : a.address + "/") : "";
    openMixer.hidden = !mixerPageUrl;
    aboutShowQR.hidden = !mixerPageUrl;
    if (mixerPageUrl) openMixer.href = mixerPageUrl;
  }).catch(function (error) { toast('Could not load About information: ' + error.message); });
}

function openSettings() {
  overlay.hidden = false;
  gear.classList.add("open");
  showTab(currentTab);                            // reopens on the tab you used last
  dialog.focus();
}
function closeSettings() {
  if (!qrDialog.hidden) { closeMixerQR(); return; }
  overlay.hidden = true;
  gear.classList.remove("open");
  gear.focus();
}
gear.addEventListener("click", openSettings);
document.getElementById("dlgClose").addEventListener("click", closeSettings);
overlay.addEventListener("mousedown", function (e) { if (e.target === overlay) closeSettings(); });   // click outside the box
document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !overlay.hidden) closeSettings(); });

var skipLoadingScreenBox = document.getElementById("skipLoadingScreen");
skipLoadingScreenBox.addEventListener("change", function () {
  var requested = skipLoadingScreenBox.checked;
  skipLoadingScreenBox.disabled = true;
  savePreference('loading screen preference', { skip_loading_screen: requested }, null, function () {
    if (skipLoadingScreenBox.checked === requested) skipLoadingScreenBox.checked = !requested;
  }, true).finally(function () { skipLoadingScreenBox.disabled = false; });
});
var confirmedHideMin = false;
var confirmedQjackctl = false;
hideBox.addEventListener("change", function () {
  var requested = hideBox.checked;
  row.classList.toggle('hide-min', requested);
  savePreference('minimized channels preference', {hide_minimized: requested}, function () {
    confirmedHideMin = requested;
  }, function () {
    if (hideBox.checked === requested) {
      hideBox.checked = confirmedHideMin;
      row.classList.toggle('hide-min', confirmedHideMin);
    }
  }, true);
});

// ---- master (output) fader: Main, Phones or a bus ----
var masterEl = document.getElementById("master");
var masterToken = 0, masterReady = false;
var masterFader = makeFader(document.getElementById("masterTrack"), document.getElementById("masterHandle"),
  document.getElementById("masterVal"), function (v) {
    if (!masterReady) return;  // Never send a stale output's displayed level.
    var out = currentOut;
    throttled("out|" + out, v, function (x) {
      post("/api/output", { out: out, control: "fader", value: x })
        .then(function (r) { return r.json().then(function (d) { if (!r.ok || d.error) throw Error(d.error || "Unable to set output"); }); })
        .catch(function (e) { toast("Output change failed: " + e.message); });
    });
  }, function () { return masterReady; });
document.getElementById("masterMute").addEventListener("click", function () {
  var button = document.getElementById("masterMute");
  if (button.disabled) return;
  button.disabled = true;
  var want = !masterEl.classList.contains("muted");
  post("/api/output", { out: currentOut, control: "mute", value: want })
    .then(r => r.json().then(d => { if (!r.ok || d.error) throw Error(d.error || 'Output mute write failed'); }))
    .then(loadMaster)  // Main/Phones soft mute moves the fader; hardware readback is authoritative.
    .catch(e => { toast('Output mute: ' + e.message); loadMaster(); loadMuteRecovery(); })
    .finally(() => { button.disabled = false; });
});
// ---- rename the active output (Main, Phones, a bus): context-menu / long press the label ----
var masterName = document.getElementById("masterName");
var masterHardwareName = masterEl.querySelector(".inname");
var lastMasterName = "";
function showMasterName(name) {
  lastMasterName = name;
  if (document.activeElement !== masterName) masterName.value = name;      // don't overwrite while typing
}
function applyOutputName(id, name) {             // update the button, the label and our list
  OUTPUTS.forEach(function (o) { if (o.id === id) o.name = name; });
  Array.prototype.forEach.call(document.querySelectorAll(".outbtn"), function (b) {
    if (b.dataset.id === id) { b.firstChild.textContent = name; b.title = name; }
  });
  if (id === currentOut) showMasterName(name);
  if (busTabsEnabled()) renderBusTabs();
}
masterName.addEventListener("change", function () {
  var name = masterName.value.trim() || lastMasterName;
  masterName.value = name;
  if (name === lastMasterName) return;
  var out = currentOut, previous = lastMasterName;
  applyOutputName(out, name);
  window.ffadoApi.serial('name|' + (ACTIVE_DEVICE || '') + '|out:' + out, function () {
    return postJson('/api/set', {strip: 'out:' + out, control: 'name', value: name});
  })
    .catch(function (error) {
      toast('Could not rename output: ' + error.message);
      if (currentOut === out && masterName.value === name) applyOutputName(out, previous);
      loadMaster();
    });
});
masterName.addEventListener("keydown", function (e) {
  if (e.key === "Enter") masterName.blur();
  if (e.key === "Escape") { masterName.value = lastMasterName; masterName.blur(); }
});
masterName.addEventListener("focus", function () { if (masterName.dataset?.gestureEdit !== "locked") masterName.select(); });

function loadMaster(options) {
  var out = OUTPUTS.filter(function (o) { return o.id === currentOut; })[0];
  window.ffadoApi.cancel('master-output');
  masterReady = false;
  document.getElementById('masterMute').disabled = true;
  masterEl.hidden = !out || !out.controllable;
  document.getElementById("masterbox").hidden = masterEl.hidden;
  if (masterEl.hidden) return;
  masterHardwareName.textContent = out.baseName;
  var token = ++masterToken;
  return window.ffadoApi.latest('master-output', '/api/output?out=' + encodeURIComponent(currentOut),
    {device: ACTIVE_DEVICE}).then(function (o) {
    if (!o || token !== masterToken) return;
    showMasterName(o.name);
    masterFader.set(o.level);
    masterEl.classList.toggle('muted', !!o.mute);
    masterReady = true;
    document.getElementById('masterMute').disabled = false;
  }).catch(function (error) {
    if (token !== masterToken) return;
    masterEl.hidden = true;
    document.getElementById('masterbox').hidden = true;
    toast('Could not read output: ' + error.message);
    if (options && options.throwOnError === true) throw error;
  });
}

// ---- Bus tabs for devices with many matrix rows. Never rename FFADO's physical identifiers. ----
var busLayout = [];
var busTabs = document.getElementById('busTabs');
var hideBusesBox = document.getElementById('hideMinBuses');
var confirmedHideBuses = false;
var BUS_TABS_THRESHOLD = 9;
var busLayoutVersion = 0;
var busLinkBusy = false;
function busTabsEnabled() { return MIXES.length >= BUS_TABS_THRESHOLD; }
function busOutput(id) { return OUTPUTS.find(function (o) { return o.mix === Number(id); }); }
function busEntries() {
  var byId = new Map();
  busLayout.forEach(function (entry) {
    if (entry && Number.isInteger(Number(entry.id)) && MIXES.some(m => m.id === Number(entry.id))) {
      byId.set(String(entry.id), {id: String(entry.id), pinned: entry.pinned !== false,
                                  minimized: entry.minimized === true});
    }
  });
  var ordered = [];
  busLayout.forEach(function (item) {
    var id = item && String(item.id);
    if (byId.has(id)) { ordered.push(byId.get(id)); byId.delete(id); }
  });
  MIXES.forEach(function (mix) {
    var id = String(mix.id);
    if (byId.has(id)) { ordered.push(byId.get(id)); byId.delete(id); }
    else if (!ordered.some(item => item.id === id)) ordered.push({id, pinned:true, minimized:false});
  });
  return ordered;
}
function updateBusMinCount() {
  var n = busEntries().filter(x => x.minimized).length;
  document.getElementById('busMinCount').textContent = n ? '(' + n + ')' : '';
}
function saveBusTabs(entries) {
  busLayout = entries.map(item => ({id: item.id, pinned: !!item.pinned, minimized: !!item.minimized}));
  var snapshot = busLayout.map(item => ({...item}));
  var version = ++busLayoutVersion, device = ACTIVE_DEVICE;
  renderBusTabs();
  return window.ffadoApi.serial('bus-layout|' + (device || ''), function () {
    return postJson('/api/bus-layout', snapshot, device);
  }).catch(function (error) {
    toast('Could not save bus tabs: ' + error.message);
    if (version === busLayoutVersion && device === ACTIVE_DEVICE) {
      readJson('/api/bus-layout', device).then(function (saved) {
        if (version === busLayoutVersion && Array.isArray(saved)) {
          busLayout = saved; renderBusTabs();
        }
      }).catch(e => toast('Could not restore bus tabs: ' + e.message));
    }
  });
}
function updateBusTabSelection() {
  busTabs.querySelectorAll('.bus-tab').forEach(function (tab) {
    var mix = Number(tab.dataset.mix);
    var selected = currentMix === mix || (STEREO_BUSES.includes(currentMix) && currentMix + 1 === mix);
    tab.classList.toggle('active', selected);
    tab.setAttribute('aria-selected', String(selected));
  });
}
function chooseBusTab(id) {
  var o = busOutput(id);
  if (o) { selectOutput(o); return; }
  var mix = Number(id);
  var next = STEREO_BUSES.includes(mix - mix % 2) ? mix - mix % 2 : mix;
  var changed = currentMix !== next;
  currentMix = next;
  markOutputs(); saveViewSelection();
  if (changed) { pendingStereoLeft = null; loadMix(); }
}
function changeBusName(id, value, input, paired = false) {
  var o = busOutput(id);
  var old = paired ? (STEREO_BUS_NAMES[id] || input.defaultValue) :
    (o ? o.name : (MIXES.find(x => x.id === Number(id)) || {}).name);
  var name = value.trim();
  if (!name || name === old) { input.value = old; return; }
  var device = ACTIVE_DEVICE;
  if (paired) {
    var left = Number(id);
    return window.ffadoApi.serial('name|' + (device || '') + '|bus-pair:' + id, () =>
      postJson('/api/bus-pair-name', {left, name}, device)).then(function () {
        if (device === ACTIVE_DEVICE) STEREO_BUS_NAMES[id] = name;
      }).catch(function (error) {
        toast('Could not rename linked bus: ' + error.message);
        if (device === ACTIVE_DEVICE) input.value = old;
      });
  }
  if (!o) {
    var mix = Number(id);
    window.ffadoApi.serial('name|' + (device || '') + '|bus:' + id, () =>
      postJson('/api/bus-name', {mix, name}, device)).then(function () {
        var m = MIXES.find(x => x.id === mix); if (m) m.name = name;
      }).catch(function (error) {
        toast('Could not rename bus: ' + error.message);
        if (device === ACTIVE_DEVICE) input.value = old;
      });
    return;
  }
  applyOutputName(o.id, name);
  window.ffadoApi.serial('name|' + (device || '') + '|out:' + o.id, () =>
    postJson('/api/set', {strip:'out:' + o.id, control:'name', value:name}, device))
    .catch(function (error) {
      toast('Could not rename bus: ' + error.message);
      if (device === ACTIVE_DEVICE) applyOutputName(o.id, old);
    });
}
function toggleBusLink(left) {
  if (busLinkBusy) return;
  busLinkBusy = true;
  var device = ACTIVE_DEVICE;
  var linked = STEREO_BUSES.includes(left);
  postJson('/api/bus-stereo', {left, linked:!linked}, device)
    .then(() => readJson('/api/describe', device))
    .then(function (info) {
      if (device !== ACTIVE_DEVICE) return;
      STEREO_BUSES = info.stereo_buses || [];
      STEREO_BUS_NAMES = info.stereo_bus_names || {};
      if (STEREO_BUSES.includes(left) && currentMix === left + 1) currentMix = left;
      buildOutputs(); markOutputs(); loadMix();
    }).catch(e => toast('Could not change bus link: ' + e.message))
    .finally(function () { busLinkBusy = false; renderBusTabs(); });
}
// A single popup is placed outside the scrolling tab bar, so the popup is not
// cropped by overflow-x:auto. It never changes FFADO routing itself.
var activeBusMenu = null;
function closeBusMenu() {
  if (!activeBusMenu) return;
  activeBusMenu.remove(); activeBusMenu = null;
}
function showActionsMenu(button, key, label, actions) {
  if (activeBusMenu?.dataset.key === key) { closeBusMenu(); return; }
  closeBusMenu();
  var menu = document.createElement('div');
  menu.className = 'bus-context-menu'; menu.dataset.key = key;
  menu.setAttribute('role', 'menu'); menu.setAttribute('aria-label', label);
  actions.forEach(function (item) {
    var el = document.createElement('button');
    el.type = 'button'; el.textContent = item[0]; el.setAttribute('role', 'menuitem');
    el.addEventListener('click', function (event) {
      event.stopPropagation(); closeBusMenu(); item[1]();
    });
    menu.appendChild(el);
  });
  document.body.appendChild(menu);
  activeBusMenu = menu;
  var rect = button.getBoundingClientRect();
  var left = Math.max(6, Math.min(rect.right - menu.offsetWidth, window.innerWidth - menu.offsetWidth - 6));
  var top = rect.bottom + 3;
  if (top + menu.offsetHeight > window.innerHeight - 6) top = Math.max(6, rect.top - menu.offsetHeight - 3);
  menu.style.left = left + 'px'; menu.style.top = top + 'px';
  menu.querySelector('button')?.focus();
}
function showBusMenu(button, entry, input, paired) {
  var left = Number(entry.id) - Number(entry.id) % 2;
  var linked = STEREO_BUSES.includes(left);
  var pairExists = MIXES.some(m => m.id === left) && MIXES.some(m => m.id === left + 1);
  var ids = paired ? [String(left), String(left + 1)] : [entry.id];
  var actions = [
    ['Rename', function () {
      if (entry.minimized) {
        saveBusTabs(busEntries().map(e => ids.includes(e.id) ? {...e, minimized:false} : e));
        input = busTabs.querySelector('[data-mix="' + entry.id + '"] .bus-name');
      }
      if (window.ffadoBeginEditing && input) window.ffadoBeginEditing(input);
    }],
    [entry.pinned ? 'Unpin' : 'Pin', function () {
      saveBusTabs(busEntries().map(e => ids.includes(e.id) ? {...e, pinned:!entry.pinned} : e));
    }],
    [entry.minimized ? 'Maximize' : 'Minimize', function () {
      saveBusTabs(busEntries().map(e => ids.includes(e.id) ? {...e, minimized:!entry.minimized} : e));
    }]
  ];
  if (GAIN_SCALE && pairExists) {
    actions.push([linked ? 'Unlink bus ' + (left + 1) + '+' + (left + 2) :
      'Link bus ' + (left + 1) + '+' + (left + 2), function () { toggleBusLink(left); }]);
  }
  showActionsMenu(button, 'bus:' + entry.id, 'Bus actions', actions);
}
document.addEventListener('pointerdown', function (event) {
  if (activeBusMenu && !activeBusMenu.contains(event.target) &&
      !event.target.closest('.bus-more, .strip-more')) closeBusMenu();
}, true);
document.addEventListener('keydown', function (event) {
  if (event.key === 'Escape' && activeBusMenu) { closeBusMenu(); event.preventDefault(); }
});
// Unlinked buses have independent drag tiles. Only linked stereo pairs
// move together: pinning either leg keeps the linked pair in place.
function renderBusTabs() {
  busTabs.hidden = !busTabsEnabled();
  document.body.classList.toggle('bus-tabs-mode', busTabsEnabled());
  if (!busTabsEnabled()) { updateBusMinCount(); return; }
  var entries = busEntries(), byId = new Map(entries.map(e => [e.id, e]));
  var used = new Set();
  busTabs.replaceChildren();
  closeBusMenu();
  function makeTab(entry, partner) {
    var mix = Number(entry.id);
    var o = busOutput(entry.id);
    var paired = !!partner;
    var tab = document.createElement('div');
    tab.className = 'bus-tab' + (paired ? ' linked' : '') + (entry.pinned ? ' pinned' : '') + (entry.minimized ? ' minimized' : '');
    tab.dataset.mix = entry.id;
    tab.setAttribute('role', 'tab'); tab.tabIndex = 0;
    tab.title = 'Select bus ' + (mix + 1) + (paired ? '+' + (mix + 2) : '') + (entry.pinned ? '; unpin in the menu to reorder' : '; drag the left grip to reorder');
    var grip = document.createElement('span'); grip.className = 'bus-grip';
    grip.textContent = '⋮'; grip.title = 'Drag to reorder buses';
    grip.setAttribute('aria-label', 'Drag bus ' + (mix + 1) + (paired ? '+' + (mix + 2) : '') + ' to reorder');
    var name = document.createElement('input'); name.className = 'bus-name';
    var normalName = o ? o.name : (MIXES.find(x => x.id === mix) || {}).name || ('Bus ' + (mix+1));
    var rightOutput = paired ? busOutput(partner.id) : null;
    var rightName = paired ? (rightOutput ? rightOutput.name : (MIXES.find(x => x.id === mix+1) || {}).name || ('Bus ' + (mix+2))) : '';
    name.value = paired ? (STEREO_BUS_NAMES[String(mix)] || (normalName + '+' + rightName)) : normalName;
    name.maxLength = paired ? 32 : 16; name.spellcheck = false;
    name.title = 'Right-click or long-press to rename';
    name.setAttribute('aria-label', 'Bus ' + (mix + 1) + (paired ? '+' + (mix + 2) : '') + ' name');
    if (window.ffadoProtectEditable) window.ffadoProtectEditable(name);
    var compactLabel = document.createElement('span'); compactLabel.className = 'bus-compact-label';
    compactLabel.textContent = paired ? (mix + 1) + '+' + (mix + 2) : String(mix + 1);
    var more = document.createElement('button'); more.type='button'; more.className='bus-more';
    more.textContent = '⋮'; more.title = 'Bus actions';
    more.setAttribute('aria-label', 'Actions for bus ' + (mix + 1));
    more.setAttribute('aria-haspopup', 'menu');
    more.addEventListener('click', function (event) {
      event.stopPropagation(); showBusMenu(more, entry, name, paired);
    });
    name.addEventListener('click', function (event) {
      event.stopPropagation();
      if (name.dataset.gestureEdit !== 'editing') chooseBusTab(mix);
    });
    name.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && name.dataset.gestureEdit === 'editing') name.blur();
      if (event.key === 'Escape' && name.dataset.gestureEdit === 'editing') {
        name.value = name.defaultValue; name.dataset.cancel = 'true'; name.blur();
      }
    });
    name.addEventListener('focus', () => {
      if (name.dataset.gestureEdit === 'locked') return;
      name.defaultValue = name.value; name.select();
    });
    name.addEventListener('blur', () => {
      if (name.dataset.cancel === 'true') { delete name.dataset.cancel; return; }
      changeBusName(entry.id, name.value, name, paired);
    });
    tab.append(grip, compactLabel, name, more);
    if (entry.minimized && hideBusesBox.checked && mix !== currentMix &&
        !(STEREO_BUSES.includes(currentMix) && mix === currentMix + 1)) tab.hidden = true;
    tab.addEventListener('click', function (event) {
      if (event.target === tab || event.target === grip) chooseBusTab(mix);
    });
    tab.addEventListener('keydown', function (event) {
      if (event.target !== tab) return;
      if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); chooseBusTab(mix);}
    });
    return tab;
  }
  // Preserve individual bus order; collapse only *linked* stereo partners.
  // Grouping every even/odd pair prevented an unpinned bus from moving if
  // its still-pinned neighbor shared the same drag tile.
  var groups = [];
  entries.forEach(e => {
    var mix = Number(e.id), left = mix - mix % 2;
    if (used.has(e.id)) return;
    var other = byId.get(String(mix % 2 ? mix-1 : mix+1));
    var group = [e]; used.add(e.id);
    if (STEREO_BUSES.includes(left) && other && !used.has(other.id)) {
      group = [byId.get(String(left)), byId.get(String(left + 1))];
      group.forEach(item => used.add(item.id));
    }
    groups.push(group);
  });
  groups.forEach(group => {
    var tile = document.createElement('div'); tile.className = 'bus-tab-tile';
    tile.dataset.ids = group.map(e => e.id).join(',');
    // A linked L/R bus pair becomes ONE tab. Unlink restores both individual
    // tabs using their original names; the paired alias is separate.
    var linkedGroup = group.length === 2 && STEREO_BUSES.includes(Number(group[0].id));
    if (linkedGroup) {
      var merged = {...group[0], pinned:group.some(x => x.pinned),
                    minimized:group.every(x => x.minimized)};
      tile.appendChild(makeTab(merged, group[1]));
    } else group.forEach(e => tile.appendChild(makeTab(e)));
    tile.classList.toggle('pinned', group.some(x => x.pinned));
    tile.querySelectorAll('.bus-grip').forEach(function (grip) {
    grip.addEventListener('pointerdown', function (event) {
      if (event.button !== 0 || group.some(x => x.pinned)) return;
      event.preventDefault();
      var pointerId = event.pointerId;
      var startX = event.clientX, startY = event.clientY;
      var dragged = false;
      tile.classList.add('dragging');
      function move(e) {
        if (e.pointerId !== pointerId) return;
        if (Math.hypot(e.clientX - startX, e.clientY - startY) >= 4) dragged = true;
        if (!dragged) return;
        var bounds = busTabs.getBoundingClientRect();
        if (e.clientX < bounds.left + 28) busTabs.scrollLeft -= 20;
        else if (e.clientX > bounds.right - 28) busTabs.scrollLeft += 20;
        var over = document.elementFromPoint(e.clientX, e.clientY)?.closest('.bus-tab-tile');
        if (over && over !== tile && over.parentNode === busTabs) {
          var rect = over.getBoundingClientRect();
          busTabs.insertBefore(tile, e.clientX > rect.left + rect.width / 2 ? over.nextSibling : over);
        }
      }
      function end(e) {
        if (e.pointerId !== pointerId) return;
        document.removeEventListener('pointermove', move);
        document.removeEventListener('pointerup', end);
        document.removeEventListener('pointercancel', end);
        tile.classList.remove('dragging');
        if (e.type === 'pointercancel') { renderBusTabs(); return; }
        if (!dragged) return;
        var before = busEntries();
        var by = new Map(before.map(x => [x.id, x]));
        var order = Array.from(busTabs.querySelectorAll(':scope > .bus-tab-tile')).flatMap(t => t.dataset.ids.split(','));
        saveBusTabs(order.map(id => by.get(id)).filter(Boolean));
      }
      document.addEventListener('pointermove', move); document.addEventListener('pointerup', end);
      document.addEventListener('pointercancel', end);
    });
    });
    busTabs.appendChild(tile);
  });
  updateBusMinCount(); updateBusTabSelection();
}
hideBusesBox.addEventListener('change', function () {
  var wanted = hideBusesBox.checked;
  renderBusTabs();
  savePreference('minimized buses preference', {hide_minimized_buses:wanted}, function () {
    confirmedHideBuses = wanted;
  }, function () {
    if (hideBusesBox.checked === wanted) { hideBusesBox.checked = confirmedHideBuses; renderBusTabs(); }
  }, true);
});

// ---- output buttons (right side): Main, Phones, then the buses ----
function markOutputs() {
  var busActive = OUTPUTS.some(function (o) { return o.id === currentOut && o.mix !== null; });
  Array.prototype.forEach.call(document.querySelectorAll(".outbtn"), function (b) {
    var o = OUTPUTS.filter(function (x) { return x.id === b.dataset.id; })[0];
    b.classList.toggle("active", b.dataset.id === currentOut);
    var shows = !busActive && o.mix !== null && (o.mix === currentMix || (STEREO_BUSES.includes(currentMix) && o.mix === currentMix+1));
    b.classList.toggle("shows", shows);
    b.title = shows ? o.name + " (the channel strips are showing this bus)" : o.name;
  });
  if (busTabsEnabled()) renderBusTabs();
}
var confirmedView = null;
function saveViewSelection() {
  var requested = {output: currentOut, mix: currentMix};
  return savePreference('selected output', requested, function () {
    confirmedView = Object.assign({}, requested);
  }, function () {
    if (confirmedView && currentOut === requested.output && currentMix === requested.mix) {
      currentOut = confirmedView.output;
      currentMix = confirmedView.mix;
      markOutputs(); loadMix(); loadMaster();
    }
  });
}
function selectOutput(o) {
  // DICE devices have monitor line outputs but no separate bus-master faders.
  // Clicking a non-controllable bus selects its matrix without hiding the
  // physical monitor's master fader.
  if (!o.controllable && o.mix !== null && OUTPUTS.some(function (x) { return x.mix === null && x.controllable; })) {
    var changed = currentMix !== o.mix;
    currentMix = STEREO_BUSES.includes(o.mix - o.mix % 2) ? o.mix - o.mix % 2 : o.mix;
    markOutputs();
    saveViewSelection();
    if (changed) { pendingStereoLeft = null; loadMix(); }
    return;
  }
  currentOut = o.id;
  var busChanged = o.mix !== null && o.mix !== currentMix;     // Main/Phones leave the channel strips alone
  if (o.mix !== null) currentMix = STEREO_BUSES.includes(o.mix - o.mix % 2) ? o.mix - o.mix % 2 : o.mix;
  markOutputs();
  saveViewSelection();
  if (busChanged) { pendingStereoLeft = null; loadMix(); }
  loadMaster();
}
function buildOutputs() {
  var box = document.getElementById("outbox");
  box.innerHTML = "";
  [["Outputs", function (o) { return o.mix === null; }],
   ["Buses",   function (o) { return o.mix !== null; }]].forEach(function (g) {
    var members = OUTPUTS.filter(g[1]);
    if (!members.length) return;
    var group = document.createElement("div");
    group.className = "outgroup" + (g[0] === "Buses" ? " bus-group" : "");
    group.innerHTML = '<div class="grouptitle">' + g[0] + '</div><div class="groupgrid' + (g[0] === "Buses" ? " busgrid" : "") + '"></div>';
    var grid = group.querySelector(".groupgrid");
    function makeOutputButton(o) {
      var btn = document.createElement("button");
      btn.className = "outbtn" + (o.mix !== null ? " bus" : "");
      btn.dataset.id = o.id;
      btn.innerHTML = '<span class="olabel"></span>';
      btn.firstChild.textContent = o.name;
      btn.title = o.name;
      btn.addEventListener("click", function () { selectOutput(o); });
      return btn;
    }
    function makeBusLink(left) {
      var linked = STEREO_BUSES.includes(left);
      var link = document.createElement('button');
      link.type = 'button'; link.className = 'bus-pair-link' + (linked ? ' is-linked' : '');
      link.textContent = linked ? '🔗 Bus ' + (left+1) + '+' + (left+2) : '↔ Link ' + (left+1) + '+' + (left+2);
      link.title = 'Toggle stereo bus link for pair ' + (left+1) + '/' + (left+2);
      link.onclick = () => post('/api/bus-stereo',{left:left,linked:!linked})
         .then(r => r.json().then(d => { if (!r.ok || d.error) throw Error(d.error || 'Bus link failed'); }))
         .then(() => deviceFetch('/api/describe').then(r => r.json()))
         .then(info => {
           STEREO_BUSES = info.stereo_buses || [];
           // A newly linked bus pair is represented by its LEFT bus. Do not
           // leave the mixer on the old Right-only state with disabled pan.
           if (STEREO_BUSES.includes(left) && currentMix === left + 1) currentMix = left;
           buildOutputs(); markOutputs(); loadMix();
         })
         .catch(e => toast(e.message));
      return link;
    }
    // Keep each stereo-bus link directly below its two bus buttons, even in
    // a six-column layout. Otherwise the link can wrap away from its pair.
    var byMix = {};
    members.forEach(function (o) { if (o.mix !== null) byMix[o.mix] = o; });
    var rendered = {};
    members.forEach(function (o) {
      if (rendered[o.id]) return;
      var leftMix = o.mix !== null ? o.mix - o.mix % 2 : -1;
      var left = byMix[leftMix], right = byMix[leftMix + 1];
      if (g[0] === 'Buses' && GAIN_SCALE && left && right) {
        var tile = document.createElement('div');
        tile.className = 'bus-pair-tile';
        tile.appendChild(makeOutputButton(left));
        tile.appendChild(makeOutputButton(right));
        tile.appendChild(makeBusLink(leftMix));
        grid.appendChild(tile);
        rendered[left.id] = rendered[right.id] = true;
      } else {
        grid.appendChild(makeOutputButton(o));
        rendered[o.id] = true;
      }
    });
    box.appendChild(group);
  });
  box.hidden = OUTPUTS.length < 2;
  renderBusTabs();
  scheduleBusGridLayout();
}

// ---- adaptive buses and resizable right bar ----
// The output and master controls remain in place on the right. A busy bus
// panel grows towards the left, within the desktop's available sidebar width.
// Small mixers (<= 8 bus entries) intentionally never exceed two columns.
var side = document.getElementById("side");
var splitter = document.getElementById("splitter");
var busGridFrame = 0;

// Bus pair cards take two columns and two rows, so the native CSS Grid
// measurement determines the right number of columns for any mixture of
// paired and unpaired bus entries. No assumptions about router data are made.
function sideLimits() {
  var busGrid = document.querySelector("#outbox .busgrid");
  var savedColumns = busGrid ? busGrid.style.getPropertyValue("--cols") : "";
  var wasNarrow = side.classList.contains("narrow"), wasWidth = side.style.width;
  // Measure the actual minimum two-column sidebar, not the currently expanded
  // bus grid. The drag handle must still shrink it to one column if requested.
  if (busGrid) busGrid.style.setProperty("--cols", "2");
  side.classList.remove("narrow");
  side.style.width = "";
  var two = side.getBoundingClientRect().width;
  var btn = document.querySelector(".outbtn"), grid = document.querySelector(".groupgrid");
  var hasButtons = !!btn && !document.getElementById("outbox").hidden;
  var step = hasButtons ? btn.offsetWidth + (parseFloat(getComputedStyle(grid).columnGap) || 8) : 76;
  var one = hasButtons ? two - step : two;
  if (wasWidth) side.style.width = wasWidth;
  side.classList.toggle("narrow", wasNarrow);
  if (busGrid) {
    if (savedColumns) busGrid.style.setProperty("--cols", savedColumns);
    else busGrid.style.removeProperty("--cols");
  }
  return { two: two, min: Math.ceil(one), max: Math.max(two, Math.min(window.innerWidth * 0.6, 800)),
           buttons: hasButtons, step: step };
}
function layoutBusGrid() {
  var grid = document.querySelector("#outbox .busgrid");
  var box = document.getElementById("outbox");
  if (!grid || box.hidden) return;
  var busCount = grid.querySelectorAll(".outbtn.bus").length;
  var lim = sideLimits();
  if (side.classList.contains("narrow")) {
    grid.style.setProperty("--cols", "1");
    return;
  }
  // Saved / manually resized sidebar widths take precedence. With the default
  // width, only grow as far as 60vw or 800px (whichever is smaller).
  var width = side.style.width ? Math.min(parseFloat(side.style.width), lim.max) : lim.max;
  var maxCols = Math.max(2, 2 + Math.floor((width - lim.two + 0.5) / lim.step));
  maxCols = Math.min(maxCols, busCount, 12);
  grid.style.setProperty("--cols", "2");
  if (busCount <= 8 || maxCols < 3) return;

  var body = side.querySelector(".sidebody");
  if (!body || body.clientHeight <= 0) return;
  // Read the actual CSS Grid height. This includes two-row stereo pair
  // cards, irregular bus counts, and mobile/short-window CSS media queries.
  var initialHeight = grid.getBoundingClientRect().height;
  // clientHeight includes the reserved toolbar clearance and bottom padding.
  // Subtract both so a tall bus grid cannot consume that safety gap.
  var bodyStyle = getComputedStyle(body);
  var verticalPadding = (parseFloat(bodyStyle.paddingTop) || 0) +
                        (parseFloat(bodyStyle.paddingBottom) || 0);
  var usableHeight = Math.max(0, body.clientHeight - verticalPadding);
  var remaining = usableHeight - (box.scrollHeight - initialHeight);
  if (initialHeight <= remaining + 1) return; // two columns already fit
  var selected = 2;
  // With pair cards, even column counts keep each Left/Right + link together.
  var hasLinks = !!grid.querySelector(".bus-pair-tile");
  for (var columns = hasLinks ? 4 : 3; columns <= maxCols; columns += hasLinks ? 2 : 1) {
    selected = columns;
    grid.style.setProperty("--cols", String(columns));
    if (grid.getBoundingClientRect().height <= remaining + 1) break;
  }
  grid.style.setProperty("--cols", String(selected));
}
function scheduleBusGridLayout() {
  if (busGridFrame) cancelAnimationFrame(busGridFrame);
  busGridFrame = requestAnimationFrame(function () {
    busGridFrame = 0;
    layoutBusGrid();
  });
}
function setSideWidth(w, lim) {
  w = Math.round(Math.max(lim.min, Math.min(lim.max, w)));
  side.style.width = w + "px";
  side.classList.toggle("narrow", lim.buttons && w < lim.two - 0.5);
  layoutBusGrid();
  return w;
}
var confirmedSideWidth = 0;
function saveSideWidth(width) {
  return savePreference('sidebar width', {side_width: width}, function () {
    confirmedSideWidth = width;
  }, function () {
    var current = side.style.width ? Math.round(parseFloat(side.style.width)) : 0;
    if (current !== width) return;
    if (confirmedSideWidth > 0) setSideWidth(confirmedSideWidth, sideLimits());
    else resetSideWidth();
  });
}
function resetSideWidth() {
  side.style.width = "";
  side.classList.remove("narrow");
  scheduleBusGridLayout();
}
splitter.addEventListener("pointerdown", function (e) {
  e.preventDefault();
  var lim = sideLimits(), startX = e.clientX, startW = side.getBoundingClientRect().width, width = startW;
  splitter.setPointerCapture(e.pointerId);
  document.body.classList.add("resizing");
  function move(ev) { width = setSideWidth(startW + (startX - ev.clientX), lim); }   // dragging left widens the bar
  function up(ev) {
    splitter.removeEventListener('pointermove', move);
    splitter.removeEventListener('pointerup', up);
    splitter.removeEventListener('pointercancel', up);
    document.body.classList.remove('resizing');
    if (ev && ev.type === 'pointercancel') {
      if (startW) setSideWidth(startW, sideLimits());
      return;
    }
    saveSideWidth(width);
  }
  splitter.addEventListener("pointermove", move);
  splitter.addEventListener("pointerup", up);
  splitter.addEventListener("pointercancel", up);
});
splitter.addEventListener("dblclick", function () {
  resetSideWidth();
  saveSideWidth(0);
});
window.addEventListener("resize", function () {                // keep a saved width inside the new window
  if (side.style.width) setSideWidth(parseFloat(side.style.width), sideLimits());
  scheduleBusGridLayout();
});
// A change in available height also changes how many bus columns are needed.
// Ignore width-only changes: those are handled by the splitter and window resize.
if (window.ResizeObserver) {
  var observedSideBodyHeight = null;
  new ResizeObserver(function (entries) {
    var height = entries[0].contentRect.height;
    if (height !== observedSideBodyHeight) {
      observedSideBodyHeight = height;
      scheduleBusGridLayout();
    }
  }).observe(side.querySelector(".sidebody"));
}

// ---- render the strips for the selected bus ----
var lastStripState = null;
var lastStripMix = null;
function renderStrips(state, layout) {
  lastStripState = state;
  lastStripMix = currentMix;
  row.innerHTML = "";
  var placed = {};
  function make(id, pinned, minimized) {
    var d = state[id];
    return buildStrip(id, d, pinned, minimized, d.partner ? state[d.partner] : null);
  }
  layout.forEach(function (entry) {
    var id = entry.id, d = state[id];
    if (!d || d.partner_of || placed[id]) return; // Right is hidden; Left retains its own position                                     // not visible right now, or already drawn
    placed[id] = true;
    row.appendChild(make(id, entry.pinned !== false, !!entry.minimized));
  });
  Object.keys(state).forEach(function (id) {                          // channels not in the saved layout yet
    if (placed[id] || state[id].partner_of) return;
    row.appendChild(make(id, true, false));
  });
  renderLinkButtons(state);
  updateMinCount();
}
// Link state is highlighted on the strip; actions live in its three-dot menu.
function renderLinkButtons(state) {
  row.querySelectorAll('.strip.stereo-pending').forEach(el => el.classList.remove('stereo-pending'));
  if (pendingStereoLeft && (!state[pendingStereoLeft] ||
      state[pendingStereoLeft].partner || state[pendingStereoLeft].partner_of)) {
    pendingStereoLeft = null;
  }
  row.querySelectorAll(':scope > .strip').forEach(function (el) {
    el.classList.toggle('stereo-pending', pendingStereoLeft === el.dataset.id);
  });
}
var loadToken = 0;
function loadMix(options) {
  // An unfinished Left selection belongs to the bus it was clicked on.
  if (pendingStereoMix !== currentMix) {
    pendingStereoLeft = null;
    pendingStereoMix = currentMix;
  }
  var token = ++loadToken;                 // ignore out-of-order replies when clicking quickly
  var mix = currentMix, device = ACTIVE_DEVICE;
  return Promise.all([
    window.ffadoApi.latest('mixer-state', '/api/state?mix=' + mix, {device}),
    window.ffadoApi.latest('mixer-layout', '/api/layout?mix=' + mix, {device})
  ]).then(function (res) {
    if (token !== loadToken || !res[0] || !res[1]) return;
    renderStrips(res[0], res[1]);
    loadMuteRecovery();
  }).catch(function (error) {
    if (token === loadToken && mix === currentMix && device === ACTIVE_DEVICE) {
      row.textContent = 'Could not read the mixer: ' + error.message;
      toast('Could not load mixer: ' + error.message);
      if (options && options.throwOnError === true) throw error;
    }
  });
}

window.refreshMatrixStrips = loadMix;

// Device chooser is available only with multiple interfaces. Server-side
// selections remain GUID-based and reload the page to isolate mixer state.
var deviceChoices = [], selectedDeviceGuid = null, switchingDevice = false;
var deviceButton = document.getElementById('deviceButton');
var deviceMenu = document.getElementById('deviceMenu');
function closeDeviceMenu(restoreFocus = false) {
  deviceMenu.hidden = true;
  deviceButton.setAttribute('aria-expanded', 'false');
  if (restoreFocus && !document.getElementById('devicebox').hidden) deviceButton.focus();
}
function positionDeviceMenu() {
  var rect = deviceButton.getBoundingClientRect();
  var left = Math.max(6, Math.min(rect.right - deviceMenu.offsetWidth, window.innerWidth - deviceMenu.offsetWidth - 6));
  var top = rect.bottom + 5;
  if (top + deviceMenu.offsetHeight > window.innerHeight - 6) top = Math.max(6, rect.top - deviceMenu.offsetHeight - 5);
  deviceMenu.style.left = left + 'px';
  deviceMenu.style.top = top + 'px';
}
function selectDevice(guid) {
  if (switchingDevice || guid === selectedDeviceGuid) { closeDeviceMenu(); return; }
  switchingDevice = true;
  deviceMenu.querySelectorAll('button').forEach(function (b) { b.disabled = true; });
  post('/api/device', {guid: guid}).then(function (r) {
    return r.json().then(function (result) {
      if (!r.ok || result.error) throw Error(result.error || 'Device selection failed');
      location.reload();
    });
  }).catch(function (error) {
    switchingDevice = false;
    closeDeviceMenu();
    toast('Could not switch audio interface: ' + error.message);
    // A failure must leave the prior device selected and the menu usable.
    renderDeviceMenu();
  });
}
function renderDeviceMenu() {
  deviceMenu.replaceChildren();
  deviceChoices.forEach(function (d) {
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'device-choice';
    b.setAttribute('role', 'menuitemradio');
    b.setAttribute('aria-checked', String(d.guid === selectedDeviceGuid));
    var check = document.createElement('span'); check.className = 'device-check';
    check.textContent = d.guid === selectedDeviceGuid ? '✓' : '';
    check.setAttribute('aria-hidden', 'true');
    var label = document.createElement('span'); label.className = 'device-label';
    var name = document.createElement('strong'); name.textContent = d.name;
    var details = document.createElement('small'); details.textContent = d.model || d.guid;
    label.append(name, details); b.append(check, label);
    b.disabled = switchingDevice;
    b.addEventListener('click', function () { selectDevice(d.guid); });
    deviceMenu.appendChild(b);
  });
}
deviceButton.addEventListener('click', function () {
  if (document.getElementById('devicebox').hidden || switchingDevice) return;
  if (!deviceMenu.hidden) { closeDeviceMenu(); return; }
  renderDeviceMenu();
  deviceMenu.hidden = false;
  deviceButton.setAttribute('aria-expanded', 'true');
  positionDeviceMenu();
  (deviceMenu.querySelector('[aria-checked="true"]') || deviceMenu.querySelector('button'))?.focus();
});
deviceMenu.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') { e.preventDefault(); closeDeviceMenu(true); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
    e.preventDefault();
    var items = Array.from(deviceMenu.querySelectorAll('button:not(:disabled)'));
    if (!items.length) return;
    var i = items.indexOf(document.activeElement);
    if (e.key === 'Home') i = 0;
    else if (e.key === 'End') i = items.length - 1;
    else i = (i + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[i].focus();
  }
});
document.addEventListener('pointerdown', function (e) {
  if (!deviceMenu.hidden && !deviceMenu.contains(e.target) && !deviceButton.contains(e.target)) closeDeviceMenu();
});
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape' && !deviceMenu.hidden) { e.preventDefault(); closeDeviceMenu(true); }
});
window.addEventListener('resize', function () { if (!deviceMenu.hidden) positionDeviceMenu(); });
function loadDevices() {
  window.ffadoApi.latest('devices', '/api/devices').then(function (data) {
    if (!data) return;
    deviceChoices = data.devices || [];
    selectedDeviceGuid = data.selected;
    var multiple = deviceChoices.length > 1;
    document.getElementById('devicebox').hidden = !multiple;
    if (!multiple) closeDeviceMenu();
    var chosen = deviceChoices.find(function (d) { return d.guid === selectedDeviceGuid; });
    deviceButton.title = chosen ? 'Switch audio interface (current: ' + chosen.name + ')' : 'Switch audio interface';
    var alias = document.getElementById('deviceAlias');
    if (alias && chosen) alias.value = chosen.alias || '';
    if (!deviceMenu.hidden) { renderDeviceMenu(); positionDeviceMenu(); }
  }).catch(function (e) { toast('Device discovery: ' + e.message); });
}
document.getElementById('saveDeviceAlias').addEventListener('click', () => {
  var name=document.getElementById('deviceAlias').value.trim();
  post('/api/device-alias',{name:name}).then(r=>r.json().then(d=>{
    if (!r.ok || d.error) throw Error(d.error || 'Cannot save alias');
    loadDevices();
  })).catch(e=>toast(e.message));
});

Promise.all([
  readJson('/api/describe'),
  readJson('/api/settings')
]).then(function (res) {
  var info = res[0], settings = res[1];
  FEATURES = info.features || {};
  GAIN_SCALE = info.gain_scale || null;
  ACTIVE_DEVICE = info.guid || null;
  window.activeFfadoDevice = ACTIVE_DEVICE;
  STEREO_BUSES = info.stereo_buses || [];
  STEREO_BUS_NAMES = info.stereo_bus_names || {};
  if (info.solo && info.solo.writable && !FEATURES.solo) FEATURES.software_solo = true;
  FADER_ALLOWED = !info.fader || !!info.fader.writable;
  MUTE_ALLOWED = !info.mute || !!info.mute.writable;
  MIXES = (info.mixes || []).map(function (m) { return Object.assign({}, m, {name: shortFfadoLabel(m.name)}); });
  if (window.configureRouting) window.configureRouting(info);
  OUTPUTS = (info.outputs || []).map(function (o) {
    return { id: o.id, name: shortFfadoLabel(o.name), baseName: o.base_name || o.name, mix: (o.mix === null || o.mix === undefined) ? null : o.mix, controllable: o.controllable,
             destination: !!o.destination };
  });
  document.title = info.device || "Mixer";
  window.syncNativeWindowTitle(info.device);
  accentOverrides = settings.accent_overrides && typeof settings.accent_overrides === "object" ? settings.accent_overrides : {};
  confirmedAccents = Object.assign({}, accentOverrides);
  confirmedTheme = settings.theme || 'dark';
  applyTheme(confirmedTheme);
  hideBox.checked = !!settings.hide_minimized;
  hideBusesBox.checked = !!settings.hide_minimized_buses;
  confirmedHideBuses = hideBusesBox.checked;
  confirmedHideMin = hideBox.checked;
  confirmedSideWidth = settings.side_width || 0;
  skipLoadingScreenBox.checked = !!settings.skip_loading_screen;
  setQjackctlEnabled(!!settings.enable_qjackctl);
  confirmedQjackctl = qjackctlEnabled;
  row.classList.toggle("hide-min", hideBox.checked);

  var sel = OUTPUTS.filter(function (o) { return o.id === settings.output && o.controllable; })[0] ||
            OUTPUTS.filter(function (o) { return o.mix === null && o.controllable; })[0] ||
            OUTPUTS.filter(function (o) { return o.id === settings.output; })[0] || OUTPUTS[0];
  currentOut = sel ? sel.id : "";
  if (sel && sel.mix !== null) currentMix = STEREO_BUSES.includes(sel.mix - sel.mix % 2) ? sel.mix - sel.mix % 2 : sel.mix;
  else if (settings.mix && settings.mix < MIXES.length) currentMix = settings.mix;
  else currentMix = MIXES.length ? MIXES[0].id : 0;
  // Saved settings may point to the Right leg of a now-linked output bus.
  if (currentMix % 2 && STEREO_BUSES.includes(currentMix - 1)) currentMix--;
  confirmedView = {output: currentOut, mix: currentMix};

  return readJson('/api/bus-layout').then(function (saved) {
    busLayout = Array.isArray(saved) ? saved : [];
  }).catch(function (error) {
    busLayout = [];
    toast('Could not load saved bus tabs: ' + error.message);
  }).then(function () {
  buildOutputs();
  loadDevices();
  loadMuteRecovery();
  markOutputs();
  loadMaster();            // shows the master box right away; the saved width is measured with it in place
  if (settings.side_width > 0) setSideWidth(settings.side_width, sideLimits());
  if (info.peak_metering) startPeakPolling();
  return loadMix();
  });
}).then(startSync).catch(function (error) {
  toast('Could not initialize mixer: ' + error.message);
});

// Read only source-mapped, hardware-provided DICE router destination peaks.
// FFADOPeakDisplay handles async polling and peak/clip hold separately.
var activePeakDisplay = null;
function startPeakPolling() {
  if (activePeakDisplay) activePeakDisplay.stop();
  activePeakDisplay = new FFADOPeakDisplay(row, ACTIVE_DEVICE);
  activePeakDisplay.start();
}

// A browser tab for web users; the OS default browser for the desktop client.
document.getElementById("aboutGithub").addEventListener("click", function (event) {
  if (!window.pywebview) return;
  event.preventDefault();
  postJson("/api/open-github", {}).catch(function (error) {
    console.error("Could not open GitHub:", error);
  });
});

// In the desktop client, request the host's default browser instead of navigating inside pywebview.
document.getElementById("aboutOpenMixer").addEventListener("click", function (event) {
  if (!window.pywebview) return;
  event.preventDefault();
  postJson("/api/open-mixer", {}).catch(function (error) { toast(error.message); });
});

// Hide the fullscreen control in pywebview, regardless of screen size.
function detectPywebviewClient() {
  if (window.pywebview) document.documentElement.classList.add("pywebview-client");
}
detectPywebviewClient();
window.addEventListener("pywebviewready", detectPywebviewClient);

// Fullscreen is available only when the browser supports the Fullscreen API.
const fullscreenButton = document.getElementById("fullscreenButton");
if (fullscreenButton) {
  function updateFullscreenButton() {
    const active = Boolean(document.fullscreenElement);
    fullscreenButton.classList.toggle("is-fullscreen", active);
    fullscreenButton.setAttribute("aria-pressed", String(active));
    fullscreenButton.setAttribute("aria-label", active ? "Exit fullscreen" : "Enter fullscreen");
    fullscreenButton.title = active ? "Exit fullscreen" : "Enter fullscreen";
  }
  fullscreenButton.addEventListener("click", async function () {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await document.documentElement.requestFullscreen();
      }
    } catch (error) {
      console.warn("Fullscreen unavailable:", error);
    }
  });
  document.addEventListener("fullscreenchange", updateFullscreenButton);
  updateFullscreenButton();
  if (!document.documentElement.requestFullscreen) fullscreenButton.disabled = true;
}
