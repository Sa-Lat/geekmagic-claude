#!/usr/bin/env bash
# Upload 240x240 GIFs to Cube (/doUpload?dir=/image/).
#
# Layout: assets/240/<skin>/<state>.gif (local) -> /image/<remote_name> (cube, flat)
#
# Cube filename convention (firmware does not navigate subdirs):
#   orb   -> <state>.gif           (no prefix, legacy)
#   <skin> -> <skin>_<state>.gif    (prefix)
#
# Usage: upload.sh                 # all skins
#        upload.sh <skin>          # one skin (e.g. waifu)
#        upload.sh <file.gif>...   # specific files; remote name inferred from
#                                  # parent dir (assets/240/<skin>/<state>.gif)
set -uo pipefail

[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
: "${CUBE_IP:?CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config}"
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
DIR_240="$PROJ/assets/240"

remote_name_for() {
  local f="$1"
  local state skin
  state="$(basename "$f" .gif)"
  skin="$(basename "$(dirname "$f")")"
  if [[ "$skin" == "orb" ]]; then
    echo "${state}.gif"
  else
    echo "${skin}_${state}.gif"
  fi
}

upload_one() {
  local f="$1"
  local remote
  remote="$(remote_name_for "$f")"
  printf "  %-30s -> %-26s " "${f#"$PROJ/"}" "$remote"
  if curl -fsS -m 30 -F "file=@$f;filename=$remote" "http://$CUBE_IP/doUpload?dir=/image/" >/dev/null 2>&1; then
    echo "OK ($(stat -c%s "$f") bytes)"
  else
    echo "FAIL"
    return 1
  fi
}

upload_skin() {
  local skin="$1"
  local skin_dir="$DIR_240/$skin"
  [[ -d "$skin_dir" ]] || { echo "skip $skin (no $skin_dir)" >&2; return; }
  shopt -s nullglob
  for f in "$skin_dir"/*.gif; do
    upload_one "$f" || true
  done
}

# pre-check
if ! curl -fsS -m 3 "http://$CUBE_IP/v.json" >/dev/null 2>&1; then
  echo "Cube unreachable at $CUBE_IP" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "Uploading all skins from $DIR_240/ -> $CUBE_IP"
  shopt -s nullglob
  for d in "$DIR_240"/*/; do
    skin="$(basename "$d")"
    echo "[$skin]"
    upload_skin "$skin"
  done
elif [[ -d "$DIR_240/$1" ]]; then
  echo "Uploading skin '$1'"
  upload_skin "$1"
else
  for f in "$@"; do
    [[ -f "$f" ]] || { echo "skip $f (not a file)" >&2; continue; }
    upload_one "$f" || true
  done
fi

echo
echo "Free space: $(curl -fsS -m 3 "http://$CUBE_IP/space.json")"
