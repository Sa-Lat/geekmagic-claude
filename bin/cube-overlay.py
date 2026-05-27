#!/usr/bin/env python3
"""cube-overlay — frameless always-on-top Tk dashboard that mirrors mock-cube
state. Renders one block per active Claude session (emoji + cwd + age) sorted
by state priority, plus 5h-window usage % and the winning state's GIF.

Run:
  python3 bin/cube-overlay.py --frameless
  CUBE_OVERLAY_X=3700 CUBE_OVERLAY_Y=920 python3 bin/cube-overlay.py --frameless

Env (defaults if CLI not given):
  CUBE_OVERLAY_MOCK         default http://127.0.0.1:8765
  CUBE_OVERLAY_X / _Y       legacy window position (migrated once)
  CUBE_OVERLAY_SIZE         gif edge length (0/unset = auto-fit to window width)
  CUBE_OVERLAY_WIDTH        window width    (default = max(180, size+2*pad))
  CUBE_OVERLAY_MAX_BLOCKS   how many session blocks to show (default 5)
  CUBE_OVERLAY_RESET_R / _B deprecated Reset override; default now =
                            current layout's primary-monitor right-bottom.
                            Per-layout anchors live in
                            ~/.config/cube/overlay-layouts.json.
"""
import argparse
import io
import json
import os
import subprocess
import sys
import tkinter as tk
import urllib.request
from PIL import Image, ImageSequence, ImageTk

POLL_MS = 500
PAD = 6


def size_metrics(win_w):
    """Map window width to font size and matching block/usage heights so
    Small windows get smaller fonts and Large windows get bigger fonts."""
    if win_w < 160:
        return {"font": 8, "block_h": 18, "usage_h": 15}
    if win_w < 220:
        return {"font": 9, "block_h": 22, "usage_h": 18}
    return {"font": 11, "block_h": 28, "usage_h": 22}

OVERLAY_ENV_PATH = os.path.expanduser("~/.config/cube/overlay.env")
LAYOUTS_PATH = os.path.expanduser("~/.config/cube/overlay-layouts.json")
SKIN_FILE = os.path.expanduser("~/.claude/.cube-skin")
SERVICE_NAME = "cube-overlay.service"
SKIN_CHOICES = ("orb", "waifu")
SIZE_PRESETS = (("Small", 140), ("Medium", 180), ("Large", 240))

