#!/usr/bin/env python3
r"""cube-overlay-win — Mochi Classic, Windows-native variant.

Runs on Windows-host (CPython + Tk + Pillow) and polls mock-cube inside
WSL via the WSL-distro IP (resolved at startup with `wsl.exe hostname -I`).
Avoids WSLg's overrideredirect/topmost/focus-steal pain and the localhost-
forwarding race with Docker port binds — traffic goes WSL-IP-direct.

Visual system (Mochi Classic):
  - Matte card surface (skin × theme palette). Outer corners square; the
    GIF gets rounded corners via Pillow alpha-mask composited against the
    card colour.
  - Sessions: small coloured dot (state) · cwd (truncated) · meta.
    Meta = age for live states, state label for ageless.
  - Usage bar: tk.Canvas, colour shifts at 50/80%.
  - No emoji — the entire seguiemj.ttf + PIL color-emoji renderer the
    previous overlay needed is gone. Mochi encodes state via the dot only.

Setup (one-time):
  1. Install Python 3.11+ for Windows.
  2. py -m pip install --user Pillow
  3. In WSL: set CUBE_MOCK_HOST=0.0.0.0 in ~/.config/cube/config, restart
     mock-cube  (`systemctl --user restart mock-cube.service`).
  4. Double-click bin/win/cube-overlay-win.pyw.

Per-machine config lives under %APPDATA%\cube\.

Skin is server-driven on Windows (whatever cube.sh in WSL has set);
Theme/Position/Size/Topmost still local-mutable via right-click menu.
Skin changes are routed via `/set?skin=NAME` on mock-cube, which proxies
to `cube.sh skin NAME` + `cube.sh redisplay` in WSL.
"""
import argparse
import ctypes
import io
import json
import math
import os
import subprocess
import sys
import tkinter as tk
import traceback
import urllib.request
from ctypes import wintypes

# pythonw.exe (.pyw startup) has no console — wire stderr to a log file
# early so silent startup crashes are debuggable.
if os.name == "nt":
    try:
        _log_path = os.path.join(
            os.environ.get("TEMP", os.path.expanduser("~")),
            "cube-overlay-win.log")
        sys.stderr = open(_log_path, "a", buffering=1, encoding="utf-8",
                          errors="replace")
        sys.stderr.write(f"\n--- start pid={os.getpid()} exe={sys.executable} ---\n")
        sys.stderr.write(f"argv={sys.argv}\n")

        def _excepthook(typ, val, tb):
            traceback.print_exception(typ, val, tb, file=sys.stderr)
            sys.stderr.flush()
        sys.excepthook = _excepthook
    except Exception:
        pass

from PIL import Image, ImageDraw, ImageFilter, ImageSequence, ImageTk

POLL_MS = 500
WINDOW_CORNER_RADIUS = 22  # outer card radius; matches Mochi gif_radius scale


def apply_round_corners(hwnd, w, h, r=WINDOW_CORNER_RADIUS):
    """Clip frameless Tk window outline to a rounded rect via SetWindowRgn.

    DWMWA_WINDOW_CORNER_PREFERENCE doesn't apply to overrideredirect windows
    (no non-client area for DWM to round). SetWindowRgn shapes the actual
    window region — corners are mildly aliased but match the Mochi card."""
    if os.name != "nt" or not hwnd:
        return
    try:
        gdi32 = ctypes.windll.gdi32
        user32 = ctypes.windll.user32
        # CreateRoundRectRgn: bottom/right are exclusive, so +1.
        rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        user32.SetWindowRgn(hwnd, rgn, True)  # OS owns rgn after this call
    except Exception as e:
        sys.stderr.write(f"apply_round_corners failed: {e}\n")

# Per-monitor DPI awareness so Tk doesn't get bitmap-scaled (blurry) on
# >100% scaling.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


# ─────────────────────────────────────────────────────────────────────────
# Dot rendering — PIL-rasterized AA dots with Gaussian glow halo.
# Replaces tk.Canvas.create_oval (no AA, no alpha). Active states pulse
# the halo alpha; idle/done/start render once at a fixed intensity.
# ─────────────────────────────────────────────────────────────────────────
DOT_FRAMES = 14                       # cycle length
DOT_TICK_MS = 70                      # ~14*70ms ≈ 1s breathing period
PULSE_STATES = {"permission", "error", "compact", "alert", "thinking"}
STATIC_PHASE = 0.55                   # idle/done/start glow level


def _dot_phase(i):
    """Sine-eased phase 0.3..1.0. Never zero — dots stay readable."""
    s = (math.sin(2 * math.pi * i / DOT_FRAMES - math.pi / 2) + 1) / 2
    return 0.3 + 0.7 * s


