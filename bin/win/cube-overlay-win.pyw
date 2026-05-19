#!/usr/bin/env python3
r"""cube-overlay-win — Windows-native variant of bin/cube-overlay.py.

Runs on Windows-host (CPython + Tk + Pillow) and polls mock-cube inside WSL via
the WSL-distro IP (resolved at startup with `wsl.exe hostname -I`). Avoids
WSLg's overrideredirect/topmost/focus-steal pain and the localhost-forwarding
race with Docker port binds — traffic goes WSL-IP-direct, never via 127.0.0.1.

Setup (one-time):
  1. Install Python 3.11+ for Windows (Microsoft Store or python.org).
  2. py -m pip install --user Pillow
  3. In WSL: set CUBE_MOCK_HOST=0.0.0.0 in ~/.config/cube/config, restart
     mock-cube  (`systemctl --user restart mock-cube.service`).
  4. Double-click bin/win/cube-overlay-win.pyw or run `py cube-overlay-win.pyw`
     from Windows-side cmd/PowerShell.

Per-machine config lives under %APPDATA%\cube\ (mirrors the WSL ~/.config/cube/
layout: overlay.env + overlay-layouts.json).

POC scope (see plan): read-only against mock-cube. Skin selection is server-
driven (whatever cube.sh in WSL has set); Theme/Position/Size still
local-mutable from the right-click menu. Skin changes are routed via
`/set?skin=NAME` on mock-cube, which proxies to `cube.sh skin NAME` +
`cube.sh redisplay` in WSL so the WSL source of truth (`~/.claude/.cube-skin`)
stays authoritative.
"""
import argparse
import ctypes
import io
import json
import os
import subprocess
import sys
import tkinter as tk
import urllib.request
from ctypes import wintypes

from PIL import Image, ImageSequence, ImageTk

POLL_MS = 500
PAD = 6

# Windows scaling: opt into per-monitor DPI awareness so Tk doesn't get
# bitmap-scaled (blurry) on >100% scaling. SetProcessDpiAwareness(2) =
# PROCESS_PER_MONITOR_DPI_AWARE. Falls back to SetProcessDPIAware on older
# Windows.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def size_metrics(win_w):
    if win_w < 160:
        return {"font": 8, "block_h": 18, "usage_h": 15}
    if win_w < 220:
        return {"font": 9, "block_h": 22, "usage_h": 18}
    return {"font": 11, "block_h": 28, "usage_h": 22}


CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "cube")
OVERLAY_ENV_PATH = os.path.join(CONFIG_DIR, "overlay.env")
LAYOUTS_PATH = os.path.join(CONFIG_DIR, "overlay-layouts.json")
WSL_IP_CACHE = {"ip": None, "ts": 0.0}
SIZE_PRESETS = (("Small", 140), ("Medium", 180), ("Large", 240))
SKIN_CHOICES = ("orb", "waifu")
THEME_NAMES = ("dark", "light")

# Palettes mirror bin/cube-overlay.py:54-120. Kept verbatim — when adding a
# new skin or theme, update both files in lockstep.
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


def palette_for(skin, theme):
    return SKIN_PALETTES.get(skin, SKIN_PALETTES["orb"]).get(theme,
           SKIN_PALETTES.get(skin, SKIN_PALETTES["orb"])["dark"])


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
    cur = read_overlay_env()
    for k, v in updates.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = str(v)
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = OVERLAY_ENV_PATH + ".tmp"
    with open(tmp, "w") as f:
        for k, v in cur.items():
            f.write(f"{k}={v}\n")
    os.replace(tmp, OVERLAY_ENV_PATH)


