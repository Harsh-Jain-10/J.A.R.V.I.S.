/**
 * J.A.R.V.I.S. v2.0 — app.js
 * ═══════════════════════════════════════════════════════════════
 * Modules:
 *   1. StateMachine     — drives IDLE / LISTENING / THINKING / SPEAKING
 *   2. CanvasRenderer   — requestAnimationFrame render loop per state
 *   3. AudioEngine      — Web Audio API mic input (for LISTENING state)
 *   4. WebSocketBridge  — WS client + auto-reconnect + message router
 *   5. CardFactory      — WEATHER / REMINDERS / SCREENSHOT card builders
 *   6. UIController     — DOM wiring, clock, transcript, REPL, settings
 *   7. window.jarvisUI  — Public IPC bridge API
 * ═══════════════════════════════════════════════════════════════
 */

'use strict';

/* ════════════════════════════════════════════════════════════
   § 1. CONSTANTS & PALETTE
   ════════════════════════════════════════════════════════════ */
const STATES = Object.freeze({
  IDLE:      'IDLE',
  LISTENING: 'LISTENING',
  THINKING:  'THINKING',
  SPEAKING:  'SPEAKING',
});

const CLR = {
  cyan:        '#00f3ff',
  cyanA55:     'rgba(0,243,255,0.55)',
  cyanA30:     'rgba(0,243,255,0.30)',
  cyanA12:     'rgba(0,243,255,0.12)',
  cyanA06:     'rgba(0,243,255,0.06)',
  indigo:      '#6366f1',
  indigoA55:   'rgba(99,102,241,0.55)',
  indigoA30:   'rgba(99,102,241,0.30)',
  indigoA12:   'rgba(99,102,241,0.12)',
  red:         '#ff3e3e',
  redA35:      'rgba(255,62,62,0.35)',
  white80:     'rgba(255,255,255,0.80)',
  white40:     'rgba(255,255,255,0.40)',
  bg:          'rgba(10,16,26,0)',           // transparent — canvas is transparent
};

const TWO_PI  = Math.PI * 2;
const HALF_PI = Math.PI / 2;

/* ════════════════════════════════════════════════════════════
   § 2. STATE MACHINE
   ════════════════════════════════════════════════════════════ */
class StateMachine {
  constructor() {
    this._state     = STATES.IDLE;
    this._listeners = [];
  }

  get state() { return this._state; }

  transition(newState) {
    if (!STATES[newState]) {
      console.warn(`[StateMachine] Unknown state: ${newState}`);
      return;
    }
    if (newState === this._state) return;
    const prev = this._state;
    this._state = newState;
    this._listeners.forEach(fn => fn(newState, prev));
  }

  onChange(fn) {
    this._listeners.push(fn);
  }
}

/* ════════════════════════════════════════════════════════════
   § 3. AUDIO ENGINE
   ════════════════════════════════════════════════════════════ */
class AudioEngine {
  constructor() {
    this._ctx      = null;
    this._analyser = null;
    this._stream   = null;
    this._dataArr  = null;
    this.level     = 0;      // 0-1 normalised RMS
    this.freqBins  = new Float32Array(64).fill(0);
  }

  async start() {
    if (this._ctx) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      this._stream = stream;
      this._ctx    = new (window.AudioContext || window.webkitAudioContext)();
      const src    = this._ctx.createMediaStreamSource(stream);
      this._analyser = this._ctx.createAnalyser();
      this._analyser.fftSize       = 128;
      this._analyser.smoothingTimeConstant = 0.80;
      src.connect(this._analyser);
      this._dataArr = new Uint8Array(this._analyser.frequencyBinCount);
      console.info('[AudioEngine] Microphone active.');
    } catch (e) {
      console.warn('[AudioEngine] Mic not available — using mock data.', e);
    }
  }

  stop() {
    if (this._stream) {
      this._stream.getTracks().forEach(t => t.stop());
      this._stream = null;
    }
    if (this._ctx) { this._ctx.close(); this._ctx = null; }
    this._analyser = null;
    this.level = 0;
  }

  /**
   * Tick: read analyser → update this.level + this.freqBins.
   * Called every animation frame.
   */
  tick(mockActive = false) {
    if (this._analyser && this._dataArr) {
      this._analyser.getByteFrequencyData(this._dataArr);
      let sum = 0;
      const len = this._dataArr.length;
      for (let i = 0; i < len; i++) sum += this._dataArr[i];
      this.level = Math.min(1, (sum / len) / 128);

      // Fill freqBins (normalised 0-1)
      const step = Math.floor(len / this.freqBins.length) || 1;
      for (let i = 0; i < this.freqBins.length; i++) {
        this.freqBins[i] = this._dataArr[i * step] / 255;
      }
    } else {
      // Mock mode: gentle sine waves when no mic
      const t = performance.now() / 1000;
      if (mockActive) {
        this.level = 0.35 + 0.30 * Math.sin(t * 3.1) + 0.15 * Math.sin(t * 7.3);
        for (let i = 0; i < this.freqBins.length; i++) {
          const phase = (i / this.freqBins.length) * TWO_PI;
          this.freqBins[i] = 0.3 + 0.4 * Math.sin(t * 4 + phase)
                                 + 0.2 * Math.sin(t * 8 + phase * 2);
        }
      } else {
        this.level = 0;
        this.freqBins.fill(0);
      }
    }
  }
}

