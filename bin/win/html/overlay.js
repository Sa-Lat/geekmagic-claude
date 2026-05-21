/* cube overlay — Mochi Classic render loop.
 *
 * Polls window.pywebview.api.dashboard() every POLL_MS, diffs against
 * last render, patches DOM. GIF fetched on (img,ts) change via
 * api.gif() which returns base64 (pywebview can't pass raw bytes).
 *
 * Falls back to embedded SAMPLE_DATA when pywebview API is absent so
 * you can preview the look by opening index.html in any browser.
 */

const POLL_MS = 500;

const AGELESS = new Set(["idle", "done", "start"]);
const PULSE_STATES = new Set(["permission", "error", "compact", "alert", "thinking"]);
const STATE_LABELS = {
  permission: "wait", thinking: "thinking", done: "done", idle: "idle",
  error: "error", compact: "compact", alert: "alert", start: "start",
};

const SAMPLE_DATA = {
  skin: "waifu",
  state: "permission",
  img: null,
  ts: 0,
  usage_5h_pct: 42,
  sessions: [
    { state: "permission", cwd: "navigatoren", age_s: 12 },
    { state: "thinking",   cwd: "cube",        age_s: 184 },
    { state: "done",       cwd: "fleet-mgmt",  age_s: 0 },
    { state: "idle",       cwd: "backend-api", age_s: 0 },
  ],
};

function formatAge(s) {
  s = Math.floor(s || 0);
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
  return m === 0 ? h + "h" : h + "h" + m + "m";
}

function usageFill(pct, dark) {
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
const gifWrapEl = document.getElementById("gif-wrap");
const gifEl = document.getElementById("gif");

/* per-render cache: avoid stomping the DOM when nothing changed */
const last = {
  skin: null, theme: null,
  rowSig: null,
  usagePct: undefined,
  gifKey: null,
};

function setSkinTheme(skin, theme) {
  if (skin && skin !== last.skin) {
    document.documentElement.setAttribute("data-skin", skin);
    root.setAttribute("data-skin", skin);  // kept for backward-compat
    last.skin = skin;
  }
  if (theme && theme !== last.theme) {
    document.documentElement.setAttribute("data-theme", theme);
    root.setAttribute("data-theme", theme);  // kept for backward-compat
    last.theme = theme;
  }
}

function sigOfSessions(sessions) {
  return sessions.map(s =>
    AGELESS.has(s.state)
      ? `${s.cwd}|${s.state}|-`
      : `${s.cwd}|${s.state}|${Math.floor((s.age_s || 0) / 30)}`
  ).join(",");
}

function renderRows(sessions) {
  const sig = sigOfSessions(sessions);
  if (sig === last.rowSig) {
    /* still need to refresh ages every second since sig only buckets at 30s */
    for (let i = 0; i < sessions.length; i++) {
      const s = sessions[i];
      if (AGELESS.has(s.state)) continue;
      const metaEl = rowsEl.children[i]?.querySelector(".meta");
      if (metaEl) metaEl.textContent = formatAge(s.age_s);
    }
    return;
  }
  last.rowSig = sig;

  /* full rebuild — small list, faster than diff-by-cwd */
  rowsEl.innerHTML = "";
  for (const s of sessions) {
    const row = document.createElement("div");
    row.className = "row";

    const dot = document.createElement("span");
    dot.className = "dot";
    /* state attr drives --acc via CSS — avoids inline var() chains that
       occasionally fail to re-resolve on theme/skin attribute swaps,
       making dots invisible mid-transition. */
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
    rowsEl.appendChild(row);
  }
}

function renderUsage(pct) {
  if (pct === last.usagePct) return;
  last.usagePct = pct;
  if (pct == null) {
    usageRowEl.hidden = true;
    dividerEl.hidden = true;
    return;
  }
  usageRowEl.hidden = false;
  dividerEl.hidden = false;
  usagePctEl.textContent = `${pct}%`;
  barFillEl.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  const override = usageFill(pct);
  barFillEl.style.background = override || "";  /* "" = inherit --bar-fill */
}

async function renderGif(img, ts) {
  const key = `${img}|${ts}`;
  if (key === last.gifKey) return;
  last.gifKey = key;
  if (!img) {
    gifWrapEl.hidden = true;
    return;
  }
  if (window.pywebview?.api?.gif) {
    try {
      const b64 = await window.pywebview.api.gif();
      if (!b64) return;
      gifEl.src = `data:image/gif;base64,${b64}`;
      gifWrapEl.hidden = false;
    } catch (e) {
      console.warn("gif fetch failed", e);
    }
  } else {
    gifWrapEl.hidden = true;  /* preview-mode: no GIF without bridge */
  }
}

function render(data) {
  if (!data) return;
  setSkinTheme(data.skin, data.theme);
  const sessions = data.sessions || [];
  sessCountEl.textContent = String(sessions.length);
  renderRows(sessions);
  renderUsage(data.usage_5h_pct ?? null);
  renderGif(data.img, data.ts);
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
    /* Sync server-driven skin into local UI (mock-cube derives from
       ~/.claude/.cube-skin). Theme is local but mirrored back so a
       reload from another instance picks up changes. */
    if (typeof ui !== "undefined") {
      if (data.skin && data.skin !== ui.skin) { ui.skin = data.skin; applyUi(); }
      if (data.theme && data.theme !== ui.theme) { ui.theme = data.theme; applyUi(); }
      if (typeof data.locked === "boolean" && data.locked !== ui.locked) {
        ui.locked = data.locked;
        applyUi();
      }
      maybeLift(data.state);
    }
  }
  render(data);
  setTimeout(poll, POLL_MS);
}