def resolve_wsl_ip(force=False):
    """Resolve the default WSL-distro's IP via `wsl.exe hostname -I`. Cached
    forever per process; on connection failure callers can pass force=True to
    re-resolve (covers `wsl --shutdown` mid-session — NAT-mode IPs drift)."""
    if not force and WSL_IP_CACHE["ip"]:
        return WSL_IP_CACHE["ip"]
    try:
        # CREATE_NO_WINDOW: keep the wsl.exe subprocess from popping a console
        # when launched via pythonw.exe (.pyw double-click).
        flags = 0x08000000 if os.name == "nt" else 0
        out = subprocess.run(["wsl.exe", "hostname", "-I"],
                             capture_output=True, text=True, timeout=3,
                             creationflags=flags)
        if out.returncode == 0 and out.stdout.strip():
            ip = out.stdout.strip().split()[0]
            WSL_IP_CACHE["ip"] = ip
            return ip
    except Exception as e:
        sys.stderr.write(f"resolve_wsl_ip failed: {e}\n")
    return None


def detect_layout_win():
    """Enumerate Windows monitors via user32.EnumDisplayMonitors. Mirrors the
    xrandr-based detect_layout() in bin/cube-overlay.py: returns
    {fingerprint, primary:(x,y,w,h), ok}. Fingerprint format matches the Linux
    side so overlay-layouts.json entries stay portable in principle."""
    user32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    MONITORINFOF_PRIMARY = 0x00000001
    # HMONITOR isn't on every wintypes vintage; fall back to HANDLE (both
    # are pointer-sized on the ABI level).
    HMONITOR = getattr(wintypes, "HMONITOR", wintypes.HANDLE)
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )
    mons = []
    primary = [None]

    def _cb(hmon, _hdc, _rect, _data):  # noqa: ARG001  callback signature
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
            return 1
        r = mi.rcMonitor
        x, y = r.left, r.top
        w, h = r.right - r.left, r.bottom - r.top
        is_primary = bool(mi.dwFlags & MONITORINFOF_PRIMARY)
        mons.append((x, y, w, h, is_primary))
        if is_primary:
            primary[0] = (x, y, w, h)
        return 1

    try:
        user32.EnumDisplayMonitors(0, None, MonitorEnumProc(_cb), 0)
    except Exception as e:
        sys.stderr.write(f"detect_layout_win failed: {e}\n")
        return None

    if not mons:
        return None
    if primary[0] is None:
        zero_off = [m for m in mons if m[0] == 0 and m[1] == 0]
        primary[0] = (zero_off[0] if zero_off else sorted(mons)[0])[:4]
    mons_sorted = sorted(mons, key=lambda m: (m[0], m[1]))
    fp = f"mon{len(mons)}:" + ",".join(
        f"{w}x{h}+{x}+{y}" for x, y, w, h, _ in mons_sorted
    )
    return {"fingerprint": fp, "primary": primary[0], "ok": True}


def detect_layout(sw, sh):
    res = detect_layout_win()
    if res:
        return res
    return {"fingerprint": f"fallback:{sw}x{sh}",
            "primary": (0, 0, sw, sh), "ok": False}