/* ════════════════════════════════════════════════════════════
   § 4. CANVAS RENDERER
   ════════════════════════════════════════════════════════════ */
class CanvasRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {StateMachine}      sm
   * @param {AudioEngine}       audio
   */
  constructor(canvas, sm, audio) {
    this._canvas = canvas;
    this._ctx    = canvas.getContext('2d');
    this._sm     = sm;
    this._audio  = audio;

    // Retina / high-DPI support
    const dpr = window.devicePixelRatio || 1;
    const w   = canvas.width;
    const h   = canvas.height;
    canvas.width  = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width  = w + 'px';
    canvas.style.height = h + 'px';
    this._ctx.scale(dpr, dpr);
    this._CW = w;  // logical size
    this._CH = h;

    // Center & radius
    this._cx = this._CW / 2;
    this._cy = this._CH / 2;
    this._R  = 80;   // main core radius

    // Animation internals
    this._rafId     = null;
    this._startTime = performance.now();
    this._particles = this._createParticles(36);
    this._thinkAngle = 0;

    // Segment angles for THINKING state
    this._segAngles = [0, 0, 0, 0];
  }

  /* ── Particle factory for LISTENING halo ──────────────── */
  _createParticles(n) {
    return Array.from({ length: n }, (_, i) => ({
      angle:  (i / n) * TWO_PI,
      radius: this._R + 18 + Math.random() * 12,
      speed:  0.004 + Math.random() * 0.006,
      size:   1.2 + Math.random() * 1.4,
      phase:  Math.random() * TWO_PI,
    }));
  }

  /* ── Start / stop the RAF loop ────────────────────────── */
  start() {
    if (this._rafId) return;
    const loop = (ts) => {
      this._frame(ts);
      this._rafId = requestAnimationFrame(loop);
    };
    this._rafId = requestAnimationFrame(loop);
  }

  stop() {
    if (this._rafId) { cancelAnimationFrame(this._rafId); this._rafId = null; }
  }

  /* ── Main frame dispatcher ────────────────────────────── */
  _frame(ts) {
    const t   = (ts - this._startTime) / 1000;  // seconds
    const ctx = this._ctx;

    // Clear
    ctx.clearRect(0, 0, this._CW, this._CH);

    // Tick audio (mock if SPEAKING, real if LISTENING)
    const mockMode = (this._sm.state === STATES.SPEAKING);
    this._audio.tick(mockMode);

    switch (this._sm.state) {
      case STATES.IDLE:      this._drawIdle(ctx, t);      break;
      case STATES.LISTENING: this._drawListening(ctx, t); break;
      case STATES.THINKING:  this._drawThinking(ctx, t);  break;
      case STATES.SPEAKING:  this._drawSpeaking(ctx, t);  break;
    }
  }

  /* ──────────────────────────────────────────────────────
     STATE 1: IDLE — Breathing cyan circle
     ────────────────────────────────────────────────────── */
  _drawIdle(ctx, t) {
    const cx = this._cx, cy = this._cy, R = this._R;

    // Breathing: opacity oscillates 0.20 → 0.60 over 3s
    const breath = 0.40 + 0.20 * Math.sin((t / 3) * TWO_PI);

    // Outer diffuse glow
    const grd = ctx.createRadialGradient(cx, cy, R * 0.4, cx, cy, R * 1.3);
    grd.addColorStop(0, `rgba(0,243,255,${(breath * 0.40).toFixed(3)})`);
    grd.addColorStop(1, 'rgba(0,243,255,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, R * 1.3, 0, TWO_PI);
    ctx.fillStyle = grd;
    ctx.fill();

    // Core circle fill
    const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
    core.addColorStop(0, `rgba(0,243,255,${(breath * 0.55).toFixed(3)})`);
    core.addColorStop(0.55, `rgba(0,243,255,${(breath * 0.25).toFixed(3)})`);
    core.addColorStop(1,  'rgba(0,243,255,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, TWO_PI);
    ctx.fillStyle = core;
    ctx.fill();

    // Crisp edge ring
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, TWO_PI);
    ctx.strokeStyle = `rgba(0,243,255,${(breath * 0.70).toFixed(3)})`;
    ctx.lineWidth   = 1.2;
    ctx.shadowColor = CLR.cyan;
    ctx.shadowBlur  = 8;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    // Tiny inner pulsing dot
    const dotR = 6 + 3 * Math.sin(t * 2);
    const dotGrd = ctx.createRadialGradient(cx, cy, 0, cx, cy, dotR);
    dotGrd.addColorStop(0, `rgba(0,243,255,${breath.toFixed(3)})`);
    dotGrd.addColorStop(1,  'rgba(0,243,255,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, dotR, 0, TWO_PI);
    ctx.fillStyle = dotGrd;
    ctx.fill();
  }

  /* ──────────────────────────────────────────────────────
     STATE 2: LISTENING — Orbiting particle halo + reactive inner ring
     ────────────────────────────────────────────────────── */
  _drawListening(ctx, t) {
    const cx = this._cx, cy = this._cy, R = this._R;
    const lv = this._audio.level;

    // --- Inner reactive ring ---
    const reactR = R * (0.78 + 0.28 * lv);
    const ringA  = 0.25 + 0.65 * lv;

    const ringGrd = ctx.createRadialGradient(cx, cy, reactR * 0.5, cx, cy, reactR);
    ringGrd.addColorStop(0, `rgba(0,243,255,${(ringA * 0.50).toFixed(3)})`);
    ringGrd.addColorStop(0.6, `rgba(0,243,255,${(ringA * 0.20).toFixed(3)})`);
    ringGrd.addColorStop(1,  'rgba(0,243,255,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, reactR, 0, TWO_PI);
    ctx.fillStyle = ringGrd;
    ctx.fill();

    ctx.beginPath();
    ctx.arc(cx, cy, reactR, 0, TWO_PI);
    ctx.strokeStyle = `rgba(0,243,255,${(0.55 + 0.35 * lv).toFixed(3)})`;
    ctx.lineWidth   = 1.5;
    ctx.shadowColor = CLR.cyan;
    ctx.shadowBlur  = 12 + 8 * lv;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    // --- Outer static ring ---
    ctx.beginPath();
    ctx.arc(cx, cy, R + 4, 0, TWO_PI);
    ctx.strokeStyle = 'rgba(0,243,255,0.12)';
    ctx.lineWidth   = 1;
    ctx.stroke();

    // --- Orbiting particles ---
    this._particles.forEach(p => {
      p.angle += p.speed * (1 + lv * 1.5);
      const pr  = p.radius + 6 * Math.sin(t * 2 + p.phase);
      const px  = cx + Math.cos(p.angle) * pr;
      const py  = cy + Math.sin(p.angle) * pr;
      const pA  = 0.35 + 0.55 * Math.sin(t * 3 + p.phase);

      ctx.beginPath();
      ctx.arc(px, py, p.size, 0, TWO_PI);
      ctx.fillStyle   = `rgba(0,243,255,${pA.toFixed(3)})`;
      ctx.shadowColor = CLR.cyan;
      ctx.shadowBlur  = 4;
      ctx.fill();
      ctx.shadowBlur  = 0;
    });

    // Small bright core
    const coreA = 0.30 + 0.40 * lv;
    ctx.beginPath();
    ctx.arc(cx, cy, 8, 0, TWO_PI);
    ctx.fillStyle = `rgba(0,243,255,${coreA.toFixed(3)})`;
    ctx.fill();
  }

  /* ──────────────────────────────────────────────────────
     STATE 3: THINKING — 4 arc segments spinning in opposite directions
     ────────────────────────────────────────────────────── */
  _drawThinking(ctx, t) {
    const cx = this._cx, cy = this._cy, R = this._R;
    const SPEED = 2.8;  // radians / second

    // Spinning outer ring
    ctx.beginPath();
    ctx.arc(cx, cy, R + 10, 0, TWO_PI);
    ctx.strokeStyle = 'rgba(99,102,241,0.15)';
    ctx.lineWidth = 1;
    ctx.stroke();

    // 4 arc segments — pairs rotate in opposite directions
    const segGap   = 0.25;  // radians of gap
    const segLen   = (TWO_PI / 4) - segGap;

    for (let i = 0; i < 4; i++) {
      const dir     = i % 2 === 0 ? 1 : -1;
      const base    = (i / 4) * TWO_PI;
      const rotated = base + dir * t * SPEED;

      const brightness = 0.55 + 0.35 * Math.sin(t * 4 + i * HALF_PI);

      ctx.beginPath();
      ctx.arc(cx, cy, R, rotated, rotated + segLen);
      ctx.strokeStyle = `rgba(99,102,241,${brightness.toFixed(3)})`;
      ctx.lineWidth   = 3;
      ctx.lineCap     = 'round';
      ctx.shadowColor = CLR.indigo;
      ctx.shadowBlur  = 10;
      ctx.stroke();
      ctx.shadowBlur  = 0;
      ctx.lineCap     = 'butt';
    }

    // Inner ring (counter spin)
    const innerA = 0.35 + 0.25 * Math.sin(t * 5);
    ctx.beginPath();
    ctx.arc(cx, cy, R * 0.65, 0, TWO_PI);
    ctx.strokeStyle = `rgba(99,102,241,${innerA.toFixed(3)})`;
    ctx.lineWidth   = 1;
    ctx.stroke();

    // Pulsing indigo core
    const dotR = 10 + 4 * Math.sin(t * 6);
    const dotGrd = ctx.createRadialGradient(cx, cy, 0, cx, cy, dotR);
    dotGrd.addColorStop(0, `rgba(99,102,241,${(0.5 + 0.3 * Math.sin(t * 6)).toFixed(3)})`);
    dotGrd.addColorStop(1, 'rgba(99,102,241,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, dotR, 0, TWO_PI);
    ctx.fillStyle = dotGrd;
    ctx.fill();
  }

  /* ──────────────────────────────────────────────────────
     STATE 4: SPEAKING — Closed-loop radial waveform
     ────────────────────────────────────────────────────── */
  _drawSpeaking(ctx, t) {
    const cx = this._cx, cy = this._cy, R = this._R;
    const bins   = this._audio.freqBins;
    const nPts   = bins.length;          // 64 points around the circle

    // --- Radial waveform path ---
    ctx.beginPath();
    for (let i = 0; i <= nPts; i++) {
      const idx   = i % nPts;
      const angle = (idx / nPts) * TWO_PI - HALF_PI;  // start at top
      const amp   = bins[idx] * 28;                    // max ±28px deformation
      const r     = R + amp;
      const px    = cx + Math.cos(angle) * r;
      const py    = cy + Math.sin(angle) * r;
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();

    // Fill with radial gradient
    const fillGrd = ctx.createRadialGradient(cx, cy, R * 0.3, cx, cy, R * 1.4);
    fillGrd.addColorStop(0, 'rgba(0,243,255,0.22)');
    fillGrd.addColorStop(1, 'rgba(0,243,255,0.02)');
    ctx.fillStyle = fillGrd;
    ctx.fill();

    // Stroke the waveform
    const lv = this._audio.level;
    ctx.strokeStyle = `rgba(0,243,255,${(0.65 + 0.30 * lv).toFixed(3)})`;
    ctx.lineWidth   = 2;
    ctx.shadowColor = CLR.cyan;
    ctx.shadowBlur  = 12 + 8 * lv;
    ctx.stroke();
    ctx.shadowBlur  = 0;

    // Inner baseline circle
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, TWO_PI);
    ctx.strokeStyle = 'rgba(0,243,255,0.18)';
    ctx.lineWidth   = 1;
    ctx.stroke();

    // Outer glow ring (expands with level)
    ctx.beginPath();
    ctx.arc(cx, cy, R + 18 + 10 * lv, 0, TWO_PI);
    ctx.strokeStyle = `rgba(0,243,255,${(0.08 + 0.12 * lv).toFixed(3)})`;
    ctx.lineWidth   = 2 + 2 * lv;
    ctx.stroke();

    // Bright core
    const coreGrd = ctx.createRadialGradient(cx, cy, 0, cx, cy, 14 + 6 * lv);
    coreGrd.addColorStop(0, `rgba(0,243,255,${(0.70 * lv + 0.20).toFixed(3)})`);
    coreGrd.addColorStop(1, 'rgba(0,243,255,0)');
    ctx.beginPath();
    ctx.arc(cx, cy, 14 + 6 * lv, 0, TWO_PI);
    ctx.fillStyle = coreGrd;
    ctx.fill();
  }
}

/* ════════════════════════════════════════════════════════════
   § 5. CARD FACTORY
   ════════════════════════════════════════════════════════════ */
const CardFactory = {

  /**
   * Build a WEATHER card element.
   * @param {Object} d  { city, temp, feels, condition, icon, humidity, wind, forecast: [{label,temp}] }
   */
  weather(d) {
    const card = document.createElement('div');
    card.className = 'card card--weather';
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">🌐 Weather — ${d.city || 'Current Location'}</span>
        <span class="card-subtitle">${d.condition || ''}</span>
      </div>
      <div class="card-body">
        <div class="weather-grid">
          <div class="weather-main">
            <span class="weather-icon">${d.icon || '🌤'}</span>
            <div>
              <div class="weather-temp">${d.temp != null ? d.temp + '°C' : '--'}</div>
              <div class="weather-condition">${d.condition || 'Unknown'}</div>
            </div>
          </div>
          <div class="weather-stat">
            <span class="weather-stat-label">Feels</span>
            <span class="weather-stat-value">${d.feels != null ? d.feels + '°' : '--'}</span>
          </div>
          <div class="weather-stat">
            <span class="weather-stat-label">Humidity</span>
            <span class="weather-stat-value">${d.humidity != null ? d.humidity + '%' : '--'}</span>
          </div>
          <div class="weather-stat">
            <span class="weather-stat-label">Wind</span>
            <span class="weather-stat-value">${d.wind != null ? d.wind + ' km/h' : '--'}</span>
          </div>
          <div class="weather-stat">
            <span class="weather-stat-label">Vis</span>
            <span class="weather-stat-value">${d.visibility || '--'}</span>
          </div>
          ${this._weatherGraph(d.forecast)}
        </div>
      </div>`;
    return card;
  },

  _weatherGraph(forecast) {
    if (!forecast || !forecast.length) return '';
    const max   = Math.max(...forecast.map(f => f.temp));
    const bars  = forecast.map(f => {
      const h = Math.max(4, Math.round((f.temp / max) * 24));
      return `<div class="wg-bar" style="height:${h}px">
                <span class="wg-label">${f.label}</span>
              </div>`;
    }).join('');
    return `<div class="weather-graph" style="margin-top:18px">${bars}</div>`;
  },

  /**
   * Build a REMINDERS card element.
   * @param {Object} d  { reminders: [{id, text, time, due}] }
   */
  reminders(d) {
    const card = document.createElement('div');
    card.className = 'card card--reminders';
    const list = (d.reminders || []).map((r, idx) => `
      <div class="reminder-item${r.due ? ' reminder-item--due' : ''}"
           style="animation-delay:${idx * 0.06}s">
        <input type="checkbox" class="reminder-check" id="rc-${r.id || idx}"
               data-id="${r.id || idx}" />
        <label class="reminder-text" for="rc-${r.id || idx}">${r.text || 'Reminder'}</label>
        <span class="reminder-time">${r.time || ''}</span>
      </div>`).join('');
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">⏰ Reminders</span>
        <span class="card-subtitle">${(d.reminders || []).length} upcoming</span>
      </div>
      <div class="card-body">
        <div class="reminder-list">${list || '<div style="color:rgba(255,255,255,0.35);font-size:10px">No upcoming reminders.</div>'}</div>
      </div>`;

    // Dismiss on check
    card.querySelectorAll('.reminder-check').forEach(cb => {
      cb.addEventListener('change', () => {
        if (cb.checked) {
          const row = cb.closest('.reminder-item');
          row.style.opacity = '0.35';
          row.style.textDecoration = 'line-through';
        }
      });
    });
    return card;
  },

  /**
   * Build a SCREENSHOT card element.
   * @param {Object} d  { path, filename, timestamp, url }
   */
  screenshot(d) {
    const card = document.createElement('div');
    card.className = 'card card--screenshot';
    const src = d.url || d.path || '';
    card.innerHTML = `
      <div class="card-header">
        <span class="card-title">📸 Screenshot</span>
        <span class="card-subtitle">${d.timestamp || ''}</span>
      </div>
      <div class="card-body">
        <div class="screenshot-preview">
          ${src
            ? `<img class="screenshot-thumb" src="${src}" alt="Screenshot thumbnail" onerror="this.style.display='none'" />`
            : '<div class="screenshot-thumb" style="background:rgba(0,243,255,0.05);display:flex;align-items:center;justify-content:center;color:rgba(0,243,255,0.25);font-size:20px">📷</div>'
          }
          <div class="screenshot-info">
            <div class="screenshot-filename">${d.filename || 'screenshot.png'}</div>
            <div class="screenshot-meta">Saved to /screenshots/</div>
            ${src ? `<div class="screenshot-meta" style="margin-top:4px">
              <a href="${src}" target="_blank"
                 style="color:rgba(0,243,255,0.50);font-size:9px;text-decoration:none;font-family:var(--font-mono)">
                OPEN ↗
              </a>
            </div>` : ''}
          </div>
        </div>
      </div>`;
    return card;
  },
};

/* ════════════════════════════════════════════════════════════
   § 6. WEBSOCKET BRIDGE
   ════════════════════════════════════════════════════════════ */
class WebSocketBridge {
  /**
   * @param {string}   url        WebSocket server URL
   * @param {Function} onMessage  Callback(parsedObject)
   * @param {Function} onStatus   Callback(statusString)
   */
  constructor(url, onMessage, onStatus) {
    this._url       = url;
    this._onMessage = onMessage;
    this._onStatus  = onStatus;
    this._ws        = null;
    this._retryMs   = 3000;
    this._retryMax  = 30000;
    this._timer     = null;
    this._connected = false;
    this._manualClose = false;
  }

  connect() {
    this._manualClose = false;
    this._tryConnect();
  }

  _tryConnect() {
    if (this._ws) { try { this._ws.close(); } catch(_) {} }

    this._onStatus('WS: CONNECTING');
    try {
      this._ws = new WebSocket(this._url);
    } catch (e) {
      console.warn('[WS] Could not create WebSocket:', e);
      this._scheduleRetry();
      return;
    }

    this._ws.addEventListener('open', () => {
      console.info('[WS] Connected to', this._url);
      this._connected = true;
      this._retryMs   = 3000;
      this._onStatus('WS: CONNECTED');
      clearTimeout(this._timer);
    });

    this._ws.addEventListener('message', ({ data }) => {
      try {
        const msg = JSON.parse(data);
        this._onMessage(msg);
      } catch (e) {
        console.warn('[WS] Non-JSON message:', data);
      }
    });

    this._ws.addEventListener('close', () => {
      this._connected = false;
      if (!this._manualClose) {
        this._onStatus('WS: RECONNECTING');
        this._scheduleRetry();
      } else {
        this._onStatus('WS: DISCONNECTED');
      }
    });

    this._ws.addEventListener('error', () => {
      this._onStatus('WS: ERROR');
    });
  }

  _scheduleRetry() {
    clearTimeout(this._timer);
    this._timer = setTimeout(() => {
      this._retryMs = Math.min(this._retryMs * 1.4, this._retryMax);
      this._tryConnect();
    }, this._retryMs);
  }

  send(obj) {
    if (this._connected && this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(JSON.stringify(obj));
      return true;
    }
    return false;
  }

  setUrl(url) {
    this._url = url;
    this._manualClose = false;
    this._retryMs = 3000;
    this._tryConnect();
  }

  disconnect() {
    this._manualClose = true;
    clearTimeout(this._timer);
    if (this._ws) this._ws.close();
  }
}

/* ════════════════════════════════════════════════════════════
   § 7. UI CONTROLLER
   ════════════════════════════════════════════════════════════ */
class UIController {
  constructor(sm, audio, renderer, wsbridge) {
    this._sm       = sm;
    this._audio    = audio;
    this._renderer = renderer;
    this._ws       = wsbridge;

    // DOM refs
    this._stateLabel  = document.getElementById('state-label');
    this._statusBadge = document.getElementById('status-badge');
    this._statusDot   = document.getElementById('status-dot');
    this._statusText  = document.getElementById('status-text');
    this._clock       = document.getElementById('live-clock');
    this._wsStatus    = document.getElementById('ws-status');
    this._panel       = document.getElementById('info-panel');
    this._panelInner  = document.getElementById('panel-inner');
    this._transcript  = document.getElementById('transcript-box');
    this._replForm    = document.getElementById('repl-form');
    this._replInput   = document.getElementById('repl-input');
    this._settingsBtn = document.getElementById('settings-btn');
    this._settingsModal = document.getElementById('settings-modal');
    this._wsUrlInput  = document.getElementById('ws-url-input');
    this._opacitySlider = document.getElementById('opacity-slider');
    this._settingsSave  = document.getElementById('settings-save');
    this._settingsCancel = document.getElementById('settings-cancel');
    this._panelCloseBtn = document.getElementById('panel-close-btn');

    this._wireEvents();
    this._startClock();

    // React to state transitions
    sm.onChange((state) => this._onStateChange(state));
  }

  /* ── Clock ──────────────────────────────────────────── */
  _startClock() {
    const tick = () => {
      const now = new Date();
      const day = ['SUN','MON','TUE','WED','THU','FRI','SAT'][now.getDay()];
      const mon = ['JAN','FEB','MAR','APR','MAY','JUN',
                   'JUL','AUG','SEP','OCT','NOV','DEC'][now.getMonth()];
      const dd  = String(now.getDate()).padStart(2,'0');
      const hh  = String(now.getHours()).padStart(2,'0');
      const mm  = String(now.getMinutes()).padStart(2,'0');
      const ss  = String(now.getSeconds()).padStart(2,'0');
      this._clock.textContent = `${day} ${dd} ${mon} · ${hh}:${mm}:${ss}`;
    };
    tick();
    setInterval(tick, 1000);
  }

  /* ── State change handler ───────────────────────────── */
  _onStateChange(state) {
    // Update label
    this._stateLabel.textContent = state;

    // Update body class for CSS-driven canvas glow
    document.body.className = `state-${state}`;

    // Kick audio engine on/off
    if (state === STATES.LISTENING) {
      this._audio.start().catch(() => {});
    } else if (state !== STATES.SPEAKING) {
      // Keep mic alive during SPEAKING for real audio (mock fills gap)
    }
  }

  /* ── Info panel ─────────────────────────────────────── */
  openPanel(cardElement) {
    this._panelInner.innerHTML = '';
    this._panelInner.appendChild(cardElement);
    this._panel.classList.add('panel--open');
    this._panel.setAttribute('aria-hidden', 'false');
  }

  closePanel() {
    this._panel.classList.remove('panel--open');
    this._panel.setAttribute('aria-hidden', 'true');
    setTimeout(() => { this._panelInner.innerHTML = ''; }, 450);
  }

  /* ── Transcript ─────────────────────────────────────── */
  addTranscriptLine(speaker, text) {
    const line = document.createElement('div');
    const isJarvis = speaker.toUpperCase() === 'JARVIS';
    line.className = `transcript-line transcript-line--${isJarvis ? 'jarvis' : 'user'}`;
    line.innerHTML = `
      <span class="transcript-tag">${speaker.toUpperCase()}</span>
      <span class="transcript-text">${this._esc(text)}</span>`;
    this._transcript.appendChild(line);
    this._transcript.scrollTop = this._transcript.scrollHeight;

    // Keep max 20 lines
    while (this._transcript.children.length > 20) {
      this._transcript.removeChild(this._transcript.firstChild);
    }
  }

  /* ── WebSocket status bar ───────────────────────────── */
  setWsStatus(text) {
    if (!this._wsStatus) return;
    this._wsStatus.textContent = text;
    const isError = text.includes('ERROR') || text.includes('DISCONNECT');
    this._statusBadge.classList.toggle('badge--error', isError);
    this._statusText.textContent = isError ? 'OFFLINE' : 'ONLINE';
  }

  /* ── DOM wiring ─────────────────────────────────────── */
  _wireEvents() {
    // REPL form submit
    this._replForm.addEventListener('submit', (e) => {
      e.preventDefault();
      const text = this._replInput.value.trim();
      if (!text) return;
      this._replInput.value = '';

      this.addTranscriptLine('You', text);

      // Trigger bridge
      if (typeof window.jarvisUI?.onCommandSubmit === 'function') {
        window.jarvisUI.onCommandSubmit(text);
      }

      // Send via WebSocket
      this._ws.send({ type: 'command', text });
    });

    // Panel close
    this._panelCloseBtn.addEventListener('click', () => this.closePanel());

    // Settings open
    this._settingsBtn.addEventListener('click', () => {
      this._settingsModal.removeAttribute('hidden');
    });

    // Settings cancel
    this._settingsCancel.addEventListener('click', () => {
      this._settingsModal.setAttribute('hidden', '');
    });

    // Settings save
    this._settingsSave.addEventListener('click', () => {
      const newUrl = this._wsUrlInput.value.trim();
      const opacity = this._opacitySlider.value;
      if (newUrl) this._ws.setUrl(newUrl);
      document.body.style.background =
        `rgba(10,16,26,${(opacity / 100).toFixed(2)})`;
      this._settingsModal.setAttribute('hidden', '');
    });

    // Close modal on overlay click
    this._settingsModal.addEventListener('click', (e) => {
      if (e.target === this._settingsModal) {
        this._settingsModal.setAttribute('hidden', '');
      }
    });

    // Close modal on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (!this._settingsModal.hasAttribute('hidden')) {
          this._settingsModal.setAttribute('hidden', '');
        }
      }
    });
  }

  _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
}

