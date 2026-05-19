#!/usr/bin/env bash
# Geekmagic SmallTV-Ultra controller for Claude Code hooks + manual use.
# Non-blocking: short timeout + always exit 0 so a dead Cube never blocks Claude.
#
# Multi-session aware: tracks state per Claude session_id (extracted from hook
# stdin JSON via jq). Aggregates by priority across all live sessions and
# pushes the winner GIF. Priority:
#   permission > error > compact > done > thinking > alert > start > idle
#
# State file: /tmp/.cube-sessions-$UID.json  (atomic via flock + temp+rename)
#   {"sessions": {"<sid>": {"state": "...", "ts": ..., "seq": N,
#                            "prev_state": "thinking|idle"}},
#    "displayed": "...", "displayed_ts": ...}
# prev_state captured on entry to alert/error/compact = last stable state.
# Stale entries pruned after CUBE_SESSION_TTL (default 3600s).
#
# Auto-revert: alert/permission/error/compact/done/start schedule a per-session
# revert that fires after N seconds. TOCTOU-safe via seq counter — if the
# session moved on (seq advanced), revert is a no-op.
# Revert target: alert/error/compact/permission -> prev_state (thinking/idle);
#                done/start -> idle (hardcoded — task ended).
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
ALERT_REVERT="${CUBE_ALERT_REVERT:-5}"
PERMISSION_REVERT="${CUBE_PERMISSION_REVERT:-$ALERT_REVERT}"
ERROR_REVERT="${CUBE_ERROR_REVERT:-$ALERT_REVERT}"
COMPACT_REVERT="${CUBE_COMPACT_REVERT:-$ALERT_REVERT}"
DONE_REVERT="${CUBE_DONE_REVERT:-5}"
START_REVERT="${CUBE_START_REVERT:-$DONE_REVERT}"
# Stop hook fires after the post-compact recap message. Suppress that `done`
# blip if `compact` was seen in this session within RECAP_WINDOW seconds.
# 0 = disable suppression. Cleared on next `thinking` (real user turn).
RECAP_WINDOW="${CUBE_RECAP_WINDOW:-60}"
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
  # start is a visual alias for done (wave anim on SessionStart) — no own GIF.
  [[ "$state" == "start" ]] && state="done"
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

# Parse hook stdin JSON into (sid, cwd) in one shot. Stdin is consumed exactly
# once by the caller and passed as the sole argument — avoids stdin-already-eaten
# bugs from running multiple `$(...)` subshells against the same pipe.
parse_hook() {
  local hook_in="$1"
  if [[ -z "$hook_in" ]]; then
    printf 'cli\t'
    return
  fi
  python3 - "$hook_in" <<'PY' 2>/dev/null || printf 'cli\t'
import json, sys
try:
    d = json.loads(sys.argv[1])
except Exception:
    print("cli\t"); sys.exit()
sid = d.get("session_id") or d.get("conversation_id") or "cli"
cwd = d.get("cwd") or ""
print(f"{sid}\t{cwd}")
PY
}

push() {
  fan_set "img=/image/$(gif_for "$1")"
}

# mutate <op> <sid> [<new_state> [<cwd>]]
#   op=update  -> upsert session slot, bump seq
#   op=evict   -> remove session
# Prints "<winner>\t<seq>" (seq is '-' for evict, -1 for recap-suppressed).
# Atomic via flock + temp+rename.
mutate() {
  local op="$1" sid="$2" new_state="${3:-idle}" cwd="${4:-}"
  mkdir -p "$(dirname "$SESSIONS_FILE")" 2>/dev/null || true
  exec 9>"$SESSIONS_FILE.lock"
  flock -x 9 2>/dev/null || true
  python3 - "$SESSIONS_FILE" "$op" "$sid" "$new_state" "$SESSION_TTL" "$RECAP_WINDOW" "$cwd" <<'PY'
import json, os, sys, tempfile, time
path, op, sid, new_state = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
ttl, recap_window = int(sys.argv[5]), int(sys.argv[6])
cwd = sys.argv[7] if len(sys.argv) > 7 else ""
try:
    with open(path) as f:
        data = json.load(f)
except (OSError, ValueError):
    data = {"sessions": {}, "displayed": "idle", "displayed_cwd": "", "displayed_ts": 0}
now = time.time()
data["sessions"] = {k: v for k, v in (data.get("sessions") or {}).items()
                    if now - v.get("ts", 0) < ttl}
seq_out = "-"
if op == "update":
    prev = data["sessions"].get(sid, {})
    # Recap suppression: `done` shortly after `compact` is the post-compact
    # recap Stop. Skip — no state change, no seq bump. Compact's own revert
    # timer (already running) handles return to idle.
    if (new_state == "done" and recap_window > 0
            and prev.get("compact_ts")
            and now - prev["compact_ts"] < recap_window):
        prev = dict(prev)
        prev.pop("compact_ts", None)
        data["sessions"][sid] = prev
        seq_out = -1
    else:
        seq_out = prev.get("seq", 0) + 1
        entry = {"state": new_state, "ts": now, "seq": seq_out,
                 "started_at": prev.get("started_at", now)}
        if new_state == "compact":
            entry["compact_ts"] = now
        elif new_state != "thinking" and "compact_ts" in prev:
            entry["compact_ts"] = prev["compact_ts"]
        # prev_state: captured on entry to transient states (alert/error/compact)
        # so their revert restores the real working state, not blanket idle.
        # Carry forward across chained transients (error->alert keeps thinking).
        TRANSIENT = {"alert", "error", "compact", "permission"}
        if new_state in TRANSIENT:
            prev_st = prev.get("state")
            if prev_st and prev_st not in TRANSIENT:
                entry["prev_state"] = prev_st
            elif prev.get("prev_state"):
                entry["prev_state"] = prev["prev_state"]
            else:
                entry["prev_state"] = "idle"
        # cwd carries forward unless a new one is supplied
        if cwd:
            entry["cwd"] = cwd
        elif "cwd" in prev:
            entry["cwd"] = prev["cwd"]
        data["sessions"][sid] = entry
elif op == "evict":
    data["sessions"].pop(sid, None)
PRIO = {"permission": 5, "error": 4, "compact": 3, "done": 2.5, "thinking": 2, "alert": 1, "start": 0.5, "idle": 0}
if data["sessions"]:
    winner_entry = max(data["sessions"].values(),
                       key=lambda v: PRIO.get(v.get("state", "idle"), 0))
    winner = winner_entry["state"]
    winner_cwd = winner_entry.get("cwd", "")
else:
    winner = "idle"
    winner_cwd = ""
data["displayed"] = winner
data["displayed_cwd"] = winner_cwd
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
  # schedule_revert <sid> <seq> <delay> [<target>]
  # target: literal state (default "idle") or "@prev" to read prev_state
  # from the session entry at fire time. @prev falls back to idle.
  local sid="$1" seq="$2" delay="$3" target="${4:-idle}"
  (( delay > 0 )) || return 0
  (
    sleep "$delay"
    local cur revert_to="$target"
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
      if [[ "$target" == "@prev" ]]; then
        revert_to=$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    print("idle"); sys.exit()
v = (d.get("sessions") or {}).get(sys.argv[2]) or {}
print(v.get("prev_state", "idle"))
' "$SESSIONS_FILE" "$sid" 2>/dev/null)
        revert_to="${revert_to:-idle}"
      fi
      local out winner
      out=$(mutate update "$sid" "$revert_to")
      winner="${out%%$'\t'*}"
      push "$winner"
    fi
  ) </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
}