/* URL query lets a single static HTML preview the dark theme without
   pywebview. e.g. file:///.../index.html?theme=dark&skin=orb */
function applyQueryOverrides() {
  const q = new URLSearchParams(location.search);
  const theme = q.get("theme");
  const skin = q.get("skin");
  if (theme || skin) setSkinTheme(skin || "waifu", theme || "light");
}

applyQueryOverrides();

/* ───────────────────────────── Phase-2: client state */
const ui = {
  theme: "light",
  skin: "waifu",
  width: 180,
  locked: false,
  topmost: true,
  lift: false,
  size_presets: [140, 180, 240],
  hide_winner: null,
  hidden: false,
};
const api = () => window.pywebview && window.pywebview.api;

function applyUi() {
  setSkinTheme(ui.skin, ui.theme);
  document.body.classList.toggle("draggable", !ui.locked);
}

/* ───────────────────────────── Drag */
const drag = { active: false };

function attachDrag() {
  const wrap = document.querySelector(".wrap");
  if (!wrap) return;

  wrap.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;            /* left-click only */
    if (ui.locked) return;
    if (e.target.closest(".ctx-menu")) return;
    drag.active = true;
    document.body.classList.add("dragging");
    /* Fire-and-forget. Python reads cursor pos via GetCursorPos so we
       don't pass screenX/Y (WebView2 reports logical pixels which mismatch
       SetWindowPos's physical-pixel coord space). */
    api()?.start_drag();
  });

  /* Move/up bound on document so we keep tracking even if cursor leaves window. */
  document.addEventListener("mousemove", () => {
    if (!drag.active) return;
    api()?.move_relative();   /* fire-and-forget; each call samples cursor fresh */
  });
  document.addEventListener("mouseup", () => {
    if (!drag.active) return;
    drag.active = false;
    document.body.classList.remove("dragging");
    api()?.end_drag();
  });
}

/* ───────────────────────────── Menu (native Win32) */
/* WebView2 frameless can't grow a DOM popup past the window's own bounds
   (~180-240 px wide), so submenus got clipped. Native TrackPopupMenu on
   the Python side lives outside the WebView2 surface — no constraint. */
function attachContextMenu() {
  document.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    api()?.show_menu();
  });
}

/* Dynamic window height — report `.wrap` content height up to Python
   whenever DOM size changes (renderRows, GIF onload, theme swap, etc.).
   Python resizes the OS window keeping the bottom-right anchor stable
   so the card "grows upward" rather than down off-screen. */
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
    });
  });
  ro.observe(wrap);
}

/* ───────────────────────────── Activity tracking (lift on activity) */
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

/* ───────────────────────────── Bootstrap */
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

/* pywebview injects the api asynchronously; window.pywebview is undefined
   when the script first runs. Always listen for pywebviewready, plus a
   fallback timer for plain-browser preview mode (no pywebview ever). */
let _bootstrapped = false;
function _kick() {
  if (_bootstrapped) return;
  _bootstrapped = true;
  bootstrap();
}
window.addEventListener("pywebviewready", _kick);
setTimeout(_kick, 800);  /* preview-mode safety net */