/* ════════════════════════════════════════════════════════════
   § 8. MESSAGE ROUTER (WS → UI)
   ════════════════════════════════════════════════════════════ */
function routeMessage(msg, sm, ui) {
  if (!msg || !msg.type) return;

  switch (msg.type) {

    // {"type":"state","value":"LISTENING"}
    case 'state':
      if (msg.value) sm.transition(msg.value.toUpperCase());
      break;

    // {"type":"card","cardType":"WEATHER","data":{...}}
    case 'card': {
      const ctype = (msg.cardType || '').toUpperCase();
      const data  = msg.data || {};
      let cardEl;
      if      (ctype === 'WEATHER')    cardEl = CardFactory.weather(data);
      else if (ctype === 'REMINDERS')  cardEl = CardFactory.reminders(data);
      else if (ctype === 'SCREENSHOT') cardEl = CardFactory.screenshot(data);
      if (cardEl) ui.openPanel(cardEl);
      break;
    }

    // {"type":"transcript","speaker":"JARVIS","text":"Hello, Sir."}
    case 'transcript':
      ui.addTranscriptLine(msg.speaker || 'JARVIS', msg.text || '');
      break;

    // {"type":"close_panel"}
    case 'close_panel':
      ui.closePanel();
      break;

    default:
      console.debug('[Router] Unhandled message type:', msg.type);
  }
}

