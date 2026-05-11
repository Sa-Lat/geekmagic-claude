#!/usr/bin/env python3
"""Generate placeholder Claude-status images with Pillow + upload to Cube.

Use this until proper pixel-art GIFs are made via the prompts/ workflow.
Produces three JPEGs (thinking, alert, idle) with simple text + bg color
matching the style guide palette.

Requirements: Pillow + requests
  pip install --user pillow requests

Usage:
  python3 ~/.claude/bin/cube-gen.py            # generate + upload all 3
  python3 ~/.claude/bin/cube-gen.py --no-upload  # write to /tmp/ only
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow missing: pip install --user pillow")

try:
    import requests
except ImportError:
    sys.exit("requests missing: pip install --user requests")

def _load_cube_ip() -> str:
    if v := os.environ.get("CUBE_IP"):
        return v
    candidates = [
        Path.home() / ".config" / "cube" / "config",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for p in candidates:
        if p.exists():
            for line in p.read_text().splitlines():
                line = line.strip()
                if line.startswith("CUBE_IP="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config")


CUBE_IP = _load_cube_ip()
SIZE = (240, 240)

BG_NAVY = (13, 21, 48)
CREAM = (244, 228, 207)
CYAN = (107, 182, 255)
ORANGE = (217, 119, 87)
RED = (229, 57, 53)
DIM = (120, 120, 140)

ASSETS = [
    ("thinking.jpg", "thinking...", BG_NAVY, ORANGE),
    ("alert.jpg",    "! ATTENTION", (90, 20, 25), (255, 240, 240)),
    ("idle.jpg",     "zzz",         (20, 24, 40), DIM),
]


def find_font(size=32):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render(text, bg, fg):
    img = Image.new("RGB", SIZE, bg)
    d = ImageDraw.Draw(img)
    font = find_font(36)
    bbox = d.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((SIZE[0] - w) / 2, (SIZE[1] - h) / 2 - 8), text, fill=fg, font=font)
    foot = find_font(14)
    fbb = d.textbbox((0, 0), "claude", font=foot)
    d.text(((SIZE[0] - (fbb[2] - fbb[0])) / 2, SIZE[1] - 28),
           "claude", fill=fg, font=foot)
    return img


def upload(img, name):
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    buf.seek(0)
    try:
        r = requests.post(
            f"http://{CUBE_IP}/doUpload",
            params={"dir": "/image/"},
            files={"file": (name, buf, "image/jpeg")},
            timeout=15,
        )
        print(f"{name}: HTTP {r.status_code}")
    except requests.RequestException as e:
        print(f"{name}: {e!s} (file may still have uploaded; check /filelist)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--out", default="/tmp")
    args = ap.parse_args()

    for name, label, bg, fg in ASSETS:
        img = render(label, bg, fg)
        if args.no_upload:
            path = Path(args.out) / name
            img.save(path, "JPEG", quality=85)
            print(f"wrote {path}")
        else:
            upload(img, name)


if __name__ == "__main__":
    main()
