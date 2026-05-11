#!/usr/bin/env bash
# Delete all images on the Cube EXCEPT the 3 status assets (thinking/alert/idle).
# Useful for freeing space before uploading new versions.
# Usage: clear-old.sh             # dry-run, lists what would be deleted
#        clear-old.sh --force     # actually delete
set -euo pipefail

[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
: "${CUBE_IP:?CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config}"
KEEP_RE="^(thinking|alert|idle)\.gif$"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

echo "Cube: $CUBE_IP"
echo "Keep: thinking.gif, alert.gif, idle.gif"
echo

files=$(curl -fsS -m 5 "http://$CUBE_IP/filelist?dir=/image/" \
  | grep -oP "href='/image/[^']+'" | sed -E "s|href='/image//?||; s|'$||" | sort -u)

if [[ -z "$files" ]]; then
  echo "no files on cube"
  exit 0
fi

while read -r f; do
  [[ -z "$f" ]] && continue
  if [[ "$f" =~ $KEEP_RE ]]; then
    printf "  keep:   %s\n" "$f"
  else
    if (( FORCE )); then
      if curl -fsS -m 5 "http://$CUBE_IP/delete?file=/image/$f" >/dev/null 2>&1; then
        printf "  DELETE: %s\n" "$f"
      else
        printf "  FAIL:   %s\n" "$f"
      fi
    else
      printf "  would-delete: %s\n" "$f"
    fi
  fi
done <<<"$files"

echo
echo "Free space: $(curl -fsS -m 3 "http://$CUBE_IP/space.json")"
(( FORCE )) || echo "(dry-run; pass --force to actually delete)"
