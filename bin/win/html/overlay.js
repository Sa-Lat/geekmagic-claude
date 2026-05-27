/* cube overlay — Mochi Classic render loop.
 *
 * Polls window.pywebview.api.dashboard() every POLL_MS, diffs against last
 * render, patches DOM. The voxel entity canvas is driven by cube-entity.js;
 * one emotion per dashboard state.
 *
 * Falls back to embedded SAMPLE_DATA when pywebview API is absent so you
 * can preview the look by opening index.html in any browser.
 */

const POLL_MS = 500;

const AGELESS = new Set(["idle", "done", "start"]);
const PULSE_STATES = new Set(["permission", "error", "compact", "alert", "thinking"]);
const STATE_LABELS = {
  permission: "wait", thinking: "thinking", done: "done", idle: "idle",
  error: "error", compact: "compact", alert: "alert", start: "start",
};

const SAMPLE_DATA = {
  state: "thinking",
  ts: 0,
  usage_5h_pct: 42,
  sessions: [
    { state: "permission", cwd: "navigatoren", age_s: 12,
      session_id: "a4f29b12-...", label: "Fix the auth middleware bug" },
    { state: "thinking",   cwd: "cube",        age_s: 184,
      session_id: "7f3a2b88-...", label: "Werden Fehler im Code abgefangen" },
    { state: "error",      cwd: "cube",        age_s: 47,
      session_id: "9c1d4401-...", label: "Add multi-session subline to overlay" },
    { state: "done",       cwd: "cube",        age_s: 0,
      session_id: "2e8a01ff-...", label: "Refactor cube.sh mutate logic" },
    { state: "idle",       cwd: "backend-api", age_s: 0,
      session_id: "d3b72077-...", label: "Investigate slow API endpoint" },
  ],
};

function formatAge(s) {
  s = Math.floor(s || 0);
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return m === 0 ? h + "h" : h + "h" + m + "m";
}

function usageFill(pct) {
  if (pct == null) return null;
  if (pct >= 80) return "#e85555";
  if (pct >= 50) return "#d7a04a";
  return null;  // null = stay on palette default --bar-fill
}

/* ───────────────────────────── DOM */
const root = document.getElementById("root");
const rowsEl = document.getElementById("rows");
const sessCountEl = document.getElementById("sess-count");
const dividerEl = document.querySelector(".divider");
const usageRowEl = document.getElementById("usage-row");
const usagePctEl = document.getElementById("usage-pct");
const barFillEl = document.getElementById("bar-fill");
const entityWrapEl = document.getElementById("entity-wrap");
const entityCanvasEl = document.getElementById("cube-entity");

/* per-render cache: avoid stomping the DOM when nothing changed */
const last = {
  theme: null,
  rowSig: null,
  usagePct: undefined,
  entityEmotion: null,
};

function setTheme(theme) {
  if (!theme || theme === last.theme) return;
  document.documentElement.setAttribute("data-theme", theme);
  root.setAttribute("data-theme", theme);
  last.theme = theme;
}

/* ───────────────────────────── Cube entity instance
 *
 * Lazily constructed on first render so the renderer's requestAnimationFrame
 * loop doesn't start until DOM is wired. setEmotion is the only call needed
 * per state change — params snap or tween based on LERP_NUMERIC inside
 * cube-entity.js.
 */
let entity = null;
function ensureEntity() {
  if (entity) return entity;
  if (!entityCanvasEl || typeof CubeEntity === "undefined") return null;
  // Canvas size = card inner width (wrap.clientWidth minus 12 px padding both
  // sides). Re-measured by ResizeObserver in attachAutoResize on width change.
  const wrap = document.querySelector(".wrap");
  const innerW = wrap ? wrap.clientWidth - 24 : 156;
  entity = new CubeEntity(entityCanvasEl, {
    size: Math.max(80, innerW),
    emotion: "thinking",
  });
  window.__cubeOverlayEntity = entity;  // expose for demo / debugging
  return entity;
}

function sublineText(s, cwdCounts) {
  if ((cwdCounts.get(s.cwd) || 0) <= 1) return "";
  return s.label || "";
}

function sigOfSessions(sessions, cwdCounts) {
  return sessions.map(s => {
    const sub = sublineText(s, cwdCounts);
    return AGELESS.has(s.state)
      ? `${s.cwd}|${s.state}|-|${sub}`
      : `${s.cwd}|${s.state}|${Math.floor((s.age_s || 0) / 30)}|${sub}`;
  }).join(",");
}

