var row = document.getElementById("row");
var FEATURES = {};
var OUTPUTS = [];
var MIXES = [];
var currentMix = 0;       // which bus the channel strips show
var currentOut = "";      // which output the master fader controls (Main, Phones or a bus)

function fmtGain(v) { return (v >= 0 ? "+" : "") + v; }

// ---- server calls ----
var CLIENT_ID = Math.random().toString(36).slice(2) + Date.now().toString(36);
function post(url, body) {
  return fetch(url, { method: "POST", headers: { "Content-Type": "application/json", "X-Client-Id": CLIENT_ID },
                      body: JSON.stringify(body) });
}
function send(strip, control, value) {
  post("/api/set", { strip: strip, control: control, value: value, mix: currentMix });
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
  var layout = Array.prototype.map.call(row.children, function (s) {
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
// Dropping a strip on the MIDDLE of another one links them as a stereo pair. Near either edge it reorders as before.
function canLink(a, b) {
  return a !== b && !isMin(a) && !isMin(b) && !a.classList.contains("stereo") && !b.classList.contains("stereo");
}
function linkStrips(dragged, target, saved) {
  Promise.resolve(saved).then(function () {          // the new order is saved first, so the pair lands in the right slot
    return post("/api/stereo?mix=" + currentMix, { action: "link", dragged: dragged, target: target });
  }).then(function (r) { return r.json(); }).then(function (res) {
    if (res.error) toast("Couldn't link: " + res.error);
    loadMix();
  });
}
function unlinkStrip(id) {
  post("/api/stereo?mix=" + currentMix, { action: "unlink", id: id })
    .then(function (r) { return r.json(); }).then(function (res) {
      if (res.error) toast("Couldn't unlink: " + res.error);
      loadMix();
    });
}

function startDrag(el, e) {
  if (isPinned(el)) return;
  e.preventDefault();
  el.classList.add("dragging");
  var linkTarget = null;
  function setLinkTarget(t) {
    if (t === linkTarget) return;
    if (linkTarget) linkTarget.classList.remove("link-target");
    linkTarget = t;
    if (t) t.classList.add("link-target");
  }
  function move(ev) {
    var t = document.elementFromPoint(ev.clientX, ev.clientY);
    if (!t) return;
    var over = t.closest(".strip");
    if (over && over !== el && over.parentNode === row) {
      var r = over.getBoundingClientRect(), frac = (ev.clientX - r.left) / r.width;
      if (canLink(el, over) && frac > 0.25 && frac < 0.75) { setLinkTarget(over); return; }   // hover = link candidate
      setLinkTarget(null);
      place(el, over, frac > 0.5);
    } else {
      setLinkTarget(null);
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
    var target = linkTarget;
    setLinkTarget(null);
    var saved = saveLayout();
    if (target) linkStrips(el.dataset.id, target.dataset.id, saved);
  }
  document.addEventListener("pointermove", move);
  document.addEventListener("pointerup", up);
  document.addEventListener("pointercancel", up);
}

// ---- a fader: drag the handle; the value is a whole number 0..100 ----
function makeFader(track, handle, label, onChange) {
  var value = 0, dragging = false;
  function render() {
    handle.style.top = (100 - value) + "%";
    label.textContent = value === 0 ? "\u221E" : value;      // 0 reads as the infinity symbol
  }
  function setValue(v) {
    value = Math.min(100, Math.max(0, Math.round(v)));
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
    if (dir) setValue(value + dir * (e.shiftKey ? 1 : 2));
  }, { passive: false });
  return { set: function (v) { if (dragging) return; value = Math.min(100, Math.max(0, Math.round(v))); render(); } };
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
  if (stereo) el.dataset.partner = pid;
  el.innerHTML =
    '<div class="grip">::::</div>' +
    '<button class="pin">' + PIN_SVG + '</button>' +
    '<button class="eye"></button>' +
    '<div class="vname"></div>' +
    '<div class="gaininv"><div class="gainrow"><div class="cap">GAIN</div>' +
      '<div class="gainboxes"><input class="gain" type="text" inputmode="numeric" autocomplete="off" spellcheck="false"></div></div>' +
      '<button class="invert" title="Polarity (invert)">\u00D8</button></div>' +
    '<div class="panrow"><div class="caprow"><span>PAN</span><span class="panval">0</span></div>' +
      '<input class="pan" type="range" min="-100" max="100" step="1" value="0" title="Double-click to center"></div>' +
    '<div class="stereorow" hidden><div class="caprow"><span>STEREO</span><span class="stval">L+R</span></div>' +
      '<div class="stereobtns"><button class="unlink" title="Split this pair back into two channels">Unlink</button></div></div>' +
    '<input class="name" maxlength="16" spellcheck="false" title="Rename">' +
    '<button class="btn solo">Solo</button>' +
    '<div class="fval"></div>' +
    '<div class="faderwrap"><div class="track"><div class="handle"></div></div></div>' +
    '<button class="btn mute">Mute</button>' +
    '<div class="inname" title="Hardware input"></div>';

  var q = function (sel) { return el.querySelector(sel); };
  var nameEl = q(".name"), invertEl = q(".invert");
  var panEl = q(".pan"), panVal = q(".panval"), soloEl = q(".solo");
  var pan = data.pan || 0;
  var missing = function (v) { return v === undefined || v === null; };

  // which controls this device offers (and which this particular channel has)
  q(".panrow").hidden = !FEATURES.pan || stereo;          // a stereo pair is fixed hard left / right
  q(".stereorow").hidden = !stereo;
  if (stereo) invertEl.title = "Polarity of both channels";
  soloEl.hidden = !FEATURES.solo;
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

  // pan (single channels only)
  function renderPan() {
    var p = Math.round(pan * 100);
    panEl.value = p;
    panVal.textContent = p === 0 ? "0" : (p < 0 ? "L" + (-p) : "R" + p);
  }
  if (FEATURES.pan) {
    panEl.disabled = !FEATURES.pan.writable;
    panEl.addEventListener("input", function () {
      pan = parseInt(panEl.value, 10) / 100;
      renderPan();
      sendThrottled(id, "pan", pan);
    });
    panEl.addEventListener("dblclick", function () { pan = 0; renderPan(); send(id, "pan", 0); });
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
  var fader = makeFader(q(".track"), q(".handle"), q(".fval"), function (v) { sendThrottled(id, "fader", v); });
  soloEl.addEventListener("click", function () { send(id, "solo", el.classList.toggle("soloed")); });
  q(".mute").addEventListener("click", function () { send(id, "mute", el.classList.toggle("muted")); });
  q(".unlink").addEventListener("click", function () { unlinkStrip(id); });

  // pin / minimize / drag
  q(".pin").addEventListener("click", function () { setPinned(el, !isPinned(el)); saveLayout(); });
  q(".eye").addEventListener("click", function () { setMinimized(el, !isMin(el)); saveLayout(); });
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
    else if (control === "pan") { if (!panDragging) { pan = value; renderPan(); } }
    else if (control === "name") {
      if (stripId && stripId !== id) return;          // the right channel's own name isn't shown on a stereo strip
      if (document.activeElement !== nameEl) { nameEl.value = value; lastName = value; q(".vname").textContent = vertical(value); }
    }
  };

  setPinned(el, pinned);
  setMinimized(el, !!minimized);
  renderPan();
  fader.set(data.fader);
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
var destBus = document.getElementById("destBus"), destTo = document.getElementById("destTo");
var destMsg = document.getElementById("destMsg"), lastDest = null, destToken = 0;

var TABS = ["general", "inout", "theme", "about"], currentTab = "general";
function showTab(name) {
  currentTab = name;
  TABS.forEach(function (t) {
    var on = t === name, tab = document.getElementById("tab-" + t);
    tab.classList.toggle("active", on);
    tab.setAttribute("aria-selected", on ? "true" : "false");
    tab.tabIndex = on ? 0 : -1;
    document.getElementById("pane-" + t).classList.toggle("off", !on);
  });
  if (name === "inout") { fillDestBuses(); }   // read the current values each time the tab opens
  if (name === "about") loadAbout();
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
  jackRefresh.hidden = true;
  showJackMessage("Checking QjackCtl...", false);
  fetch("/api/qjackctl/status", { cache: "no-store" }).then(function (r) {
    if (!r.ok) throw new Error("Status unavailable");
    return r.json();
  }).then(function (status) {
    jackButtons.hidden = !status.running;
    jackRefresh.hidden = !!status.running;
    showJackMessage(status.running ? JACK_HINT : "QjackCtl not running. Launch it and check again.", !status.running);
  }).catch(function () {
    jackButtons.hidden = true;
    jackRefresh.hidden = false;
    showJackMessage("Unable to check QjackCtl status. Try again.", true);
  });
}
jackRefresh.addEventListener("click", checkJackStatus);
checkJackStatus();
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

function loadAbout() {
  fetch("/api/about").then(function (r) { return r.json(); }).then(function (a) {
    document.getElementById("aboutName").textContent = a.name;
    document.getElementById("aboutVersion").textContent = a.version ? "Version " + a.version : "";
    document.getElementById("aboutMode").textContent = a.mode || "-";
    document.getElementById("aboutDevice").textContent = a.device || "-";
    document.getElementById("aboutAddress").textContent = a.address || "-";
  });
}

function openSettings() {
  overlay.hidden = false;
  gear.classList.add("open");
  showTab(currentTab);                            // reopens on the tab you used last
  dialog.focus();
}
function closeSettings() {
  overlay.hidden = true;
  gear.classList.remove("open");
  gear.focus();
}
gear.addEventListener("click", openSettings);
document.getElementById("dlgClose").addEventListener("click", closeSettings);
overlay.addEventListener("mousedown", function (e) { if (e.target === overlay) closeSettings(); });   // click outside the box
document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !overlay.hidden) closeSettings(); });

// where a bus is sent: pick a bus, pick its destination
function fillDestBuses() {
  var buses = OUTPUTS.filter(function (o) { return o.mix !== null && o.destination; });
  document.getElementById("destFields").hidden = !buses.length;
  document.getElementById("destNone").hidden = !!buses.length;
  if (!buses.length) return;
  // open on the bus you're working with: the active output if it's a bus, otherwise the bus the strips show
  var keep = (buses.filter(function (o) { return o.id === currentOut; })[0] ||
              buses.filter(function (o) { return o.mix === currentMix; })[0] || buses[0]).id;
  destBus.innerHTML = "";
  buses.forEach(function (o) {
    var opt = document.createElement("option");
    opt.value = o.id; opt.textContent = o.name;
    destBus.appendChild(opt);
  });
  destBus.value = keep;
  loadDestination();
}
function loadDestination() {
  var id = destBus.value, token = ++destToken;
  destMsg.textContent = ""; destMsg.classList.remove("err");
  if (!id) return;
  fetch("/api/destination?out=" + encodeURIComponent(id)).then(function (r) { return r.json(); }).then(function (d) {
    if (token !== destToken) return;
    destTo.innerHTML = "";
    if (d.error) { destMsg.textContent = d.error; destMsg.classList.add("err"); return; }
    d.options.forEach(function (o) {
      var opt = document.createElement("option"), out = o.output && OUTPUTS.filter(function (x) { return x.id === o.output; })[0];
      opt.value = o.value;
      if (out) opt.dataset.output = out.id;                   // a destination that is really an output shows that output's name
      opt.textContent = out ? out.name : o.name;
      destTo.appendChild(opt);
    });
    destTo.value = d.value;
    lastDest = d.value;
  });
}
destBus.addEventListener("change", loadDestination);
destTo.addEventListener("change", function () {
  var id = destBus.value, value = parseInt(destTo.value, 10);
  destMsg.textContent = ""; destMsg.classList.remove("err");
  post("/api/destination", { out: id, value: value }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) { destTo.value = lastDest; destMsg.textContent = d.error; destMsg.classList.add("err"); }
    else lastDest = value;
  });
});
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
    throttled("out|" + out, v, function (x) { post("/api/output", { out: out, control: "fader", value: x }); });
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
  Array.prototype.forEach.call(destBus.options, function (opt) { if (opt.value === id) opt.textContent = name; });
  Array.prototype.forEach.call(destTo.options, function (opt) { if (opt.dataset.output === id) opt.textContent = name; });
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
  return fetch("/api/output?out=" + encodeURIComponent(currentOut)).then(function (r) { return r.json(); }).then(function (o) {
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
    var shows = !busActive && o.mix !== null && o.mix === currentMix;
    b.classList.toggle("shows", shows);
    b.title = shows ? o.name + " (the channel strips are showing this bus)" : o.name;
  });
}
function selectOutput(o) {
  currentOut = o.id;
  var busChanged = o.mix !== null && o.mix !== currentMix;     // Main/Phones leave the channel strips alone
  if (o.mix !== null) currentMix = o.mix;
  markOutputs();
  post("/api/settings", { output: currentOut, mix: currentMix });
  if (busChanged) loadMix();
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
    group.className = "outgroup";
    group.innerHTML = '<div class="grouptitle">' + g[0] + '</div><div class="groupgrid"></div>';
    members.forEach(function (o) {
      var btn = document.createElement("button");
      btn.className = "outbtn" + (o.mix !== null ? " bus" : "");
      btn.dataset.id = o.id;
      btn.innerHTML = '<span class="olabel"></span>';
      btn.firstChild.textContent = o.name;
      btn.title = o.name;
      btn.addEventListener("click", function () { selectOutput(o); });
      group.querySelector(".groupgrid").appendChild(btn);
    });
    box.appendChild(group);
  });
  box.hidden = OUTPUTS.length < 2;
}

