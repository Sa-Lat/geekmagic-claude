#!/usr/bin/env bash
# Deploy project scripts to ~/.claude/bin/ so Claude Code hooks pick them up.
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$HOME/.claude/bin"
mkdir -p "$TARGET"

install -m 0755 "$PROJ/bin/cube.sh"          "$TARGET/cube.sh"
install -m 0755 "$PROJ/bin/cube-gen.py"      "$TARGET/cube-gen.py"
install -m 0755 "$PROJ/bin/cube-watchdog.sh" "$TARGET/cube-watchdog.sh"

echo "Deployed:"
ls -la "$TARGET/cube.sh" "$TARGET/cube-gen.py" "$TARGET/cube-watchdog.sh"

if "$TARGET/cube.sh" ping >/dev/null 2>&1; then
  echo "Cube ping OK"
else
  echo "Cube ping FAIL — scripts deployed but device unreachable" >&2
fi
