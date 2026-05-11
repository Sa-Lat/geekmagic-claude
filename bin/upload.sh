#!/usr/bin/env bash
# Upload 240x240 GIFs to Cube (/doUpload?dir=/image/).
# Usage: upload.sh                 # all *.gif in ../assets/240/
#        upload.sh <file.gif>...   # specific files
set -uo pipefail

[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
: "${CUBE_IP:?CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config}"
PROJ="$(cd "$(dirname "$0")/.." && pwd)"
DIR_240="$PROJ/assets/240"

upload_one() {
  local f="$1"
  printf "  %-20s " "$(basename "$f")"
  if curl -fsS -m 30 -F "file=@$f" "http://$CUBE_IP/doUpload?dir=/image/" >/dev/null 2>&1; then
    echo "OK ($(stat -c%s "$f") bytes)"
  else
    echo "FAIL"
    return 1
  fi
}

# pre-check
if ! curl -fsS -m 3 "http://$CUBE_IP/v.json" >/dev/null 2>&1; then
  echo "Cube unreachable at $CUBE_IP" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "Uploading $DIR_240/*.gif -> $CUBE_IP"
  shopt -s nullglob
  for f in "$DIR_240"/*.gif; do
    upload_one "$f" || true
  done
else
  for f in "$@"; do
    [[ -f "$f" ]] || { echo "skip $f (not a file)" >&2; continue; }
    upload_one "$f" || true
  done
fi

echo
echo "Free space: $(curl -fsS -m 3 "http://$CUBE_IP/space.json")"
