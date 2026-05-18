#!/usr/bin/env bash
# Geekmagic SmallTV-Ultra controller for Claude Code hooks + manual use.
# Non-blocking: short timeout + always exit 0 so a dead Cube never blocks Claude.
#
# Multi-session aware: tracks state per Claude session_id (extracted from hook
# stdin JSON via jq). Aggregates by priority across all live sessions and
# pushes the winner GIF. Priority:
#   permission > error > compact > done > thinking > alert > idle
#
# State file: /tmp/.cube-sessions-$UID.json  (atomic via flock + temp+rename)
#   {"sessions": {"<sid>": {"state": "...", "ts": ..., "seq": N}},
#    "displayed": "...", "displayed_ts": ...}
# Stale entries pruned after CUBE_SESSION_TTL (default 3600s).
#
# Auto-revert: alert/permission/error/compact/done schedule a per-session
# revert that fires after N seconds. TOCTOU-safe via seq counter — if the
# session moved on (seq advanced), revert is a no-op.
#
# Skins: selector stored in ~/.claude/.cube-skin. Cube-side files are flat:
#   orb    -> /image/<state>.gif         (no prefix, legacy default)
#   waifu  -> /image/waifu_<state>.gif   (and dedicated permission/error/compact/done)
# Local sources are organized per-skin (assets/<skin>/<state>.gif); upload.sh
# translates to the flat cube convention since /image/ has no subdir support.
#
# Deprecated: CUBE_STATE_FILE (legacy single-label file, no longer used).

set -u
[[ -z "${CUBE_IP:-}" && -f "$HOME/.config/cube/config" ]] && source "$HOME/.config/cube/config"
[[ -z "${CUBE_IP:-}" && -f "$(dirname "$0")/../.env" ]] && source "$(dirname "$0")/../.env"
: "${CUBE_IP:?CUBE_IP not set — copy .env.example to .env or write CUBE_IP=<ip> to ~/.config/cube/config}"

TIMEOUT="${CUBE_TIMEOUT:-2}"
SKIN_FILE="${CUBE_SKIN_FILE:-$HOME/.claude/.cube-skin}"
SESSIONS_FILE="${CUBE_SESSIONS_FILE:-/tmp/.cube-sessions-$UID.json}"
SESSION_TTL="${CUBE_SESSION_TTL:-3600}"
ALERT_REVERT="${CUBE_ALERT_REVERT:-30}"
PERMISSION_REVERT="${CUBE_PERMISSION_REVERT:-0}"
ERROR_REVERT="${CUBE_ERROR_REVERT:-$ALERT_REVERT}"
COMPACT_REVERT="${CUBE_COMPACT_REVERT:-$ALERT_REVERT}"
DONE_REVERT="${CUBE_DONE_REVERT:-5}"
CURL=(curl -fsS -m "$TIMEOUT")
# Comma-separated host[:port] list; every state-mutation is fanned out here in
# addition to $CUBE_IP. Real cube failures are already silent — same for mirrors.
CUBE_MIRROR="${CUBE_MIRROR:-}"

# fan_set <query_suffix>  — fire /set?<suffix> to real cube + every mirror.
# All failures swallowed; non-blocking by design.
fan_set() {
  local suffix="$1" tgt
  "${CURL[@]}" "http://$CUBE_IP/set?$suffix" >/dev/null 2>&1 || true
  if [[ -n "$CUBE_MIRROR" ]]; then
    local IFS=','
    for tgt in $CUBE_MIRROR; do
      "${CURL[@]}" "http://$tgt/set?$suffix" >/dev/null 2>&1 || true
    done
  fi
}

skin_get() { cat "$SKIN_FILE" 2>/dev/null || echo orb; }
prefix() { case "$(skin_get)" in waifu) echo "waifu_" ;; *) echo "" ;; esac; }

