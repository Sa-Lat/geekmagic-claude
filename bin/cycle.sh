#!/usr/bin/env bash
# Visual smoke-test: cycle through thinking → alert → idle on the Cube.
# Usage: cycle.sh [delay_seconds]   # default 5
set -euo pipefail

DELAY="${1:-5}"
CUBE="$(dirname "$0")/cube.sh"

for state in thinking alert idle; do
  printf "%-9s " "$state"
  "$CUBE" "$state"
  echo "(showing for ${DELAY}s)"
  sleep "$DELAY"
done

[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
echo "final state: $(curl -fsS -m 3 "http://${CUBE_IP}/app.json")"
