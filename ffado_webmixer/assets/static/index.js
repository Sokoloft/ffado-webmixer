var row = document.getElementById("row");
var FEATURES = {};
var FADER_ALLOWED = true;
var MUTE_ALLOWED = true;
var OUTPUTS = [];
var MIXES = [];
var GAIN_SCALE = null;
var STEREO_BUSES = [];
var ACTIVE_DEVICE = null;
var currentMix = 0;       // which bus the channel strips show
var currentOut = "";      // which output the master fader controls (Main, Phones or a bus)

function fmtGain(v) { return (v >= 0 ? "+" : "") + v; }

// ---- server calls ----
var CLIENT_ID = Math.random().toString(36).slice(2) + Date.now().toString(36);
function post(url, body) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Client-Id": CLIENT_ID,
                                 "X-FFADO-Device": ACTIVE_DEVICE || "" },
                      body: JSON.stringify(body) });
}
// Device-specific reads must never silently return another unit when two
// tabs of the same browser share a session cookie and one changes devices.
function deviceFetch(url) {
  return fetch(url, {cache: "no-store", headers: ACTIVE_DEVICE ? {"X-FFADO-Device": ACTIVE_DEVICE} : {}});
}

function send(strip, control, value) {
  return post("/api/set", { strip: strip, control: control, value: value, mix: currentMix })
    .then(function (r) { return r.json().then(function (d) { if (!r.ok || d.error) throw Error(d.error || "FFADO rejected the change"); }); })
    .catch(function (e) { toast("Mixer change failed: " + e.message); loadMuteRecovery(); loadMix(); });
}
// Drags fire many events; send at most one request per 50 ms per key, always ending on the latest value.
var pendingVals = {}, sendTimers = {};
function throttled(key, value, fn) {
  if (sendTimers[key]) { pendingVals[key] = value; return; }
  fn(value);
  sendTimers[key] = setTimeout(function () {
    sendTimers[key] = null;
    if (key in pendingVals) { var v = pendingVals[key]; delete pendingVals[key]; fn(v); }
  }, 50);
}
function sendThrottled(strip, control, value) {
  throttled(strip + "|" + control, value, function (v) { send(strip, control, v); });
}

