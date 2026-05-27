#!/usr/bin/env python3
r"""cube-overlay-win-html — pywebview/WebView2 variant of the overlay.

Runs on Windows-host as a frameless WebView2 window that renders
bin/win/html/index.html (inlined). Polls mock-cube inside WSL via a
JS bridge (avoids cross-origin / Docker port collisions), persists
window anchor per monitor layout, mirrors the Tk variant's WSL-IP
resolution and crash-log wiring.

Feature parity with the Tk variant (`cube-overlay-win.pyw`): drag,
right-click menu (Theme / Skin / Position / Size / Window / Hide /
Quit), lift-on-activity, hide auto-unhide on state change. All
window-mgmt routes through `SetWindowPos` via ctypes — physical
pixels under per-monitor DPI awareness, sidestepping EdgeChromium's
logical-pixel `window.move`.

Setup (one-time):
  1. Install Python 3.13 for Windows (3.14 pythonnet has no wheels yet).
  2. py -3.13 -m pip install --user pywebview
  3. In WSL: set CUBE_MOCK_HOST=0.0.0.0 in ~/.config/cube/config, restart
     mock-cube  (`systemctl --user restart mock-cube.service`).
  4. Double-click bin/win/cube-overlay-win-html.pyw.

Per-machine config lives under %APPDATA%\cube\ (shared with the Tk
variant — same overlay.env and overlay-layouts.json keys).
"""
import argparse
import base64
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from ctypes import wintypes

# pythonw.exe (.pyw startup) has no console — wire stderr to a log file
# early so silent startup crashes are debuggable.
if os.name == "nt":
    try:
        _log_path = os.path.join(
            os.environ.get("TEMP", os.path.expanduser("~")),
            "cube-overlay-win-html.log")
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

# Per-monitor DPI awareness so WebView2 renders crisp on >100% scaling.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass

# pywebview's logger emits multi-KB "Error while processing
# window.native.AccessibilityObject.Bounds.Empty.Empty.Empty..." spam when
# pythonnet hits the System.Drawing.Rectangle.Empty self-reference cycle.
# The error is caught internally — we just don't want 10 KB of recursion
# noise in the crash log. Set BEFORE importing webview so the logger is
# already at the right level when pywebview's modules attach handlers.
import logging
logging.getLogger("pywebview").setLevel(logging.CRITICAL)

import webview  # pip install pywebview

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "cube")
OVERLAY_ENV_PATH = os.path.join(CONFIG_DIR, "overlay.env")
LAYOUTS_PATH = os.path.join(CONFIG_DIR, "overlay-layouts.json")
WSL_IP_CACHE = {"ip": None, "ts": 0.0}
THEME_NAMES = ("light", "dark")
SIZE_PRESETS = (140, 180, 240)
AGELESS_STATES = {"idle", "done", "start"}
WINDOW_TITLE = "cube-overlay"
HTML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "html")
INDEX_HTML = os.path.join(HTML_DIR, "index.html")

# SetWindowPos flags
SWP_NOACTIVATE = 0x0010
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2


def win32_move(hwnd, x=None, y=None, w=None, h=None, topmost=None):
    """SetWindowPos in physical pixels; bypasses EdgeChromium's logical-
    pixel confusion under per-monitor DPI awareness. Skipping x/y or w/h
    sets the corresponding SWP_NO* flag so partial moves don't stomp
    the other axis."""
    if not hwnd:
        return False
    flags = SWP_NOACTIVATE
    if x is None or y is None:
        flags |= SWP_NOMOVE
        x = y = 0
    if w is None or h is None:
        flags |= SWP_NOSIZE
        w = h = 0
    if topmost is True:
        z = HWND_TOPMOST
    elif topmost is False:
        z = HWND_NOTOPMOST
    else:
        z = HWND_TOP  # ignored when SWP_NOZORDER would be set, but we always
                     # want a z update so it's fine to leave HWND_TOP
    return bool(ctypes.windll.user32.SetWindowPos(
        hwnd, z, int(x), int(y), int(w), int(h), flags))


def win32_get_rect(hwnd):
    if not hwnd:
        return None
    r = wintypes.RECT()
    if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r)):
        return (r.left, r.top, r.right, r.bottom)
    return None