function renderRows(sessions) {
  const cwdCounts = new Map();
  for (const s of sessions) {
    cwdCounts.set(s.cwd, (cwdCounts.get(s.cwd) || 0) + 1);
  }

  const sig = sigOfSessions(sessions, cwdCounts);
  if (sig === last.rowSig) {
    /* refresh ages every second since sig only buckets at 30 s */
    for (let i = 0; i < sessions.length; i++) {
      const s = sessions[i];
      if (AGELESS.has(s.state)) continue;
      const metaEl = rowsEl.children[i]?.querySelector(".meta");
      if (metaEl) metaEl.textContent = formatAge(s.age_s);
    }
    return;
  }
  last.rowSig = sig;

  rowsEl.innerHTML = "";
  for (const s of sessions) {
    const block = document.createElement("div");
    block.className = "row-block";

    const row = document.createElement("div");
    row.className = "row";

    const dot = document.createElement("span");
    dot.className = "dot";
    dot.setAttribute("data-state", s.state);
    if (PULSE_STATES.has(s.state)) dot.setAttribute("data-live", "true");

    const cwd = document.createElement("span");
    cwd.className = "cwd";
    cwd.textContent = s.cwd || "—";

    const meta = document.createElement("span");
    meta.className = "meta";
    if (AGELESS.has(s.state)) {
      meta.setAttribute("data-ageless", "true");
      meta.textContent = STATE_LABELS[s.state] || s.state;
    } else {
      meta.textContent = formatAge(s.age_s);
    }

    row.appendChild(dot);
    row.appendChild(cwd);
    row.appendChild(meta);
    block.appendChild(row);

    const subTxt = sublineText(s, cwdCounts);
    if (subTxt) {
      const sub = document.createElement("div");
      sub.className = "subline";
      sub.textContent = subTxt;
      block.appendChild(sub);
    }

    rowsEl.appendChild(block);
  }
}

function renderUsage(pct) {
  /* In slim mode (hide_entity) the usage row is the only thing below the
   * session list, so always show it — placeholder "—" while pct null (e.g.
   * ccusage not running yet). In normal mode auto-hide so a missing ccusage
   * doesn't leave an empty "Use —" sitting above the entity. */
  const slim = !!ui.hide_entity;
  const sig = `${pct}|${slim ? 1 : 0}`;
  if (sig === last.usagePct) return;
  last.usagePct = sig;
  if (pct == null && !slim) {
    usageRowEl.hidden = true;
    dividerEl.hidden = true;
    return;
  }
  usageRowEl.hidden = false;
  dividerEl.hidden = slim;  /* divider only between rows and Use when entity present */
  if (pct == null) {
    usagePctEl.textContent = "—";
    barFillEl.style.width = "0%";
    barFillEl.style.background = "";
  } else {
    usagePctEl.textContent = `${pct}%`;
    barFillEl.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    const override = usageFill(pct);
    barFillEl.style.background = override || "";
  }
}

/* Drive the cube-entity from the winner state. Called every poll;
 * setEmotion is cheap (config object spread + tween-capture) and the
 * renderer's RAF loop picks up the new params on the next frame. */
function renderEntity(state) {
  const ent = ensureEntity();
  if (!ent) return;
  if (ui.hide_entity) {
    if (entityWrapEl) entityWrapEl.hidden = true;
    ent.pause();
    return;
  }
  if (entityWrapEl) entityWrapEl.hidden = false;
  ent.resume();
  const emo = (window.CUBE_STATE_TO_EMOTION && window.CUBE_STATE_TO_EMOTION[state]) || "idle";
  if (emo !== last.entityEmotion) {
    ent.setEmotion(emo);
    last.entityEmotion = emo;
  }
}

function invalidateRender() {
  last.usagePct = undefined;
  last.entityEmotion = null;
}

function render(data) {
  if (!data) return;
  setTheme(data.theme);
  const sessions = data.sessions || [];
  sessCountEl.textContent = String(sessions.length);
  renderRows(sessions);
  renderUsage(data.usage_5h_pct ?? null);
  renderEntity(data.state);
}

/* ───────────────────────────── poll loop */
async function poll() {
  let data = null;
  if (window.pywebview?.api?.dashboard) {
    try {
      data = await window.pywebview.api.dashboard();
    } catch (e) {
      console.warn("dashboard fetch failed", e);
    }
  } else {
    data = SAMPLE_DATA;  /* preview mode */
  }
  if (data) {
    if (typeof ui !== "undefined") {
      if (data.theme && data.theme !== ui.theme) { ui.theme = data.theme; applyUi(); }
      if (typeof data.locked === "boolean" && data.locked !== ui.locked) {
        ui.locked = data.locked;
        applyUi();
      }
      if (typeof data.hide_entity === "boolean" && data.hide_entity !== ui.hide_entity) {
        ui.hide_entity = data.hide_entity;
        invalidateRender();
      }
      maybeLift(data.state);
    }
  }
  render(data);
  setTimeout(poll, POLL_MS);
}