def render_dot(color_hex, render_px, phase, card_hex):
    """Flat-RGB dot with AA core + soft halo, baked on card-coloured bg.

    Returns RGB (no alpha). The dot's edges blend into the card color
    inside the PIL image itself, so Tk just blits — no straight-alpha
    composite at the widget layer, no LANCZOS-edge grey fringe.

    Pulse modulates BOTH halo alpha (40..255) and halo radius
    (0.20..0.28 of size). On dark themes the radius motion is the
    primary visual cue because alpha differences read smaller against
    low-luminance bg."""
    scale = 4
    W = render_px * scale
    cr, cg, cb = _hex_to_rgb(color_hex)
    bg = _hex_to_rgb(card_hex)
    cx = cy = W // 2
    # Core breathes too — small but perceptible heartbeat. Dark themes
    # rely on this more than alpha (alpha contrast against dark bg
    # reads weaker perceptually).
    core_r = int(W * (0.13 + 0.06 * phase))
    halo_r = int(W * (0.20 + 0.10 * phase))
    blur_r = int(W * 0.08)
    halo_alpha = int(25 + 230 * phase)
    base = Image.new("RGBA", (W, W), bg + (255,))
    halo = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(halo).ellipse(
        (cx - halo_r, cy - halo_r, cx + halo_r, cy + halo_r),
        fill=(cr, cg, cb, halo_alpha))
    halo = halo.filter(ImageFilter.GaussianBlur(radius=blur_r))
    base = Image.alpha_composite(base, halo)
    ImageDraw.Draw(base).ellipse(
        (cx - core_r, cy - core_r, cx + core_r, cy + core_r),
        fill=(cr, cg, cb, 255))
    return base.convert("RGB").resize((render_px, render_px), Image.LANCZOS)


CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "cube")
OVERLAY_ENV_PATH = os.path.join(CONFIG_DIR, "overlay.env")
LAYOUTS_PATH = os.path.join(CONFIG_DIR, "overlay-layouts.json")
WSL_IP_CACHE = {"ip": None, "ts": 0.0}
SIZE_PRESETS = (("Small", 140), ("Medium", 180), ("Large", 240))
SKIN_CHOICES = ("orb", "waifu")
THEME_NAMES = ("light", "dark")

# ─────────────────────────────────────────────────────────────────────────
# Mochi palette — keep in lockstep with bin/cube-overlay.py:MOCHI_PALETTE.
# When changing one, change both.
# ─────────────────────────────────────────────────────────────────────────
MOCHI_PALETTE = {
    "waifu": {
        "light": {
            "card":      "#fbe9f1",
            "text":      "#4a1834",
            "meta":      "#7a4866",
            "meta_dim":  "#a88898",
            "brand":     "#a8326a",
            "brand_dim": "#b88098",
            "divider":   "#f2d0e0",
            "bar_track": "#f2d0e0",
            "bar_fill":  "#ff5ba1",
            "usage_fg":  "#8a2862",
            "dots": {
                "permission": "#ff4a96", "thinking":   "#a875e0",
                "done":       "#5fa83f", "idle":       "#bd9fb1",
                "error":      "#ff5a72", "compact":    "#c060d8",
                "alert":      "#ff8c4a", "start":      "#7a8cff",
            },
        },
        "dark": {
            "card":      "#2a1226",
            "text":      "#ffe5f2",
            "meta":      "#d99eba",
            "meta_dim":  "#9e7088",
            "brand":     "#ff8ec8",
            "brand_dim": "#a86b88",
            "divider":   "#4a1834",
            "bar_track": "#3a0f28",
            "bar_fill":  "#ff5ba1",
            "usage_fg":  "#ff8ec8",
            "dots": {
                "permission": "#ff5ba1", "thinking":   "#c08cf0",
                "done":       "#7fce5a", "idle":       "#a08090",
                "error":      "#ff7088", "compact":    "#d078e8",
                "alert":      "#ffa060", "start":      "#9aa8ff",
            },
        },
    },
    "orb": {
        "light": {
            "card":      "#ece3f5",
            "text":      "#311566",
            "meta":      "#5a4a88",
            "meta_dim":  "#8a7eb0",
            "brand":     "#5a3aa8",
            "brand_dim": "#8472c0",
            "divider":   "#dcd0ec",
            "bar_track": "#dcd0ec",
            "bar_fill":  "#7458d6",
            "usage_fg":  "#4b2a96",
            "dots": {
                "permission": "#ff5ba1", "thinking":   "#7458d6",
                "done":       "#5fa83f", "idle":       "#8e7fb8",
                "error":      "#ff5a72", "compact":    "#a04ed8",
                "alert":      "#ff8c4a", "start":      "#5870e0",
            },
        },
        "dark": {
            "card":      "#1c1535",
            "text":      "#ebe3ff",
            "meta":      "#a89dd0",
            "meta_dim":  "#7a6ea0",
            "brand":     "#b59cff",
            "brand_dim": "#7e6cad",
            "divider":   "#2a1d4d",
            "bar_track": "#231642",
            "bar_fill":  "#9b85ff",
            "usage_fg":  "#b59cff",
            "dots": {
                "permission": "#ff7eb8", "thinking":   "#9b85ff",
                "done":       "#7fce5a", "idle":       "#8e7fb8",
                "error":      "#ff7088", "compact":    "#b890ee",
                "alert":      "#ffa060", "start":      "#7e90ff",
            },
        },
    },
}

