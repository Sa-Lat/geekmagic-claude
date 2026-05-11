#!/usr/bin/env bash
# Geekmagic SmallTV-Ultra controller for Claude Code hooks + manual use.
# Non-blocking: short timeout + always exit 0 so a dead Cube never blocks Claude.
#
# Skins: filename prefix selects mascot set. Stored in ~/.claude/.cube-skin.
#   orb    -> thinking.gif / alert.gif / idle.gif        (default)
#   waifu  -> waifu_thinking.gif / waifu_alert.gif / waifu_idle.gif
#
# Alert auto-revert: after ALERT_REVERT seconds, falls back to idle.
# Background job is skipped if a newer state was set in the meantime.

set -u
[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
: "${CUBE_IP:?CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config}"
TIMEOUT="${CUBE_TIMEOUT:-2}"
SKIN_FILE="${CUBE_SKIN_FILE:-$HOME/.claude/.cube-skin}"
STATE_FILE="${CUBE_STATE_FILE:-/tmp/.cube-state-$UID}"
ALERT_REVERT="${CUBE_ALERT_REVERT:-12}"
PERMISSION_REVERT="${CUBE_PERMISSION_REVERT:-30}"
CURL=(curl -fsS -m "$TIMEOUT")

skin_get() { cat "$SKIN_FILE" 2>/dev/null || echo orb; }

prefix() {
  case "$(skin_get)" in
    waifu) echo "waifu_" ;;
    *)     echo "" ;;
  esac
}

show() {
  # show <state-label> <filename>
  local label="$1" file="$2"
  echo "$label" > "$STATE_FILE" 2>/dev/null || true
  "${CURL[@]}" "http://$CUBE_IP/set?img=/image/$file" >/dev/null 2>&1 || true
}

schedule_revert() {
  # schedule_revert <state-label> <seconds>
  # if no newer state arrives within N seconds, set idle.
  local current_label="$1" delay="$2"
  (( delay > 0 )) || return 0
  (
    sleep "$delay"
    if [[ "$(cat "$STATE_FILE" 2>/dev/null)" == "$current_label" ]]; then
      show idle "$(prefix)idle.gif"
    fi
  ) </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
}

case "${1:-}" in
  thinking)   show thinking   "$(prefix)thinking.gif" ;;
  alert)      show alert      "$(prefix)alert.gif"; schedule_revert alert "$ALERT_REVERT" ;;
  permission) show permission "$(prefix)alert.gif"; schedule_revert permission "$PERMISSION_REVERT" ;;
  idle)       show idle       "$(prefix)idle.gif" ;;
  img)      show img-"${2:-?}" "${2:-}" ;;
  theme)    "${CURL[@]}" "http://$CUBE_IP/set?theme=${2:-1}" >/dev/null 2>&1 || true ;;
  brt)      "${CURL[@]}" "http://$CUBE_IP/set?brt=${2:-50}"  >/dev/null 2>&1 || true ;;
  list)     "${CURL[@]}" "http://$CUBE_IP/filelist?dir=/image/" 2>&1 || true ;;
  skin)
    case "${2:-}" in
      orb|waifu)
        mkdir -p "$(dirname "$SKIN_FILE")"
        echo "$2" > "$SKIN_FILE"
        echo "skin: $2"
        ;;
      ""|show|status)
        echo "current: $(skin_get)"
        echo "available: orb, waifu"
        ;;
      *) echo "unknown skin: $2 (use orb|waifu)" >&2; exit 1 ;;
    esac
    ;;
  info)
    echo "--- v ---";     "${CURL[@]}" "http://$CUBE_IP/v.json"     2>&1 || true; echo
    echo "--- app ---";   "${CURL[@]}" "http://$CUBE_IP/app.json"   2>&1 || true; echo
    echo "--- space ---"; "${CURL[@]}" "http://$CUBE_IP/space.json" 2>&1 || true; echo
    echo "--- skin ---";  echo "$(skin_get) (prefix=\"$(prefix)\")"
    echo "--- state ---"; echo "$(cat "$STATE_FILE" 2>/dev/null || echo none) (revert in ${ALERT_REVERT}s on alert)"
    ;;
  ping)
    if "${CURL[@]}" "http://$CUBE_IP/v.json" >/dev/null 2>&1; then
      echo "OK"
    else
      echo "FAIL" >&2
      exit 1
    fi
    ;;
  *)
    cat >&2 <<EOF
cube.sh — Geekmagic SmallTV-Ultra controller

Usage: $0 <command> [arg]
  thinking | alert | permission | idle
                               Show status GIF (uses current skin)
                               alert auto-reverts after CUBE_ALERT_REVERT s,
                               permission after CUBE_PERMISSION_REVERT s
  img <filename>               Show specific image in /image/
  skin [orb|waifu]             Get / set mascot skin
  theme <1-7>                  Switch cube theme (1 Weather, 3 Album, 7 Simple)
  brt <-10..100>               Set brightness
  list                         List uploaded images
  info                         Dump device + skin + state info
  ping                         Connectivity check (exits 1 on fail)

Env: CUBE_IP (required; or set in .env / ~/.config/cube/config),
     CUBE_TIMEOUT (default 2),
     CUBE_SKIN_FILE (default ~/.claude/.cube-skin),
     CUBE_ALERT_REVERT (default 12 seconds; 0 disables),
     CUBE_PERMISSION_REVERT (default 30 seconds; 0 disables)
EOF
    ;;
esac
exit 0