/* URL query lets a single static HTML preview a different theme without
   pywebview. e.g. file:///.../index.html?theme=dark */
function applyQueryOverrides() {
  const q = new URLSearchParams(location.search);
  const theme = q.get("theme");
  if (theme) setTheme(theme);
}
applyQueryOverrides();

/* ───────────────────────────── client state */
const ui = {
  theme: "light",
  width: 180,
  locked: false,
  topmost: true,
  lift: false,
  size_presets: [140, 180, 240],
  hide_winner: null,
  hidden: false,
  hide_entity: false,
};
const api = () => window.pywebview && window.pywebview.api;

function applyUi() {
  setTheme(ui.theme);
  document.body.classList.toggle("draggable", !ui.locked);
}

/* ───────────────────────────── Drag */
const drag = { active: false };

function attachDrag() {
  const wrap = document.querySelector(".wrap");
  if (!wrap) return;

  wrap.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    if (ui.locked) return;
    if (e.target.closest(".ctx-menu")) return;
    drag.active = true;
    document.body.classList.add("dragging");
    /* Fire-and-forget. Python reads cursor pos via GetCursorPos so we don't
       pass screenX/Y (WebView2 reports logical px which mismatch SetWindowPos's
       physical-pixel coord space). */
    api()?.start_drag();
  });

  document.addEventListener("mousemove", () => {
    if (!drag.active) return;
    api()?.move_relative();
  });
  document.addEventListener("mouseup", () => {
    if (!drag.active) return;
    drag.active = false;
    document.body.classList.remove("dragging");
    api()?.end_drag();
  });
}

/* Menu is native Win32 (TrackPopupMenu) — frameless WebView2 clips DOM popups
   past its own bounds, so we hand off to TrackPopupMenu which lives outside
   the WebView2 surface. */
function attachContextMenu() {
  document.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    api()?.show_menu();
  });
}

/* Dynamic window height — report `.wrap` content height up to Python whenever
   DOM size changes. Python resizes the OS window keeping the bottom-right
   anchor stable so the card "grows upward" rather than down off-screen. */
function attachAutoResize() {
  const wrap = document.querySelector(".wrap");
  if (!wrap || typeof ResizeObserver === "undefined") return;
  let lastH = 0, raf = 0;
  const ro = new ResizeObserver(entries => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const h = Math.ceil(wrap.getBoundingClientRect().height);
      if (h && h !== lastH) {
        lastH = h;
        api()?.resize_height(h);
      }
      // Cube-entity tracks card-width changes — re-size canvas's internal
      // resolution to match its rendered px box so it stays crisp at every
      // overlay size preset.
      if (entity && entityCanvasEl) {
        const cssW = Math.round(entityCanvasEl.getBoundingClientRect().width);
        if (cssW && Math.abs(cssW - entity.size) > 2) entity.setSize(cssW);
      }
    });
  });
  ro.observe(wrap);
  if (entityCanvasEl) ro.observe(entityCanvasEl);
}

/* Lift on activity: idle/done/start → pulse-state crossing brings the window
   to front so a long-idle overlay surfaces when work resumes. */
let activityState = { lastWinner: null };
function maybeLift(newWinner) {
  if (!ui.lift) {
    activityState.lastWinner = newWinner;
    return;
  }
  if (activityState.lastWinner
      && AGELESS.has(activityState.lastWinner)
      && PULSE_STATES.has(newWinner)) {
    api()?.bring_to_front();
  }
  activityState.lastWinner = newWinner;
}

async function bootstrap() {
  const bridge = api();
  if (bridge && bridge.initial_state) {
    try {
      Object.assign(ui, await bridge.initial_state());
    } catch (e) {
      console.warn("initial_state failed", e);
    }
  }
  applyUi();
  attachDrag();
  attachContextMenu();
  attachAutoResize();
  poll();
}

/* pywebview injects api asynchronously; window.pywebview is undefined when
   the script first runs. Always listen for pywebviewready, plus a fallback
   timer for plain-browser preview mode (no pywebview ever). */
let _bootstrapped = false;
function _kick() {
  if (_bootstrapped) return;
  _bootstrapped = true;
  bootstrap();
}
window.addEventListener("pywebviewready", _kick);
setTimeout(_kick, 800);  /* preview-mode safety net */
