/* CubeEntity — vanilla-JS canvas voxel renderer for the cube overlay.
 *
 * Drop-in replacement for the GIF in bin/win/html/index.html. No
 * dependencies — runs in WebView2 / pywebview directly. Same renderer
 * core as cube-entity.jsx from the design project; the React wrapper is
 * gone, and presets are pruned to just the 8 emotions the overlay needs.
 *
 * Usage:
 *   const canvas = document.getElementById('cube-entity');
 *   const entity = new CubeEntity(canvas, { size: 156 });
 *   entity.setEmotion('thinking');   // or any of CUBE_EMOTIONS keys
 *
 * State → emotion mapping is done by the caller (overlay.js). Each
 * emotion is a complete snapshot of ~18 params; setEmotion swaps them
 * all atomically.
 */

(function () {
  "use strict";

  /* ───────────────────────────── Base config (memorized by the user)
   *
   * Core is fixed across all emotions: hue 188 cyan, sat 90, size 0.22,
   * glow 1.0. Pitch is fixed at 0.7 rad (~40°). radiusOffset 0.24 so
   * cubes have breathing room from the core. Emotions only vary cube
   * color + motion language.
   */
  const BASE_CFG = {
    bg: "#05070b",
    pitch: 0.7,
    orbitSpeed: 0.22,
    formation: "ring3",
    cubeSizeMul: 1,
    radiusOffset: 0.24,
    zoom: 0.95,
    cubeHue: 205, cubeSat: 45,
    coreHue: 188, coreSat: 90,
    coreSize: 0.22, coreGlow: 1.0,
    breatheAmp: 0.025, bobAmp: 0.04,
    radialPulse: { amp: 0.07, freq: 0.55, wave: 2.5 },
    flashRate: 1.6,
    attentionTilt: 0,
    shakeAmp: 0, shakeFreq: 22,
  };

  /* ───────────────────────────── Emotions
   *
   * Each entry overlays a subset of BASE_CFG. `radialPulse` is built
   * from radialAmp/Freq/Wave at setEmotion time so the editor-driven
   * JSON format matches the React app's TWEAK_DEFAULTS.
   */
  const EMOTIONS = {
    idle: {
      desc: "Schläft beinahe — ganz langsame Rotation, schwacher Atem, Cubes desaturiert.",
      params: {
        orbitSpeed: 0.04,
        cubeHue: 210, cubeSat: 22,
        bg: "#04060a",
        breatheAmp: 0.025, bobAmp: 0.015,
        radialAmp: 0.015, radialFreq: 0.12, radialWave: 0,
        flashRate: 0, attentionTilt: 0,
        shakeAmp: 0,
      },
    },
    thinking: {
      desc: "Ripple nach außen + Synapsen — verarbeitet aktiv.",
      params: {
        orbitSpeed: 0.22,
        cubeHue: 205, cubeSat: 45,
        bg: "#05070b",
        breatheAmp: 0.025, bobAmp: 0.04,
        radialAmp: 0.07, radialFreq: 0.55, radialWave: 2.5,
        flashRate: 1.6, attentionTilt: 0,
        shakeAmp: 0,
      },
    },
    listening: {
      desc: "Frage erkannt — Cubes lavendel, Attention-Tilt aktiv, synchroner Puls.",
      params: {
        orbitSpeed: 0.10,
        cubeHue: 280, cubeSat: 55,
        bg: "#08040a",
        breatheAmp: 0.02, bobAmp: 0.025,
        radialAmp: 0.08, radialFreq: 0.75, radialWave: 0,
        flashRate: 0.2, attentionTilt: 0.22,
        shakeAmp: 0,
      },
    },
    focused: {
      desc: "Konzentriert — elektroblaue Cubes, schnelle Rotation, kein Atem.",
      params: {
        orbitSpeed: 0.55,
        cubeHue: 215, cubeSat: 70,
        bg: "#020608",
        breatheAmp: 0.005, bobAmp: 0.01,
        radialAmp: 0.02, radialFreq: 1.0, radialWave: 0,
        flashRate: 0.5, attentionTilt: 0,
        shakeAmp: 0,
      },
    },
    curious: {
      desc: "Schaut sich was an — teale Cubes, leichte Tilt, vereinzelte Flashes.",
      params: {
        orbitSpeed: 0.16,
        cubeHue: 180, cubeSat: 55,
        bg: "#080604",
        breatheAmp: 0.025, bobAmp: 0.05,
        radialAmp: 0.05, radialFreq: 0.5, radialWave: 1.8,
        flashRate: 0.8, attentionTilt: 0.15,
        shakeAmp: 0,
      },
    },
    happy: {
      desc: "Fertig & zufrieden — grüne Cubes blühen synchron auf, wie ein Ausatmen.",
      params: {
        orbitSpeed: 0.18,
        cubeHue: 115, cubeSat: 65,
        bg: "#04080a",
        breatheAmp: 0.04, bobAmp: 0.05,
        radialAmp: 0.10, radialFreq: 0.45, radialWave: 0,
        flashRate: 0, attentionTilt: 0,
        shakeAmp: 0,
      },
    },
    surprised: {
      desc: "Etwas Unerwartetes — Cubes springen weit nach außen, magenta-pink, kurzer Shake.",
      params: {
        orbitSpeed: 0.08,
        cubeHue: 332, cubeSat: 75,
        bg: "#05030a",
        breatheAmp: 0.08, bobAmp: 0.08,
        radialAmp: 0.14, radialFreq: 0.5, radialWave: 0,
        flashRate: 1.5, attentionTilt: 0,
        shakeAmp: 0.8, shakeFreq: 22,
      },
    },
    error: {
      desc: "Etwas ist schief — kurzes Zittern, orange-rote Cubes pulsieren hochfrequent.",
      params: {
        orbitSpeed: 0.0,
        cubeHue: 22, cubeSat: 65,
        bg: "#0a0306",
        breatheAmp: 0.0, bobAmp: 0.07,
        radialAmp: 0.10, radialFreq: 1.4, radialWave: 0.6,
        flashRate: 3.2, attentionTilt: 0,
        shakeAmp: 2.0, shakeFreq: 28,
      },
    },
  };

  /* ───────────────────────────── PRNG + formation generator */
  function makeRng(seed) {
    let s = seed | 0 || 1;
    return function () {
      s ^= s << 13; s ^= s >>> 17; s ^= s << 5;
      return ((s >>> 0) % 100000) / 100000;
    };
  }

  function hashStr(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return h >>> 0;
  }

  /* ────────────────────────────── Tween helpers
   *
   * setEmotion no longer snaps the config — it captures the current cfg
   * as `from`, the target emotion's cfg as `to`, and the per-frame loop
   * lerps between them with ease-in-out cubic. Hues take the shortest
   * path around the colour wheel (handles 350 → 10 jump as +20°, not
   * -340°). bg is parsed as either #rrggbb or rgb(r,g,b) and re-emitted
   * as rgb() so a mid-transition cfg can itself be a transition source.
   */
  /* LERP_NUMERIC lists params that morph smoothly between emotions.
   *
   * Subtlety rationale: the eye latches onto continuous CHANGE — a
   * shake that ramps up over a second is far more distracting than a
   * shake that simply appears. So motion-language params (orbitSpeed,
   * shake, flash, bob, breathe, attention) snap instantly. Only colour
   * and the radial-pulse envelope fade — because those are gradients,
   * and a hard cut on a gradient is what would actually look wrong.
   *
   * Net effect: emotion swaps register as a gentle ½sec colour wash
   * instead of a slow-motion transformation. */
  const LERP_NUMERIC = [
    "cubeSat", "coreSat", "coreGlow",
  ];

  function lerp(a, b, t) { return a + (b - a) * t; }

  function lerpHue(a, b, t) {
    let d = b - a;
    if (d > 180) d -= 360;
    if (d < -180) d += 360;
    return (a + d * t + 360) % 360;
  }

  function easeInOutSine(t) {
    return -(Math.cos(Math.PI * t) - 1) / 2;
  }

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
  }

  function parseColor(s) {
    if (!s) return { r: 0, g: 0, b: 0 };
    if (s.charAt(0) === "#") {
      const h = s.slice(1);
      return {
        r: parseInt(h.substr(0, 2), 16),
        g: parseInt(h.substr(2, 2), 16),
        b: parseInt(h.substr(4, 2), 16),
      };
    }
    const m = s.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (m) return { r: +m[1], g: +m[2], b: +m[3] };
    return { r: 0, g: 0, b: 0 };
  }

  function lerpBg(a, b, t) {
    const pa = parseColor(a), pb = parseColor(b);
    return "rgb("
      + Math.round(pa.r + (pb.r - pa.r) * t) + ","
      + Math.round(pa.g + (pb.g - pa.g) * t) + ","
      + Math.round(pa.b + (pb.b - pa.b) * t) + ")";
  }

  function lerpCfg(a, b, t) {
    // Start from the TARGET so non-lerped params (motion, shake, etc.)
    // are already at their new values from the very first transition
    // frame — they just don't visibly animate.
    const out = Object.assign({}, b);
    for (let i = 0; i < LERP_NUMERIC.length; i++) {
      const k = LERP_NUMERIC[i];
      out[k] = lerp(a[k], b[k], t);
    }
    out.cubeHue = lerpHue(a.cubeHue, b.cubeHue, t);
    out.coreHue = lerpHue(a.coreHue, b.coreHue, t);
    out.bg = lerpBg(a.bg, b.bg, t);
    const ra = a.radialPulse || { amp: 0, freq: 0, wave: 0 };
    const rb = b.radialPulse || { amp: 0, freq: 0, wave: 0 };
    out.radialPulse = {
      amp:  lerp(ra.amp,  rb.amp,  t),
      freq: rb.freq,    // freq/wave snap — they change perceived motion speed
      wave: rb.wave,
    };
    return out;
  }

  function buildCfgFromEmotion(name) {
    const emo = EMOTIONS[name];
    if (!emo) return Object.assign({}, BASE_CFG);
    const p = Object.assign({}, BASE_CFG, emo.params);
    p.radialPulse = {
      amp:  p.radialAmp  != null ? p.radialAmp  : 0,
      freq: p.radialFreq != null ? p.radialFreq : 0,
      wave: p.radialWave != null ? p.radialWave : 0,
    };
    delete p.radialAmp; delete p.radialFreq; delete p.radialWave;
    return p;
  }

  function genFormation(kind, seed) {
    const r = makeRng(seed);
    const cubes = [];
    function push(radius, angle, height, size) {
      cubes.push({
        r: radius, a: angle, y: height, s: size,
        bobPhase: r() * Math.PI * 2,
        bobFreq: 0.7 + r() * 0.9,
        seed: r(),
      });
    }
    if (kind === "ring3" || !kind) {
      [
        { n: 5, rad: 0.35, size: 0.42 },
        { n: 10, rad: 0.75, size: 0.30 },
        { n: 18, rad: 1.25, size: 0.24 },
      ].forEach(function (ring, ri) {
        for (let i = 0; i < ring.n; i++) {
          const a = (i / ring.n) * Math.PI * 2 + ri * 0.31;
          const jitR = (r() - 0.5) * 0.08;
          const jitY = (r() - 0.5) * 0.08;
          const jitS = (r() - 0.5) * 0.05;
          push(ring.rad + jitR, a, jitY, ring.size + jitS);
        }
      });
    } else if (kind === "scatter") {
      const n = 80;
      for (let i = 0; i < n; i++) {
        const u = r();
        const rad = 0.25 + (1 - Math.sqrt(1 - u)) * 1.15;
        const a = r() * Math.PI * 2;
        const y = (r() - 0.5) * 0.18;
        const sz = 0.36 - rad * 0.10 + (r() - 0.5) * 0.04;
        push(rad, a, y, Math.max(0.14, sz));
      }
    } else if (kind === "sparse") {
      [
        { n: 4, rad: 0.4, size: 0.36 },
        { n: 8, rad: 0.95, size: 0.28 },
        { n: 12, rad: 1.45, size: 0.22 },
      ].forEach(function (ring, ri) {
        for (let i = 0; i < ring.n; i++) {
          const a = (i / ring.n) * Math.PI * 2 + ri * 0.17;
          const jitR = (r() - 0.5) * 0.06;
          const jitY = (r() - 0.5) * 0.06;
          push(ring.rad + jitR, a, jitY, ring.size);
        }
      });
    }
    return cubes;
  }

  /* ───────────────────────────── Cube vertex / face data */
  const CORNERS = [];
  for (let i = 0; i < 8; i++) {
    CORNERS.push([
      (i & 1) ? 0.5 : -0.5,
      (i & 2) ? 0.5 : -0.5,
      (i & 4) ? 0.5 : -0.5,
    ]);
  }

  // outward-CCW windings + world normals
  const FACES = [
    { idx: [0, 1, 3, 2], n: [0, 0, -1] },
    { idx: [4, 5, 7, 6], n: [0, 0,  1] },
    { idx: [0, 4, 6, 2], n: [-1, 0, 0] },
    { idx: [5, 1, 3, 7], n: [ 1, 0, 0] },
    { idx: [0, 1, 5, 4], n: [0, -1, 0] },
    { idx: [6, 7, 3, 2], n: [0,  1, 0] },
  ];

  const LIGHT = (function () {
    const v = [0.28, 0.92, 0.28];
    const m = Math.hypot(v[0], v[1], v[2]);
    return [v[0] / m, v[1] / m, v[2] / m];
  })();

  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }

  /* ───────────────────────────── CubeEntity class */
  class CubeEntity {
    constructor(canvas, opts) {
      opts = opts || {};
      this.canvas = canvas;
      this.size = opts.size || 200;
      this.speedMul = opts.speedMul == null ? 1 : opts.speedMul;
      this.paused = false;
      this.cfg = Object.assign({}, BASE_CFG);
      this._lastFormation = this.cfg.formation;
      this._cubes = genFormation(this.cfg.formation, hashStr(opts.seed || "cube"));
      this._flashes = [];
      this._yaw = 0;          // accumulated orbit yaw — frame-independent
      this._yawT = null;      // last t (in seconds) we advanced yaw at
      this._setupCanvas();
      this._last = performance.now();
      this._acc = 0;
      this._loop = this._loop.bind(this);
      this._raf = requestAnimationFrame(this._loop);
      if (opts.emotion) this.setEmotion(opts.emotion);
    }

    setEmotion(name, opts) {
      opts = opts || {};
      const emo = EMOTIONS[name];
      if (!emo) return;
      const target = buildCfgFromEmotion(name);
      const duration = opts.duration != null ? opts.duration : (this._defaultDuration != null ? this._defaultDuration : 600);
      // First-time set OR explicit instant: snap, no tween.
      if (opts.instant || duration <= 0 || !this._cfgReady) {
        this.cfg = target;
        this._transition = null;
        this._cfgReady = true;
      } else {
        // Capture *current* cfg (possibly mid-transition) as the tween
        // origin — means rapid emotion swaps interpolate from wherever
        // we are right now, not from the last target.
        const from = Object.assign({}, this.cfg);
        from.radialPulse = Object.assign({}, this.cfg.radialPulse || {});
        this._transition = {
          from: from,
          to: target,
          t0: performance.now(),
          duration: duration,
        };
      }
      this._currentEmotion = name;
      // Formation is discrete (no tween possible). Swap immediately;
      // in practice all 8 emotions use ring3 so this is a no-op.
      if (target.formation && target.formation !== this._lastFormation) {
        this._lastFormation = target.formation;
        this._cubes = genFormation(target.formation, hashStr(name));
      }
    }

    setTransitionDuration(ms) { this._defaultDuration = ms; }

    setSize(size) {
      this.size = size;
      this._setupCanvas();
    }

    setSpeed(mul) { this.speedMul = mul; }
    pause() { this.paused = true; }
    resume() { this.paused = false; }

    destroy() {
      if (this._raf) cancelAnimationFrame(this._raf);
      this._raf = null;
    }

    /* ───── internals ───── */
    _setupCanvas() {
      const dpr = window.devicePixelRatio || 1;
      this.canvas.width = this.size * dpr;
      this.canvas.height = this.size * dpr;
      this.canvas.style.width = this.size + "px";
      this.canvas.style.height = this.size + "px";
      const ctx = this.canvas.getContext("2d");
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(dpr, dpr);
      ctx.imageSmoothingEnabled = true;
      this.ctx = ctx;
    }

    _loop(now) {
      const dt = now - this._last;
      this._last = now;
      if (!this.paused) this._acc += dt * this.speedMul;
      // Tween: interpolate cfg toward target if a transition is active.
      if (this._transition) {
        const tr = this._transition;
        const k = Math.min(1, (now - tr.t0) / tr.duration);
        const e = easeInOutSine(k);
        this.cfg = lerpCfg(tr.from, tr.to, e);
        if (k >= 1) this._transition = null;
      }
      this._render(this._acc / 1000);
      this._raf = requestAnimationFrame(this._loop);
    }

    _rotate(p, yaw, pitch) {
      let x = p[0], y = p[1], z = p[2];
      const cY = Math.cos(yaw), sY = Math.sin(yaw);
      const xz0 = x * cY - z * sY; z = x * sY + z * cY; x = xz0;
      const cP = Math.cos(pitch), sP = Math.sin(pitch);
      const yz0 = y * cP - z * sP; z = y * sP + z * cP; y = yz0;
      return [x, y, z];
    }

    _project(p, W, zoom) {
      const camZ = 3.6;
      const d = camZ - p[2];
      const fov = W * (zoom != null ? zoom : 0.95);
      return [(p[0] / d) * fov + W / 2, (-p[1] / d) * fov + W / 2, p[2]];
    }

    _faceColor(shade, distFactor, flashAmt) {
      const cfg = this.cfg;
      const baseL = 18 + shade * 42;
      const distL = baseL * (0.55 + 0.45 * distFactor);
      const finalL = Math.min(90, distL + flashAmt * 35);
      const sat = cfg.cubeSat * (0.5 + 0.5 * distFactor) + flashAmt * 20;
      return "hsl(" + cfg.cubeHue + ", " + Math.min(100, sat) + "%, " + finalL + "%)";
    }

    _drawCore(ctx, W, intensity) {
      const cfg = this.cfg;
      const cx = W / 2, cy = W / 2;
      const baseR = W * cfg.coreSize * 0.5;
      const outerR = baseR * (2.8 + 0.5 * intensity);
      const halo = ctx.createRadialGradient(cx, cy, baseR * 0.2, cx, cy, outerR);
      halo.addColorStop(0,    "hsla(" + cfg.coreHue + ", " + cfg.coreSat + "%, 70%, " + (0.55 * cfg.coreGlow * intensity) + ")");
      halo.addColorStop(0.45, "hsla(" + cfg.coreHue + ", " + cfg.coreSat + "%, 55%, " + (0.18 * cfg.coreGlow) + ")");
      halo.addColorStop(1,    "hsla(" + cfg.coreHue + ", " + cfg.coreSat + "%, 50%, 0)");
      ctx.fillStyle = halo;
      ctx.fillRect(cx - outerR, cy - outerR, outerR * 2, outerR * 2);

      const orb = ctx.createRadialGradient(cx, cy, 0, cx, cy, baseR);
      orb.addColorStop(0,    "hsla(" + cfg.coreHue + ", " + Math.min(100, cfg.coreSat + 10) + "%, " + Math.min(90, 70 + intensity * 15) + "%, " + (0.95 * cfg.coreGlow) + ")");
      orb.addColorStop(0.5,  "hsla(" + cfg.coreHue + ", " + cfg.coreSat + "%, 60%, " + (0.55 * cfg.coreGlow * intensity) + ")");
      orb.addColorStop(1,    "hsla(" + cfg.coreHue + ", " + cfg.coreSat + "%, 50%, 0)");
      ctx.fillStyle = orb;
      ctx.fillRect(cx - baseR * 1.4, cy - baseR * 1.4, baseR * 2.8, baseR * 2.8);
    }

    _render(t) {
      const ctx = this.ctx;
      const W = this.size;
      const cfg = this.cfg;

      ctx.fillStyle = cfg.bg;
      ctx.fillRect(0, 0, W, W);

      // shake (high-freq screen-space jitter, for error/surprised)
      const shakeAmp = cfg.shakeAmp || 0;
      const shakeFreq = cfg.shakeFreq || 18;
      if (shakeAmp > 0) {
        const sx = (Math.sin(t * shakeFreq * 7.2) + Math.sin(t * shakeFreq * 13.1)) * 0.5 * shakeAmp;
        const sy = (Math.sin(t * shakeFreq * 9.7 + 1.3) + Math.sin(t * shakeFreq * 11.4 + 0.9)) * 0.5 * shakeAmp;
        ctx.save();
        ctx.translate(sx, sy);
      }

      // Yaw integration: keep accumulating during transitions now
      // that transitions are sub-second — the brief continuation reads
      // as natural inertia instead of a freeze-frame.
      if (this._yawT == null) this._yawT = t;
      const yawDt = t - this._yawT;
      this._yawT = t;
      if (yawDt > 0) {
        this._yaw += yawDt * cfg.orbitSpeed * Math.PI * 2 * 0.18;
      }
      const yaw = this._yaw;
      const attnYaw = cfg.attentionTilt
        ? Math.sin(t * 0.27) * cfg.attentionTilt + Math.sin(t * 0.13 + 1.7) * cfg.attentionTilt * 0.6
        : 0;
      const pitch = cfg.pitch
        + Math.sin(t * 0.19) * 0.04
        + Math.sin(t * 0.077 + 2.3) * 0.06
        + (cfg.attentionTilt ? Math.sin(t * 0.21 + 0.7) * cfg.attentionTilt * 0.5 : 0);

      const breathe = 1
        + Math.sin(t * 0.9) * cfg.breatheAmp * 0.6
        + Math.sin(t * 0.41 + 1.1) * cfg.breatheAmp;

      const corePulse = 0.78
        + Math.sin(t * 1.1) * 0.08
        + Math.sin(t * 0.43 + 0.9) * 0.12
        + Math.sin(t * 2.7 + 2.1) * 0.04;

      // synapse flashes
      const flashes = this._flashes;
      if (cfg.flashRate > 0) {
        const expected = cfg.flashRate * 0.016;
        if (Math.random() < expected && flashes.length < 6) {
          flashes.push({
            cubeIdx: Math.floor(Math.random() * this._cubes.length),
            t0: t,
            dur: 0.45 + Math.random() * 0.35,
          });
        }
        for (let i = flashes.length - 1; i >= 0; i--) {
          if (t - flashes[i].t0 > flashes[i].dur) flashes.splice(i, 1);
        }
      }

      const rp = cfg.radialPulse || { amp: 0, freq: 0, wave: 0 };
      const sizeMul = cfg.cubeSizeMul != null ? cfg.cubeSizeMul : 1;
      const radiusOffset = cfg.radiusOffset != null ? cfg.radiusOffset : 0;

      const items = [];

      for (let ci = 0; ci < this._cubes.length; ci++) {
        const c = this._cubes[ci];
        const radial = rp.amp ? Math.sin(t * rp.freq * Math.PI * 2 - (rp.wave || 0) * c.r) * rp.amp : 0;
        const ringR = c.r * breathe + radial + radiusOffset;
        const wx = Math.cos(c.a) * ringR;
        const wz = Math.sin(c.a) * ringR;
        const wy = c.y + Math.sin(t * c.bobFreq + c.bobPhase) * cfg.bobAmp;

        let flashAmt = 0;
        for (let fi = 0; fi < flashes.length; fi++) {
          if (flashes[fi].cubeIdx === ci) {
            const k = (t - flashes[fi].t0) / flashes[fi].dur;
            if (k >= 0 && k <= 1) {
              const a = k < 0.15 ? k / 0.15 : 1 - (k - 0.15) / 0.85;
              if (a > flashAmt) flashAmt = a;
            }
          }
        }

        const cs = c.s * sizeMul;
        const projCorners = new Array(8);
        for (let i = 0; i < 8; i++) {
          const co = CORNERS[i];
          const w = [wx + co[0] * cs, wy + co[1] * cs, wz + co[2] * cs];
          const r = this._rotate(w, yaw + attnYaw, pitch);
          projCorners[i] = { r: r, p: this._project(r, W, cfg.zoom) };
        }

        const center = this._rotate([wx, wy, wz], yaw + attnYaw, pitch);
        const distFactor = clamp01((center[2] + 1.6) / 3.0);

        for (let fi = 0; fi < FACES.length; fi++) {
          const face = FACES[fi];
          const pts = [
            projCorners[face.idx[0]].p,
            projCorners[face.idx[1]].p,
            projCorners[face.idx[2]].p,
            projCorners[face.idx[3]].p,
          ];
          const area =
            (pts[1][0] - pts[0][0]) * (pts[2][1] - pts[0][1]) -
            (pts[1][1] - pts[0][1]) * (pts[2][0] - pts[0][0]);
          if (area >= -0.5) continue;
          const rn = this._rotate(face.n, yaw + attnYaw, pitch);
          const dot = rn[0] * LIGHT[0] + rn[1] * LIGHT[1] + rn[2] * LIGHT[2];
          const shade = clamp01(0.18 + Math.max(0, dot) * 0.95);
          const meanZ = (projCorners[face.idx[0]].r[2]
            + projCorners[face.idx[1]].r[2]
            + projCorners[face.idx[2]].r[2]
            + projCorners[face.idx[3]].r[2]) / 4;
          items.push({
            kind: "face", z: meanZ, pts: pts,
            color: this._faceColor(shade, distFactor, flashAmt),
            edge: flashAmt > 0.2,
          });
        }
      }

      // core glow as a z=0 sprite — back-side cubes drawn before, front-side after
      items.push({ kind: "core", z: 0 });
      items.sort(function (a, b) { return a.z - b.z; });

      for (let i = 0; i < items.length; i++) {
        const it = items[i];
        if (it.kind === "face") {
          ctx.beginPath();
          ctx.moveTo(it.pts[0][0], it.pts[0][1]);
          for (let k = 1; k < it.pts.length; k++) ctx.lineTo(it.pts[k][0], it.pts[k][1]);
          ctx.closePath();
          ctx.fillStyle = it.color;
          ctx.fill();
          ctx.lineWidth = 0.6;
          ctx.strokeStyle = it.edge
            ? "hsla(" + cfg.cubeHue + ", 100%, 90%, 0.85)"
            : "rgba(0,0,0,0.35)";
          ctx.stroke();
        } else if (it.kind === "core") {
          this._drawCore(ctx, W, corePulse);
        }
      }

      if (shakeAmp > 0) ctx.restore();
    }
  }

  // Map cube dashboard state → emotion. Caller can override.
  const STATE_TO_EMOTION = {
    thinking:   "thinking",
    permission: "listening",
    done:       "happy",
    idle:       "idle",
    error:      "error",
    compact:    "focused",
    alert:      "surprised",
    start:      "curious",
  };

  window.CubeEntity = CubeEntity;
  window.CUBE_EMOTIONS = EMOTIONS;
  window.CUBE_STATE_TO_EMOTION = STATE_TO_EMOTION;
})();