gif_for() {
  local state="$1" pfx
  pfx="$(prefix)"
  # waifu skin has dedicated permission/error/compact GIFs; orb still falls back to alert.gif
  if [[ "$pfx" == "waifu_" ]]; then
    case "$state" in
      thinking|alert|permission|error|compact|done|idle) echo "${pfx}${state}.gif"; return ;;
    esac
  fi
  case "$state" in
    thinking)                       echo "${pfx}thinking.gif" ;;
    alert|permission|error|compact) echo "${pfx}alert.gif" ;;
    done)                           echo "${pfx}done.gif" ;;
    *)                              echo "${pfx}idle.gif" ;;
  esac
}

session_id_from_stdin() {
  if [[ -t 0 ]]; then echo cli; return; fi
  local sid
  sid=$(jq -r '.session_id // .conversation_id // "cli"' 2>/dev/null) || sid=cli
  echo "${sid:-cli}"
}

push() {
  fan_set "img=/image/$(gif_for "$1")"
}

# mutate <op> <sid> [<new_state>]
#   op=update  -> upsert session slot, bump seq
#   op=evict   -> remove session
# Prints "<winner>\t<seq>" (seq is '-' for evict). Atomic via flock + temp+rename.
mutate() {
  local op="$1" sid="$2" new_state="${3:-idle}"
  mkdir -p "$(dirname "$SESSIONS_FILE")" 2>/dev/null || true
  exec 9>"$SESSIONS_FILE.lock"
  flock -x 9 2>/dev/null || true
  python3 - "$SESSIONS_FILE" "$op" "$sid" "$new_state" "$SESSION_TTL" <<'PY'
import json, os, sys, tempfile, time
path, op, sid, new_state, ttl = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
try:
    with open(path) as f:
        data = json.load(f)
except (OSError, ValueError):
    data = {"sessions": {}, "displayed": "idle", "displayed_ts": 0}
now = time.time()
data["sessions"] = {k: v for k, v in (data.get("sessions") or {}).items()
                    if now - v.get("ts", 0) < ttl}
seq_out = "-"
if op == "update":
    prev = data["sessions"].get(sid, {})
    seq_out = prev.get("seq", 0) + 1
    data["sessions"][sid] = {"state": new_state, "ts": now, "seq": seq_out}
elif op == "evict":
    data["sessions"].pop(sid, None)
PRIO = {"permission": 5, "error": 4, "compact": 3, "done": 2.5, "thinking": 2, "alert": 1, "idle": 0}
if data["sessions"]:
    winner = max(data["sessions"].values(),
                 key=lambda v: PRIO.get(v.get("state", "idle"), 0))["state"]
else:
    winner = "idle"
data["displayed"] = winner
data["displayed_ts"] = now
d = os.path.dirname(path) or "."
fd, tmp = tempfile.mkstemp(dir=d, prefix=".cube-", suffix=".tmp")
with os.fdopen(fd, "w") as f:
    json.dump(data, f)
os.replace(tmp, path)
print(f"{winner}\t{seq_out}")
PY
  flock -u 9 2>/dev/null || true
  exec 9>&-
}

schedule_revert() {
  # schedule_revert <sid> <seq> <delay>
  local sid="$1" seq="$2" delay="$3"
  (( delay > 0 )) || return 0
  (
    sleep "$delay"
    local cur
    cur=$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit()
v = (d.get("sessions") or {}).get(sys.argv[2]) or {}
print(v.get("seq", ""))
' "$SESSIONS_FILE" "$sid" 2>/dev/null)
    if [[ "$cur" == "$seq" ]]; then
      local out winner
      out=$(mutate update "$sid" idle)
      winner="${out%%$'\t'*}"
      push "$winner"
    fi
  ) </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
}

show() {
  local new_state="$1" sid out winner seq delay=0
  sid=$(session_id_from_stdin)
  out=$(mutate update "$sid" "$new_state")
  winner="${out%%$'\t'*}"
  seq="${out##*$'\t'}"
  push "$winner"
  case "$new_state" in
    alert)      delay="$ALERT_REVERT" ;;
    permission) delay="$PERMISSION_REVERT" ;;
    error)      delay="$ERROR_REVERT" ;;
    compact)    delay="$COMPACT_REVERT" ;;
    done)       delay="$DONE_REVERT" ;;
  esac
  schedule_revert "$sid" "$seq" "$delay"
}

