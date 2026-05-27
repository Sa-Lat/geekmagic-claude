#!/usr/bin/env bash
# Deploy WSL-side runtime to ~/.claude/bin/ so Claude Code hooks pick it up.
set -euo pipefail

PROJ="$(cd "$(dirname "$0")/.." && pwd)"
TARGET="$HOME/.claude/bin"
mkdir -p "$TARGET"

install -m 0755 "$PROJ/bin/cube.sh"      "$TARGET/cube.sh"
install -m 0755 "$PROJ/bin/mock-cube.py" "$TARGET/mock-cube.py"

UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"
install -m 0644 "$PROJ/bin/mock-cube.service" "$UNITS/mock-cube.service"

echo "Deployed:"
ls -la "$TARGET/cube.sh" "$TARGET/mock-cube.py"
echo
echo "systemd --user unit installed in $UNITS/"
echo "  systemctl --user daemon-reload && systemctl --user enable --now mock-cube"
