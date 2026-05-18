#!/usr/bin/env bash
# Resize GIFs to 240x240 (Cube native resolution) using nearest-neighbor.
# Layout: assets/<skin>/<state>.gif -> assets/240/<skin>/<state>.gif
#
# Usage: resize.sh                   # all skins, all states
#        resize.sh <skin>            # one skin (e.g. waifu)
#        resize.sh <file.gif>...     # specific files -> next to source as 240-<name>
set -euo pipefail

if ! command -v gifsicle >/dev/null 2>&1; then
  echo "gifsicle missing: sudo apt install gifsicle" >&2
  exit 1
fi

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
SRC_DIR="$PROJ/assets"
OUT_DIR="$SRC_DIR/240"

resize_one() {
  local in="$1" out="$2"
  mkdir -p "$(dirname "$out")"
  gifsicle --resize 240x240 --resize-method=sample -o "$out" "$in"
  printf "  %s -> %s (%s bytes)\n" "${in#"$PROJ/"}" "${out#"$PROJ/"}" "$(stat -c%s "$out")"
}

resize_skin() {
  local skin="$1"
  local skin_src="$SRC_DIR/$skin"
  [[ -d "$skin_src" ]] || { echo "skip $skin (no $skin_src)" >&2; return; }
  shopt -s nullglob
  local found=0
  for f in "$skin_src"/*.gif; do
    resize_one "$f" "$OUT_DIR/$skin/$(basename "$f")"
    found=1
  done
  [[ $found -eq 1 ]] || echo "  (no .gif in $skin_src)"
}

if [[ $# -eq 0 ]]; then
  echo "Resizing all skins in $SRC_DIR/ -> $OUT_DIR/"
  shopt -s nullglob
  for d in "$SRC_DIR"/*/; do
    skin="$(basename "$d")"
    [[ "$skin" == "240" || "$skin" == "desktop" ]] && continue
    echo "[$skin]"
    resize_skin "$skin"
  done
elif [[ -d "$SRC_DIR/$1" ]]; then
  # Single skin
  echo "Resizing skin '$1'"
  resize_skin "$1"
else
  # Explicit files: write 240-<name> next to source (caller responsibility)
  for f in "$@"; do
    [[ -f "$f" ]] || { echo "skip $f (not a file)" >&2; continue; }
    out_dir="$(dirname "$f")"
    name="$(basename "$f")"
    resize_one "$f" "$out_dir/240-$name"
  done
fi