# ─────────────────────────────────────────────────────────────────────────
# HWND discovery — pywebview's window.native.Handle is the canonical path,
# but its debug-introspection chokes on AccessibilityObject (observed in
# logs: "maximum recursion depth exceeded"). Fall back to EnumWindows +
# PID filter so we never end up with HWND=0 and silently-dead win32_move
# calls.
# ─────────────────────────────────────────────────────────────────────────
def _enum_pid_windows():
    user32 = ctypes.windll.user32
    pid = os.getpid()
    out = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int, wintypes.HWND, wintypes.LPARAM)

    @WNDENUMPROC
    def cb(hwnd, _):
        wpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        if wpid.value != pid:
            return 1
        if not user32.IsWindowVisible(hwnd):
            return 1
        title = ctypes.create_unicode_buffer(256)
        cls = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        user32.GetClassNameW(hwnd, cls, 256)
        out.append((hwnd, title.value, cls.value))
        return 1

    user32.EnumWindows(cb, 0)
    return out


def find_hwnd(window):
    """Try pywebview's native form Handle first; on any failure, enumerate
    visible windows in our PID and pick the one with matching title or
    fall back to the first visible. Logs diagnostic enum-dump so we can
    inspect what the WebView2 host actually looks like."""
    try:
        # pythonnet wraps Win32 HANDLE as System.IntPtr — call ToInt64()
        # to unwrap to a Python int. Raw int(IntPtr) raises TypeError.
        h = int(window.native.Handle.ToInt64())
        if h:
            sys.stderr.write(f"hwnd via window.native.Handle: {h:#x}\n")
            return h
    except Exception as e:
        sys.stderr.write(f"window.native.Handle failed: {e}\n")
    candidates = _enum_pid_windows()
    sys.stderr.write(f"PID windows: {candidates}\n")
    for hwnd, title, _cls in candidates:
        if title == WINDOW_TITLE:
            sys.stderr.write(f"hwnd via enum (title match): {hwnd:#x}\n")
            return hwnd
    if candidates:
        hwnd = candidates[0][0]
        sys.stderr.write(f"hwnd via enum (first visible): {hwnd:#x}\n")
        return hwnd
    sys.stderr.write("hwnd discovery: no candidates\n")
    return 0


# ─────────────────────────────────────────────────────────────────────────
# Win32 native popup menu — TrackPopupMenu. DOM context-menu can't grow
# past the WebView2 frameless window's bounds, so submenus get clipped
# when card is 180-240 px wide. Native menu lives outside the WebView2
# surface entirely and has no such constraint.
# ─────────────────────────────────────────────────────────────────────────
MF_STRING = 0x0000
MF_POPUP = 0x0010
MF_SEPARATOR = 0x0800
MF_CHECKED = 0x0008
TPM_RETURNCMD = 0x0100
TPM_RIGHTBUTTON = 0x0002

# Menu item IDs (kept ≥100 to stay clear of common WM_COMMAND territory).
MENU_IDS = {
    "theme_light": 100, "theme_dark": 101,
    "skin_orb": 110, "skin_waifu": 111, "skin_cube": 112,
    "pos_lock": 120, "pos_reset": 121,
    "size_140": 130, "size_180": 131, "size_240": 132,
    "win_topmost": 140, "win_lift": 141, "win_front": 142,
    "win_gif": 143,
    "hide": 150, "quit": 151,
}


# ─────────────────────────────────────────────────────────────────────────
# overlay.env  (shared with Tk variant)
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


# ─────────────────────────────────────────────────────────────────────────
# WSL IP resolution (lifted from cube-overlay-win.pyw)
# ─────────────────────────────────────────────────────────────────────────
def resolve_wsl_ip(force=False):
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


# ─────────────────────────────────────────────────────────────────────────
# Monitor layout (EnumDisplayMonitors → fingerprint + primary rect)
# ─────────────────────────────────────────────────────────────────────────
def detect_layout_win():
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
        ctypes.c_int, HMONITOR, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM,
    )
    mons, primary = [], [None]

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
    return {"fingerprint": fp, "primary": primary[0]}


def detect_layout(sw, sh):
    return detect_layout_win() or {
        "fingerprint": f"fallback:{sw}x{sh}",
        "primary": (0, 0, sw, sh),
    }


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