AGELESS_STATES = {"idle", "done", "start"}
STATE_LABELS = {
    "idle": "idle", "done": "done", "start": "start",
    "permission": "wait", "thinking": "think",
    "error": "error", "compact": "compact", "alert": "alert",
}


def palette_for(skin, theme):
    return MOCHI_PALETTE.get(skin, MOCHI_PALETTE["orb"]).get(
        theme, MOCHI_PALETTE.get(skin, MOCHI_PALETTE["orb"])["light"])


def size_metrics(win_w):
    """Mochi proportions per window width."""
    if win_w < 160:
        return {"font": 10, "brand": 8,  "row_pad": 2,
                "dot": 7,  "bar": 6, "pad": 10, "gap": 6,
                "gif_radius": 10}
    if win_w < 220:
        return {"font": 12, "brand": 9,  "row_pad": 3,
                "dot": 8,  "bar": 7, "pad": 12, "gap": 7,
                "gif_radius": 14}
    return         {"font": 13, "brand": 10, "row_pad": 4,
                    "dot": 9,  "bar": 8, "pad": 14, "gap": 8,
                    "gif_radius": 18}


def format_age(s):
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h" if m == 0 else f"{h}h{m}m"


# ─────────────────────────────────────────────────────────────────────────
# Config files
# ─────────────────────────────────────────────────────────────────────────
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
    """`wsl.exe hostname -I`. Cached forever per process; force=True
    re-resolves (NAT-mode IPs drift on `wsl --shutdown`)."""
    if not force and WSL_IP_CACHE["ip"]:
        return WSL_IP_CACHE["ip"]
    try:
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
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
    """user32.EnumDisplayMonitors → {fingerprint, primary:(x,y,w,h), ok}."""
    user32 = ctypes.windll.user32

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    MONITORINFOF_PRIMARY = 0x00000001
    HMONITOR = getattr(wintypes, "HMONITOR", wintypes.HANDLE)
    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )
    mons = []
    primary = [None]

    def _cb(hmon, _hdc, _rect, _data):  # noqa: ARG001
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


# ─────────────────────────────────────────────────────────────────────────
# Mock-cube fetch
# ─────────────────────────────────────────────────────────────────────────
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


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def load_frames(gif_bytes, size, radius, bg_hex):
    """GIF → rounded-rect-masked PhotoImage frames. The mask is composited
    against the card colour so corners read as 'cut' against the matte
    surface (not framed against the desktop)."""
    img = Image.open(io.BytesIO(gif_bytes))
    frames, durations = [], []
    bg_rgb = _hex_to_rgb(bg_hex)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size, size), radius=radius, fill=255)

    for f in ImageSequence.Iterator(img):
        rgba = f.convert("RGBA")
        if rgba.size != (size, size):
            rgba = rgba.resize((size, size), Image.LANCZOS)
        bg = Image.new("RGBA", (size, size), bg_rgb + (255,))
        bg.paste(rgba, (0, 0), rgba)
        bg.putalpha(mask)
        frames.append(bg)
        durations.append(max(20, f.info.get("duration", 100)))
    return frames, durations