// ---- resizable right bar ----
// Drag the handle on its left edge. The master fader, bus box and cog keep their size; extra width is empty
// space, and below the width two columns need, the Outputs/Buses buttons fall back to a single column.
var side = document.getElementById("side");
var splitter = document.getElementById("splitter");

function sideLimits() {
  var wasNarrow = side.classList.contains("narrow"), wasWidth = side.style.width;
  side.classList.remove("narrow");
  side.style.width = "";
  var two = side.getBoundingClientRect().width;               // what the content needs with two columns
  var btn = document.querySelector(".outbtn"), grid = document.querySelector(".groupgrid");
  var hasButtons = !!btn && !document.getElementById("outbox").hidden;
  var one = hasButtons ? two - btn.offsetWidth - (parseFloat(getComputedStyle(grid).columnGap) || 8) : two;
  if (wasWidth) side.style.width = wasWidth;
  side.classList.toggle("narrow", wasNarrow);
  return { two: two, min: Math.ceil(one), max: Math.max(two, Math.min(window.innerWidth * 0.6, 800)), buttons: hasButtons };
}
function setSideWidth(w, lim) {
  w = Math.round(Math.max(lim.min, Math.min(lim.max, w)));
  side.style.width = w + "px";
  side.classList.toggle("narrow", lim.buttons && w < lim.two - 0.5);
  return w;
}
function resetSideWidth() {
  side.style.width = "";
  side.classList.remove("narrow");
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
});

