#!/usr/bin/env python3
"""Cube-entity overlay backend — local HTTP aggregator.

Reads the per-session JSON written by `cube.sh` and exposes the aggregated
winner state + active session list at /dashboard.json. Also surfaces the 5h
Claude usage percent via `ccusage` (async, cached).

Endpoints:
  GET /dashboard.json   {state, cwd, ts, usage_5h_pct, sessions}

Run:
  python3 bin/mock-cube.py [--host 127.0.0.1] [--port 8765]

Bind to 0.0.0.0 so the Windows-host overlay can reach mock-cube across the
WSL-IP boundary (cube-overlay-win-html.pyw resolves the WSL IP at startup):
  CUBE_MOCK_HOST=0.0.0.0 python3 bin/mock-cube.py
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

SESSIONS_FILE = f"/tmp/.cube-sessions-{os.getuid()}.json"
SESSION_TTL = int(os.environ.get("CUBE_SESSION_TTL", "3600"))
IDLE_TTL = int(os.environ.get("CUBE_IDLE_TTL", "600"))

# Mirrors cube.sh PRIO map. Keep in sync.
SESSION_PRIO = {"permission": 5, "error": 4, "compact": 3, "done": 2.5,
                "thinking": 2, "alert": 1, "start": 0.5, "idle": 0}

USAGE_TTL = 30  # seconds — ccusage subprocess is slow, cache hard
USAGE_ARGS = ["blocks", "--json", "--active", "--token-limit", "max"]
_USAGE = {"ts": 0.0, "pct": None, "refreshing": False, "lock": threading.Lock()}


def _find_ccusage_cmd():
    """Resolve the ccusage invocation. Order: explicit env override, npx in
    PATH, then nvm install dirs (systemd --user services don't see ~/.nvm)."""
    override = os.environ.get("CUBE_CCUSAGE_CMD")
    if override:
        return override.split()
    npx = shutil.which("npx")
    if not npx:
        cands = sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/npx")),
                       reverse=True)
        npx = next((c for c in cands if os.access(c, os.X_OK)), None)
    if not npx:
        return None
    return [npx, "-y", "ccusage@latest"]


def _read_sessions_list():
    """Return [{cwd, state, age_s, session_id, label}, ...] sorted by PRIO
    desc then age asc; idle bucket sorted by cwd at the bottom. Stale entries
    (TTL exceeded) filtered out. Empty list on any error."""
    try:
        with open(SESSIONS_FILE) as f:
            d = json.load(f)
    except Exception:
        return []
    now = time.time()
    out = []
    for sid, entry in (d.get("sessions") or {}).items():
        ts = entry.get("ts", 0)
        age = now - ts
        if age >= SESSION_TTL:
            continue
        # Idle-specific prune: crashed Claude sessions never fire SessionEnd
        # and would linger an hour. CUBE_IDLE_TTL=0 disables this fast path.
        if entry.get("state") == "idle" and IDLE_TTL > 0 and age >= IDLE_TTL:
            continue
        out.append({
            "cwd": os.path.basename((entry.get("cwd") or "").rstrip("/")),
            "state": entry.get("state", "idle"),
            "age_s": int(age),
            "session_id": sid,
            "label": entry.get("label", ""),
        })
    # Active by PRIO desc + age asc (freshness cue); idle alphabetically by cwd
    # so it doesn't reshuffle on the per-second tick.
    idle = [s for s in out if s["state"] == "idle"]
    active = [s for s in out if s["state"] != "idle"]
    active.sort(key=lambda s: (-SESSION_PRIO.get(s["state"], 0), s["age_s"]))
    idle.sort(key=lambda s: s["cwd"].lower())
    return active + idle


def _winner_from_sessions(sessions):
    """Pick the highest-priority active session. Returns (state, cwd)."""
    if not sessions:
        return "idle", ""
    winner = max(sessions, key=lambda s: SESSION_PRIO.get(s["state"], 0))
    return winner["state"], winner["cwd"]


def _parse_iso(s):
    """ISO-8601 → epoch seconds. ccusage emits `...Z`; fromisoformat needs +00:00."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _refresh_usage():
    pct = None
    cmd = _find_ccusage_cmd()
    if cmd is None:
        sys.stderr.write("ccusage: npx not found (set CUBE_CCUSAGE_CMD or install node)\n")
    else:
        # npx shebang is `#!/usr/bin/env node` — ensure the resolved npx's
        # sibling `node` is on PATH (systemd --user PATH excludes nvm).
        env = os.environ.copy()
        env["PATH"] = f"{os.path.dirname(cmd[0])}:{env.get('PATH', '')}"
        try:
            out = subprocess.run(cmd + USAGE_ARGS, capture_output=True, text=True, timeout=60, env=env)
            if out.returncode == 0 and out.stdout:
                blocks = (json.loads(out.stdout).get("blocks") or [])
                if blocks:
                    blk = blocks[0]
                    # ccusage --active sometimes hands back a stale block (its 5h
                    # window already lapsed). Verify before using.
                    end_ts = _parse_iso(blk.get("endTime"))
                    is_active = blk.get("isActive", True)
                    stale = (not is_active) or (end_ts is not None and time.time() > end_ts)
                    if stale:
                        pct = 0
                    else:
                        # tokenLimitStatus.percentUsed is projection (burnRate * remainingMinutes).
                        # We want actual current usage. CUBE_USAGE_TOKEN_LIMIT can override
                        # ccusage's historical-max limit to match the Anthropic plan quota.
                        tls = blk.get("tokenLimitStatus") or {}
                        total = blk.get("totalTokens")
                        limit_env = os.environ.get("CUBE_USAGE_TOKEN_LIMIT")
                        limit = int(limit_env) if limit_env else tls.get("limit")
                        if total and limit:
                            pct = int(round(total / limit * 100))
            else:
                sys.stderr.write(f"ccusage rc={out.returncode}: {out.stderr[:200]}\n")
        except Exception as e:
            sys.stderr.write(f"ccusage refresh failed: {e}\n")
    with _USAGE["lock"]:
        _USAGE["pct"] = pct
        _USAGE["ts"] = time.time()
        _USAGE["refreshing"] = False


def _read_usage_pct():
    """Return cached 5h-window usage percent. Refreshes asynchronously when
    cache is older than USAGE_TTL so the GET request never blocks on ccusage."""
    now = time.time()
    with _USAGE["lock"]:
        fresh = (now - _USAGE["ts"]) < USAGE_TTL
        pct = _USAGE["pct"]
        if not fresh and not _USAGE["refreshing"]:
            _USAGE["refreshing"] = True
            _USAGE["ts"] = now  # tentative — prevent thundering herd
            threading.Thread(target=_refresh_usage, daemon=True).start()
    return pct


class H(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[{time.strftime('%H:%M:%S')}] {fmt % args}\n")

    def _send(self, body, ctype="text/plain", code=200):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload, code=200):
        self._send(json.dumps(payload), "application/json", code)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/dashboard.json":
            sessions = _read_sessions_list()
            state, cwd = _winner_from_sessions(sessions)
            return self._json({
                "state": state,
                "cwd": cwd,
                "ts": time.time(),
                "usage_5h_pct": _read_usage_pct(),
                "sessions": sessions,
            })
        self.send_response(404)
        self.end_headers()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=os.environ.get("CUBE_MOCK_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("CUBE_MOCK_PORT", "8765")))
    a = ap.parse_args()
    print(f"cube-entity backend on http://{a.host}:{a.port}", file=sys.stderr)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
