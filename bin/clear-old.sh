#!/usr/bin/env bash
# Delete all images on the Cube EXCEPT the active status assets.
# Keep = anything matching <state>.gif (orb) or <skin>_<state>.gif (other skins),
# derived from the local layout assets/240/<skin>/<state>.gif.
# Usage: clear-old.sh             # dry-run, lists what would be deleted
#        clear-old.sh --force     # actually delete
set -euo pipefail

[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
: "${CUBE_IP:?CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config}"

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
DIR_240="$PROJ/assets/240"

# Build keep-list from local layout: orb files keep their state name, others
# get <skin>_ prefix (mirror of upload.sh remote_name_for).
keep_files=()
if [[ -d "$DIR_240" ]]; then
  shopt -s nullglob
  for skin_dir in "$DIR_240"/*/; do
    skin="$(basename "$skin_dir")"
    for f in "$skin_dir"*.gif; do
      state="$(basename "$f" .gif)"
      if [[ "$skin" == "orb" ]]; then
        keep_files+=("${state}.gif")
      else
        keep_files+=("${skin}_${state}.gif")
      fi
    done
  done
fi

if [[ ${#keep_files[@]} -eq 0 ]]; then
  echo "warning: no local files under $DIR_240 — falling back to legacy keep-list" >&2
  keep_files=(thinking.gif alert.gif idle.gif done.gif)
fi

# Build alternation regex: ^(a\.gif|b\.gif|...)$
KEEP_RE="^($(IFS='|'; echo "${keep_files[*]}"))$"
KEEP_RE="${KEEP_RE//./\\.}"

FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

echo "Cube: $CUBE_IP"
echo "Keep (${#keep_files[@]} files):"
printf "  %s\n" "${keep_files[@]}"
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