// ---- render the strips for the selected bus ----
function renderStrips(state, layout) {
  row.innerHTML = "";
  var placed = {};
  function make(id, pinned, minimized) {
    var d = state[id];
    return buildStrip(id, d, pinned, minimized, d.partner ? state[d.partner] : null);
  }
  layout.forEach(function (entry) {
    var id = entry.id, d = state[id];
    if (d && d.partner_of) { id = d.partner_of; d = state[id]; }     // a stereo pair sits where its first channel is listed
    if (!d || placed[id]) return;                                     // not visible right now, or already drawn
    placed[id] = true;
    row.appendChild(make(id, entry.pinned !== false, !!entry.minimized));
  });
  Object.keys(state).forEach(function (id) {                          // channels not in the saved layout yet
    if (placed[id] || state[id].partner_of) return;
    row.appendChild(make(id, true, false));
  });
  updateMinCount();
}
var loadToken = 0;
function loadMix() {
  var token = ++loadToken;                 // ignore out-of-order replies when clicking quickly
  return Promise.all([
    fetch("/api/state?mix=" + currentMix).then(function (r) { return r.json(); }),
    fetch("/api/layout?mix=" + currentMix).then(function (r) { return r.json(); })
  ]).then(function (res) {
    if (token !== loadToken) return;
    if (res[0].error) { row.textContent = "Could not read the mixer: " + res[0].error; return; }
    renderStrips(res[0], res[1]);
  });
}

