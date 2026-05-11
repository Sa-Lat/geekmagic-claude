#!/usr/bin/env bash
# Resize GIFs to 240x240 (Cube native resolution) using nearest-neighbor.
# Usage: resize.sh                   # all GIFs in ../assets/ → ../assets/240/
#        resize.sh <file.gif>...     # specific files → next to source
set -euo pipefail

if ! command -v gifsicle >/dev/null 2>&1; then
  echo "gifsicle missing: sudo apt install gifsicle" >&2
  exit 1
fi

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$PROJ/assets"
OUT_DIR="$SRC_DIR/240"
mkdir -p "$OUT_DIR"

resize_one() {
  local in="$1" out="$2"
  gifsicle --resize 240x240 --resize-method=sample -o "$out" "$in"
  printf "  %s -> %s (%s bytes)\n" "$(basename "$in")" "$out" "$(stat -c%s "$out")"
}

if [[ $# -eq 0 ]]; then
  echo "Resizing all GIFs in $SRC_DIR/ -> $OUT_DIR/"
  shopt -s nullglob
  for f in "$SRC_DIR"/*.gif; do
    resize_one "$f" "$OUT_DIR/$(basename "$f")"
  done
else
  for f in "$@"; do
    [[ -f "$f" ]] || { echo "skip $f (not a file)" >&2; continue; }
    out_dir="$(dirname "$f")"
    name="$(basename "$f")"
    resize_one "$f" "$out_dir/240-$name"
  done
fi