# Per-skin × theme palettes. Each block tint is hand-picked to read against
# the skin's GIF palette so the overlay reads as a single visual surface,
# not chrome stuck onto a sprite. Chrome (window bg, usage line, overflow
# row) follows the skin too, not a universal black/white.
EMOJI = {
    "permission": "🔐", "error": "❌", "compact": "📦", "alert": "⚠",
    "thinking":   "⚙",  "done":  "✅", "start":   "👋", "idle":  "💤",
}
SKIN_PALETTES = {
    "orb": {
        "dark": {
            "chrome": {"bg": "#33241a", "fg_bright": "#e0d4c0", "fg_dim": "#807060",
                       "usage_bg": "#433022"},
            "states": {
                "permission": {"bg": "#4a3a0e", "fg": "#ffd860"},
                "error":      {"bg": "#4a1a14", "fg": "#ff9080"},
                "compact":    {"bg": "#2e1d3c", "fg": "#c8a8e0"},
                "alert":      {"bg": "#4a2a0c", "fg": "#ffb060"},
                "thinking":   {"bg": "#1f2a32", "fg": "#9fb8c8"},
                "done":       {"bg": "#1a3010", "fg": "#a0d090"},
                "start":      {"bg": "#1f2a32", "fg": "#aac8d8"},
                "idle":       {"bg": "#2a1d14", "fg": "#a89070"},
            },
        },
        "light": {
            "chrome": {"bg": "#f0e6d2", "fg_bright": "#2a1810", "fg_dim": "#605040",
                       "usage_bg": "#e0d6c0"},
            "states": {
                "permission": {"bg": "#fae6a8", "fg": "#7a5500"},
                "error":      {"bg": "#fad0c0", "fg": "#8a2010"},
                "compact":    {"bg": "#e8d4f0", "fg": "#5a2080"},
                "alert":      {"bg": "#fadcb0", "fg": "#8a4010"},
                "thinking":   {"bg": "#d4e0e8", "fg": "#2a4055"},
                "done":       {"bg": "#d4e8c8", "fg": "#2a5520"},
                "start":      {"bg": "#d4e0e8", "fg": "#2a5070"},
                "idle":       {"bg": "#ebe1d2", "fg": "#7a7060"},
            },
        },
    },
    "waifu": {
        "dark": {
            "chrome": {"bg": "#332034", "fg_bright": "#f0d8e0", "fg_dim": "#806878",
                       "usage_bg": "#432b44"},
            "states": {
                "permission": {"bg": "#4a1f3a", "fg": "#ff9bde"},
                "error":      {"bg": "#4a1424", "fg": "#ff8a9b"},
                "compact":    {"bg": "#3a1438", "fg": "#e0a8d4"},
                "alert":      {"bg": "#4a2435", "fg": "#ffadc8"},
                "thinking":   {"bg": "#2a1d3a", "fg": "#c0a8d8"},
                "done":       {"bg": "#2a3a1f", "fg": "#a8d098"},
                "start":      {"bg": "#2a1d3a", "fg": "#c8b0e0"},
                "idle":       {"bg": "#2a1a2c", "fg": "#a890a0"},
            },
        },
        "light": {
            "chrome": {"bg": "#f7e6ef", "fg_bright": "#2a1020", "fg_dim": "#605060",
                       "usage_bg": "#ead8e2"},
            "states": {
                "permission": {"bg": "#fad0e8", "fg": "#7a1058"},
                "error":      {"bg": "#fac8d0", "fg": "#8a1825"},
                "compact":    {"bg": "#eecdef", "fg": "#5a1860"},
                "alert":      {"bg": "#fadce5", "fg": "#8a3055"},
                "thinking":   {"bg": "#e0d0f0", "fg": "#3a1d70"},
                "done":       {"bg": "#d0e8c8", "fg": "#205a20"},
                "start":      {"bg": "#e0d0f0", "fg": "#3a2080"},
                "idle":       {"bg": "#f5e8ee", "fg": "#806068"},
            },
        },
    },
}
THEME_NAMES = ("dark", "light")


def palette_for(skin, theme):
    return SKIN_PALETTES.get(skin, SKIN_PALETTES["orb"]).get(theme,
           SKIN_PALETTES.get(skin, SKIN_PALETTES["orb"])["dark"])


# Module-level chrome colors initialized to orb/dark; overwritten by main().
BG = SKIN_PALETTES["orb"]["dark"]["chrome"]["bg"]
FG_DIM = SKIN_PALETTES["orb"]["dark"]["chrome"]["fg_dim"]
FG_BRIGHT = SKIN_PALETTES["orb"]["dark"]["chrome"]["fg_bright"]


def format_age(s):
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h" if m == 0 else f"{h}h{m}m"


def read_overlay_env():
    """Parse overlay.env into dict. Empty dict if file missing or unreadable."""
    d = {}
    try:
        with open(OVERLAY_ENV_PATH) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip()
    except OSError:
        pass
    return d


def write_overlay_env(updates):
    """Atomic merge-write of overlay.env. updates: {KEY: value-or-None-to-delete}."""
    cur = read_overlay_env()
    for k, v in updates.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = str(v)
    os.makedirs(os.path.dirname(OVERLAY_ENV_PATH), exist_ok=True)
    tmp = OVERLAY_ENV_PATH + ".tmp"
    with open(tmp, "w") as f:
        for k, v in cur.items():
            f.write(f"{k}={v}\n")
    os.replace(tmp, OVERLAY_ENV_PATH)


def read_skin():
    try:
        return open(SKIN_FILE).read().strip() or "orb"
    except OSError:
        return "orb"