// ---- live sync: changes made on other pages arrive here ----
function stripEl(id) {                          // a stereo strip answers to both of its channels
  return row.querySelector('.strip[data-id="' + id + '"], .strip[data-partner="' + id + '"]');
}

function applyLayout() {                         // order / pinned / minimized changed on another page
  if (row.querySelector(".dragging")) return;    // don't yank a strip out of the user's hand
  fetch("/api/layout?mix=" + currentMix).then(function (r) { return r.json(); }).then(function (layout) {
    var current = Array.prototype.slice.call(row.children), byId = {}, used = [], ordered = [];
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
  });
}

function onSyncEvent(ev) {
  if (ev.origin === CLIENT_ID) return;           // our own change coming back
  var el;
  if (ev.type === "strip") {
    var shared = ev.control === "gain" || ev.control === "invert";    // belong to the channel, not to one bus
    if (!shared && ev.mix !== currentMix) return;
    el = stripEl(ev.strip);
    if (el) el._apply(ev.control, ev.value, ev.strip);
  } else if (ev.type === "name") {
    if (ev.strip.indexOf("out:") === 0) { applyOutputName(ev.strip.slice(4), ev.value); return; }
    el = stripEl(ev.strip);
    if (el) el._apply("name", ev.value, ev.strip);
  } else if (ev.type === "output") {
    if (ev.out !== currentOut) return;
    if (ev.control === "fader") masterFader.set(ev.value); else loadMaster();   // Main/Phones mute can move the level
  } else if (ev.type === "destination") {
    if (!overlay.hidden && currentTab === "inout" && destBus.value === ev.out) loadDestination();
  } else if (ev.type === "layout") {
    if (ev.mix === currentMix) applyLayout();     // another bus's arrangement doesn't concern this page
  } else if (ev.type === "stereo") {
    if (!row.querySelector(".dragging")) loadMix();   // pairs changed: redraw the strips
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
  fetch("/api/describe").then(function (r) { return r.json(); }),
  fetch("/api/settings").then(function (r) { return r.json(); })
]).then(function (res) {
  var info = res[0], settings = res[1];
  FEATURES = info.features || {};
  MIXES = info.mixes || [];
  OUTPUTS = (info.outputs || []).map(function (o) {
    return { id: o.id, name: o.name, baseName: o.base_name || o.name, mix: (o.mix === null || o.mix === undefined) ? null : o.mix, controllable: o.controllable,
             destination: !!o.destination };
  });
  document.title = info.device || "Mixer";
  accentOverrides = settings.accent_overrides && typeof settings.accent_overrides === "object" ? settings.accent_overrides : {};
  applyTheme(settings.theme || "dark");
  hideBox.checked = !!settings.hide_minimized;
  skipLoadingScreenBox.checked = !!settings.skip_loading_screen;
  row.classList.toggle("hide-min", hideBox.checked);

  var sel = OUTPUTS.filter(function (o) { return o.id === settings.output; })[0] || OUTPUTS[0];
  currentOut = sel ? sel.id : "";
  if (sel && sel.mix !== null) currentMix = sel.mix;
  else if (settings.mix && settings.mix < MIXES.length) currentMix = settings.mix;
  else currentMix = MIXES.length ? MIXES[0].id : 0;

  buildOutputs();
  markOutputs();
  loadMaster();            // shows the master box right away; the saved width is measured with it in place
  if (settings.side_width > 0) setSideWidth(settings.side_width, sideLimits());
  return loadMix();
}).then(startSync);

// A browser tab for web users; the OS default browser for the desktop client.
document.getElementById("aboutGithub").addEventListener("click", function (event) {
  if (!window.pywebview) return;
  event.preventDefault();
  fetch("/api/open-github", { method: "POST" }).catch(function (error) {
    console.error("Could not open GitHub:", error);
  });
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
