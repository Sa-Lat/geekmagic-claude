#!/usr/bin/env python3
"""cube-overlay — frameless always-on-top Tk dashboard that mirrors mock-cube
state. Renders one block per active Claude session (emoji + cwd + age) sorted
by state priority, plus 5h-window usage % and the winning state's GIF.

Run:
  python3 bin/cube-overlay.py --frameless
  CUBE_OVERLAY_X=3700 CUBE_OVERLAY_Y=920 python3 bin/cube-overlay.py --frameless

Env (defaults if CLI not given):
  CUBE_OVERLAY_MOCK         default http://127.0.0.1:8080
  CUBE_OVERLAY_X / _Y       window position
  CUBE_OVERLAY_SIZE         gif edge length (default 100)
  CUBE_OVERLAY_WIDTH        window width    (default = max(180, size+2*pad))
  CUBE_OVERLAY_MAX_BLOCKS   how many session blocks to show (default 5)
"""
import argparse
import io
import json
import os
import sys
import tkinter as tk
import urllib.request
from PIL import Image, ImageSequence, ImageTk

POLL_MS = 500
PAD = 6
BLOCK_H = 22
USAGE_H = 18
BG = "#000000"
FG_DIM = "#888888"
FG_BRIGHT = "#dddddd"

# Per-state visual identity: emoji + colored bg + fg. Mirrors cube.sh PRIO buckets.
STATE_VISUALS = {
    "permission": {"emoji": "🔐", "bg": "#5a4a14", "fg": "#ffeb85"},
    "error":      {"emoji": "❌", "bg": "#5a1414", "fg": "#ff9b9b"},
    "compact":    {"emoji": "📦", "bg": "#3a1f4a", "fg": "#d4a5ff"},
    "alert":      {"emoji": "⚠",  "bg": "#5a3914", "fg": "#ffc385"},
    "thinking":   {"emoji": "⚙",  "bg": "#1a2a3a", "fg": "#a5c8ff"},
    "done":       {"emoji": "✅", "bg": "#1a3a1f", "fg": "#9be5b0"},
    "start":      {"emoji": "👋", "bg": "#1a2a3a", "fg": "#a5d0ff"},
    "idle":       {"emoji": "💤", "bg": "#1a1a1a", "fg": "#777777"},
}


def format_age(s):
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h" if m == 0 else f"{h}h{m}m"


def block_text(sess):
    vis = STATE_VISUALS.get(sess["state"], STATE_VISUALS["idle"])
    cwd = sess.get("cwd") or "—"
    # Idle blocks omit the age — they'd tick second-by-second without value
    # and trigger reshuffles. Active states show age as a "what's fresh" cue.
    if sess["state"] == "idle":
        return f"{vis['emoji']} {cwd}"
    return f"{vis['emoji']} {cwd} · {format_age(sess['age_s'])}"


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