def load_layouts():
    try:
        with open(LAYOUTS_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_layout_anchor(fp, anchor_r, anchor_b):
    layouts = load_layouts()
    layouts[fp] = {"anchor_r": int(anchor_r), "anchor_b": int(anchor_b)}
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = LAYOUTS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(layouts, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, LAYOUTS_PATH)


AGELESS_STATES = {"idle", "done", "start"}


def block_text(sess):
    emoji = EMOJI.get(sess["state"], EMOJI["idle"])
    cwd = sess.get("cwd") or "—"
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
    env = read_overlay_env()
    default_port = env.get("CUBE_OVERLAY_PORT", os.environ.get("CUBE_OVERLAY_PORT", "8080"))
    default_mock = os.environ.get("CUBE_OVERLAY_MOCK") or env.get("CUBE_OVERLAY_MOCK")

    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", default=default_mock,
                    help="full URL override; if omitted, derived from wsl.exe hostname -I")
    ap.add_argument("--port", default=default_port,
                    help="mock-cube port on WSL (default 8080)")
    ap.add_argument("--margin", type=int, default=20)
    ap.add_argument("--size", type=int,
                    default=int(env.get("CUBE_OVERLAY_SIZE", 0)),
                    help="gif edge length; 0 = auto-fit to window width")
    ap.add_argument("--width", type=int,
                    default=int(env.get("CUBE_OVERLAY_WIDTH", 0)),
                    help="window width; 0 = derive from size + padding")
    ap.add_argument("--max-blocks", type=int,
                    default=int(env.get("CUBE_OVERLAY_MAX_BLOCKS", 5)))
    ap.add_argument("--frameless", action="store_true", default=True,
                    help="overrideredirect borderless (default on Windows)")
    ap.add_argument("--decorated", dest="frameless", action="store_false",
                    help="show window decorations (debug)")
    args = ap.parse_args()

    mock_url = args.mock
    if not mock_url:
        ip = resolve_wsl_ip()
        if not ip:
            sys.stderr.write("Could not resolve WSL IP via `wsl.exe hostname -I`. "
                             "Pass --mock http://<ip>:<port> explicitly.\n")
            sys.exit(2)
        mock_url = f"http://{ip}:{args.port}"

    win_w = args.width if args.width > 0 else max(180, (args.size or 100) + 2 * PAD)
    if args.size <= 0:
        args.size = win_w - 2 * PAD
    metrics = size_metrics(win_w)
    block_h = metrics["block_h"]
    usage_h = metrics["usage_h"]
    font_size = metrics["font"]

    # Skin is server-driven on Windows: comes from mock-cube /dashboard.json
    # ("skin" field). We track it locally for palette + change-detection.
    skin_name = "orb"
    theme_name = env.get("CUBE_OVERLAY_THEME", "dark")
    if theme_name not in THEME_NAMES:
        theme_name = "dark"
    pal = palette_for(skin_name, theme_name)
    global BG, FG_DIM, FG_BRIGHT
    BG = pal["chrome"]["bg"]
    FG_DIM = pal["chrome"]["fg_dim"]
    FG_BRIGHT = pal["chrome"]["fg_bright"]

    root = tk.Tk()
    root.title("cube-overlay-win")
    if args.frameless:
        root.overrideredirect(True)
    # Native Windows topmost: respected by the Win32 compositor without the
    # WSLg focus-steal side effect. No <Visibility> rebind needed.
    root.attributes("-topmost", True)
    root.configure(bg=BG)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    init_h = PAD + block_h + usage_h + args.size + 2 * PAD
    layout = detect_layout(sw, sh)
    fp = layout["fingerprint"]
    layouts = load_layouts()
    px, py, pw, ph = layout["primary"]

    def _in_bounds(r, b):
        # Windows multi-monitor: secondary monitors can sit at negative
        # offsets (mon to the left of primary). Use virtual desktop bounds.
        return r > -10_000 and b > -10_000 and r < 50_000 and b < 50_000

    anchor_source = "cache"
    if fp in layouts and _in_bounds(layouts[fp].get("anchor_r", 0),
                                    layouts[fp].get("anchor_b", 0)):
        anchor_right = int(layouts[fp]["anchor_r"])
        anchor_bottom = int(layouts[fp]["anchor_b"])
    else:
        anchor_right = px + pw // 2 + win_w // 2
        anchor_bottom = py + ph // 2 + init_h // 2
        anchor_source = "center"
        save_layout_anchor(fp, anchor_right, anchor_bottom)

    x = anchor_right - win_w
    y = anchor_bottom - init_h
    sys.stderr.write(
        f"mock={mock_url}  layout={fp}  source={anchor_source}  "
        f"primary={px},{py},{pw}x{ph}  anchor=br({anchor_right},{anchor_bottom})  "
        f"pos=+{x}+{y}  win={win_w}x{init_h}  gif={args.size}  max_blocks={args.max_blocks}\n"
    )
    root.geometry(f"{win_w}x{init_h}+{x}+{y}")

    blocks_frame = tk.Frame(root, bd=0, highlightthickness=0, bg=BG)
    blocks_frame.pack(side="top", fill="x", padx=PAD, pady=(PAD, 0))

    usage_bg = pal["chrome"].get("usage_bg", BG)
    usage_lbl = tk.Label(root, text="", fg=FG_DIM, bg=usage_bg,
                         font=("TkDefaultFont", font_size, "bold"),
                         anchor="w", padx=6, pady=2)
    usage_lbl.pack(side="top", fill="x", padx=PAD, pady=(2, 0))

    gif_lbl = tk.Label(root, bd=0, highlightthickness=0, bg=BG)
    gif_lbl.pack(side="bottom", pady=(3, PAD))

    cur = {"img": None, "ts": 0, "frames": [], "durs": [], "idx": 0,
           "visible": True, "anim_job": None,
           "block_widgets": [],
           "block_sig": None,
           "last_height": init_h,
           "anchor_right": anchor_right,
           "anchor_bottom": anchor_bottom,
           "fingerprint": fp,
           "primary": layout["primary"],
           "hidden_by_user": False,
           "hide_winner": None,
           "last_winner": None,
           "theme": theme_name,
           "skin": skin_name,
           "mock": mock_url,
           "consecutive_failures": 0}

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
        # gif_lbl's reqheight is 1 until an image is bound. Resize once after
        # first load so the window grows to fit the GIF instead of cropping
        # the top/bottom edges.
        resize_window(0)
        if len(cur["frames"]) > 1:
            cur["anim_job"] = root.after(durs[0], animate)

    def resize_window(_n_blocks):
        # Tk-true height: Windows-Tk font rendering at DPI-aware scale doesn't
        # match the WSLg formula (PAD + n*(block_h+2) + usage_h + size + 2*PAD)
        # well — the static estimate undercounts and the GIF gets clipped.
        # Let Tk compute the actual required height after widget repacks.
        root.update_idletasks()
        h = root.winfo_reqheight()
        if h <= 1 or h == cur["last_height"]:
            return
        new_x = cur["anchor_right"] - win_w
        new_y = cur["anchor_bottom"] - h
        root.geometry(f"{win_w}x{h}+{new_x}+{new_y}")
        cur["last_height"] = h

    def render_sessions(sessions):
        shown = sessions[: args.max_blocks]
        overflow = max(0, len(sessions) - args.max_blocks)

        def _sig_entry(s):
            return (s["cwd"], s["state"]) if s["state"] in AGELESS_STATES \
                   else (s["cwd"], s["state"], s["age_s"] // 30)
        sig = tuple(_sig_entry(s) for s in shown) + (overflow,)
        if sig == cur["block_sig"]:
            return
        cur["block_sig"] = sig

        widgets = cur["block_widgets"]
        needed = len(shown) + (1 if overflow else 0)

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

        while len(widgets) > needed:
            fr, _ = widgets.pop()
            fr.destroy()

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
        s = fetch_dashboard(cur["mock"])
        if s is None:
            cur["consecutive_failures"] += 1
            # After 3 consecutive misses, the WSL IP may have drifted
            # (NAT-mode reassigns on `wsl --shutdown`). Re-resolve and
            # rebuild the mock URL.
            if cur["consecutive_failures"] == 3 and not args.mock:
                new_ip = resolve_wsl_ip(force=True)
                if new_ip:
                    new_url = f"http://{new_ip}:{args.port}"
                    if new_url != cur["mock"]:
                        sys.stderr.write(f"wsl-ip drift: {cur['mock']} -> {new_url}\n")
                        cur["mock"] = new_url
            root.after(POLL_MS * 4, poll)
            return
        cur["consecutive_failures"] = 0
        # Skin from mock (server-driven). cube.sh in WSL is the source of
        # truth; this overlay observes it.
        live_skin = s.get("skin") or "orb"
        if live_skin != cur["skin"]:
            apply_palette(live_skin, cur["theme"])
        update_dashboard(s)
        if (s.get("img"), s.get("ts")) != (cur["img"], cur["ts"]):
            data = fetch_gif(cur["mock"])
            if data:
                load(data)
                cur["img"] = s.get("img")
                cur["ts"] = s.get("ts")
        winner = (s.get("state"), s.get("img"))
        cur["last_winner"] = winner
        if cur["hidden_by_user"]:
            if winner != cur["hide_winner"]:
                cur["hidden_by_user"] = False
                show()
        else:
            show()
        root.after(POLL_MS, poll)

    def user_hide():
        cur["hidden_by_user"] = True
        cur["hide_winner"] = cur["last_winner"]
        hide()

    def menu_kwargs():
        pal = palette_for(cur["skin"], cur["theme"])
        return dict(
            bg=pal["chrome"]["bg"],
            fg=pal["chrome"]["fg_bright"],
            activebackground=pal["states"]["thinking"]["bg"],
            activeforeground=pal["states"]["thinking"]["fg"],
            bd=0,
        )

    def apply_palette(skin, theme):
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
        cur["block_sig"] = None
        for m in cur.get("menus") or ():
            try:
                m.configure(**menu_kwargs())
            except tk.TclError:
                pass
        # Sync skin radiobutton with server-driven changes (CLI cube.sh skin
        # …, or another overlay's menu click). NameError-guarded because
        # apply_palette can fire from poll() before skin_var exists during
        # very early init.
        try:
            skin_var.set(skin)
        except NameError:
            pass

    def set_theme(name):
        apply_palette(cur["skin"], name)
        write_overlay_env({"CUBE_OVERLAY_THEME": name})

    def set_skin(name):
        # Route through mock-cube's /set?skin=NAME — mock-cube proxies to
        # cube.sh skin + redisplay in WSL. The redisplay push updates
        # STATE.img server-side; the next poll cycle picks up the new skin
        # and re-applies the palette automatically.
        try:
            urllib.request.urlopen(f"{cur['mock']}/set?skin={name}", timeout=2).read()
        except Exception as e:
            sys.stderr.write(f"set_skin({name}) failed: {e}\n")

    def restart_overlay():
        # pythonw.exe (for .pyw) doesn't open a console; DETACHED_PROCESS
        # ensures the new instance survives the current's destroy().
        flags = 0x00000008 if os.name == "nt" else 0  # DETACHED_PROCESS
        try:
            subprocess.Popen([sys.executable] + sys.argv,
                             creationflags=flags, close_fds=True)
        except Exception as e:
            sys.stderr.write(f"restart failed: {e}\n")
            return
        root.after(150, root.destroy)

    def reset_position():
        px, py, pw, ph = cur["primary"]
        save_layout_anchor(cur["fingerprint"], px + pw, py + ph)
        restart_overlay()

    def set_size(w):
        write_overlay_env({"CUBE_OVERLAY_WIDTH": str(w), "CUBE_OVERLAY_SIZE": None})
        restart_overlay()

    theme_var = tk.StringVar(value=theme_name)
    skin_var = tk.StringVar(value=cur["skin"])
    size_var = tk.IntVar(value=win_w)
    lock_var = tk.BooleanVar(value=env.get("CUBE_OVERLAY_POSITION_LOCKED", "1") == "1")

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
        try:
            menu.tk_popup(root.winfo_rootx(), ev.y_root)
        finally:
            menu.grab_release()

    drag = {"active": False, "off_x": 0, "off_y": 0}

    def drag_start(ev):
        if lock_var.get():
            return
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

    # One-shot height refine after Tk lays out the empty widgets — covers the
    # gap before the first GIF arrives so the window doesn't open with a
    # visibly cropped GIF row.
    root.after_idle(lambda: resize_window(0))
    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