def detect_layout(sw, sh):
    """Return {fingerprint, primary:(x,y,w,h), ok} for current monitor setup.
    xrandr-enriched when available (distinguishes Dock/Undock + identifies
    primary monitor); else falls back to {sw}x{sh} fingerprint with the full
    virtual screen as the implicit primary."""
    try:
        out = subprocess.run(
            ["xrandr", "--listmonitors"],
            timeout=1, capture_output=True, text=True, check=True,
        ).stdout
    except Exception:
        return {"fingerprint": f"fallback:{sw}x{sh}",
                "primary": (0, 0, sw, sh), "ok": False}

    mons = []
    primary = None
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("Monitors:"):
            continue
        # Format: "0: +*XWAYLAND0 1920/509x1080/286+0+0  XWAYLAND0"
        parts = line.split()
        if len(parts) < 3:
            continue
        flags = parts[1]            # "+*NAME" or "+NAME"
        is_primary = "*" in flags
        geom = parts[2]             # "1920/509x1080/286+0+0"
        try:
            wh, _, rest = geom.partition("x")
            w = int(wh.split("/")[0])
            hpart, _, off = rest.partition("+")
            h = int(hpart.split("/")[0])
            xo, _, yo = off.partition("+")
            x = int(xo); y = int(yo)
        except (ValueError, IndexError):
            continue
        mons.append((x, y, w, h, is_primary))
        if is_primary:
            primary = (x, y, w, h)

    if not mons:
        return {"fingerprint": f"fallback:{sw}x{sh}",
                "primary": (0, 0, sw, sh), "ok": False}

    # Heuristic: no `*` → pick monitor at +0+0, else first by x_off.
    if primary is None:
        zero_off = [m for m in mons if m[0] == 0 and m[1] == 0]
        primary = (zero_off[0] if zero_off else sorted(mons)[0])[:4]

    mons_sorted = sorted(mons, key=lambda m: (m[0], m[1]))
    fp = f"mon{len(mons)}:" + ",".join(
        f"{w}x{h}+{x}+{y}" for x, y, w, h, _ in mons_sorted
    )
    return {"fingerprint": fp, "primary": primary, "ok": True}