show() {
  local new_state="$1" hook_in="" sid cwd out winner seq delay=0 target=idle
  [[ -t 0 ]] || hook_in=$(cat)
  IFS=$'\t' read -r sid cwd < <(parse_hook "$hook_in")
  out=$(mutate update "$sid" "$new_state" "$cwd")
  winner="${out%%$'\t'*}"
  seq="${out##*$'\t'}"
  # seq=-1 signals recap suppression — no push, no revert scheduling.
  [[ "$seq" == "-1" ]] && return 0
  push "$winner"
  case "$new_state" in
    alert)      delay="$ALERT_REVERT";      target="@prev" ;;
    error)      delay="$ERROR_REVERT";      target="@prev" ;;
    compact)    delay="$COMPACT_REVERT";    target="@prev" ;;
    permission) delay="$PERMISSION_REVERT"; target="@prev" ;;
    done)       delay="$DONE_REVERT" ;;
    start)      delay="$START_REVERT" ;;
  esac
  schedule_revert "$sid" "$seq" "$delay" "$target"
}

end_session() {
  local hook_in="" sid cwd out winner
  [[ -t 0 ]] || hook_in=$(cat)
  IFS=$'\t' read -r sid cwd < <(parse_hook "$hook_in")
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
  thinking|alert|permission|error|compact|done|idle|start) show "$1" ;;
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
import os as _os
print(f"displayed: {d.get('displayed','idle')}  cwd={_os.path.basename((d.get('displayed_cwd') or '').rstrip('/'))}")
sessions = d.get("sessions") or {}
if not sessions:
    print("(no live sessions)")
else:
    for sid, v in sessions.items():
        age = int(now - v.get("ts", 0))
        cwd_b = _os.path.basename((v.get("cwd") or "").rstrip("/"))
        print(f"  {sid[:8]:<8}  {v.get('state',''):<10}  seq={v.get('seq','?'):>3}  age={age}s  cwd={cwd_b}")
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
  thinking | alert | permission | error | compact | done | idle | start
                               Per-session state. session_id is read from hook
                               stdin JSON (jq); manual CLI maps to "cli".
                               Aggregated across all live sessions by priority:
                                 permission > error > compact > done > thinking > alert > start > idle
                               start = SessionStart wave (visual alias for done.gif).
                               Auto-revert (per-session, TOCTOU-safe via seq):
                                 alert      after CUBE_ALERT_REVERT s   (5) -> prev_state
                                 permission after CUBE_PERMISSION_REVERT s (= alert) -> prev_state
                                 error      after CUBE_ERROR_REVERT s   (= alert) -> prev_state
                                 compact    after CUBE_COMPACT_REVERT s (= alert) -> prev_state
                                 done       after CUBE_DONE_REVERT s    (5)  -> idle
                                 start      after CUBE_START_REVERT s   (= done) -> idle
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
  SessionStart              -> start
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
     CUBE_ALERT_REVERT (default 5; 0 = forever),
     CUBE_PERMISSION_REVERT (default = ALERT_REVERT; 0 = forever),
     CUBE_ERROR_REVERT / CUBE_COMPACT_REVERT (default = ALERT_REVERT),
     CUBE_DONE_REVERT (default 5),
     CUBE_START_REVERT (default = DONE_REVERT),
     CUBE_RECAP_WINDOW (default 60s; 0 = off — suppresses post-compact done)
EOF
    ;;
esac
exit 0