// Interrupted software mute/solo is journaled per FireWire GUID. No automatic
// restoration: recovering nonzero gains after a reboot could be dangerously loud.
function loadMuteRecovery() {
  deviceFetch('/api/mute-recovery').then(r => r.json()).then(data => {
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
function isPinned(el) { return el.classList.contains("pinned"); }
function isMin(el) { return el.classList.contains("minimized"); }
function saveLayout() {
  var layout = Array.prototype.map.call(row.querySelectorAll(":scope > .strip"), function (s) {
    return { id: s.dataset.id, pinned: isPinned(s), minimized: isMin(s) };
  });
  return post("/api/layout?mix=" + currentMix, layout);   // each bus keeps its own order / pins / minimized
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
  var btn = el.querySelector(".eye");
  btn.innerHTML = min ? EYE_SHUT : EYE_OPEN;
  btn.title = min ? "Maximize" : "Minimize";
  el.querySelector(".vname").textContent = vertical(el.querySelector(".name").value);
  updateMinCount();
}
function setPinned(el, pinned) {
  el.classList.toggle("pinned", pinned);
  el.querySelector(".pin").title = pinned ? "Pinned. Click to unpin and move" : "Click to pin in place";
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
  row.querySelectorAll('.strip .link-toggle, .strip.stereo .unlink').forEach(function (button) {
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

// ---- a fader: precise fractional level where FFADO declares native dB gain ----
function makeFader(track, handle, label, onChange) {
  var value = 0, dragging = false;
  function render() {
    handle.style.top = (100 - value) + "%";
    if (GAIN_SCALE && (GAIN_SCALE.mode === "dice_db" || GAIN_SCALE.mode === "rme_db")) {
      var db = value === 0 ? null : GAIN_SCALE.min_db + value * (GAIN_SCALE.max_db - GAIN_SCALE.min_db) / 100;
      label.textContent = db === null ? "−∞ dB" : (db > 0 ? "+" : "") + db.toFixed(1) + " dB";
    } else {
      label.textContent = value === 0 ? "−∞" : value;
    }
  }
  function setValue(v) {
    var precise = GAIN_SCALE && (GAIN_SCALE.mode === "dice_db" || GAIN_SCALE.mode === "rme_db");
    value = Math.min(100, Math.max(0, precise ? Math.round(v * 10000) / 10000 : Math.round(v)));
    render();
    onChange(value);
  }
  handle.addEventListener("pointerdown", function (e) {
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
  // wheel over the fader: 2 per notch, 1 with Shift held
  var acc = { v: 0 };
  track.parentNode.addEventListener("wheel", function (e) {
    e.preventDefault();
    var dir = wheelDir(e, acc);
    if (dir) setValue(value + dir * (GAIN_SCALE ? (e.shiftKey ? 0.15 : 0.75) : (e.shiftKey ? 1 : 2)));
  }, { passive: false });
  return { set: function (v) { if (dragging) return; value = Math.min(100, Math.max(0, GAIN_SCALE ? Number(v) : Math.round(v))); render(); } };
}

// ---- a gain box: shown as +20, typed as 20 or +20; Up/Down arrows and the mouse wheel nudge it ----
function bindGain(inputEl, chId, initial) {
  var gmin = FEATURES.gain.min, gmax = FEATURES.gain.max, gain = initial, acc = { v: 0 };
  var missing = function () { return gain === undefined || gain === null; };
  inputEl.disabled = !FEATURES.gain.writable;
  inputEl.value = missing() ? "" : fmtGain(gain);
  inputEl.classList.toggle("na", missing());
  function commit(v, rapid) {
    if (isNaN(v) || missing()) { inputEl.value = missing() ? "" : fmtGain(gain); return; }
    gain = Math.max(gmin, Math.min(gmax, v));
    inputEl.value = fmtGain(gain);
    if (rapid) throttled(chId + "|gain", gain, function (x) { send(chId, "gain", x); });
    else send(chId, "gain", gain);
  }
  inputEl.addEventListener("wheel", function (e) {            // wheel over the box: +/-1 per notch
    if (inputEl.disabled || missing()) return;
    e.preventDefault();
    var dir = wheelDir(e, acc);
    if (dir) commit(gain + dir, true);
  }, { passive: false });
  inputEl.addEventListener("focus", function () { inputEl.select(); });
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
    '<button class="pin">' + PIN_SVG + '</button>' +
    '<button class="eye"></button>' +
    '<div class="vname"></div>' +
    '<div class="gaininv"><div class="gainrow" title="Hardware input gain/trim, separate from digital mixer volume"><div class="cap">INPUT GAIN</div>' +
      '<div class="gainboxes"><input class="gain" type="text" inputmode="numeric" autocomplete="off" spellcheck="false" aria-label="Hardware input gain"></div></div>' +
      '<button class="invert" title="Polarity (invert)">\u00D8</button></div>' +
    '<div class="panrow"><div class="caprow"><span>PAN</span><span class="panval">0</span></div>' +
      '<input class="pan" type="range" min="-100" max="100" step="1" value="0" title="Double-click to center"></div>' +

    '<input class="name" maxlength="16" spellcheck="false" title="Rename">' +
    '<button class="btn solo">Solo</button>' +
    '<div class="fval" title="Digital mixer volume"></div>' +
    '<div class="faderwrap"><div class="track" title="Digital mixer volume"><div class="handle"></div></div>' +
      '<button type="button" class="peak-meter" hidden title="FFADO router destination peak (not post-fader)" aria-label="Clear peak holds">' +
        '<span class="peak-lane" data-side="left"><span class="peak-bar"></span><span class="peak-hold"></span><span class="peak-clip"></span></span>' +
        (stereo ? '<span class="peak-lane" data-side="right"><span class="peak-bar"></span><span class="peak-hold"></span><span class="peak-clip"></span></span>' : '') +
      '</button></div>' +
    '<button class="btn mute">Mute</button>' +
    '<div class="inname" title="Hardware input"></div>' +
    (stereo ? '<button class="unlink" type="button" title="Unlink stereo channels" aria-label="Unlink stereo channels">' + CHAIN_LINK_SVG + '</button>' : '');

  var q = function (sel) { return el.querySelector(sel); };
  var nameEl = q(".name"), invertEl = q(".invert");
  var panEl = q(".pan"), panVal = q(".panval"), soloEl = q(".solo");
  // Do not turn an unavailable hardware balance (null) into fake center.
  var panAvailable = data.pan !== null && data.pan !== undefined &&
    Number.isFinite(Number(data.pan)) && data.pan_available !== false;
  var pan = panAvailable ? Number(data.pan) : 0;
  var missing = function (v) { return v === undefined || v === null; };

  // which controls this device offers (and which this particular channel has)
  q(".panrow").hidden = !FEATURES.pan && !STEREO_BUSES.includes(currentMix);
  if (stereo) invertEl.title = "Polarity of both channels";
  soloEl.hidden = !FEATURES.solo && !(FEATURES.software_solo);
  q(".mute").hidden = !MUTE_ALLOWED;
  q(".faderwrap").classList.toggle("read-only", !FADER_ALLOWED);
  q(".gainrow").hidden = !FEATURES.gain;
  invertEl.hidden = !FEATURES.invert;
  q(".gaininv").hidden = !FEATURES.gain && !FEATURES.invert;
  q(".gainrow").classList.toggle("na", missing(data.gain) && (!stereo || missing(partner.gain)));
  invertEl.classList.toggle("na", missing(data.invert) && (!stereo || missing(partner.invert)));
  q(".inname").textContent = data.input || "";

  // rename (the label above the solo button): Enter saves, Esc reverts. A stereo pair is named under its left channel.
  nameEl.value = data.name;
  var lastName = data.name;
  nameEl.addEventListener("change", function () {
    var n = nameEl.value.trim() || lastName;
    nameEl.value = n; lastName = n;
    q(".vname").textContent = vertical(n);
    send(id, "name", n);
  });
  nameEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter") nameEl.blur();
    if (e.key === "Escape") { nameEl.value = lastName; nameEl.blur(); }
  });

  // gain: one box. On a stereo strip the server applies it to both channels.
  var gain1 = null;
  if (FEATURES.gain) gain1 = bindGain(q(".gain"), id, missing(data.gain) && stereo ? partner.gain : data.gain);

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
  if (FEATURES.pan || STEREO_BUSES.includes(currentMix)) {
    panEl.disabled = !panAvailable ||
      (STEREO_BUSES.includes(currentMix) ? false : !FEATURES.pan.writable);
    if (data.pan_note) {
      panEl.title = data.pan_note;
      panVal.title = data.pan_note;
    } else if (!panAvailable) {
      panEl.title = "Hardware balance is unavailable";
      panVal.title = panEl.title;
    }
    panEl.addEventListener("input", function () {
      if (panEl.disabled) return;
      pan = parseInt(panEl.value, 10) / 100;
      renderPan();
      sendThrottled(id, "pan", pan);
    });
    panEl.addEventListener("dblclick", function () {
      if (panEl.disabled) return;
      pan = 0; renderPan(); send(id, "pan", 0);
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
      renderPan();
      sendThrottled(id, "pan", pan);
    }, { passive: false });
  }

  // fader, solo, mute. On a stereo strip these go to the left channel and the server moves the right one too.
  var fader = makeFader(q(".track"), q(".handle"), q(".fval"), function (v) { if (FADER_ALLOWED) sendThrottled(id, "fader", v); });
  function toggleHardware(control, on) {
    post('/api/set', { strip:id, control:control, value:on, mix:currentMix })
      .then(r => r.json().then(d => { if (!r.ok || d.error) throw Error(d.error || 'Hardware write failed'); }))
      .then(() => el.classList.toggle(control === 'solo' ? 'soloed' : 'muted', on))
      .catch(e => { toast(control + ': ' + e.message); loadMix(); });
  }
  soloEl.addEventListener("click", function () { toggleHardware('solo', !el.classList.contains('soloed')); });
  q(".mute").addEventListener("click", function () { if (MUTE_ALLOWED) toggleHardware('mute', !el.classList.contains('muted')); });
  if (stereo) {
    q(".unlink").title = 'Unlink — Left: ' + (data.input || id) + ', Right: ' + (partner.input || pid);
    q(".unlink").disabled = stereoLinkBusy;
    q(".unlink").addEventListener("click", function () { unlinkStrip(id); });
  }

  // pin / minimize / drag
  q(".pin").addEventListener("click", function () { setPinned(el, !isPinned(el)); saveLayout(); });
  q(".eye").addEventListener("click", function () {
    setMinimized(el, !isMin(el));
    if (lastStripState) renderLinkButtons(lastStripState);
    saveLayout();
  });
  q(".grip").addEventListener("pointerdown", function (e) { startDrag(el, e); });
  q(".vname").addEventListener("pointerdown", function (e) { startDrag(el, e); });

  var panDragging = false;
  panEl.addEventListener("pointerdown", function () {
    panDragging = true;
    window.addEventListener("pointerup", function () { panDragging = false; }, { once: true });
  });
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
        panEl.disabled = !panAvailable ||
          (STEREO_BUSES.includes(currentMix) ? false : !FEATURES.pan.writable);
        renderPan();
      }
    }
    else if (control === "name") {
      if (stripId && stripId !== id) return;          // the right channel's own name isn't shown on a stereo strip
      if (document.activeElement !== nameEl) { nameEl.value = value; lastName = value; q(".vname").textContent = vertical(value); }
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
    valueLabel.textContent = "MAX " + valueLabel.textContent;
    valueLabel.classList.add("level-mismatch");
    if (Array.isArray(data.pair_faders)) {
      var labelFor = function (v) {
        if (!GAIN_SCALE) return String(Math.round(v));
        if (!v) return "−∞ dB";
        var db = GAIN_SCALE.min_db + v * (GAIN_SCALE.max_db - GAIN_SCALE.min_db) / 100;
        return db.toFixed(1) + " dB";
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
fetch("/api/themes").then(r => r.json()).then(names => {
  THEMES.splice(0, THEMES.length, ...names);
  themeSelect.replaceChildren(...names.map(name => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name.replace(/[-_]/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    return option;
  }));
  applyTheme(document.documentElement.dataset.theme || "dark");
}).catch(console.error);
function applyTheme(name) {
  if (THEMES.length && THEMES.indexOf(name) === -1) name = "dark";
  name = setMixerTheme(name);
  themeSelect.value = name;
  if (typeof updateAccent === "function") updateAccent();
}
themeSelect.addEventListener("change", function () {
  applyTheme(themeSelect.value);
  post("/api/settings", { theme: themeSelect.value });
});

// Accent overrides are stored per theme in the existing settings JSON.
var accentOverrides = {};
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
  return post("/api/settings", { accent_overrides: accentOverrides });
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
  fetch("/api/qjackctl/status", { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error("Status unavailable");
    return r.json();
  }).then(function (status) {
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
  var oldValue = qjackctlEnabled;
  var newValue = jackEnableBox.checked;
  setQjackctlEnabled(newValue);
  post("/api/settings", { enable_qjackctl: newValue }).then(function (response) {
    if (!response.ok) throw Error("Could not save QjackCtl setting");
  }).catch(function (error) {
    setQjackctlEnabled(oldValue);
    toast(error.message);
  });
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
    post("/api/qjackctl", { window: btn.dataset.window }).then(function (r) { return r.json(); }).then(function (d) {
      if (d.error) showJackMessage(d.error, true);
      else showJackMessage("Asked QjackCtl to open the " + label + ". If nothing opens, turn on Setup > Misc > Other > " +
                           "Enable D-Bus interface in QjackCtl.", false);
    }).catch(function () {
      showJackMessage("Couldn't reach the server.", true);
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
  fetch("/api/about").then(function (r) { return r.json(); }).then(function (a) {
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
  });
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
  post("/api/settings", { skip_loading_screen: skipLoadingScreenBox.checked });
});
hideBox.addEventListener("change", function () {
  row.classList.toggle("hide-min", hideBox.checked);
  post("/api/settings", { hide_minimized: hideBox.checked });
});

// ---- master (output) fader: Main, Phones or a bus ----
var masterEl = document.getElementById("master");
var masterToken = 0;
var masterFader = makeFader(document.getElementById("masterTrack"), document.getElementById("masterHandle"),
  document.getElementById("masterVal"), function (v) {
    var out = currentOut;
    throttled("out|" + out, v, function (x) {
      post("/api/output", { out: out, control: "fader", value: x })
        .then(function (r) { return r.json().then(function (d) { if (!r.ok || d.error) throw Error(d.error || "Unable to set output"); }); })
        .catch(function (e) { toast("Output change failed: " + e.message); });
    });
  });
document.getElementById("masterMute").addEventListener("click", function () {
  var want = !masterEl.classList.contains("muted");
  post("/api/output", { out: currentOut, control: "mute", value: want }).then(loadMaster);   // reload: Main/Phones mute moves the fader
});
// ---- rename the active output (Main, Phones, a bus): click its label above the master fader ----
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
}
masterName.addEventListener("change", function () {
  var name = masterName.value.trim() || lastMasterName;
  masterName.value = name;
  if (name === lastMasterName) return;
  applyOutputName(currentOut, name);
  post("/api/set", { strip: "out:" + currentOut, control: "name", value: name });     // saved with the other names
});
masterName.addEventListener("keydown", function (e) {
  if (e.key === "Enter") masterName.blur();
  if (e.key === "Escape") { masterName.value = lastMasterName; masterName.blur(); }
});
masterName.addEventListener("focus", function () { masterName.select(); });

function loadMaster() {
  var out = OUTPUTS.filter(function (o) { return o.id === currentOut; })[0];
  masterEl.hidden = !out || !out.controllable;
  document.getElementById("masterbox").hidden = masterEl.hidden;
  if (masterEl.hidden) return;
  masterHardwareName.textContent = out.baseName;
  var token = ++masterToken;
  return deviceFetch("/api/output?out=" + encodeURIComponent(currentOut)).then(function (r) { return r.json(); }).then(function (o) {
    if (token !== masterToken || o.error) return;
    showMasterName(o.name);
    masterFader.set(o.level);
    masterEl.classList.toggle("muted", !!o.mute);
  });
}

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
}
function selectOutput(o) {
  // DICE devices have monitor line outputs but no separate bus-master faders.
  // Clicking a non-controllable bus selects its matrix without hiding the
  // physical monitor's master fader.
  if (!o.controllable && o.mix !== null && OUTPUTS.some(function (x) { return x.mix === null && x.controllable; })) {
    var changed = currentMix !== o.mix;
    currentMix = STEREO_BUSES.includes(o.mix - o.mix % 2) ? o.mix - o.mix % 2 : o.mix;
    markOutputs();
    post("/api/settings", { output: currentOut, mix: currentMix });
    if (changed) { pendingStereoLeft = null; loadMix(); }
    return;
  }
  currentOut = o.id;
  var busChanged = o.mix !== null && o.mix !== currentMix;     // Main/Phones leave the channel strips alone
  if (o.mix !== null) currentMix = STEREO_BUSES.includes(o.mix - o.mix % 2) ? o.mix - o.mix % 2 : o.mix;
  markOutputs();
  post("/api/settings", { output: currentOut, mix: currentMix });
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
         .then(info => { STEREO_BUSES=info.stereo_buses||[]; buildOutputs(); loadMix(); })
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
  function up() {
    splitter.removeEventListener("pointermove", move);
    splitter.removeEventListener("pointerup", up);
    splitter.removeEventListener("pointercancel", up);
    document.body.classList.remove("resizing");
    post("/api/settings", { side_width: width });
  }
  splitter.addEventListener("pointermove", move);
  splitter.addEventListener("pointerup", up);
  splitter.addEventListener("pointercancel", up);
});
splitter.addEventListener("dblclick", function () {
  resetSideWidth();
  post("/api/settings", { side_width: 0 });
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
// Each mono strip gets its own link button at the lower right. A pending
// first click is highlighted as Left; all other unpaired channels can be Right.
function renderLinkButtons(state) {
  row.querySelectorAll('.strip > .link-toggle').forEach(b => b.remove());
  row.querySelectorAll('.strip.stereo-pending').forEach(el => el.classList.remove('stereo-pending'));
  if (pendingStereoLeft && (!state[pendingStereoLeft] ||
      state[pendingStereoLeft].partner || state[pendingStereoLeft].partner_of)) {
    pendingStereoLeft = null;
  }
  row.querySelectorAll(':scope > .strip').forEach(el => {
    var id = el.dataset.id;
    if (!state[id] || state[id].partner || state[id].partner_of) return;
    var selected = pendingStereoLeft === id;
    el.classList.toggle('stereo-pending', selected);
    var b = document.createElement('button');
    b.className = 'unlink link-toggle';
    b.type = 'button';
    b.title = selected ? 'Cancel Left selection' :
      (pendingStereoLeft ? 'Select channel as Right' : 'Select channel as Left');
    b.innerHTML = CHAIN_LINK_SVG;
    b.setAttribute('aria-label', b.title);
    b.setAttribute('aria-pressed', String(selected));
    b.disabled = stereoLinkBusy;
    b.addEventListener('click', () => chooseStereoChannel(id));
    el.appendChild(b);
  });
}
var loadToken = 0;
function loadMix() {
  // An unfinished Left selection belongs to the bus it was clicked on.
  if (pendingStereoMix !== currentMix) {
    pendingStereoLeft = null;
    pendingStereoMix = currentMix;
  }
  var token = ++loadToken;                 // ignore out-of-order replies when clicking quickly
  return Promise.all([
    deviceFetch("/api/state?mix=" + currentMix).then(function (r) { return r.json(); }),
    deviceFetch("/api/layout?mix=" + currentMix).then(function (r) { return r.json(); })
  ]).then(function (res) {
    if (token !== loadToken) return;
    if (res[0].error) { row.textContent = "Could not read the mixer: " + res[0].error; return; }
    renderStrips(res[0], res[1]);
    loadMuteRecovery();
  });
}

window.refreshMatrixStrips = loadMix;

// Device tabs are per browser session. Saved names are stored by GUID.
function loadDevices() {
  fetch('/api/devices').then(r=>r.json()).then(data => {
    var tabs=document.getElementById('deviceTabs'); tabs.replaceChildren();
    tabs.hidden = !data.devices || data.devices.length < 2;
    (data.devices || []).forEach(d => {
      var b=document.createElement('button'); b.type='button';
      b.className='device-tab' + (data.selected===d.guid ? ' active':'');
      b.textContent=d.name; b.title=d.model + ' · ' + d.guid;
      b.setAttribute('role','tab'); b.setAttribute('aria-selected', String(data.selected===d.guid));
      b.addEventListener('click', () => {
        if (data.selected===d.guid || b.disabled) return;
        b.disabled = true;
        post('/api/device',{guid:d.guid}).then(r=>r.json().then(v=>{
          if (!r.ok || v.error) throw Error(v.error||'Device selection failed');
          location.reload();
        })).catch(e=>{ b.disabled = false; toast(e.message); });
      });
      tabs.appendChild(b);
    });
    var chosen=(data.devices||[]).find(d=>d.guid===data.selected);
    var alias=document.getElementById('deviceAlias'); if (alias && chosen) alias.value=chosen.alias||'';
  }).catch(e=>toast('Device discovery: '+e.message));
}
document.getElementById('saveDeviceAlias').addEventListener('click', () => {
  var name=document.getElementById('deviceAlias').value.trim();
  post('/api/device-alias',{name:name}).then(r=>r.json().then(d=>{
    if (!r.ok || d.error) throw Error(d.error || 'Cannot save alias');
    loadDevices();
  })).catch(e=>toast(e.message));
});

// ---- live sync: changes made on other pages arrive here ----
function stripEl(id) {                          // a stereo strip answers to both of its channels
  return row.querySelector('.strip[data-id="' + id + '"], .strip[data-partner="' + id + '"]');
}

function applyLayout() {                         // order / pinned / minimized changed on another page
  if (row.querySelector(".dragging")) return;    // don't yank a strip out of the user's hand
  deviceFetch("/api/layout?mix=" + currentMix).then(function (r) { return r.json(); }).then(function (layout) {
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
  });
}

function onSyncEvent(ev) {
  if (ev.device && ACTIVE_DEVICE && ev.device !== ACTIVE_DEVICE) return;
  if (window.routingSyncEvent) window.routingSyncEvent(ev);
  // Matrix writes change derived fader and pan values, including our own writes.
  // Always re-read the affected bus; a single crosspoint can change both.
  if (ev.type === "matrix") {
    if (ev.output === currentMix ||
        (STEREO_BUSES.includes(currentMix) && ev.output === currentMix + 1)) loadMix();
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
    if (ev.control === "fader" || ev.control === "pan") { loadMix(); return; }
    el = stripEl(ev.strip);
    if (el) el._apply(ev.control, ev.value, ev.strip);
  } else if (ev.type === "name") {
    if (ev.strip.indexOf("out:") === 0) { applyOutputName(ev.strip.slice(4), ev.value); return; }
    el = stripEl(ev.strip);
    if (el) el._apply("name", ev.value, ev.strip);
  } else if (ev.type === "output") {
    if (ev.out !== currentOut) return;
    if (ev.control === "fader") masterFader.set(ev.value); else loadMaster();   // Main/Phones mute can move the level
  } else if (ev.type === "layout") {
    if (ev.mix === currentMix) applyLayout();     // another bus's arrangement doesn't concern this page
  } else if (ev.type === "bus-stereo") {
    deviceFetch('/api/describe').then(r => r.json()).then(info => {
      STEREO_BUSES = info.stereo_buses || []; buildOutputs(); loadMix();
    });
  } else if (ev.type === "stereo") {
    if (ev.mix !== undefined && ev.mix !== currentMix) return;
    if (!row.querySelector(".dragging")) loadMix();   // only this bus's pairs changed
  }
}

var syncOpened = false;
function startSync() {
  var source = new EventSource("/api/events");
  source.onmessage = function (m) { try { onSyncEvent(JSON.parse(m.data)); } catch (e) { /* ignore a bad message */ } };
  source.onopen = function () {
    if (syncOpened) { loadMix(); loadMaster(); }  // reconnected: pick up anything missed meanwhile
    syncOpened = true;
  };
}

Promise.all([
  deviceFetch("/api/describe").then(function (r) { return r.json(); }),
  deviceFetch("/api/settings").then(function (r) { return r.json(); })
]).then(function (res) {
  var info = res[0], settings = res[1];
  FEATURES = info.features || {};
  GAIN_SCALE = info.gain_scale || null;
  ACTIVE_DEVICE = info.guid || null;
  window.activeFfadoDevice = ACTIVE_DEVICE;
  STEREO_BUSES = info.stereo_buses || [];
  if (info.solo && info.solo.writable && !FEATURES.solo) FEATURES.software_solo = true;
  FADER_ALLOWED = !info.fader || !!info.fader.writable;
  MUTE_ALLOWED = !info.mute || !!info.mute.writable;
  MIXES = info.mixes || [];
  if (window.configureRouting) window.configureRouting(info);
  OUTPUTS = (info.outputs || []).map(function (o) {
    return { id: o.id, name: o.name, baseName: o.base_name || o.name, mix: (o.mix === null || o.mix === undefined) ? null : o.mix, controllable: o.controllable,
             destination: !!o.destination };
  });
  document.title = info.device || "Mixer";
  accentOverrides = settings.accent_overrides && typeof settings.accent_overrides === "object" ? settings.accent_overrides : {};
  applyTheme(settings.theme || "dark");
  hideBox.checked = !!settings.hide_minimized;
  skipLoadingScreenBox.checked = !!settings.skip_loading_screen;
  setQjackctlEnabled(!!settings.enable_qjackctl);
  row.classList.toggle("hide-min", hideBox.checked);

  var sel = OUTPUTS.filter(function (o) { return o.id === settings.output && o.controllable; })[0] ||
            OUTPUTS.filter(function (o) { return o.mix === null && o.controllable; })[0] ||
            OUTPUTS.filter(function (o) { return o.id === settings.output; })[0] || OUTPUTS[0];
  currentOut = sel ? sel.id : "";
  if (sel && sel.mix !== null) currentMix = STEREO_BUSES.includes(sel.mix - sel.mix % 2) ? sel.mix - sel.mix % 2 : sel.mix;
  else if (settings.mix && settings.mix < MIXES.length) currentMix = settings.mix;
  else currentMix = MIXES.length ? MIXES[0].id : 0;

  buildOutputs();
  loadDevices();
  loadMuteRecovery();
  markOutputs();
  loadMaster();            // shows the master box right away; the saved width is measured with it in place
  if (settings.side_width > 0) setSideWidth(settings.side_width, sideLimits());
  if (info.peak_metering) startPeakPolling();
  return loadMix();
}).then(startSync);

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
  fetch("/api/open-github", { method: "POST" }).catch(function (error) {
    console.error("Could not open GitHub:", error);
  });
});

// In the desktop client, request the host's default browser instead of navigating inside pywebview.
document.getElementById("aboutOpenMixer").addEventListener("click", function (event) {
  if (!window.pywebview) return;
  event.preventDefault();
  fetch("/api/open-mixer", { method: "POST" }).then(function (response) {
    if (!response.ok) throw Error("Could not open the mixer in the system browser");
  }).catch(function (error) { toast(error.message); });
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
