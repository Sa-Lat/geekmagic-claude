#!/usr/bin/env python3
"""cube-overlay — frameless always-on-top Tk dashboard that mirrors mock-cube
state. Two text lines (project cwd, 5h-window usage %) above the animated GIF.
Hidden when state=idle.

Run:
  python3 bin/cube-overlay.py --frameless
  CUBE_OVERLAY_X=3700 CUBE_OVERLAY_Y=920 python3 bin/cube-overlay.py --frameless

Env (defaults if CLI not given):
  CUBE_OVERLAY_MOCK   default http://127.0.0.1:8080
  CUBE_OVERLAY_X / CUBE_OVERLAY_Y   window position
  CUBE_OVERLAY_SIZE   gif edge length (default 100)
  CUBE_OVERLAY_WIDTH  window width    (default = size + 2*pad, min 120)
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
TEXT_H = 38  # height of the two-line dashboard above the gif
BG = "#000000"
FG_DIM = "#888888"
FG_BRIGHT = "#dddddd"


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
            rgba = rgba.resize((size, size), Image.NEAREST)
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
    ap.add_argument("--x", type=int, default=None, help="window X; env CUBE_OVERLAY_X")
    ap.add_argument("--y", type=int, default=None, help="window Y; env CUBE_OVERLAY_Y")
    ap.add_argument("--frameless", action="store_true", help="overrideredirect borderless")
    args = ap.parse_args()

    win_w = args.width if args.width > 0 else max(120, args.size + 2 * PAD)
    win_h = TEXT_H + args.size + 2 * PAD

    root = tk.Tk()
    root.title("cube-overlay")
    if args.frameless:
        root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.configure(bg=BG)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    x = args.x if args.x is not None else int(os.environ.get("CUBE_OVERLAY_X", sw - win_w - args.margin))
    y = args.y if args.y is not None else int(os.environ.get("CUBE_OVERLAY_Y", sh - win_h - args.margin))
    print(f"mock={args.mock}  pos=+{x}+{y}  win={win_w}x{win_h}  gif={args.size}", file=sys.stderr)
    root.geometry(f"{win_w}x{win_h}+{x}+{y}")

    # Top dashboard frame (cwd + 5h usage)
    top = tk.Frame(root, bd=0, highlightthickness=0, bg=BG, height=TEXT_H)
    top.pack(side="top", fill="x", padx=PAD, pady=(PAD, 0))
    top.pack_propagate(False)
    cwd_lbl = tk.Label(top, text="", fg=FG_BRIGHT, bg=BG,
                       font=("TkDefaultFont", 9, "bold"), anchor="w")
    cwd_lbl.pack(anchor="w", fill="x")
    usage_lbl = tk.Label(top, text="", fg=FG_DIM, bg=BG,
                         font=("TkDefaultFont", 9), anchor="w")
    usage_lbl.pack(anchor="w", fill="x")

    # GIF below
    gif_lbl = tk.Label(root, bd=0, highlightthickness=0, bg=BG)
    gif_lbl.pack(side="bottom", pady=(0, PAD))

    cur = {"img": None, "ts": 0, "frames": [], "durs": [], "idx": 0,
           "visible": True, "anim_job": None}

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

    def update_dashboard(d):
        cwd = (d.get("cwd") or "").strip()
        cwd_lbl.configure(text=cwd if cwd else "—")
        pct = d.get("usage_5h_pct")
        usage_lbl.configure(text=usage_label(pct), fg=usage_color(pct))

    def poll():
        s = fetch_dashboard(args.mock)
        if s is None:
            root.after(POLL_MS * 4, poll)
            return
        update_dashboard(s)
        state = s.get("state", "idle")
        if state == "idle":
            hide()
        else:
            if (s.get("img"), s.get("ts")) != (cur["img"], cur["ts"]):
                data = fetch_gif(args.mock)
                if data:
                    load(data)
                    cur["img"] = s.get("img")
                    cur["ts"] = s.get("ts")
            show()
        root.after(POLL_MS, poll)

    root.withdraw()
    cur["visible"] = False

    root.bind("<Escape>", lambda _e: root.destroy())
    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