def usage_fill(pct, pal):
    if pct is None:
        return pal["bar_track"]
    if pct >= 80:
        return "#e85555"
    if pct >= 50:
        return "#d7a04a"
    return pal["bar_fill"]


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────
def main():
    env = read_overlay_env()
    default_port = env.get("CUBE_OVERLAY_PORT", os.environ.get("CUBE_OVERLAY_PORT", "8080"))
    default_mock = os.environ.get("CUBE_OVERLAY_MOCK") or env.get("CUBE_OVERLAY_MOCK")

    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", default=default_mock,
                    help="full URL override; if omitted, derived from wsl.exe hostname -I")
    ap.add_argument("--port", default=default_port)
    ap.add_argument("--margin", type=int, default=20)
    ap.add_argument("--size", type=int,
                    default=int(env.get("CUBE_OVERLAY_SIZE", 0)),
                    help="gif edge length; 0 = auto-fit")
    ap.add_argument("--width", type=int,
                    default=int(env.get("CUBE_OVERLAY_WIDTH", 0)))
    ap.add_argument("--max-blocks", type=int,
                    default=int(env.get("CUBE_OVERLAY_MAX_BLOCKS", 5)))
    ap.add_argument("--frameless", action="store_true", default=True)
    ap.add_argument("--decorated", dest="frameless", action="store_false")
    args = ap.parse_args()

    mock_url = args.mock
    if not mock_url:
        ip = resolve_wsl_ip()
        if not ip:
            sys.stderr.write("Could not resolve WSL IP via `wsl.exe hostname -I`. "
                             "Pass --mock http://<ip>:<port> explicitly.\n")
            sys.exit(2)
        mock_url = f"http://{ip}:{args.port}"

    win_w = args.width if args.width > 0 else 180
    metrics = size_metrics(win_w)
    if args.size <= 0:
        args.size = win_w - 2 * metrics["pad"]

    skin_name = "orb"  # server-driven, will update on first poll
    theme_name = env.get("CUBE_OVERLAY_THEME", "light")
    if theme_name not in THEME_NAMES:
        theme_name = "light"
    pal = palette_for(skin_name, theme_name)

    root = tk.Tk()
    root.title("cube-overlay-win")
    if args.frameless:
        root.overrideredirect(True)
    topmost_default = env.get("CUBE_OVERLAY_TOPMOST", "1") == "1"
    lift_activity_default = env.get("CUBE_OVERLAY_LIFT_ON_ACTIVITY", "0") == "1"
    root.attributes("-topmost", topmost_default)
    root.configure(bg=pal["card"])

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    init_h = (metrics["pad"] + 16 +
              4 * (metrics["font"] + 2 * metrics["row_pad"] + 2) +
              6 + metrics["font"] + 6 + 8 + args.size + metrics["pad"])

    layout = detect_layout(sw, sh)
    fp = layout["fingerprint"]
    layouts = load_layouts()
    px, py, pw, ph = layout["primary"]

    def _in_bounds(r, b):
        # Windows multi-monitor: secondary monitors can sit at negative
        # offsets. Use generous virtual-desktop bounds.
        return r > -10_000 and b > -10_000 and r < 50_000 and b < 50_000

    if fp in layouts and _in_bounds(layouts[fp].get("anchor_r", 0),
                                    layouts[fp].get("anchor_b", 0)):
        anchor_right = int(layouts[fp]["anchor_r"])
        anchor_bottom = int(layouts[fp]["anchor_b"])
    else:
        anchor_right = px + pw // 2 + win_w // 2
        anchor_bottom = py + ph // 2 + init_h // 2
        save_layout_anchor(fp, anchor_right, anchor_bottom)

    x = anchor_right - win_w
    y = anchor_bottom - init_h
    sys.stderr.write(
        f"mock={mock_url}  layout={fp}  primary={px},{py},{pw}x{ph}  "
        f"anchor=br({anchor_right},{anchor_bottom})  pos=+{x}+{y}  "
        f"win={win_w}x{init_h}  gif={args.size}\n"
    )
    root.geometry(f"{win_w}x{init_h}+{x}+{y}")

    # ── Shell ───────────────────────────────────────────────────────
    PAD = metrics["pad"]
    shell = tk.Frame(root, bd=0, highlightthickness=0, bg=pal["card"])
    shell.pack(fill="both", expand=True, padx=PAD, pady=PAD)

    brand_frame = tk.Frame(shell, bg=pal["card"], bd=0, highlightthickness=0)
    brand_frame.pack(fill="x", pady=(0, 6))
    brand_lbl = tk.Label(brand_frame, text="CUBE", bg=pal["card"],
                         fg=pal["brand"],
                         font=("Segoe UI Semibold", metrics["brand"], "bold"),
                         anchor="w")
    brand_lbl.pack(side="left")
    sess_lbl = tk.Label(brand_frame, text="0", bg=pal["card"],
                        fg=pal["brand_dim"],
                        font=("Segoe UI Semibold", metrics["brand"], "bold"),
                        anchor="e")
    sess_lbl.pack(side="right")

    blocks_frame = tk.Frame(shell, bg=pal["card"], bd=0, highlightthickness=0)
    blocks_frame.pack(fill="x")

    divider = tk.Frame(shell, bg=pal["divider"], height=1, bd=0,
                       highlightthickness=0)
    divider.pack(fill="x", pady=(5, 4))

    usage_frame = tk.Frame(shell, bg=pal["card"], bd=0, highlightthickness=0)
    usage_frame.pack(fill="x")
    usage_lbl = tk.Label(usage_frame, text="USE —", bg=pal["card"],
                         fg=pal["usage_fg"],
                         font=("Segoe UI Semibold", metrics["brand"], "bold"),
                         anchor="w")
    usage_lbl.pack(side="left")
    usage_pct_lbl = tk.Label(usage_frame, text="", bg=pal["card"],
                             fg=pal["usage_fg"],
                             font=("Segoe UI Semibold", metrics["brand"], "bold"),
                             anchor="e")
    usage_pct_lbl.pack(side="right")
    bar_canvas = tk.Canvas(shell, height=metrics["bar"], bd=0,
                           highlightthickness=0, bg=pal["card"])
    bar_canvas.pack(fill="x", pady=(2, 0))

    gif_lbl = tk.Label(shell, bd=0, highlightthickness=0, bg=pal["card"])
    gif_lbl.pack(side="bottom", pady=(8, 0))

    cur = {
        "img": None, "ts": 0, "frames": [], "durs": [], "idx": 0,
        "visible": True, "anim_job": None,
        "block_widgets": [], "block_sig": None,
        "last_height": init_h,
        "anchor_right": anchor_right, "anchor_bottom": anchor_bottom,
        "fingerprint": fp, "primary": layout["primary"],
        "hidden_by_user": False, "hide_winner": None, "last_winner": None,
        "theme": theme_name, "skin": skin_name,
        "mock": mock_url, "consecutive_failures": 0,
        "win_w": win_w, "gif_size": args.size, "metrics": metrics,
        "last_gif_bytes": None,
        "dot_cache": {}, "dot_phase": 0, "dot_tick_job": None,
    }

    def dot_render_px():
        # Keep slim — wider canvas eats from the cwd label column.
        # +8 gives enough head-room for the halo's alpha fade without
        # square-fringe leakage at the bounding box.
        return max(14, cur["metrics"]["dot"] + 8)

    def get_dot_image(color_hex, phase_idx):
        """Cached PhotoImage for (color, phase, size, card_bg). Card bg
        is in the key because the dot is rasterised onto an opaque card
        background — palette swap invalidates."""
        p = palette_for(cur["skin"], cur["theme"])
        rpx = dot_render_px()
        key = (color_hex, phase_idx, rpx, p["card"])
        img = cur["dot_cache"].get(key)
        if img is None:
            phase = _dot_phase(phase_idx)
            pil = render_dot(color_hex, rpx, phase, p["card"])
            img = ImageTk.PhotoImage(pil)
            cur["dot_cache"][key] = img
        return img

    # ── GIF ─────────────────────────────────────────────────────────
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
        p = palette_for(cur["skin"], cur["theme"])
        pil_frames, durs = load_frames(
            gif_bytes, cur["gif_size"],
            radius=cur["metrics"]["gif_radius"],
            bg_hex=p["card"])
        cur["frames"] = [ImageTk.PhotoImage(f) for f in pil_frames]
        cur["durs"] = durs
        cur["idx"] = 0
        if cur["anim_job"]:
            root.after_cancel(cur["anim_job"])
            cur["anim_job"] = None
        gif_lbl.configure(image=cur["frames"][0])
        resize_window()
        if len(cur["frames"]) > 1:
            cur["anim_job"] = root.after(durs[0], animate)

    def resize_window():
        # Let Tk compute actual required height; Windows-Tk font metrics at
        # DPI-aware scale don't match a hand-rolled formula.
        root.update_idletasks()
        h = root.winfo_reqheight()
        if h <= 1 or h == cur["last_height"]:
            return
        new_x = cur["anchor_right"] - cur["win_w"]
        new_y = cur["anchor_bottom"] - h
        root.geometry(f"{cur['win_w']}x{h}+{new_x}+{new_y}")
        cur["last_height"] = h
        # Re-clip outline to new bounds — region is in window coords, must
        # follow every geometry change or corners get cut off.
        root.update_idletasks()
        apply_round_corners(root.winfo_id(), cur["win_w"], h)

    # ── Sessions ────────────────────────────────────────────────────
    def _ensure_row(i):
        if i < len(cur["block_widgets"]):
            return cur["block_widgets"][i]
        p = palette_for(cur["skin"], cur["theme"])
        m = cur["metrics"]
        row = tk.Frame(blocks_frame, bg=p["card"], bd=0,
                       highlightthickness=0, cursor=cur.get("cursor", ""))
        row.grid_columnconfigure(1, weight=1)
        # Label (vs Canvas) so the widget sizes to the PhotoImage exactly
        # — no canvas-bg ring around the dot raster, which was reading as
        # a faint grey halo when Tk's chrome bg didn't match the baked
        # card colour byte-for-byte under DPI scaling.
        init_img = get_dot_image(p["dots"]["idle"], 0)
        dot_lbl = tk.Label(row, image=init_img, bg=p["card"], bd=0,
                           highlightthickness=0,
                           cursor=cur.get("cursor", ""))
        dot_lbl.image = init_img  # keep ref alive
        dot_lbl.grid(row=0, column=0, padx=(0, m["gap"]))
        cwd = tk.Label(row, text="", bg=p["card"], fg=p["text"],
                       font=("Segoe UI Semibold", m["font"], "bold"),
                       anchor="w", cursor=cur.get("cursor", ""))
        cwd.grid(row=0, column=1, sticky="ew")
        meta = tk.Label(row, text="", bg=p["card"], fg=p["meta"],
                        font=("Segoe UI Semibold",
                              max(8, m["font"] - 2), "bold"),
                        anchor="e", cursor=cur.get("cursor", ""))
        meta.grid(row=0, column=2, padx=(m["gap"], 0))
        row.pack(fill="x", pady=(m["row_pad"], m["row_pad"]))
        w = {"frame": row, "dot": dot_lbl,
             "cwd": cwd, "meta": meta,
             "dot_color": p["dots"]["idle"], "dot_state": "idle"}
        cur["block_widgets"].append(w)
        return w

    def _shrink_rows(needed):
        while len(cur["block_widgets"]) > needed:
            w = cur["block_widgets"].pop()
            w["frame"].destroy()

    def render_sessions(sessions):
        shown = sessions[: args.max_blocks]
        overflow = max(0, len(sessions) - args.max_blocks)

        def _sig(s):
            return (s["cwd"], s["state"]) if s["state"] in AGELESS_STATES \
                   else (s["cwd"], s["state"], s["age_s"] // 30)
        sig = tuple(_sig(s) for s in shown) + (overflow,)
        if sig == cur["block_sig"]:
            return
        cur["block_sig"] = sig

        p = palette_for(cur["skin"], cur["theme"])
        needed = len(shown) + (1 if overflow else 0)
        _shrink_rows(needed)

        for i, s in enumerate(shown):
            w = _ensure_row(i)
            dot_col = p["dots"].get(s["state"], p["dots"]["idle"])
            w["dot_color"] = dot_col
            w["dot_state"] = s["state"]
            phase = cur["dot_phase"] if s["state"] in PULSE_STATES \
                    else int(STATIC_PHASE * DOT_FRAMES)
            img = get_dot_image(dot_col, phase)
            w["dot"].configure(image=img)
            w["dot"].image = img
            w["cwd"].configure(text=s["cwd"] or "—", fg=p["text"])
            ageless = s["state"] in AGELESS_STATES
            meta_txt = STATE_LABELS.get(s["state"], "") if ageless \
                       else format_age(s["age_s"])
            w["meta"].configure(text=meta_txt,
                                fg=p["meta_dim"] if ageless else p["meta"])
        if overflow:
            w = _ensure_row(len(shown))
            w["dot_color"] = p["meta_dim"]
            w["dot_state"] = "idle"  # don't pulse the overflow marker
            img = get_dot_image(p["meta_dim"],
                                int(STATIC_PHASE * DOT_FRAMES))
            w["dot"].configure(image=img)
            w["dot"].image = img
            w["cwd"].configure(text=f"+{overflow} more", fg=p["meta"])
            w["meta"].configure(text="")

        resize_window()

    def render_usage(pct):
        p = palette_for(cur["skin"], cur["theme"])
        usage_lbl.configure(text="USE" if pct is not None else "USE —",
                            fg=p["usage_fg"])
        usage_pct_lbl.configure(
            text=f"{pct}%" if pct is not None else "",
            fg=p["usage_fg"])
        bar_canvas.delete("all")
        w = bar_canvas.winfo_width()
        if w <= 1:
            bar_canvas.update_idletasks()
            w = bar_canvas.winfo_width()
        h = cur["metrics"]["bar"]
        bar_canvas.create_rectangle(0, 0, w, h,
                                    fill=p["bar_track"], outline="")
        if pct is not None and pct > 0 and w > 1:
            fill_w = max(2, int(w * pct / 100))
            bar_canvas.create_rectangle(0, 0, fill_w, h,
                                        fill=usage_fill(pct, p), outline="")

    def update_dashboard(d):
        render_sessions(d.get("sessions") or [])
        sess_lbl.configure(text=str(len(d.get("sessions") or [])))
        render_usage(d.get("usage_5h_pct"))

    # ── Palette switching ───────────────────────────────────────────
    def repaint_chrome():
        p = palette_for(cur["skin"], cur["theme"])
        root.configure(bg=p["card"])
        shell.configure(bg=p["card"])
        brand_frame.configure(bg=p["card"])
        brand_lbl.configure(bg=p["card"], fg=p["brand"])
        sess_lbl.configure(bg=p["card"], fg=p["brand_dim"])
        blocks_frame.configure(bg=p["card"])
        divider.configure(bg=p["divider"])
        usage_frame.configure(bg=p["card"])
        usage_lbl.configure(bg=p["card"], fg=p["usage_fg"])
        usage_pct_lbl.configure(bg=p["card"], fg=p["usage_fg"])
        bar_canvas.configure(bg=p["card"])
        gif_lbl.configure(bg=p["card"])
        for w in cur["block_widgets"]:
            w["frame"].configure(bg=p["card"])
            w["dot"].configure(bg=p["card"])
            w["cwd"].configure(bg=p["card"], fg=p["text"])
            w["meta"].configure(bg=p["card"], fg=p["meta"])
        for m in cur.get("menus") or ():
            try:
                m.configure(bg=p["card"], fg=p["text"],
                            activebackground=p["divider"],
                            activeforeground=p["text"])
            except tk.TclError:
                pass

    def apply_palette(skin, theme):
        cur["skin"] = skin
        cur["theme"] = theme
        repaint_chrome()
        cur["block_sig"] = None
        cur["dot_cache"].clear()  # halo is composited against card bg
        # Re-rasterize GIF: the alpha mask is composited against the card
        # colour, which just changed.
        if cur.get("last_gif_bytes"):
            load(cur["last_gif_bytes"])
        try:
            skin_var.set(skin)
        except NameError:
            pass

    def set_theme(name):
        apply_palette(cur["skin"], name)
        write_overlay_env({"CUBE_OVERLAY_THEME": name})

    def set_skin(name):
        # Route through mock-cube's /set?skin=NAME — mock-cube proxies to
        # cube.sh skin + redisplay in WSL. Next poll picks up the new skin
        # and re-applies the palette.
        try:
            urllib.request.urlopen(f"{cur['mock']}/set?skin={name}", timeout=2).read()
        except Exception as e:
            sys.stderr.write(f"set_skin({name}) failed: {e}\n")

    def restart_overlay():
        flags = 0x00000008 if os.name == "nt" else 0  # DETACHED_PROCESS
        safe_cwd = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        try:
            subprocess.Popen([sys.executable] + sys.argv,
                             creationflags=flags, close_fds=True,
                             cwd=safe_cwd)
        except Exception as e:
            sys.stderr.write(f"restart failed: {e}\n")
            return
        root.after(150, root.destroy)

    def reset_position():
        px, py, pw, ph = cur["primary"]
        save_layout_anchor(cur["fingerprint"], px + pw, py + ph)
        restart_overlay()

    def apply_size(w):
        # Live size change — no restart roundtrip. (Windows-Tk subprocess
        # re-spawn via UNC argv[0] + pythonw + DETACHED_PROCESS has been
        # observed to silently fail on multi-monitor.)
        cur["win_w"] = w
        cur["gif_size"] = w - 2 * cur["metrics"]["pad"]
        cur["metrics"] = size_metrics(w)
        cur["gif_size"] = w - 2 * cur["metrics"]["pad"]
        new_brand = ("Segoe UI Semibold", cur["metrics"]["brand"], "bold")
        new_row = ("Segoe UI Semibold", cur["metrics"]["font"], "bold")
        new_meta = ("Segoe UI Semibold",
                    max(8, cur["metrics"]["font"] - 2), "bold")
        brand_lbl.configure(font=new_brand)
        sess_lbl.configure(font=new_brand)
        usage_lbl.configure(font=new_brand)
        usage_pct_lbl.configure(font=new_brand)
        bar_canvas.configure(height=cur["metrics"]["bar"])
        for ww in cur["block_widgets"]:
            ww["cwd"].configure(font=new_row)
            ww["meta"].configure(font=new_meta)
        cur["block_sig"] = None
        cur["last_height"] = 0
        cur["dot_cache"].clear()  # dot_render_px tied to metrics["dot"]
        # Re-create rows so canvas widths match new dot_render_px.
        _shrink_rows(0)
        if cur.get("last_gif_bytes"):
            load(cur["last_gif_bytes"])
        else:
            cur["ts"] = -1
        resize_window()

    def set_size(w):
        write_overlay_env({"CUBE_OVERLAY_WIDTH": str(w),
                           "CUBE_OVERLAY_SIZE": None})
        apply_size(w)

    def user_hide():
        cur["hidden_by_user"] = True
        cur["hide_winner"] = cur["last_winner"]
        hide()

    def bring_to_front():
        # Win10/11 foreground-lock blocks SetForegroundWindow from background
        # processes; flicker -topmost to lift above current z-order without
        # the focus-steal side effect.
        root.attributes("-topmost", True)
        root.lift()
        root.after(50, lambda: root.attributes("-topmost", topmost_var.get()))

    # ── Menu ────────────────────────────────────────────────────────
    theme_var = tk.StringVar(value=theme_name)
    skin_var = tk.StringVar(value=cur["skin"])
    size_var = tk.IntVar(value=win_w)
    lock_var = tk.BooleanVar(value=env.get("CUBE_OVERLAY_POSITION_LOCKED", "1") == "1")
    topmost_var = tk.BooleanVar(value=topmost_default)
    lift_activity_var = tk.BooleanVar(value=lift_activity_default)

    def apply_cursor():
        c = "" if lock_var.get() else "fleur"
        cur["cursor"] = c
        for wdg in (root, shell, brand_frame, brand_lbl, sess_lbl,
                    blocks_frame, divider, usage_frame, usage_lbl,
                    usage_pct_lbl, bar_canvas, gif_lbl):
            try:
                wdg.configure(cursor=c)
            except tk.TclError:
                pass
        for w in cur["block_widgets"]:
            for k in ("frame", "dot", "cwd", "meta"):
                try:
                    w[k].configure(cursor=c)
                except tk.TclError:
                    pass

    def toggle_lock():
        write_overlay_env({"CUBE_OVERLAY_POSITION_LOCKED":
                           "1" if lock_var.get() else "0"})
        apply_cursor()

    def toggle_topmost():
        on = topmost_var.get()
        root.attributes("-topmost", on)
        write_overlay_env({"CUBE_OVERLAY_TOPMOST": "1" if on else "0"})

    def toggle_lift_activity():
        write_overlay_env({"CUBE_OVERLAY_LIFT_ON_ACTIVITY":
                           "1" if lift_activity_var.get() else "0"})

    p_now = palette_for(skin_name, theme_name)
    mk = dict(bg=p_now["card"], fg=p_now["text"],
              activebackground=p_now["divider"],
              activeforeground=p_now["text"], bd=0)
    menu = tk.Menu(root, tearoff=0, **mk)
    theme_m = tk.Menu(menu, tearoff=0, **mk)
    for t in THEME_NAMES:
        theme_m.add_radiobutton(label=t.capitalize(), variable=theme_var,
                                value=t, command=lambda n=t: set_theme(n))
    menu.add_cascade(label="Theme", menu=theme_m)
    skin_m = tk.Menu(menu, tearoff=0, **mk)
    for sk in SKIN_CHOICES:
        skin_m.add_radiobutton(label=sk, variable=skin_var, value=sk,
                               command=lambda n=sk: set_skin(n))
    menu.add_cascade(label="Skin", menu=skin_m)
    pos_m = tk.Menu(menu, tearoff=0, **mk)
    pos_m.add_checkbutton(label="Locked", variable=lock_var,
                          command=toggle_lock)
    pos_m.add_command(label="Reset", command=reset_position)
    menu.add_cascade(label="Position", menu=pos_m)
    size_m = tk.Menu(menu, tearoff=0, **mk)
    for label, w in SIZE_PRESETS:
        size_m.add_radiobutton(label=f"{label} ({w}px)", variable=size_var,
                               value=w, command=lambda x=w: set_size(x))
    menu.add_cascade(label="Size", menu=size_m)
    window_m = tk.Menu(menu, tearoff=0, **mk)
    window_m.add_checkbutton(label="Always on Top", variable=topmost_var,
                             command=toggle_topmost)
    window_m.add_checkbutton(label="Lift on Activity",
                             variable=lift_activity_var,
                             command=toggle_lift_activity)
    window_m.add_command(label="Bring to Front", command=bring_to_front)
    menu.add_cascade(label="Window", menu=window_m)
    menu.add_separator()
    menu.add_command(label="Hide", command=user_hide)
    menu.add_command(label="Quit", command=root.destroy)
    cur["menus"] = (menu, theme_m, skin_m, pos_m, size_m, window_m)

    def show_menu(ev):
        try:
            menu.tk_popup(root.winfo_rootx(), ev.y_root)
        finally:
            menu.grab_release()

    # ── Drag ────────────────────────────────────────────────────────
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
        nx = ev.x_root - drag["off_x"]
        ny = ev.y_root - drag["off_y"]
        root.geometry(f"{cur['win_w']}x{cur['last_height']}+{nx}+{ny}")

    def drag_end(_ev):
        if not drag["active"]:
            return
        drag["active"] = False
        cur["anchor_right"] = root.winfo_rootx() + cur["win_w"]
        cur["anchor_bottom"] = root.winfo_rooty() + cur["last_height"]
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

    # ── Dot pulse tick ──────────────────────────────────────────────
    def tick_dots():
        cur["dot_phase"] = (cur["dot_phase"] + 1) % DOT_FRAMES
        static_idx = int(STATIC_PHASE * DOT_FRAMES)
        for w in cur["block_widgets"]:
            state = w.get("dot_state", "idle")
            color = w.get("dot_color")
            if not color:
                continue
            # Static states don't need a redraw every tick; their image
            # never changes. Skip the configure call to save CPU.
            if state not in PULSE_STATES:
                continue
            try:
                img = get_dot_image(color, cur["dot_phase"])
                w["dot"].configure(image=img)
                w["dot"].image = img
            except tk.TclError:
                pass
        cur["dot_tick_job"] = root.after(DOT_TICK_MS, tick_dots)

    # ── Poll loop ───────────────────────────────────────────────────
    def poll():
        s = fetch_dashboard(cur["mock"])
        if s is None:
            cur["consecutive_failures"] += 1
            # 3 misses → re-resolve WSL IP (NAT drift after `wsl --shutdown`).
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
        # Skin from mock — cube.sh in WSL is source of truth.
        live_skin = s.get("skin") or "orb"
        if live_skin != cur["skin"]:
            apply_palette(live_skin, cur["theme"])
        update_dashboard(s)
        if (s.get("img"), s.get("ts")) != (cur["img"], cur["ts"]):
            data = fetch_gif(cur["mock"])
            if data:
                cur["last_gif_bytes"] = data
                load(data)
                cur["img"] = s.get("img")
                cur["ts"] = s.get("ts")
        winner = (s.get("state"), s.get("img"))
        prev_winner = cur["last_winner"]
        cur["last_winner"] = winner
        if (lift_activity_var.get()
                and prev_winner is not None
                and prev_winner != winner
                and winner[0] != "idle"):
            bring_to_front()
        if cur["hidden_by_user"]:
            if winner != cur["hide_winner"]:
                cur["hidden_by_user"] = False
                show()
        else:
            show()
        root.after(POLL_MS, poll)

    root.after_idle(lambda: resize_window())
    root.after(100, poll)
    root.after(DOT_TICK_MS, tick_dots)
    root.mainloop()


if __name__ == "__main__":
    main()
