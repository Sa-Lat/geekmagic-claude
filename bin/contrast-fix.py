#!/usr/bin/env python3
"""Per-frame Saturation / Contrast / Sharpness adjustment for animated GIFs.

Rescues 1-2px dark detail (eyelashes, eyebrows, outlines) from quantization
loss on mono-palette anime pixel-art before Cube display.

Defaults match prompts/04-workflow.md recipe (Sat -10, Con +30). The Sharpness
boost is on top of the documented recipe and helps preserve thin dark lines
across palette reduction by pulling pixel-neighbor contrast up.

Usage:
    contrast-fix.py <in.gif> <out.gif> [--sat 0.85] [--con 1.45] [--sharp 1.5]
"""
import argparse
import sys
from PIL import Image, ImageEnhance, ImageSequence


def adjust(im, sat, con, sharp):
    im = im.convert("RGB")
    if sat != 1.0:
        im = ImageEnhance.Color(im).enhance(sat)
    if con != 1.0:
        im = ImageEnhance.Contrast(im).enhance(con)
    if sharp != 1.0:
        im = ImageEnhance.Sharpness(im).enhance(sharp)
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--sat", type=float, default=0.85, help="0.85 = -15%")
    ap.add_argument("--con", type=float, default=1.45, help="1.45 = +45%")
    ap.add_argument("--sharp", type=float, default=1.5, help="1.5 = +50%")
    ap.add_argument("--colors", type=int, default=64)
    args = ap.parse_args()

    src = Image.open(args.input)
    frames, durations = [], []
    for frame in ImageSequence.Iterator(src):
        rgb = adjust(frame, args.sat, args.con, args.sharp)
        q = rgb.quantize(colors=args.colors, dither=Image.Dither.NONE)
        frames.append(q)
        durations.append(frame.info.get("duration", 170))

    loop = src.info.get("loop", 0)
    frames[0].save(
        args.output,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=loop,
        disposal=2,
        optimize=False,
    )
    print(
        f"  {args.input} -> {args.output} "
        f"(sat={args.sat}, con={args.con}, sharp={args.sharp}, colors={args.colors})"
    )


if __name__ == "__main__":
    sys.exit(main())
