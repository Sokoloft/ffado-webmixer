/* Live FFADO DICE EAP router-destination peaks. No invented meters for other
 * families. Peak/near-clip holds are browser-only and never write to FFADO.
 * Decoder lives in peak_metering.py; this module handles display and polling.
 */
(function (root) {
  "use strict";
  const HOLD_MS = 1600;
  const CLIP_HOLD_MS = 4000;
  const POLL_MS = 150;
  const FALLBACK_MS = 1000;
  const FLOOR_DB = -60;

  class PeakDisplay {
    constructor(row, guid, fetcher) {
      this.row = row;
      this.guid = guid;
      this.fetcher = fetcher || (url => fetch(url, {cache: 'no-store',
        headers: this.guid ? {'X-FFADO-Device': this.guid} : {}}));
      this.states = new Map();
      this.timer = null;
      this.stopped = true;
      this.hadMeters = false;
      this.onVisibility = () => {
        if (document.hidden) {
          this.states.clear();
          this.hideAll();
        } else if (!this.stopped) {
          clearTimeout(this.timer);
          this.timer = setTimeout(() => this.poll(), 0);
        }
      };
    }
    hideAll() {
      this.row.querySelectorAll('.peak-meter').forEach(meter => { meter.hidden = true; });
    }
    start() {
      if (!this.stopped) return;
      this.stopped = false;
      document.addEventListener('visibilitychange', this.onVisibility);
      this.poll();
    }
    stop() {
      this.stopped = true;
      clearTimeout(this.timer);
      document.removeEventListener('visibilitychange', this.onVisibility);
      this.states.clear();
      this.hideAll();
    }
    schedule(delay) {
      if (!this.stopped) this.timer = setTimeout(() => this.poll(), delay);
    }
    async poll() {
      if (this.stopped) return;
      if (document.hidden) { this.schedule(FALLBACK_MS); return; }
      try {
        const response = await this.fetcher('/api/peaks');
        if (!response.ok) throw Error('peak request failed');
        const data = await response.json();
        if (this.stopped) return;
        if (data.guid && this.guid && data.guid !== this.guid) {
          // Per-browser selected device changed: never display another unit.
          this.states.clear(); this.hideAll(); this.schedule(FALLBACK_MS); return;
        }
        if (!data.available || !data.channels) {
          this.states.clear(); this.hideAll();
          // Probe unsupported hardware only once per page; a reload retries.
          this.stop(); return;
        }
        this.render(data, performance.now());
        document.dispatchEvent(new CustomEvent('ffado-peaks', {detail:data}));
        this.schedule(POLL_MS);
      } catch (error) {
        this.states.clear(); this.hideAll(); this.schedule(FALLBACK_MS);
      }
    }
    render(data, now) {
      const active = new Set();
      this.row.querySelectorAll('.strip').forEach(el => {
        const meter = el.querySelector('.peak-meter');
        if (!meter) return;
        const col = (el.dataset.id || '').split('/')[1];
        const partner = (el.dataset.partner || '').split('/')[1];
        const inputs = [data.channels[col]];
        if (partner !== undefined) inputs.push(data.channels[partner]);
        const samples = inputs.filter(item => item && Number.isFinite(item.level) && item.level >= 0 && item.level <= 1);
        if (!samples.length) { meter.hidden = true; return; }
        const sample = samples.reduce((a, b) => a.level >= b.level ? a : b);
        const near = samples.some(item => item.near_full_scale);
        const key = el.dataset.id + (el.dataset.partner ? '+' + el.dataset.partner : '');
        active.add(key);
        let state = this.states.get(key);
        if (!state) {
          state = {held: sample.level, holdUntil: 0, clipUntil: 0};
          this.states.set(key, state);
        }
        if (sample.level >= state.held || now >= state.holdUntil) {
          state.held = sample.level;
          state.holdUntil = now + HOLD_MS;
        }
        if (near) state.clipUntil = now + CLIP_HOLD_MS;
        meter.hidden = false;
        meter.querySelector('.peak-bar').style.height = (sample.level * 100).toFixed(2) + '%';
        meter.querySelector('.peak-hold').style.bottom = (state.held * 100).toFixed(2) + '%';
        meter.classList.toggle('clipping', now < state.clipUntil);
        const db = sample.db === null ? '−∞' : `${sample.db.toFixed(1)}`;
        const names = samples.map(s => s.destination).join(' / ');
        meter.title = `${names}: ${db} dB (relative to FFADO full scale; not calibrated dBFS). ` +
                      'Meter is at the router destination before mixer gain. Click to clear peak/clip hold.';
        meter.onclick = () => {
          // Clear hold; a still-overloaded channel can immediately relatch.
          state.holdUntil = 0; state.held = 0; state.clipUntil = 0;
          meter.classList.remove('clipping');
          meter.querySelector('.peak-hold').style.bottom = '0%';
        };
      });
      for (const key of this.states.keys()) if (!active.has(key)) this.states.delete(key);
    }
  }
  root.FFADOPeakDisplay = PeakDisplay;
  // Pure class export for offline validation; no Node dependency at runtime.
  if (typeof module !== 'undefined' && module.exports) module.exports = PeakDisplay;
})(typeof window !== 'undefined' ? window : globalThis);