end_session() {
  local sid out winner
  sid=$(session_id_from_stdin)
  out=$(mutate evict "$sid")
  winner="${out%%$'\t'*}"
  push "$winner"
}

redisplay() {
  # Re-push current aggregated display state without mutating session map.
  # Used by the watchdog after a cube reboot to restore a known image.
  local winner
  winner=$(python3 - "$SESSIONS_FILE" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("idle")
    sys.exit()
print(d.get("displayed", "idle"))
PY
)
  push "${winner:-idle}"
}

case "${1:-}" in
  thinking|alert|permission|error|compact|done|idle) show "$1" ;;
  end)        end_session ;;
  redisplay)  redisplay ;;
  img)        fan_set "img=/image/${2:-}" ;;
  theme)      fan_set "theme=${2:-1}" ;;
  brt)        fan_set "brt=${2:-50}" ;;
  list)       "${CURL[@]}" "http://$CUBE_IP/filelist?dir=/image/" 2>&1 || true ;;
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
    echo "--- sessions ---"
    python3 - "$SESSIONS_FILE" <<'PY'
import json, sys, time
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("(no sessions file)")
    sys.exit()
now = time.time()
print(f"displayed: {d.get('displayed','idle')}")
sessions = d.get("sessions") or {}
if not sessions:
    print("(no live sessions)")
else:
    for sid, v in sessions.items():
        age = int(now - v.get("ts", 0))
        print(f"  {sid[:8]:<8}  {v.get('state',''):<10}  seq={v.get('seq','?'):>3}  age={age}s")
PY
    ;;
  ping)
    if "${CURL[@]}" "http://$CUBE_IP/v.json" >/dev/null 2>&1; then
      echo OK
    else
      echo FAIL >&2
      exit 1
    fi
    ;;
  *)
    cat >&2 <<EOF
cube.sh — Geekmagic SmallTV-Ultra controller (multi-session aware)

Usage: $0 <command> [arg]
  thinking | alert | permission | error | compact | done | idle
                               Per-session state. session_id is read from hook
                               stdin JSON (jq); manual CLI maps to "cli".
                               Aggregated across all live sessions by priority:
                                 permission > error > compact > done > thinking > alert > idle
                               Auto-revert (per-session, TOCTOU-safe via seq):
                                 alert      after CUBE_ALERT_REVERT s   (30)
                                 permission after CUBE_PERMISSION_REVERT s (0 = forever)
                                 error      after CUBE_ERROR_REVERT s   (= alert)
                                 compact    after CUBE_COMPACT_REVERT s (= alert)
                                 done       after CUBE_DONE_REVERT s    (5)
  end                          Evict current session_id (used by SessionEnd).
  redisplay                    Re-push current aggregated state (no mutation).
                               Used by cube-watchdog after device reboot.
  img <filename>               Show image (session-agnostic).
  skin [orb|waifu]             Get / set mascot skin.
  theme <1-7>                  1 Weather, 3 Album, 7 Simple.
  brt <-10..100>               Brightness (-10 = off).
  list                         List uploaded images.
  info                         Device + skin + live sessions + aggregate.
  ping                         Connectivity check (exits 1 on fail).

Hook mapping (mirrors peon-ping):
  SessionStart              -> idle
  UserPromptSubmit          -> thinking
  Stop                      -> done
  SessionEnd                -> end
  Notification              -> alert
  PermissionRequest         -> permission
  PostToolUseFailure (Bash) -> error
  PreCompact                -> compact

Env: CUBE_IP (required; or .env / ~/.config/cube/config),
     CUBE_TIMEOUT (default 2),
     CUBE_SKIN_FILE (default ~/.claude/.cube-skin),
     CUBE_SESSIONS_FILE (default /tmp/.cube-sessions-\$UID.json),
     CUBE_SESSION_TTL (default 3600 seconds — stale-session prune),
     CUBE_ALERT_REVERT (default 30; 0 = forever),
     CUBE_PERMISSION_REVERT (default 0 = forever),
     CUBE_ERROR_REVERT / CUBE_COMPACT_REVERT (default = ALERT_REVERT),
     CUBE_DONE_REVERT (default 5)
EOF
    ;;
esac
exit 0