/* ════════════════════════════════════════════════════════════
   § 9. BOOTSTRAP
   ════════════════════════════════════════════════════════════ */
const sm       = new StateMachine();
const audio    = new AudioEngine();
const canvas   = document.getElementById('visualizer');
const renderer = new CanvasRenderer(canvas, sm, audio);

// Set initial body class
document.body.className = `state-${sm.state}`;

let ui; // declared here so wsbridge callback can reference it

const wsbridge = new WebSocketBridge(
  'ws://localhost:8000',
  (msg) => routeMessage(msg, sm, ui),
  (status) => { if (ui) ui.setWsStatus(status); }
);

ui = new UIController(sm, audio, renderer, wsbridge);

// Start rendering loop
renderer.start();

// Attempt WebSocket connection
wsbridge.connect();

/* ════════════════════════════════════════════════════════════
   § 10. PUBLIC API — window.jarvisUI
   The Python backend (pywebview / Electron IPC) calls these.
   ════════════════════════════════════════════════════════════ */
window.jarvisUI = {

  /**
   * Move the visualizer to a new state.
   * @param {'IDLE'|'LISTENING'|'THINKING'|'SPEAKING'} stateName
   */
  updateState(stateName) {
    sm.transition(stateName);
  },

  /**
   * Inject and slide open an info panel card.
   * @param {'WEATHER'|'REMINDERS'|'SCREENSHOT'} cardType
   * @param {Object} cardData  Card-specific payload
   */
  showCard(cardType, cardData) {
    const ctype = (cardType || '').toUpperCase();
    let cardEl;
    if      (ctype === 'WEATHER')    cardEl = CardFactory.weather(cardData   || {});
    else if (ctype === 'REMINDERS')  cardEl = CardFactory.reminders(cardData  || {});
    else if (ctype === 'SCREENSHOT') cardEl = CardFactory.screenshot(cardData || {});
    else {
      console.warn('[jarvisUI] Unknown card type:', cardType);
      return;
    }
    ui.openPanel(cardEl);
  },

  /**
   * Close the slide-out info panel.
   */
  hidePanel() {
    ui.closePanel();
  },

  /**
   * Add a line to the transcript display.
   * @param {'JARVIS'|'You'} speaker
   * @param {string}         text
   */
  addTranscript(speaker, text) {
    ui.addTranscriptLine(speaker, text);
  },

  /**
   * Override this function to receive text typed in the REPL bar.
   * The Python bridge (pywebview) should replace this at startup.
   * @param {string} text
   */
  onCommandSubmit(text) {
    // Default: echo to transcript
    console.info('[jarvisUI] Command submitted:', text);
    ui.addTranscriptLine('You', text);
    // Send via WebSocket too
    wsbridge.send({ type: 'command', text });
  },

  /**
   * Send any arbitrary JSON object to the Python WS server.
   * @param {Object} obj
   */
  send(obj) {
    return wsbridge.send(obj);
  },
};

