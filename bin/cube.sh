#!/usr/bin/env bash
# Claude-Code multi-session state machine.
#
# Each hook fires `cube.sh <state>` with the hook stdin JSON on stdin. The
# session_id + cwd are extracted from that JSON and a per-session record is
# upserted into the sessions file. The aggregated winner (highest PRIO across
# live sessions) is what the overlay renders.
#
# Designed to never block Claude: every path swallows errors and exits 0.
#
# Sessions file: /tmp/.cube-sessions-$UID.json  (atomic via flock + temp+rename)
#   {"sessions": {"<sid>": {"state": "...", "ts": ..., "seq": N,
#                            "prev_state": "thinking|idle",
#                            "cwd": "...", "label": "...", "started_at": ...}},
#    "displayed": "...", "displayed_ts": ...}
# prev_state captured on entry to alert/error/compact/permission = last stable
# state. Carries across chained transients (error→alert keeps thinking).
# Stale entries pruned after CUBE_SESSION_TTL (default 3600 s); idle entries
# additionally drop at CUBE_IDLE_TTL (default 600 s) for crashed Claude
# instances that never fire SessionEnd.
#
# Auto-revert: alert/permission/error/compact/done/start schedule a per-session
# revert that fires after N seconds. TOCTOU-safe via seq counter — if the
# session moved on (seq advanced), revert is a no-op.
# Revert target: alert/error/compact/permission → prev_state (thinking/idle);
#                done/start → idle (hardcoded — task ended).
#
# Error debounce: PostToolUseFailure fires the moment a Bash tool fails, but
# Claude often retries successfully in the same turn — the user only sees an
# error flash for an issue that resolved itself. CUBE_ERROR_GRACE (default 3 s)
# defers the entire mutate+revert. Any non-error state for the same session
# during the window (or SessionEnd) drops the pending entry — silent no-op.
# Persistent errors show after grace. Set CUBE_ERROR_GRACE=0 to disable.
#
# Recap suppression: the Stop hook fires right after PreCompact's recap
# message. If `done` lands within CUBE_RECAP_WINDOW s (default 60) of the
# session's last `compact`, the mutation is skipped — no seq bump, no revert
# — so the existing compact→prev_state revert handles the return cleanly.

set -u

SESSIONS_FILE="${CUBE_SESSIONS_FILE:-/tmp/.cube-sessions-$UID.json}"
PENDING_ERROR_FILE="${CUBE_PENDING_ERROR_FILE:-/tmp/.cube-pending-errors-$UID.json}"
SESSION_TTL="${CUBE_SESSION_TTL:-3600}"
IDLE_TTL="${CUBE_IDLE_TTL:-600}"
ALERT_REVERT="${CUBE_ALERT_REVERT:-5}"
PERMISSION_REVERT="${CUBE_PERMISSION_REVERT:-$ALERT_REVERT}"
ERROR_REVERT="${CUBE_ERROR_REVERT:-$ALERT_REVERT}"
ERROR_GRACE="${CUBE_ERROR_GRACE:-3}"
COMPACT_REVERT="${CUBE_COMPACT_REVERT:-$ALERT_REVERT}"
DONE_REVERT="${CUBE_DONE_REVERT:-5}"
START_REVERT="${CUBE_START_REVERT:-$DONE_REVERT}"
RECAP_WINDOW="${CUBE_RECAP_WINDOW:-60}"

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

