#!/usr/bin/env bash
# Poll cube reachability. On offline -> online transition (i.e. cube finished
# booting after a power cycle / firmware crash), re-push the current
# aggregated display state via `cube.sh redisplay`.
#
# Without this daemon a cube reboot leaves whatever image the firmware lands on
# until the next Claude hook fires; with it, the cube always returns to its
# Claude-driven state within $CUBE_WATCHDOG_INTERVAL seconds.
#
# Run as a long-lived process. systemd --user unit shipped next to this script
# (bin/cube-watchdog.service); also fine via `nohup ... &` or tmux/screen.
#
# Env:
#   CUBE_IP                 (required, same lookup as cube.sh)
#   CUBE_WATCHDOG_INTERVAL  poll seconds, default 15
#   CUBE_WATCHDOG_PING_TIMEOUT  curl -m for each probe, default 3
set -u

[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
: "${CUBE_IP:?CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config}"

CUBE="$(dirname "$0")/cube.sh"
INTERVAL="${CUBE_WATCHDOG_INTERVAL:-15}"
PING_TIMEOUT="${CUBE_WATCHDOG_PING_TIMEOUT:-3}"

log() { printf "%s cube-watchdog %s\n" "$(date -Iseconds)" "$*"; }

probe() {
  curl -fsS -m "$PING_TIMEOUT" "http://$CUBE_IP/v.json" >/dev/null 2>&1
}

trap 'log "exit"; exit 0' INT TERM

log "starting (cube=$CUBE_IP interval=${INTERVAL}s)"
prev=unknown
while true; do
  if probe; then
    state=up
  else
    state=down
  fi
  if [[ "$state" == "up" && "$prev" != "up" ]]; then
    "$CUBE" redisplay >/dev/null 2>&1 || true
    log "reconnect detected (prev=$prev) -> redisplay pushed"
  elif [[ "$state" == "down" && "$prev" == "up" ]]; then
    log "cube went offline"
  fi
  prev="$state"
  sleep "$INTERVAL"
done