def usage_color(pct):
    if pct is None:
        return FG_DIM
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
    ap.add_argument("--mock", default=os.environ.get("CUBE_OVERLAY_MOCK", "http://127.0.0.1:8080"))
    ap.add_argument("--margin", type=int, default=20)
    ap.add_argument("--size", type=int,
                    default=int(os.environ.get("CUBE_OVERLAY_SIZE", 100)),
                    help="gif edge length (pixels)")
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

    win_w = args.width if args.width > 0 else max(180, args.size + 2 * PAD)

    root = tk.Tk()
    root.title("cube-overlay")
    if args.frameless:
        root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=BG)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    # Saved X/Y semantics: treat as the top-left of a legacy 120-wide × 150-tall
    # window. Derive the bottom-right anchor from that legacy footprint so the
    # corner stays put even when the new layout's width/height differ.
    LEGACY_W, LEGACY_H = 120, 150
    init_h = PAD + BLOCK_H + USAGE_H + args.size + 2 * PAD
    saved_x = args.x if args.x is not None else int(os.environ.get("CUBE_OVERLAY_X", sw - win_w - args.margin))
    saved_y = args.y if args.y is not None else int(os.environ.get("CUBE_OVERLAY_Y", sh - init_h - args.margin))
    anchor_right = saved_x + LEGACY_W
    anchor_bottom = saved_y + LEGACY_H
    x = anchor_right - win_w
    y = anchor_bottom - init_h
    print(f"mock={args.mock}  anchor=br({anchor_right},{anchor_bottom})  pos=+{x}+{y}  win={win_w}x{init_h}  gif={args.size}  max_blocks={args.max_blocks}", file=sys.stderr)
    root.geometry(f"{win_w}x{init_h}+{x}+{y}")

    # Session blocks container (dynamic children)
    blocks_frame = tk.Frame(root, bd=0, highlightthickness=0, bg=BG)
    blocks_frame.pack(side="top", fill="x", padx=PAD, pady=(PAD, 0))

    # Usage line (separator-style)
    usage_lbl = tk.Label(root, text="", fg=FG_DIM, bg=BG,
                         font=("TkDefaultFont", 9), anchor="w")
    usage_lbl.pack(side="top", fill="x", padx=PAD, pady=(2, 0))

    # GIF (Char) below
    gif_lbl = tk.Label(root, bd=0, highlightthickness=0, bg=BG)
    gif_lbl.pack(side="bottom", pady=(0, PAD))

    cur = {"img": None, "ts": 0, "frames": [], "durs": [], "idx": 0,
           "visible": True, "anim_job": None,
           "block_widgets": [],    # list of (Frame, Label) tuples
           "block_sig": None,      # signature of last-rendered session list
           "last_height": init_h,
           "anchor_right": anchor_right,
           "anchor_bottom": anchor_bottom}

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
            root.attributes("-topmost", True)
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
        h = PAD + max(1, n_blocks) * (BLOCK_H + 2) + USAGE_H + args.size + 2 * PAD
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
        # Signature: per-session tuple. Idle entries drop age entirely (no
        # age shown, no reshuffle on tick); active entries use 30s buckets so
        # per-second changes don't trigger re-render. Plus overflow count.
        def _sig_entry(s):
            return (s["cwd"], s["state"]) if s["state"] == "idle" \
                   else (s["cwd"], s["state"], s["age_s"] // 30)
        sig = tuple(_sig_entry(s) for s in shown) + (overflow,)
        if sig == cur["block_sig"]:
            return
        cur["block_sig"] = sig

        widgets = cur["block_widgets"]
        needed = len(shown) + (1 if overflow else 0)

        # Grow widget pool
        while len(widgets) < needed:
            fr = tk.Frame(blocks_frame, bd=0, highlightthickness=0, bg=BG)
            lbl = tk.Label(fr, text="", bg=BG, fg=FG_BRIGHT,
                           font=("TkDefaultFont", 9, "bold"), anchor="w",
                           padx=6, pady=2)
            lbl.pack(fill="x")
            fr.pack(fill="x", pady=(0, 2))
            widgets.append((fr, lbl))

        # Shrink widget pool
        while len(widgets) > needed:
            fr, _ = widgets.pop()
            fr.destroy()

        # Update text + colors
        for i, sess in enumerate(shown):
            vis = STATE_VISUALS.get(sess["state"], STATE_VISUALS["idle"])
            _, lbl = widgets[i]
            lbl.configure(text=block_text(sess), bg=vis["bg"], fg=vis["fg"])
        if overflow:
            _, lbl = widgets[len(shown)]
            lbl.configure(text=f"  +{overflow} more", bg=BG, fg=FG_DIM)

        resize_window(needed)

    def update_dashboard(d):
        render_sessions(d.get("sessions") or [])
        pct = d.get("usage_5h_pct")
        usage_lbl.configure(text=usage_label(pct), fg=usage_color(pct))

    def poll():
        s = fetch_dashboard(args.mock)
        if s is None:
            root.after(POLL_MS * 4, poll)
            return
        update_dashboard(s)
        if (s.get("img"), s.get("ts")) != (cur["img"], cur["ts"]):
            data = fetch_gif(args.mock)
            if data:
                load(data)
                cur["img"] = s.get("img")
                cur["ts"] = s.get("ts")
        show()
        root.after(POLL_MS, poll)

    # Idle no longer auto-hides; overlay stays visible as ambient display.

    root.bind("<Escape>", lambda _e: root.destroy())
    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
