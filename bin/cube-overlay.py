#!/usr/bin/env python3
"""cube-overlay — frameless always-on-top Tk window that mirrors mock-cube
state. Hidden when state=idle, animated GIF otherwise.

Run:
  python3 bin/cube-overlay.py --frameless
  CUBE_OVERLAY_X=3700 CUBE_OVERLAY_Y=920 python3 bin/cube-overlay.py --frameless

Env (defaults if CLI not given):
  CUBE_OVERLAY_MOCK  default http://127.0.0.1:8080
  CUBE_OVERLAY_X / CUBE_OVERLAY_Y  window position
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


def fetch_state(mock):
    try:
        with urllib.request.urlopen(f"{mock}/state.json", timeout=1) as r:
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", default=os.environ.get("CUBE_OVERLAY_MOCK", "http://127.0.0.1:8080"))
    ap.add_argument("--margin", type=int, default=20)
    ap.add_argument("--size", type=int, default=120)
    ap.add_argument("--x", type=int, default=None, help="window X; env CUBE_OVERLAY_X")
    ap.add_argument("--y", type=int, default=None, help="window Y; env CUBE_OVERLAY_Y")
    ap.add_argument("--frameless", action="store_true", help="overrideredirect borderless")
    args = ap.parse_args()

    root = tk.Tk()
    root.title("cube-overlay")
    if args.frameless:
        root.overrideredirect(True)
    root.attributes("-topmost", True)

    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    x = args.x if args.x is not None else int(os.environ.get("CUBE_OVERLAY_X", sw - args.size - args.margin))
    y = args.y if args.y is not None else int(os.environ.get("CUBE_OVERLAY_Y", sh - args.size - args.margin))
    print(f"mock={args.mock}  pos=+{x}+{y}  size={args.size}", file=sys.stderr)
    root.geometry(f"{args.size}x{args.size}+{x}+{y}")

    label = tk.Label(root, bd=0, highlightthickness=0)
    label.pack()

    # mutable holders to dodge nonlocal/global boilerplate
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
        label.configure(image=cur["frames"][cur["idx"]])
        cur["anim_job"] = root.after(cur["durs"][cur["idx"]], animate)

    def load(gif_bytes):
        pil_frames, durs = load_frames(gif_bytes, args.size)
        cur["frames"] = [ImageTk.PhotoImage(f) for f in pil_frames]
        cur["durs"] = durs
        cur["idx"] = 0
        if cur["anim_job"]:
            root.after_cancel(cur["anim_job"])
            cur["anim_job"] = None
        label.configure(image=cur["frames"][0])
        if len(cur["frames"]) > 1:
            cur["anim_job"] = root.after(durs[0], animate)

    def poll():
        s = fetch_state(args.mock)
        if s is None:
            root.after(POLL_MS * 4, poll)
            return
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

    # start hidden — wait for first poll before showing anything
    root.withdraw()
    cur["visible"] = False

    root.bind("<Escape>", lambda _e: root.destroy())
    root.after(100, poll)
    root.mainloop()


if __name__ == "__main__":
    main()
