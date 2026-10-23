/* FFADO DICE EAP router-destination peaks displayed beside input strips.
 * These are router destination readings, NOT post-fader or calibrated dBFS.
 * One lane per real input. An arbitrary stereo pair keeps its Left/Right order.
 * All controls here are read-only; tapping a meter clears browser-only holds.
 */
(function (root) {
  "use strict";
  const HOLD_MS = 1600;
  const CLIP_HOLD_MS = 4000;
  const POLL_MS = 100; // HTTP fallback only; normal transport is server push
  const FALLBACK_MS = 1000;
  const RECONNECT_MS = 1000;
  const MAX_RECONNECT_MS = 30000;

  function validSample(item) {
    return item && typeof item.destination === 'string' &&
      Number.isFinite(item.level) && item.level >= 0 && item.level <= 1 &&
      (item.db === null || Number.isFinite(item.db));
  }
  // Mixer /api/state strip IDs are zero-padded (ch/00, ch/01, ...), but
  // /api/peaks.channels uses decimal JSON keys ('0', '1', ...). Always map
  // numeric channel indices, never literal padded strings or display names.
  function channelKey(stripId) {
    const match = /^ch\/(\d+)$/.exec(stripId || '');
    if (!match) return null;
    const index = Number(match[1]);
    return Number.isSafeInteger(index) ? String(index) : null;
  }
  function sampleText(item) {
    return `${item.destination}: ${item.db === null ? '−∞' : item.db.toFixed(1)} dB`;
  }

  class PeakDisplay {
    constructor(row, guid, fetcher) {
      this.row = row;
      this.guid = guid;
      this.fetcher = fetcher || (url => fetch(url, {cache: 'no-store',
        headers: this.guid ? {'X-FFADO-Device': this.guid} : {}}));
      this.states = new Map();
      // Avoid repeated child-node searches while metering dozens of strips.
      this.meterNodes = new WeakMap();
      this.boundMeters = new WeakSet();
      this.timer = null;
      this.stream = null;
      this.streamWatchdog = null;
      this.reconnectTimer = null;
      this.reconnectDelay = RECONNECT_MS;
      this.stopped = true;
      this.generation = 0;
      this.onVisibility = () => {
        if (document.hidden) {
          ++this.generation;
          this.closeStream();
          clearTimeout(this.timer);
          this.timer = null;
          this.clearReconnect();
          this.states.clear();
          this.hideAll();
        } else if (!this.stopped) {
          this.reconnectDelay = RECONNECT_MS;
          this.beginTransport();
        }
      };
    }
    hideAll() {
      this.row.querySelectorAll('.peak-meter').forEach(meter => { meter.hidden = true; });
    }
    start() {
      if (!this.stopped) return;
      this.stopped = false;
      this.reconnectDelay = RECONNECT_MS;
      ++this.generation;
      document.addEventListener('visibilitychange', this.onVisibility);
      this.beginTransport();
    }
    stop() {
      this.stopped = true;
      ++this.generation;  // discard requests started before stop/restart
      clearTimeout(this.timer);
      this.timer = null;
      this.clearReconnect();
      this.closeStream();
      document.removeEventListener('visibilitychange', this.onVisibility);
      this.states.clear();
      this.hideAll();
    }
    schedule(delay) {
      clearTimeout(this.timer);
      if (!this.stopped && !document.hidden) this.timer = setTimeout(() => this.poll(), delay);
    }
    clearReconnect() {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    scheduleReconnect() {
      if (this.stopped || document.hidden || this.reconnectTimer !== null ||
          typeof root.EventSource !== 'function') return;
      const generation = this.generation;
      const delay = this.reconnectDelay;
      this.reconnectDelay = Math.min(delay * 2, MAX_RECONNECT_MS);
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        if (!this.stopped && !document.hidden && generation === this.generation) this.beginTransport();
      }, delay);
    }
    closeStream() {
      clearTimeout(this.streamWatchdog);
      this.streamWatchdog = null;
      if (this.stream) this.stream.close();
      this.stream = null;
    }
    beginTransport() {
      if (document.hidden || this.stopped) return;
      clearTimeout(this.timer);
      this.timer = null;
      this.clearReconnect();
      this.closeStream();
      // A transport change also invalidates any in-flight fallback request.
      const generation = ++this.generation;
      if (typeof root.EventSource !== 'function') {
        this.poll();
        return;
      }
      let stream;
      try {
        stream = new root.EventSource('/api/peak-stream');
      } catch (error) {
        this.schedule(0);
        this.scheduleReconnect();
        return;
      }
      this.stream = stream;
      const fallback = () => {
        if (this.stopped || generation !== this.generation || this.stream !== stream) return;
        this.closeStream();
        // An older deployment or a lost SSE connection still works through
        // the existing JSON endpoint. Never run two hardware polling loops.
        this.schedule(0);
        this.scheduleReconnect();
      };
      const watchdog = () => {
        clearTimeout(this.streamWatchdog);
        this.streamWatchdog = setTimeout(fallback, 3000);
      };
      stream.onmessage = event => {
        if (this.stopped || generation !== this.generation || this.stream !== stream) return;
        watchdog();
        try {
          const data = JSON.parse(event.data);
          if (data.guid && this.guid && data.guid !== this.guid) {
            this.states.clear(); this.hideAll(); this.stop(); return;
          }
          this.reconnectDelay = RECONNECT_MS;
          if (!data.available || !data.channels) {
            this.states.clear(); this.hideAll();
            // No real meter on this device: release the sampler. A transient
            // FFADO/D-Bus exception carries `error` and may recover.
            if (!data.error) this.stop();
            return;
          }
          this.render(data, performance.now());
          document.dispatchEvent(new CustomEvent('ffado-peaks', {detail:data}));
        } catch (error) {
          fallback();
        }
      };
      stream.onerror = fallback;
      watchdog();
    }
    async poll() {
      if (this.stopped || this.stream) return;
      if (document.hidden) return;
      const generation = this.generation;
      try {
        const response = await this.fetcher('/api/peaks');
        if (this.stopped || generation !== this.generation || this.stream || document.hidden) return;
        if (response.status === 401 || response.status === 403) {
          this.stop();
          return;
        }
        if (!response.ok) throw Error('peak request failed');
        const data = await response.json();
        if (this.stopped || generation !== this.generation || this.stream || document.hidden) return;
        if (data.guid && this.guid && data.guid !== this.guid) {
          // Never expose peaks from a different FireWire device.
          this.stop(); return;
        }
        if (!data.available || !data.channels) {
          this.stop(); // Unsupported FFADO interface: no fabricated meters.
          return;
        }
        this.render(data, performance.now());
        document.dispatchEvent(new CustomEvent('ffado-peaks', {detail:data}));
        this.schedule(POLL_MS);
      } catch (error) {
        if (this.stopped || generation !== this.generation || this.stream || document.hidden) return;
        this.states.clear(); this.hideAll(); this.schedule(FALLBACK_MS);
      }
    }
    cachedLane(meter, side) {
      let nodes = this.meterNodes.get(meter);
      if (!nodes) { nodes = {}; this.meterNodes.set(meter, nodes); }
      if (!nodes[side]) {
        const lane = meter.querySelector(`.peak-lane[data-side="${side}"]`);
        if (!lane) return null;
        nodes[side] = {lane, bar: lane.querySelector('.peak-bar'),
                       hold: lane.querySelector('.peak-hold')};
      }
      return nodes[side];
    }
    render(data, now) {
      const active = new Set();
      const channels = data.channels || {};
      this.row.querySelectorAll('.strip').forEach(el => {
        const meter = el.querySelector('.peak-meter');
        if (!meter) return;
        const left = channelKey(el.dataset.id);
        const right = el.dataset.partner ? channelKey(el.dataset.partner) : null;
        const lanes = [{side: 'left', channel: left}];
        if (right !== null) lanes.push({side: 'right', channel: right});
        const details = [];
        let any = false;
        lanes.forEach(({side, channel}) => {
          const cached = this.cachedLane(meter, side);
          if (!cached) return;
          const {lane} = cached;
          const item = channel === null ? null : channels[channel];
          if (!validSample(item)) { lane.hidden = true; return; }
          any = true;
          lane.hidden = false;
          const key = `${el.dataset.id}|${side}|${channel}|${item.destination}`;
          active.add(key);
          let state = this.states.get(key);
          if (!state) {
            state = {held: item.level, holdUntil: now + HOLD_MS, clipUntil: 0};
            this.states.set(key, state);
          }
          if (item.level >= state.held || now >= state.holdUntil) {
            state.held = item.level;
            state.holdUntil = now + HOLD_MS;
          }
          if (item.near_full_scale) state.clipUntil = now + CLIP_HOLD_MS;
          // Reveal only the signal height from a full-height gradient, so the
          // yellow/red bands stay at the physical top of the meter track.
          cached.bar.style.clipPath =
            `inset(${((1 - item.level) * 100).toFixed(2)}% 0 0 0)`;
          cached.hold.style.bottom = (state.held * 100).toFixed(2) + '%';
          lane.classList.toggle('clipping', now < state.clipUntil);
          const text = `${right !== null ? (side === 'left' ? 'Left · ' : 'Right · ') : ''}${sampleText(item)}`;
          lane.title = text;
          details.push(text);
        });
        meter.hidden = !any;
        if (!any) return;
        meter.classList.toggle('stereo-meter', right !== null);
        meter.title = `${details.join(' / ')}. FFADO router destination (not post-fader or calibrated dBFS). Click to clear holds.`;
        meter.setAttribute('aria-label', `Clear peak holds: ${details.join('; ')}. FFADO router destination readings, not measured post-fader.`);
        // Attach once per DOM meter; the closures created for every 100 ms
        // sample previously cost work even when the user never clicked.
        if (!this.boundMeters.has(meter)) {
          this.boundMeters.add(meter);
          meter.onclick = () => {
          for (const key of this.states.keys()) {
            if (key.startsWith(`${el.dataset.id}|`)) this.states.delete(key);
          }
          for (const side of ['left', 'right']) {
            const cached = this.cachedLane(meter, side);
            if (!cached) continue;
            cached.lane.classList.remove('clipping');
            cached.hold.style.bottom = '0%';
          }
          };
        }
      });
      for (const key of this.states.keys()) if (!active.has(key)) this.states.delete(key);
    }
  }
  root.FFADOPeakDisplay = PeakDisplay;
  if (typeof module !== 'undefined' && module.exports) module.exports = PeakDisplay;
})(typeof window !== 'undefined' ? window : globalThis);