def anchor_in_bounds(anchor_r, anchor_b, w, h, primary):
    """Saved anchor must place the whole window within primary monitor.
    Returns False for stale anchors from a previous (larger) layout — the
    caller then falls back to bottom-right of current primary. Without
    this check, layout shrinks (dock undock, monitor unplug) leave the
    overlay positioned off-screen with no in-app way to recover."""
    px, py, pw, ph = primary
    x = anchor_r - w
    y = anchor_b - h
    return (px <= x and x + w <= px + pw
            and py <= y and y + h <= py + ph)


# ─────────────────────────────────────────────────────────────────────────
# JS bridge
# ─────────────────────────────────────────────────────────────────────────
class JsApi:
    """Methods exposed via window.pywebview.api in the WebView.

    pywebview marshals these calls synchronously; JS sees a Promise that
    resolves with the return value. urllib + ctypes happen on the bridge
    thread, not the WebView UI thread — UI stays responsive."""

    def __init__(self, mock_url, port, env):
        # network
        self.mock_url = mock_url
        self.port = port
        self.consecutive_failures = 0
        # user state from overlay.env
        self.theme = env.get("CUBE_OVERLAY_THEME", "light")
        if self.theme not in THEME_NAMES:
            self.theme = "light"
        try:
            self.width = int(env.get("CUBE_OVERLAY_WIDTH", "180"))
        except ValueError:
            self.width = 180
        self.locked = env.get("CUBE_OVERLAY_POSITION_LOCKED", "0") == "1"
        self.topmost = env.get("CUBE_OVERLAY_TOPMOST", "1") == "1"
        self.lift_on_activity = env.get(
            "CUBE_OVERLAY_LIFT_ON_ACTIVITY", "0") == "1"
        self.hide_gif = env.get("CUBE_OVERLAY_HIDE_GIF", "0") == "1"
        # runtime (set after window creation)
        self.hwnd = None
        self.window = None
        self.fingerprint = None
        self.primary_rect = (0, 0, 1920, 1080)
        # Stable bottom-right anchor in physical pixels. Set in main() at
        # startup, updated by drag-end and reset_position. resize_height
        # uses this instead of `rect.b` so a WinForms-DPI-scaled rect
        # can't lock the window off-screen.
        self.anchor_r = None
        self.anchor_b = None
        # hide/show + activity tracking
        self.hidden_by_user = False
        self.hide_winner = None
        self.last_winner = None
        # drag
        self.drag_origin = None
        # init paint locking — prevents bring_to_front during initial setup
        self._initialised = False

    # ── data ────────────────────────────────────────────────────────────
    def _maybe_resolve_drift(self):
        # 3 consecutive misses → re-resolve WSL IP. NAT-mode IPs drift on
        # `wsl --shutdown`; cache update lets next poll succeed.
        if self.consecutive_failures < 3:
            return
        new_ip = resolve_wsl_ip(force=True)
        if not new_ip:
            return
        candidate = f"http://{new_ip}:{self.port}"
        if candidate != self.mock_url:
            sys.stderr.write(
                f"wsl-ip drift: {self.mock_url} -> {candidate}\n")
            self.mock_url = candidate

    def dashboard(self):
        try:
            with urllib.request.urlopen(
                f"{self.mock_url}/dashboard.json", timeout=1) as r:
                d = json.loads(r.read())
            self.consecutive_failures = 0
        except Exception:
            self.consecutive_failures += 1
            self._maybe_resolve_drift()
            return None
        d["theme"] = self.theme  # JS uses this to set data-theme
        d["locked"] = self.locked  # JS uses to gate drag UX
        d["hide_gif"] = self.hide_gif  # JS hides .gif-wrap + .divider when on
        state = d.get("state")
        # Auto-unhide if user-hidden and state differs from hide_winner.
        if self.hidden_by_user and state != self.hide_winner and self.window:
            self.hidden_by_user = False
            self.hide_winner = None
            try:
                self.window.show()
            except Exception as e:
                sys.stderr.write(f"auto-unhide failed: {e}\n")
        # Lift on activity: idle/done/start → pulse state crossing.
        if (self._initialised and self.lift_on_activity
                and self.last_winner in AGELESS_STATES
                and state and state not in AGELESS_STATES):
            self._bring_to_front_async()
        self.last_winner = state
        return d

    def gif(self):
        try:
            with urllib.request.urlopen(
                f"{self.mock_url}/current.gif", timeout=2) as r:
                return base64.b64encode(r.read()).decode("ascii")
        except Exception as e:
            sys.stderr.write(f"gif fetch failed: {e}\n")
            return None

    # ── bootstrap for JS ────────────────────────────────────────────────
    def initial_state(self):
        return {
            "theme": self.theme,
            "width": self.width,
            "locked": self.locked,
            "topmost": self.topmost,
            "lift": self.lift_on_activity,
            "hide_gif": self.hide_gif,
            "size_presets": list(SIZE_PRESETS),
        }

    # ── menu mutators ───────────────────────────────────────────────────
    def set_theme(self, name):
        if name not in THEME_NAMES:
            return None
        self.theme = name
        write_overlay_env({"CUBE_OVERLAY_THEME": name})
        return name

    def set_skin(self, name):
        """Route through mock-cube's /set?skin=NAME — proxies to
        `cube.sh skin NAME` + `cube.sh redisplay` in WSL. Next poll
        picks up the new skin from /dashboard.json."""
        try:
            with urllib.request.urlopen(
                f"{self.mock_url}/set?skin={name}", timeout=2) as r:
                r.read()
        except Exception as e:
            sys.stderr.write(f"set_skin({name}) failed: {e}\n")
        return name

    def set_size(self, w):
        try:
            w = int(w)
        except (TypeError, ValueError):
            return None
        self.width = w
        write_overlay_env({"CUBE_OVERLAY_WIDTH": str(w)})
        # Resize window: keep stored bottom-right anchor stable (so size
        # changes don't drag a wrongly-positioned rect along).
        rect = win32_get_rect(self.hwnd)
        if rect:
            l, t, r, b = rect
            h = b - t
            anchor_r = self.anchor_r if self.anchor_r is not None else r
            anchor_b = self.anchor_b if self.anchor_b is not None else b
            new_x = anchor_r - w
            new_y = anchor_b - h
            px, py, pw, ph = self.primary_rect
            if new_x < px: new_x = px
            if new_x + w > px + pw: new_x = px + pw - w
            if new_y < py: new_y = py
            if new_y + h > py + ph: new_y = py + ph - h
            win32_move(self.hwnd, new_x, new_y, w, h)
        return w

    def set_lock(self, on):
        self.locked = bool(on)
        write_overlay_env({"CUBE_OVERLAY_POSITION_LOCKED":
                           "1" if self.locked else "0"})
        return self.locked

    def set_topmost(self, on):
        self.topmost = bool(on)
        write_overlay_env({"CUBE_OVERLAY_TOPMOST":
                           "1" if self.topmost else "0"})
        win32_move(self.hwnd, topmost=self.topmost)
        return self.topmost

    def set_lift(self, on):
        self.lift_on_activity = bool(on)
        write_overlay_env({"CUBE_OVERLAY_LIFT_ON_ACTIVITY":
                           "1" if self.lift_on_activity else "0"})
        return self.lift_on_activity

    def set_hide_gif(self, on):
        self.hide_gif = bool(on)
        write_overlay_env({"CUBE_OVERLAY_HIDE_GIF":
                           "1" if self.hide_gif else "0"})
        return self.hide_gif

    # ── window-management ───────────────────────────────────────────────
    def _bring_to_front_async(self):
        """Lift to top z without focus-steal. If not normally topmost,
        restore HWND_NOTOPMOST after a short delay so the window doesn't
        get stuck above other topmost windows."""
        if not self.hwnd:
            return
        win32_move(self.hwnd, topmost=True)
        if not self.topmost:
            threading.Timer(
                0.06,
                lambda: win32_move(self.hwnd, topmost=False)).start()

    def bring_to_front(self):
        self._bring_to_front_async()

    def hide(self):
        if not self.window:
            return
        # Capture current winner so we know when to auto-unhide.
        try:
            with urllib.request.urlopen(
                f"{self.mock_url}/dashboard.json", timeout=1) as r:
                d = json.loads(r.read())
            self.hide_winner = d.get("state")
        except Exception:
            self.hide_winner = None
        self.hidden_by_user = True
        try:
            self.window.hide()
        except Exception as e:
            sys.stderr.write(f"hide failed: {e}\n")

    def quit(self):
        if not self.window:
            return
        try:
            self.window.destroy()
        except Exception as e:
            sys.stderr.write(f"quit failed: {e}\n")

    # ── native popup menu ───────────────────────────────────────────────
    def show_menu(self):
        """Dispatch native menu open to the WinForms UI thread.

        TrackPopupMenu requires the calling thread to own the HWND.
        JS bridge calls run on bridge threads — we must Invoke onto
        the form's UI thread via WinForms.BeginInvoke."""
        if not self.window or not self.hwnd:
            return
        try:
            from System import Action  # pythonnet — provided by pywebview
            self.window.native.BeginInvoke(Action(self._open_native_menu))
        except Exception as e:
            sys.stderr.write(f"show_menu dispatch failed: {e}\n")
            # Fallback: try direct call (works on some pywebview builds
            # where bridge thread happens to be the UI thread).
            try:
                self._open_native_menu()
            except Exception as e2:
                sys.stderr.write(f"show_menu direct call failed: {e2}\n")

    def _mk_submenu(self, items):
        """items = list of (flags, item_id, text, submenu_handle). When
        submenu_handle != 0 the item is a popup (text is label); else
        leaf. None entry = separator."""
        user32 = ctypes.windll.user32
        h = user32.CreatePopupMenu()
        for item in items:
            if item is None:
                user32.AppendMenuW(h, MF_SEPARATOR, 0, None)
                continue
            flags, item_id, text, sub = item
            if sub:
                user32.AppendMenuW(h, MF_POPUP | flags, sub, text)
            else:
                user32.AppendMenuW(h, MF_STRING | flags, item_id, text)
        return h

    def _open_native_menu(self):
        user32 = ctypes.windll.user32
        ck_theme_l = MF_CHECKED if self.theme == "light" else 0
        ck_theme_d = MF_CHECKED if self.theme == "dark" else 0
        # Skin is server-driven (mock-cube). We can't know "current" skin
        # reliably without a poll — just show both without check marks.
        ck_lock = MF_CHECKED if self.locked else 0
        ck_top = MF_CHECKED if self.topmost else 0
        ck_lift = MF_CHECKED if self.lift_on_activity else 0
        ck_gif = MF_CHECKED if not self.hide_gif else 0  # "Show GIF" — checked = visible
        ck_w140 = MF_CHECKED if self.width == 140 else 0
        ck_w180 = MF_CHECKED if self.width == 180 else 0
        ck_w240 = MF_CHECKED if self.width == 240 else 0
        M = MENU_IDS

        theme_m = self._mk_submenu([
            (ck_theme_l, M["theme_light"], "Light", 0),
            (ck_theme_d, M["theme_dark"], "Dark", 0),
        ])
        skin_m = self._mk_submenu([
            (0, M["skin_orb"], "orb", 0),
            (0, M["skin_waifu"], "waifu", 0),
            (0, M["skin_cube"], "cube", 0),
        ])
        pos_m = self._mk_submenu([
            (ck_lock, M["pos_lock"], "Locked", 0),
            (0, M["pos_reset"], "Reset Position", 0),
        ])
        size_m = self._mk_submenu([
            (ck_w140, M["size_140"], "Small (140 px)", 0),
            (ck_w180, M["size_180"], "Medium (180 px)", 0),
            (ck_w240, M["size_240"], "Large (240 px)", 0),
        ])
        win_m = self._mk_submenu([
            (ck_top, M["win_topmost"], "Always on Top", 0),
            (ck_lift, M["win_lift"], "Lift on Activity", 0),
            (ck_gif, M["win_gif"], "Show GIF", 0),
            (0, M["win_front"], "Bring to Front", 0),
        ])
        root_m = self._mk_submenu([
            (0, 0, "Theme", theme_m),
            (0, 0, "Skin", skin_m),
            (0, 0, "Position", pos_m),
            (0, 0, "Size", size_m),
            (0, 0, "Window", win_m),
            None,
            (0, M["hide"], "Hide", 0),
            (0, M["quit"], "Quit", 0),
        ])

        cur = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(cur))
        # Documented quirk — without SetForegroundWindow the popup may
        # not dismiss on outside-click reliably.
        user32.SetForegroundWindow(self.hwnd)
        cmd_id = user32.TrackPopupMenu(
            root_m,
            TPM_RETURNCMD | TPM_RIGHTBUTTON,
            cur.x, cur.y, 0, self.hwnd, None)
        # DestroyMenu cascades to all submenus appended via MF_POPUP.
        user32.DestroyMenu(root_m)
        self._dispatch_menu(cmd_id)

    def _dispatch_menu(self, cmd_id):
        if not cmd_id:
            return  # menu dismissed
        M = MENU_IDS
        if cmd_id == M["theme_light"]:
            self.set_theme("light")
        elif cmd_id == M["theme_dark"]:
            self.set_theme("dark")
        elif cmd_id == M["skin_orb"]:
            self.set_skin("orb")
        elif cmd_id == M["skin_waifu"]:
            self.set_skin("waifu")
        elif cmd_id == M["skin_cube"]:
            self.set_skin("cube")
        elif cmd_id == M["pos_lock"]:
            self.set_lock(not self.locked)
        elif cmd_id == M["pos_reset"]:
            self.reset_position()
        elif cmd_id == M["size_140"]:
            self.set_size(140)
        elif cmd_id == M["size_180"]:
            self.set_size(180)
        elif cmd_id == M["size_240"]:
            self.set_size(240)
        elif cmd_id == M["win_topmost"]:
            self.set_topmost(not self.topmost)
        elif cmd_id == M["win_lift"]:
            self.set_lift(not self.lift_on_activity)
        elif cmd_id == M["win_gif"]:
            self.set_hide_gif(not self.hide_gif)
        elif cmd_id == M["win_front"]:
            self.bring_to_front()
        elif cmd_id == M["hide"]:
            self.hide()
        elif cmd_id == M["quit"]:
            self.quit()

    def reset_position(self):
        if not self.hwnd:
            return
        px, py, pw, ph = self.primary_rect
        rect = win32_get_rect(self.hwnd)
        h = (rect[3] - rect[1]) if rect else 420
        anchor_r = px + pw - 20
        anchor_b = py + ph - 20
        new_x = anchor_r - self.width
        new_y = anchor_b - h
        win32_move(self.hwnd, new_x, new_y, self.width, h)
        self.anchor_r = anchor_r
        self.anchor_b = anchor_b
        save_layout_anchor(self.fingerprint, anchor_r, anchor_b)

    def save_anchor(self):
        rect = win32_get_rect(self.hwnd)
        if not rect or not self.fingerprint:
            return
        l, t, r, b = rect
        self.anchor_r = r
        self.anchor_b = b
        save_layout_anchor(self.fingerprint, r, b)

    # ── drag ────────────────────────────────────────────────────────────
    # JS screenX/Y in WebView2 = logical (CSS) pixels; SetWindowPos uses
    # physical. GetCursorPos returns physical (process is DPI-aware) — same
    # coord space as SetWindowPos. JS just signals start/move/end; Python
    # reads cursor each call. Race-free even with async bridge ordering
    # because each move_relative computes from a fresh cursor sample.
    def _cursor_pos(self):
        p = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(p)):
            return None
        return (p.x, p.y)

    def start_drag(self):
        if self.locked or not self.hwnd:
            return
        rect = win32_get_rect(self.hwnd)
        cur = self._cursor_pos()
        if not rect or not cur:
            return
        self.drag_origin = (cur[0], cur[1], rect[0], rect[1])

    def move_relative(self):
        if not self.drag_origin or self.locked or not self.hwnd:
            return
        cur = self._cursor_pos()
        if not cur:
            return
        orig_cx, orig_cy, orig_x, orig_y = self.drag_origin
        win32_move(self.hwnd,
                   orig_x + cur[0] - orig_cx,
                   orig_y + cur[1] - orig_cy)

    def end_drag(self):
        if not self.drag_origin:
            return
        self.drag_origin = None
        self.save_anchor()

    # ── dynamic height ──────────────────────────────────────────────────
    def resize_height(self, h):
        """JS ResizeObserver reports `.wrap` content height after every
        DOM mutation. Resize the OS window to match.

        Bottom-right anchor is read from `self.anchor_b` (set at startup,
        updated on drag-end/reset). Earlier versions anchored at
        `rect.b` — but WinForms DPI-scaling can leave the post-creation
        rect off-screen (logical pixels passed through Form.Top scale
        by the monitor's DPI factor), and anchoring there locks the
        window off-screen forever. Stored anchor is in physical pixels
        and bounds-checked against primary, so it always lands on-screen."""
        if not self.hwnd:
            sys.stderr.write(f"resize_height({h}): no hwnd\n")
            return
        rect = win32_get_rect(self.hwnd)
        if not rect:
            sys.stderr.write(f"resize_height({h}): no rect\n")
            return
        l, t, r, b = rect
        w = r - l
        cur_h = b - t
        try:
            new_h = max(60, int(h))
        except (TypeError, ValueError):
            sys.stderr.write(f"resize_height({h}): bad value\n")
            return
        if new_h == cur_h:
            return
        # Prefer the stored anchor for the bottom edge. Falls back to
        # rect.b only if anchor was somehow never initialised.
        anchor_b = self.anchor_b if self.anchor_b is not None else b
        anchor_r = self.anchor_r if self.anchor_r is not None else r
        new_y = anchor_b - new_h
        new_x = anchor_r - w
        # Clamp into primary monitor so a very tall card (or a stale
        # anchor) can't push the window off-screen.
        px, py, pw, ph = self.primary_rect
        if new_y < py:
            new_y = py
        if new_y + new_h > py + ph:
            new_y = py + ph - new_h
        if new_x < px:
            new_x = px
        if new_x + w > px + pw:
            new_x = px + pw - w
        sys.stderr.write(
            f"resize_height: {cur_h} -> {new_h} "
            f"(rect t={t} b={b}; anchor_b={anchor_b}; pos -> {new_x},{new_y})\n")
        win32_move(self.hwnd, new_x, new_y, w, new_h)


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────
def main():
    env = read_overlay_env()
    default_port = env.get("CUBE_OVERLAY_PORT",
                           os.environ.get("CUBE_OVERLAY_PORT", "8765"))
    default_mock = (os.environ.get("CUBE_OVERLAY_MOCK")
                    or env.get("CUBE_OVERLAY_MOCK"))

    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", default=default_mock,
                    help="full URL override; if omitted, derived from "
                         "wsl.exe hostname -I")
    ap.add_argument("--port", default=default_port)
    args = ap.parse_args()

    mock_url = args.mock
    if not mock_url:
        ip = resolve_wsl_ip()
        if not ip:
            sys.stderr.write(
                "Could not resolve WSL IP via `wsl.exe hostname -I`. "
                "Pass --mock http://<ip>:<port> explicitly.\n")
            sys.exit(2)
        mock_url = f"http://{ip}:{args.port}"

    api = JsApi(mock_url, args.port, env)

    # Layout fingerprint → window position. Restore saved anchor if
    # present, else fall back to bottom-right of primary monitor.
    sw, sh = 1920, 1080  # rough — only used in fallback path
    layout = detect_layout(sw, sh)
    fp = layout["fingerprint"]
    px, py, pw, ph = layout["primary"]
    api.fingerprint = fp
    api.primary_rect = (px, py, pw, ph)

    init_w = api.width
    init_h = 420  # rough vertical room; JS content fits within

    layouts = load_layouts()
    if fp in layouts:
        anchor_r = int(layouts[fp].get("anchor_r", px + pw - 20))
        anchor_b = int(layouts[fp].get("anchor_b", py + ph - 20))
        if not anchor_in_bounds(anchor_r, anchor_b,
                                init_w, init_h, layout["primary"]):
            sys.stderr.write(
                f"saved anchor ({anchor_r},{anchor_b}) out of primary "
                f"bounds {layout['primary']}; resetting to bottom-right\n")
            anchor_r = px + pw - 20
            anchor_b = py + ph - 20
            save_layout_anchor(fp, anchor_r, anchor_b)
    else:
        anchor_r = px + pw - 20
        anchor_b = py + ph - 20
        save_layout_anchor(fp, anchor_r, anchor_b)

    x = anchor_r - init_w
    y = anchor_b - init_h
    api.anchor_r = anchor_r
    api.anchor_b = anchor_b

    sys.stderr.write(
        f"mock={mock_url}  layout={fp}  primary={px},{py},{pw}x{ph}  "
        f"anchor=br({anchor_r},{anchor_b})  pos=+{x}+{y}  "
        f"win={init_w}x{init_h}  theme={api.theme}\n"
    )

    # WebView2 can't load file:// from UNC paths (\\wsl.localhost\...).
    # Inline CSS + JS into the HTML and pass as `html=` so pywebview
    # serves it via its built-in transient HTTP server — no file-URL
    # quirks, no UNC issues.
    try:
        html_doc = open(INDEX_HTML, encoding="utf-8").read()
        css_doc = open(os.path.join(HTML_DIR, "overlay.css"),
                       encoding="utf-8").read()
        js_doc = open(os.path.join(HTML_DIR, "overlay.js"),
                      encoding="utf-8").read()
        entity_doc = open(os.path.join(HTML_DIR, "cube-entity.js"),
                          encoding="utf-8").read()
    except OSError as e:
        sys.stderr.write(f"asset read failed: {e}\n")
        sys.exit(3)
    html_doc = html_doc.replace(
        '<link rel="stylesheet" href="overlay.css">',
        f"<style>\n{css_doc}\n</style>")
    # cube-entity.js must inline BEFORE overlay.js — overlay.js references
    # window.CubeEntity at import time (ensureEntity). External <script src>
    # tags don't resolve in pywebview's html= mode (no base URL).
    html_doc = html_doc.replace(
        '<script src="cube-entity.js"></script>',
        f"<script>\n{entity_doc}\n</script>")
    html_doc = html_doc.replace(
        '<script src="overlay.js"></script>',
        f"<script>\n{js_doc}\n</script>")
    # Pre-set the root's data-theme so the first paint is on the right
    # palette (before the first dashboard poll comes back).
    html_doc = html_doc.replace(
        'data-theme="light"', f'data-theme="{api.theme}"')  # replaces on both html + #root

    # NOTE: transparent=True on EdgeChromium creates a layered window;
    # WebView2 painting into a layered surface is broken on most pywebview
    # builds — DWM thumbnail (taskbar preview) shows the content but the
    # actual window stays invisible. Opaque window + card-coloured bg
    # restores visibility at the cost of square outer corners. The
    # .wrap's border-radius still rounds visually because the bg
    # matches: viewer sees a card-coloured rect with whatever inner
    # chrome CSS paints.
    card_bg = "#2a1226" if api.theme == "dark" else "#fbe9f1"
    window = webview.create_window(
        WINDOW_TITLE,
        html=html_doc,
        js_api=api,
        x=x, y=y,
        width=init_w, height=init_h,
        min_size=(80, 60),  # pywebview default is (200,100) — clips Small (140 px)
        frameless=True,
        easy_drag=False,
        on_top=api.topmost,
        resizable=False,
        background_color=card_bg,
    )
    api.window = window

    def on_closed():
        # Anchor is persisted on drag-end already; this catches edge
        # cases (user resizes externally, OS moves window). Skip if
        # api.save_anchor already ran in end_drag.
        try:
            api.save_anchor()
        except Exception as e:
            sys.stderr.write(f"save on close failed: {e}\n")

    window.events.closed += on_closed

    def on_loaded():
        # Hook the DOM-ready event rather than `webview.start`'s callback:
        # on pywebview 6 EdgeChromium, the start callback fires before
        # the WinForms Form is wired into window.native, so HWND discovery
        # comes back NULL. By `loaded`, the form exists and the window is
        # visible, so both `window.native.Handle` and EnumWindows work.
        sys.stderr.write(f"loaded; window.native = {window.native!r}\n")
        hwnd = find_hwnd(window)
        if not hwnd:
            sys.stderr.write("HWND discovery failed at loaded event\n")
            return
        api.hwnd = hwnd
        win32_move(hwnd, x, y, init_w, init_h, topmost=api.topmost)
        api._initialised = True
        sys.stderr.write(f"hwnd installed: {hwnd:#x}\n")

    window.events.loaded += on_loaded
    webview.start(debug=False)


if __name__ == "__main__":
    main()