def load_layouts():
    """Read overlay-layouts.json → dict. {} if missing/unreadable."""
    try:
        with open(LAYOUTS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_layout_anchor(fp, anchor_r, anchor_b):
    """Atomic merge-write of overlay-layouts.json for one fingerprint."""
    layouts = load_layouts()
    layouts[fp] = {"anchor_r": int(anchor_r), "anchor_b": int(anchor_b)}
    os.makedirs(os.path.dirname(LAYOUTS_PATH), exist_ok=True)
    tmp = LAYOUTS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(layouts, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, LAYOUTS_PATH)


def wslg_probe():
    """Spawn a tiny decorated Tk window in a subprocess for ~120ms. WSLg bug:
    after a service restart, overrideredirect (frameless) windows occasionally
    fail to map until any decorated X11 client surfaces. This nudge wakes the
    compositor. Window is 1x1 offscreen so user never sees it. Harmless on
    non-WSLg setups (just a brief extra process). Timeout caps at 3s in case
    Tk hangs."""
    script = (
        "import tkinter as tk\n"
        "r = tk.Tk()\n"
        "r.title('cube-probe')\n"
        "r.geometry('1x1+-2000+-2000')\n"
        "r.update()\n"
        "r.after(120, r.destroy)\n"
        "r.mainloop()\n"
    )
    try:
        subprocess.run([sys.executable, "-c", script],
                       timeout=3, capture_output=True)
    except Exception:
        pass


AGELESS_STATES = {"idle", "done", "start"}


def block_text(sess):
    emoji = EMOJI.get(sess["state"], EMOJI["idle"])
    cwd = sess.get("cwd") or "—"
    # idle: ambient, no actionable age. done/start: 5s blips, age=0 always.
    # Other states (thinking/permission/error/compact/alert) show "how long".
    if sess["state"] in AGELESS_STATES:
        return f"{emoji} {cwd}"
    return f"{emoji} {cwd} · {format_age(sess['age_s'])}"


def fetch_dashboard(mock):
    try:
        with urllib.request.urlopen(f"{mock}/dashboard.json", timeout=1) as r:
            return json.loads(r.read())
    except Exception:
        return None


def fetch_gif(mock):
    try:
        with urllib.request.urlopen(f"{mock}/current.gif", timeout=2) as r:
            return r.read()
    except Exception:
        return None


def load_frames(gif_bytes, size):
    img = Image.open(io.BytesIO(gif_bytes))
    frames, durations = [], []
    for f in ImageSequence.Iterator(img):
        rgba = f.convert("RGBA")
        if rgba.size != (size, size):
            rgba = rgba.resize((size, size), Image.LANCZOS)
        frames.append(rgba)
        durations.append(max(20, f.info.get("duration", 100)))
    return frames, durations


def usage_color(pct, theme="dark"):
    if pct is None:
        return FG_DIM
    if theme == "light":
        # Darker variants — saturated mid-tones disappear against light bg.
        if pct >= 80:
            return "#a51010"
        if pct >= 50:
            return "#7a5500"
        return "#2a6020"
    if pct >= 80:
        return "#e85555"
    if pct >= 50:
        return "#d7c84a"
    return "#5fd06a"


def usage_label(pct):
    if pct is None:
        return "Usage —"
    return f"Usage {pct}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", default=os.environ.get("CUBE_OVERLAY_MOCK", "http://127.0.0.1:8765"))
    ap.add_argument("--margin", type=int, default=20)
    ap.add_argument("--size", type=int,
                    default=int(os.environ.get("CUBE_OVERLAY_SIZE", 0)),
                    help="gif edge length (pixels). 0 = auto-fit to window width.")
    ap.add_argument("--width", type=int,
                    default=int(os.environ.get("CUBE_OVERLAY_WIDTH", 0)),
                    help="window width (0 = derive from size + padding)")
    ap.add_argument("--max-blocks", type=int,
                    default=int(os.environ.get("CUBE_OVERLAY_MAX_BLOCKS", 5)),
                    help="cap on session blocks (default 5)")
    ap.add_argument("--x", type=int, default=None, help="window X; env CUBE_OVERLAY_X")
    ap.add_argument("--y", type=int, default=None, help="window Y; env CUBE_OVERLAY_Y")
    ap.add_argument("--frameless", action="store_true", help="overrideredirect borderless")
    args = ap.parse_args()

    win_w = args.width if args.width > 0 else max(180, (args.size or 100) + 2 * PAD)
    # Auto-fit: GIF fills window width minus padding when size wasn't set.
    if args.size <= 0:
        args.size = win_w - 2 * PAD
    metrics = size_metrics(win_w)
    block_h = metrics["block_h"]
    usage_h = metrics["usage_h"]
    font_size = metrics["font"]

    # Initial skin + theme. Skin is per-state-source from cube.sh; theme is
    # the dark/light preference. Both can flip live via right-click menu.
    skin_name = read_skin()
    theme_name = os.environ.get("CUBE_OVERLAY_THEME", "dark")
    if theme_name not in THEME_NAMES:
        theme_name = "dark"
    pal = palette_for(skin_name, theme_name)
    global BG, FG_DIM, FG_BRIGHT
    BG = pal["chrome"]["bg"]
    FG_DIM = pal["chrome"]["fg_dim"]
    FG_BRIGHT = pal["chrome"]["fg_bright"]

    # WSLg compositor wake-up before creating the real frameless window.
    if args.frameless:
        wslg_probe()

    root = tk.Tk()
    root.title("cube-overlay")
    if args.frameless:
        root.overrideredirect(True)
    root.attributes("-topmost", True)
    # Passive focus model: the overlay declares it does not actively grab
    # input focus from other apps. Without this, WSLg pulls text-input focus
    # from whatever's focused (terminal, editor) on every overlay redraw.
    try:
        root.focusmodel("passive")
    except tk.TclError:
        pass
    root.configure(bg=BG)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    init_h = PAD + block_h + usage_h + args.size + 2 * PAD
    # Per-layout anchor: each monitor setup (Dock/Undock, Home/Office)
    # gets its own bottom-right anchor. Unknown layouts center on the
    # primary monitor; legacy global anchor migrates into the current
    # layout on first run.
    layout = detect_layout(sw, sh)
    fp = layout["fingerprint"]
    layouts = load_layouts()
    px, py, pw, ph = layout["primary"]

    def _in_bounds(r, b):
        return 0 < r <= sw and 0 < b <= sh

    anchor_source = "cache"
    if fp in layouts and _in_bounds(layouts[fp].get("anchor_r", 0),
                                    layouts[fp].get("anchor_b", 0)):
        anchor_right = int(layouts[fp]["anchor_r"])
        anchor_bottom = int(layouts[fp]["anchor_b"])
    else:
        env_ar = os.environ.get("CUBE_OVERLAY_ANCHOR_R")
        env_ab = os.environ.get("CUBE_OVERLAY_ANCHOR_B")
        if env_ar and env_ab and _in_bounds(int(env_ar), int(env_ab)):
            anchor_right = int(env_ar)
            anchor_bottom = int(env_ab)
            anchor_source = "migrate-anchor"
        elif args.x is not None or args.y is not None \
             or "CUBE_OVERLAY_X" in os.environ or "CUBE_OVERLAY_Y" in os.environ:
            legacy_x = args.x if args.x is not None else int(os.environ.get("CUBE_OVERLAY_X", px + pw - win_w - args.margin))
            legacy_y = args.y if args.y is not None else int(os.environ.get("CUBE_OVERLAY_Y", py + ph - init_h - args.margin))
            anchor_right = legacy_x + win_w
            anchor_bottom = legacy_y + init_h
            anchor_source = "migrate-xy"
        else:
            # Center on primary monitor.
            anchor_right = px + pw // 2 + win_w // 2
            anchor_bottom = py + ph // 2 + init_h // 2
            anchor_source = "center"
        save_layout_anchor(fp, anchor_right, anchor_bottom)

    # Strip legacy global anchor keys (now stored per-layout).
    try:
        write_overlay_env({
            "CUBE_OVERLAY_ANCHOR_R": None,
            "CUBE_OVERLAY_ANCHOR_B": None,
            "CUBE_OVERLAY_X": None,
            "CUBE_OVERLAY_Y": None,
        })
    except Exception:
        pass

    x = anchor_right - win_w
    y = anchor_bottom - init_h
    print(f"mock={args.mock}  layout={fp}  source={anchor_source}  primary={px},{py},{pw}x{ph}  anchor=br({anchor_right},{anchor_bottom})  pos=+{x}+{y}  win={win_w}x{init_h}  gif={args.size}  max_blocks={args.max_blocks}", file=sys.stderr)
    root.geometry(f"{win_w}x{init_h}+{x}+{y}")

    # Session blocks container (dynamic children)
    blocks_frame = tk.Frame(root, bd=0, highlightthickness=0, bg=BG)
    blocks_frame.pack(side="top", fill="x", padx=PAD, pady=(PAD, 0))

    # Usage line (separator-style)
    usage_bg = pal["chrome"].get("usage_bg", BG)
    usage_lbl = tk.Label(root, text="", fg=FG_DIM, bg=usage_bg,
                         font=("TkDefaultFont", font_size, "bold"),
                         anchor="w", padx=6, pady=2)
    usage_lbl.pack(side="top", fill="x", padx=PAD, pady=(2, 0))

    # GIF (Char) below
    gif_lbl = tk.Label(root, bd=0, highlightthickness=0, bg=BG)
    gif_lbl.pack(side="bottom", pady=(3, PAD))

    cur = {"img": None, "ts": 0, "frames": [], "durs": [], "idx": 0,
           "visible": True, "anim_job": None,
           "block_widgets": [],    # list of (Frame, Label) tuples
           "block_sig": None,      # signature of last-rendered session list
           "last_height": init_h,
           "anchor_right": anchor_right,
           "anchor_bottom": anchor_bottom,
           "fingerprint": fp,
           "primary": layout["primary"],
           "hidden_by_user": False,  # set by Hide menu, cleared on state change
           "hide_winner": None,      # (state, img) at time of hide
           "last_winner": None,
           "theme": theme_name,
           "skin": skin_name}

    def hide():
        if cur["anim_job"]:
            root.after_cancel(cur["anim_job"])
            cur["anim_job"] = None
        if cur["visible"]:
            root.withdraw()
            cur["visible"] = False

    def show():
        if not cur["visible"]:
            root.deiconify()
            cur["visible"] = True

    def animate():
        cur["idx"] = (cur["idx"] + 1) % len(cur["frames"])
        gif_lbl.configure(image=cur["frames"][cur["idx"]])
        cur["anim_job"] = root.after(cur["durs"][cur["idx"]], animate)

    def load(gif_bytes):
        pil_frames, durs = load_frames(gif_bytes, args.size)
        cur["frames"] = [ImageTk.PhotoImage(f) for f in pil_frames]
        cur["durs"] = durs
        cur["idx"] = 0
        if cur["anim_job"]:
            root.after_cancel(cur["anim_job"])
            cur["anim_job"] = None
        gif_lbl.configure(image=cur["frames"][0])
        if len(cur["frames"]) > 1:
            cur["anim_job"] = root.after(durs[0], animate)

    def resize_window(n_blocks):
        h = PAD + max(1, n_blocks) * (block_h + 2) + usage_h + args.size + 2 * PAD
        if h == cur["last_height"]:
            return
        # Anchor bottom-right: window grows upward, not downward.
        new_x = cur["anchor_right"] - win_w
        new_y = cur["anchor_bottom"] - h
        root.geometry(f"{win_w}x{h}+{new_x}+{new_y}")
        cur["last_height"] = h

    def render_sessions(sessions):
        # Cap + overflow marker. Sessions already PRIO-sorted from mock.
        shown = sessions[: args.max_blocks]
        overflow = max(0, len(sessions) - args.max_blocks)
        # Signature: per-session tuple. Ageless states (idle/done/start) drop
        # age from the sig (no rerender on tick); others use 30s buckets so
        # per-second changes don't trigger re-render. Plus overflow count.
        def _sig_entry(s):
            return (s["cwd"], s["state"]) if s["state"] in AGELESS_STATES \
                   else (s["cwd"], s["state"], s["age_s"] // 30)
        sig = tuple(_sig_entry(s) for s in shown) + (overflow,)
        if sig == cur["block_sig"]:
            return
        cur["block_sig"] = sig

        widgets = cur["block_widgets"]
        needed = len(shown) + (1 if overflow else 0)

        # Grow widget pool
        cursor = cur.get("cursor", "")
        while len(widgets) < needed:
            fr = tk.Frame(blocks_frame, bd=0, highlightthickness=0, bg=BG,
                          cursor=cursor)
            lbl = tk.Label(fr, text="", bg=BG, fg=FG_BRIGHT,
                           font=("TkDefaultFont", font_size, "bold"), anchor="w",
                           padx=6, pady=2, cursor=cursor)
            lbl.pack(fill="x")
            fr.pack(fill="x", pady=(0, 2))
            widgets.append((fr, lbl))

        # Shrink widget pool
        while len(widgets) > needed:
            fr, _ = widgets.pop()
            fr.destroy()

        # Update text + colors (per-skin/theme state palette)
        states_pal = palette_for(cur["skin"], cur["theme"])["states"]
        for i, sess in enumerate(shown):
            vis = states_pal.get(sess["state"], states_pal["idle"])
            _, lbl = widgets[i]
            lbl.configure(text=block_text(sess), bg=vis["bg"], fg=vis["fg"])
        if overflow:
            _, lbl = widgets[len(shown)]
            lbl.configure(text=f"  +{overflow} more", bg=BG, fg=FG_DIM)

        resize_window(needed)

    def update_dashboard(d):
        render_sessions(d.get("sessions") or [])
        pct = d.get("usage_5h_pct")
        usage_lbl.configure(text=usage_label(pct),
                            fg=usage_color(pct, cur["theme"]))

    def poll():
        # No periodic topmost/lift — WSLg interprets that as a focus-grab
        # signal. Visibility-driven lift below handles "obscured by other
        # window" without stealing focus.
        s = fetch_dashboard(args.mock)
        if s is None:
            root.after(POLL_MS * 4, poll)
            return
        # Detect external skin change (menu-driven or cube.sh from terminal).
        live_skin = read_skin()
        if live_skin != cur["skin"]:
            apply_palette(live_skin, cur["theme"])
        update_dashboard(s)
        if (s.get("img"), s.get("ts")) != (cur["img"], cur["ts"]):
            data = fetch_gif(args.mock)
            if data:
                load(data)
                cur["img"] = s.get("img")
                cur["ts"] = s.get("ts")
        winner = (s.get("state"), s.get("img"))
        cur["last_winner"] = winner
        # Auto-reopen: if user hid the overlay, watch for the winner to change.
        if cur["hidden_by_user"]:
            if winner != cur["hide_winner"]:
                cur["hidden_by_user"] = False
                show()
            # else stay hidden, keep polling
        else:
            show()
        root.after(POLL_MS, poll)

    # Idle no longer auto-hides; overlay stays visible as ambient display.
    # User-driven hide is via right-click menu (re-shows on next state change).

    def user_hide():
        cur["hidden_by_user"] = True
        cur["hide_winner"] = cur["last_winner"]
        hide()

    def menu_kwargs():
        """Chrome-derived kwargs for tk.Menu — keeps right-click menu visually
        consistent with the overlay's skin/theme instead of the system default."""
        pal = palette_for(cur["skin"], cur["theme"])
        return dict(
            bg=pal["chrome"]["bg"],
            fg=pal["chrome"]["fg_bright"],
            activebackground=pal["states"]["thinking"]["bg"],
            activeforeground=pal["states"]["thinking"]["fg"],
            bd=0,
        )

    def apply_palette(skin, theme):
        """Update chrome + state-block colors to the (skin, theme) palette."""
        global BG, FG_DIM, FG_BRIGHT
        pal = palette_for(skin, theme)
        BG = pal["chrome"]["bg"]
        FG_DIM = pal["chrome"]["fg_dim"]
        FG_BRIGHT = pal["chrome"]["fg_bright"]
        usage_bg = pal["chrome"].get("usage_bg", BG)
        root.configure(bg=BG)
        blocks_frame.configure(bg=BG)
        usage_lbl.configure(bg=usage_bg)
        gif_lbl.configure(bg=BG)
        cur["skin"] = skin
        cur["theme"] = theme
        # Force re-render so block bgs/fgs + overflow row pick up new palette.
        cur["block_sig"] = None
        # Re-theme menus (created later; cur["menus"] absent on initial run).
        for m in cur.get("menus") or ():
            try:
                m.configure(**menu_kwargs())
            except tk.TclError:
                pass

    def set_theme(name):
        apply_palette(cur["skin"], name)
        write_overlay_env({"CUBE_OVERLAY_THEME": name})

    def set_skin(name):
        cube = os.path.expanduser("~/.claude/bin/cube.sh")
        try:
            subprocess.run([cube, "skin", name], timeout=3, capture_output=True)
            # Force an immediate re-push of the current aggregated state under
            # the new skin so the GIF flips now, not at the next state change.
            subprocess.run([cube, "redisplay"], timeout=3, capture_output=True)
        except Exception:
            pass

    def restart_overlay():
        try:
            subprocess.Popen(["systemctl", "--user", "restart", SERVICE_NAME])
        except Exception:
            pass

    def reset_position():
        # Reset = bottom-right of the current layout's primary monitor.
        # CUBE_OVERLAY_RESET_R/_B env wins if set (deprecated, kept for one
        # release for users with custom home anchors in their config).
        px, py, pw, ph = cur["primary"]
        env_r = os.environ.get("CUBE_OVERLAY_RESET_R")
        env_b = os.environ.get("CUBE_OVERLAY_RESET_B")
        reset_r = int(env_r) if env_r else px + pw
        reset_b = int(env_b) if env_b else py + ph
        save_layout_anchor(cur["fingerprint"], reset_r, reset_b)
        restart_overlay()

    def set_size(w):
        # Anchor (bottom-right) is persistent across sizes — new window grows
        # up-and-left from the same corner. No X/Y to write here.
        write_overlay_env({"CUBE_OVERLAY_WIDTH": str(w), "CUBE_OVERLAY_SIZE": None})
        restart_overlay()

    # Tk variables for radiobutton sync
    theme_var = tk.StringVar(value=theme_name)
    skin_var = tk.StringVar(value=read_skin())
    size_var = tk.IntVar(value=win_w)
    lock_var = tk.BooleanVar(value=os.environ.get("CUBE_OVERLAY_POSITION_LOCKED", "1") == "1")

    def apply_cursor():
        c = "" if lock_var.get() else "fleur"
        cur["cursor"] = c
        for w in (root, blocks_frame, usage_lbl, gif_lbl):
            try:
                w.configure(cursor=c)
            except tk.TclError:
                pass
        for fr, lbl in cur["block_widgets"]:
            try:
                fr.configure(cursor=c)
                lbl.configure(cursor=c)
            except tk.TclError:
                pass

    def toggle_lock():
        write_overlay_env({"CUBE_OVERLAY_POSITION_LOCKED": "1" if lock_var.get() else "0"})
        apply_cursor()

    mk = menu_kwargs()
    menu = tk.Menu(root, tearoff=0, **mk)
    theme_m = tk.Menu(menu, tearoff=0, **mk)
    for t in ("dark", "light"):
        theme_m.add_radiobutton(label=t.capitalize(), variable=theme_var,
                                value=t, command=lambda n=t: set_theme(n))
    menu.add_cascade(label="Theme", menu=theme_m)
    skin_m = tk.Menu(menu, tearoff=0, **mk)
    for sk in SKIN_CHOICES:
        skin_m.add_radiobutton(label=sk, variable=skin_var, value=sk,
                               command=lambda n=sk: set_skin(n))
    menu.add_cascade(label="Skin", menu=skin_m)
    pos_m = tk.Menu(menu, tearoff=0, **mk)
    pos_m.add_checkbutton(label="Locked", variable=lock_var, command=toggle_lock)
    pos_m.add_command(label="Reset", command=reset_position)
    menu.add_cascade(label="Position", menu=pos_m)
    size_m = tk.Menu(menu, tearoff=0, **mk)
    for label, w in SIZE_PRESETS:
        size_m.add_radiobutton(label=f"{label} ({w}px)", variable=size_var,
                               value=w, command=lambda x=w: set_size(x))
    menu.add_cascade(label="Size", menu=size_m)
    menu.add_separator()
    menu.add_command(label="Hide", command=user_hide)
    menu.add_command(label="Quit", command=root.destroy)
    cur["menus"] = (menu, theme_m, skin_m, pos_m, size_m)

    def show_menu(ev):
        # Anchor the menu at the overlay's left edge so it grows rightward
        # into screen real-estate, not into the right-monitor void when the
        # overlay sits at the right edge.
        try:
            menu.tk_popup(root.winfo_rootx(), ev.y_root)
        finally:
            menu.grab_release()

    # Drag-to-reposition (only when not locked via menu)
    drag = {"active": False, "off_x": 0, "off_y": 0}

    def drag_start(ev):
        if lock_var.get():
            return
        # bind_all catches Button-1 on menu items too; skip those so clicking
        # Reset/Size/etc. doesn't engage the drag system + clobber the menu's
        # write in drag_end.
        try:
            if ev.widget.winfo_class() == "Menu":
                return
        except Exception:
            return
        drag["active"] = True
        drag["off_x"] = ev.x_root - root.winfo_rootx()
        drag["off_y"] = ev.y_root - root.winfo_rooty()

    def drag_motion(ev):
        if not drag["active"]:
            return
        new_x = ev.x_root - drag["off_x"]
        new_y = ev.y_root - drag["off_y"]
        root.geometry(f"{win_w}x{cur['last_height']}+{new_x}+{new_y}")

    def drag_end(_ev):
        if not drag["active"]:
            return
        drag["active"] = False
        new_x = root.winfo_rootx()
        new_y = root.winfo_rooty()
        # New anchor = current bottom-right corner. Persist per-layout so
        # other monitor setups keep their own positions.
        cur["anchor_right"] = new_x + win_w
        cur["anchor_bottom"] = new_y + cur["last_height"]
        try:
            save_layout_anchor(cur["fingerprint"],
                               cur["anchor_right"], cur["anchor_bottom"])
        except Exception:
            pass

    apply_cursor()

    root.bind_all("<Button-1>", drag_start)
    root.bind_all("<B1-Motion>", drag_motion)
    root.bind_all("<ButtonRelease-1>", drag_end)
    root.bind_all("<Button-3>", show_menu)
    root.bind("<Escape>", lambda _e: root.destroy())

    # On X11, when another window covers ours we get a VisibilityNotify with
    # state=VisibilityFullyObscured. lift() then raises us back without the
    # focus-grab that -topmost/wm_attributes trigger on WSLg.
    def _on_visibility(ev):
        try:
            state = str(ev.state)
        except Exception:
            return
        if "Obscured" in state:
            try:
                root.lift()
            except tk.TclError:
                pass
    root.bind("<Visibility>", _on_visibility)

    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