# mutate <op> <sid> [<new_state> [<cwd> [<label>]]]
#   op=update  -> upsert session slot, bump seq
#   op=evict   -> remove session
# Prints "<winner>\t<seq>" (seq is '-' for evict, -1 for recap-suppressed).
# Atomic via flock + temp+rename.
mutate() {
  local op="$1" sid="$2" new_state="${3:-idle}" cwd="${4:-}" label="${5:-}"
  mkdir -p "$(dirname "$SESSIONS_FILE")" 2>/dev/null || true
  exec 9>"$SESSIONS_FILE.lock"
  flock -x 9 2>/dev/null || true
  python3 - "$SESSIONS_FILE" "$op" "$sid" "$new_state" "$SESSION_TTL" "$RECAP_WINDOW" "$cwd" "$IDLE_TTL" "$label" <<'PY'
import json, os, sys, tempfile, time
path, op, sid, new_state = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
ttl, recap_window = int(sys.argv[5]), int(sys.argv[6])
cwd = sys.argv[7] if len(sys.argv) > 7 else ""
idle_ttl = int(sys.argv[8]) if len(sys.argv) > 8 else 0
label = sys.argv[9] if len(sys.argv) > 9 else ""
try:
    with open(path) as f:
        data = json.load(f)
except (OSError, ValueError):
    data = {"sessions": {}, "displayed": "idle", "displayed_cwd": "", "displayed_ts": 0}
now = time.time()
def _alive(v):
    age = now - v.get("ts", 0)
    if age >= ttl:
        return False
    if v.get("state") == "idle" and idle_ttl > 0 and age >= idle_ttl:
        return False
    return True
data["sessions"] = {k: v for k, v in (data.get("sessions") or {}).items() if _alive(v)}
seq_out = "-"
if op == "update":
    prev = data["sessions"].get(sid, {})
    # Recap suppression: `done` shortly after `compact` is the post-compact
    # recap Stop. Skip — no state change, no seq bump.
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
        TRANSIENT = {"alert", "error", "compact", "permission"}
        if new_state in TRANSIENT:
            prev_st = prev.get("state")
            if prev_st and prev_st not in TRANSIENT:
                entry["prev_state"] = prev_st
            elif prev.get("prev_state"):
                entry["prev_state"] = prev["prev_state"]
            else:
                entry["prev_state"] = "idle"
        if cwd:
            entry["cwd"] = cwd
        elif "cwd" in prev:
            entry["cwd"] = prev["cwd"]
        if label:
            entry["label"] = label
        elif "label" in prev:
            entry["label"] = prev["label"]
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

# Pending-error map: {<sid>: {"ts": <float>, "cwd": <str>, "label": <str>}}.
# Each error overwrites its sid's entry with a fresh ts; deferred job claims by
# ts-match, so older deferred jobs whose ts no longer matches no-op silently.
pending_error_write() {
  local sid="$1" cwd="$2" label="$3"
  mkdir -p "$(dirname "$PENDING_ERROR_FILE")" 2>/dev/null || true
  exec 8>"$PENDING_ERROR_FILE.lock"
  flock -x 8 2>/dev/null || true
  python3 - "$PENDING_ERROR_FILE" "$sid" "$cwd" "$label" <<'PY'
import json, os, sys, tempfile, time
path, sid, cwd, label = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
try:
    with open(path) as f: data = json.load(f)
except Exception:
    data = {}
ts = time.time()
data[sid] = {"ts": ts, "cwd": cwd, "label": label}
d = os.path.dirname(path) or "."
fd, tmp = tempfile.mkstemp(dir=d, prefix=".cube-pe-", suffix=".tmp")
with os.fdopen(fd, "w") as f: json.dump(data, f)
os.replace(tmp, path)
print(repr(ts))
PY
  flock -u 8 2>/dev/null || true
  exec 8>&-
}

pending_error_clear() {
  local sid="$1"
  [[ -f "$PENDING_ERROR_FILE" ]] || return 0
  exec 8>"$PENDING_ERROR_FILE.lock"
  flock -x 8 2>/dev/null || true
  python3 - "$PENDING_ERROR_FILE" "$sid" <<'PY' 2>/dev/null
import json, os, sys, tempfile
path, sid = sys.argv[1], sys.argv[2]
try:
    with open(path) as f: data = json.load(f)
except Exception:
    sys.exit()
if sid not in data: sys.exit()
del data[sid]
d = os.path.dirname(path) or "."
fd, tmp = tempfile.mkstemp(dir=d, prefix=".cube-pe-", suffix=".tmp")
with os.fdopen(fd, "w") as f: json.dump(data, f)
os.replace(tmp, path)
PY
  flock -u 8 2>/dev/null || true
  exec 8>&-
}

# Claim a pending entry by sid+ts match. Prints "<cwd>\t<label>" on success,
# nothing on stale/missing. Removes the entry on success.
pending_error_claim() {
  local sid="$1" ts="$2"
  [[ -f "$PENDING_ERROR_FILE" ]] || return 0
  exec 8>"$PENDING_ERROR_FILE.lock"
  flock -x 8 2>/dev/null || true
  python3 - "$PENDING_ERROR_FILE" "$sid" "$ts" <<'PY' 2>/dev/null
import json, os, sys, tempfile
path, sid, want_ts = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f: data = json.load(f)
except Exception:
    sys.exit()
entry = data.get(sid)
if not entry: sys.exit()
if repr(entry.get("ts", 0)) != want_ts: sys.exit()
del data[sid]
d = os.path.dirname(path) or "."
fd, tmp = tempfile.mkstemp(dir=d, prefix=".cube-pe-", suffix=".tmp")
with os.fdopen(fd, "w") as f: json.dump(data, f)
os.replace(tmp, path)
print(f"{entry.get('cwd','')}\t{entry.get('label','')}")
PY
  flock -u 8 2>/dev/null || true
  exec 8>&-
}

# Real error path: mutate + schedule_revert. Used by show() when ERROR_GRACE=0
# and by the deferred job after grace expires.
do_error_now() {
  local sid="$1" cwd="$2" label="$3" out seq
  out=$(mutate update "$sid" "error" "$cwd" "$label")
  seq="${out##*$'\t'}"
  [[ "$seq" == "-1" ]] && return 0
  schedule_revert "$sid" "$seq" "$ERROR_REVERT" "@prev"
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
      mutate update "$sid" "$revert_to" >/dev/null
    fi
  ) </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
}