/* ════════════════════════════════════════════════════════════
   § 11. DEMO CYCLE (remove in production, useful for preview)
   Comment out the call below to disable the auto-demo.
   ════════════════════════════════════════════════════════════ */
function _runDemoCycle() {
  const sequence = [
    { delay: 1500,  fn: () => sm.transition('LISTENING'),
      log: ['JARVIS', 'Awaiting your command, Sir.'] },
    { delay: 5000,  fn: () => sm.transition('THINKING'),
      log: ['You', 'What\'s the weather in Sonipat?'] },
    { delay: 8000,  fn: () => sm.transition('SPEAKING'),
      log: ['JARVIS', 'It is currently 32°C and partly cloudy in Sonipat, Sir.'] },
    { delay: 12000, fn: () => {
        window.jarvisUI.showCard('WEATHER', {
          city: 'Sonipat', temp: 32, feels: 34, condition: 'Partly Cloudy',
          icon: '⛅', humidity: 62, wind: 18, visibility: '8 km',
          forecast: [
            { label: 'Now', temp: 32 }, { label: '+3h', temp: 35 },
            { label: '+6h', temp: 30 }, { label: '+9h', temp: 27 },
            { label: '+12h', temp: 25 },
          ],
        });
      },
    },
    { delay: 16000, fn: () => {
        window.jarvisUI.hidePanel();
        sm.transition('IDLE');
      },
    },
    { delay: 20000, fn: () => {
        window.jarvisUI.showCard('REMINDERS', {
          reminders: [
            { id: 1, text: 'Team standup meeting',       time: '10:00 AM', due: false },
            { id: 2, text: 'Drink water',                time: '10:30 AM', due: true  },
            { id: 3, text: 'Review pull request #42',    time: '02:00 PM', due: false },
            { id: 4, text: 'Push JARVIS UI to GitHub',   time: '08:00 PM', due: false },
          ],
        });
        sm.transition('SPEAKING');
      },
      log: ['JARVIS', 'You have 4 upcoming reminders, Sir. One is due now.'],
    },
    { delay: 26000, fn: () => {
        window.jarvisUI.hidePanel();
        sm.transition('IDLE');
      },
    },
  ];

  sequence.forEach(({ delay, fn, log }) => {
    setTimeout(() => {
      fn();
      if (log) ui.addTranscriptLine(log[0], log[1]);
    }, delay);
  });
}

// Run demo — comment out the line below to disable
_runDemoCycle();
