#!/usr/bin/env bash
# Visual smoke-test: cycle through all 7 status states on the Cube.
# Usage: cycle.sh [delay_seconds]   # default 4
#        cycle.sh short             # only thinking/alert/idle (legacy 3-state)
set -euo pipefail

CUBE="$(dirname "$0")/cube.sh"

if [[ "${1:-}" == "short" ]]; then
  STATES=(thinking alert idle)
  DELAY=5
else
  STATES=(thinking alert permission error compact done idle)
  DELAY="${1:-4}"
fi

for state in "${STATES[@]}"; do
  printf "%-11s " "$state"
  "$CUBE" "$state"
  echo "(showing for ${DELAY}s)"
  sleep "$DELAY"
done

[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
echo "final state: $(curl -fsS -m 3 "http://${CUBE_IP}/app.json")"