show() {
  local new_state="$1" hook_in="" sid cwd label="" out seq delay=0 target=idle
  [[ -t 0 ]] || hook_in=$(cat)
  IFS=$'\t' read -r sid cwd < <(parse_hook "$hook_in")
  # Resolve session label = first user message from Claude's per-project JSONL
  # (same source claude --resume shows). Encoded cwd: '/' → '-'. SessionStart
  # fires before any user prompt exists, so label is empty there; mutate's
  # carry-forward keeps it sticky once a later UserPromptSubmit populates it.
  if [[ -n "$sid" && "$sid" != "cli" && -n "$cwd" ]]; then
    local encoded="${cwd//\//-}"
    local jsonl="$HOME/.claude/projects/${encoded}/${sid}.jsonl"
    if [[ -f "$jsonl" ]]; then
      label=$(timeout 0.3 python3 - "$jsonl" 2>/dev/null <<'PY' || true
import json, sys
with open(sys.argv[1]) as f:
    for line in f:
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get("message", {}).get("role") == "user":
            c = d["message"].get("content", "")
            t = c if isinstance(c, str) else (c[0].get("text", "") if c else "")
            t = " ".join(t.split())
            print(t[:60])
            break
PY
)
    fi
  fi
  # Any non-error state invalidates a pending-error debounce. Catches the
  # "Bash failed, Claude retried successfully" case: PostToolUseFailure arms
  # the pending error, a follow-up state clears it before grace expires.
  if [[ "$new_state" != "error" ]]; then
    pending_error_clear "$sid"
  fi

  # Defer error display by ERROR_GRACE so transient failures resolved on retry
  # never flash error. CUBE_ERROR_GRACE=0 → immediate display.
  if [[ "$new_state" == "error" && "${ERROR_GRACE:-0}" -gt 0 ]]; then
    local pe_ts claim
    pe_ts=$(pending_error_write "$sid" "$cwd" "$label")
    (
      sleep "$ERROR_GRACE"
      claim=$(pending_error_claim "$sid" "$pe_ts")
      [[ -z "$claim" ]] && exit 0
      IFS=$'\t' read -r c_cwd c_label <<<"$claim"
      do_error_now "$sid" "$c_cwd" "$c_label"
    ) </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null || true
    return 0
  fi

  out=$(mutate update "$sid" "$new_state" "$cwd" "$label")
  seq="${out##*$'\t'}"
  # seq=-1 signals recap suppression — no revert scheduling.
  [[ "$seq" == "-1" ]] && return 0
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
  local hook_in="" sid cwd
  [[ -t 0 ]] || hook_in=$(cat)
  IFS=$'\t' read -r sid cwd < <(parse_hook "$hook_in")
  pending_error_clear "$sid"
  mutate evict "$sid" >/dev/null
}

case "${1:-}" in
  thinking|alert|permission|error|compact|done|idle|start) show "$1" ;;
  end)        end_session ;;
  info)
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
  *)
    cat >&2 <<EOF
cube.sh — Claude-Code multi-session state machine

Usage: $0 <command> [arg]
  thinking | alert | permission | error | compact | done | idle | start
                               Per-session state. session_id is read from hook
                               stdin JSON; manual CLI maps to "cli".
                               Aggregated across all live sessions by priority:
                                 permission > error > compact > done > thinking > alert > start > idle
                               Auto-revert (per-session, TOCTOU-safe via seq):
                                 alert      after CUBE_ALERT_REVERT s   (5) -> prev_state
                                 permission after CUBE_PERMISSION_REVERT s (= alert) -> prev_state
                                 error      after CUBE_ERROR_REVERT s   (= alert) -> prev_state
                                 compact    after CUBE_COMPACT_REVERT s (= alert) -> prev_state
                                 done       after CUBE_DONE_REVERT s    (5)  -> idle
                                 start      after CUBE_START_REVERT s   (= done) -> idle
  end                          Evict current session_id (used by SessionEnd).
  info                         Live sessions + aggregate winner.

Hook mapping:
  SessionStart              -> start
  UserPromptSubmit          -> thinking
  Stop                      -> done
  SessionEnd                -> end
  Notification              -> alert
  PermissionRequest         -> permission
  PostToolUseFailure (Bash) -> error
  PreCompact                -> compact

Env: CUBE_SESSIONS_FILE (default /tmp/.cube-sessions-\$UID.json),
     CUBE_SESSION_TTL (default 3600 s — stale-session prune),
     CUBE_IDLE_TTL (default 600 s — idle-specific prune for crashed Claude),
     CUBE_ALERT_REVERT (default 5; 0 = forever),
     CUBE_PERMISSION_REVERT / CUBE_ERROR_REVERT / CUBE_COMPACT_REVERT
       (default = ALERT_REVERT),
     CUBE_ERROR_GRACE (default 3 s; 0 = off — defers error so a Bash failure
       resolved on retry never flashes),
     CUBE_DONE_REVERT (default 5),
     CUBE_START_REVERT (default = DONE_REVERT),
     CUBE_RECAP_WINDOW (default 60 s; 0 = off — suppresses post-compact done)
EOF
    ;;
esac
exit 0
