#!/usr/bin/env bash
# Deploy project scripts to ~/.claude/bin/ so Claude Code hooks pick them up.
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$HOME/.claude/bin"
mkdir -p "$TARGET"

install -m 0755 "$PROJ/bin/cube.sh"          "$TARGET/cube.sh"
install -m 0755 "$PROJ/bin/cube-gen.py"      "$TARGET/cube-gen.py"
install -m 0755 "$PROJ/bin/cube-watchdog.sh" "$TARGET/cube-watchdog.sh"
install -m 0755 "$PROJ/bin/mock-cube.py"     "$TARGET/mock-cube.py"
install -m 0755 "$PROJ/bin/cube-overlay.py"  "$TARGET/cube-overlay.py"

UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"
install -m 0644 "$PROJ/bin/cube-watchdog.service" "$UNITS/cube-watchdog.service"
install -m 0644 "$PROJ/bin/mock-cube.service"     "$UNITS/mock-cube.service"
install -m 0644 "$PROJ/bin/cube-overlay.service"  "$UNITS/cube-overlay.service"

echo "Deployed:"
ls -la "$TARGET/cube.sh" "$TARGET/cube-gen.py" "$TARGET/cube-watchdog.sh" \
       "$TARGET/mock-cube.py" "$TARGET/cube-overlay.py"
echo
echo "systemd --user units installed in $UNITS/"
echo "  systemctl --user daemon-reload && systemctl --user enable --now mock-cube cube-overlay"

if "$TARGET/cube.sh" ping >/dev/null 2>&1; then
  echo "Cube ping OK"
else
  echo "Cube ping FAIL — scripts deployed but device unreachable" >&2
fi
