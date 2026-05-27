#!/usr/bin/env python3
"""Mock Geekmagic SmallTV-Ultra — local HTTP server that mimics the cube's
endpoints so cube.sh / hooks can run without the physical device.

Endpoints:
  GET  /set?img=&theme=&brt=   state-set (mirrors what cube.sh push() sends)
  GET  /state.json             current state (for cube-overlay polling)
  GET  /dashboard.json         state + cwd of winning session + 5h-usage pct
  GET  /current.gif            resolved local source asset for STATE.img
  GET  /v.json /app.json /space.json   minimal mock JSON
  GET  /filelist?dir=/image/   HTML list of available assets
  POST /doUpload               200 OK, body discarded

Run:
  python3 bin/mock-cube.py [--host 127.0.0.1] [--port 8765]

Then point cube.sh at it (parallel to real cube):
  CUBE_MIRROR=127.0.0.1:8765
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

SKIN_FILE = os.path.expanduser("~/.claude/.cube-skin")


def read_skin_file(default="orb"):
    try:
        with open(SKIN_FILE) as f:
            v = f.read().strip()
        return v or default
    except OSError:
        return default


STATE = {"img": "/image/idle.gif", "state": "idle", "theme": 3, "brt": 50, "ts": 0.0,
         "skin": read_skin_file()}
ASSETS_DIR = None  # set in main()
KNOWN_STATES = {"idle", "thinking", "alert", "permission", "error", "compact", "done"}

SESSIONS_FILE = f"/tmp/.cube-sessions-{os.getuid()}.json"
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


def _read_displayed_cwd():
    try:
        with open(SESSIONS_FILE) as f:
            d = json.load(f)
    except Exception:
        return ""
    return os.path.basename((d.get("displayed_cwd") or "").rstrip("/"))


# Mirrors cube.sh PRIO map. Keep in sync.
SESSION_PRIO = {"permission": 5, "error": 4, "compact": 3, "done": 2.5,
                "thinking": 2, "alert": 1, "start": 0.5, "idle": 0}
SESSION_TTL = int(os.environ.get("CUBE_SESSION_TTL", "3600"))
IDLE_TTL = int(os.environ.get("CUBE_IDLE_TTL", "600"))


def _read_sessions_list():
    """Return [{cwd, state, age_s}, ...] sorted by PRIO desc then age asc.
    Stale entries (TTL exceeded) filtered out. Empty list on any error."""
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
        # and would linger an hour. CUBE_IDLE_TTL=0 disables and falls back
        # to the unified SESSION_TTL.
        if entry.get("state") == "idle" and IDLE_TTL > 0 and age >= IDLE_TTL:
            continue
        # age = time since last state change (ts is bumped on every mutate).
        # Not session-start; that's not actionable info for the user.
        # session_id + label surface for the overlay's multi-session subline
        # (visible when same cwd appears multiple times concurrently). label is
        # the first user message of the session (same identifier claude --resume
        # shows), captured by cube.sh from ~/.claude/projects/<...>/<sid>.jsonl.
        out.append({
            "cwd": os.path.basename((entry.get("cwd") or "").rstrip("/")),
            "state": entry.get("state", "idle"),
            "age_s": int(age),
            "session_id": sid,
            "label": entry.get("label", ""),
        })
    # Split idle from active: active sorted by PRIO desc + age asc (freshness
    # cue); idle sorted alphabetically by cwd (no second-by-second reshuffle).
    # Idle always lands at the bottom of the list.
    idle = [s for s in out if s["state"] == "idle"]
    active = [s for s in out if s["state"] != "idle"]
    active.sort(key=lambda s: (-SESSION_PRIO.get(s["state"], 0), s["age_s"]))
    idle.sort(key=lambda s: s["cwd"].lower())
    return active + idle


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
                    # ccusage --active sometimes hands back the last block even
                    # when its 5h window already lapsed (e.g. yesterday-evening
                    # block surfacing on next-morning startup). Verify the block
                    # is actually live now before using its totals — otherwise
                    # the overlay shows a stale % after a long idle gap.
                    end_ts = _parse_iso(blk.get("endTime"))
                    is_active = blk.get("isActive", True)
                    stale = (not is_active) or (end_ts is not None and time.time() > end_ts)
                    if stale:
                        pct = 0
                    else:
                        # tokenLimitStatus.percentUsed is projection (burnRate * remainingMinutes).
                        # We want actual current usage, so divide raw totalTokens by the
                        # plan-specific token limit. ccusage's --token-limit max picks
                        # the highest historical block — that rarely matches Anthropic's
                        # actual Max-plan quota, so CUBE_USAGE_TOKEN_LIMIT can override.
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


def derive_state(img_path):
    """img=/image/waifu_thinking.gif -> 'thinking'.  img=/image/alert.gif -> 'alert'."""
    base = os.path.basename(img_path or "")
    name = base.rsplit(".", 1)[0]
    if "_" in name:
        suffix = name.split("_", 1)[1]
        if suffix in KNOWN_STATES:
            return suffix
    if name in KNOWN_STATES:
        return name
    return "alert"  # unknown filename → treat as non-idle so overlay still shows it


def _proxy_set_skin(skin):
    cube = os.path.expanduser("~/.claude/bin/cube.sh")
    if not os.path.isfile(cube):
        return
    try:
        subprocess.run([cube, "skin", skin], timeout=5, capture_output=True)
        subprocess.run([cube, "redisplay"], timeout=5, capture_output=True)
    except Exception as e:
        sys.stderr.write(f"set?skin proxy failed: {e}\n")


def derive_skin(img_path):
    """img=/image/waifu_thinking.gif -> 'waifu'.  img=/image/alert.gif -> STATE['skin'].
    Orb uses unprefixed filenames (legacy convention); any other prefix is the
    skin name. Exposed in /dashboard.json so the Windows overlay can pick the
    right palette without reading ~/.claude/.cube-skin off the WSL filesystem.
    Unprefixed filenames fall through to STATE['skin'] (read from
    ~/.claude/.cube-skin at startup) so the overlay shows the right palette
    immediately after mock-cube boots, before the first state-push arrives."""
    base = os.path.basename(img_path or "")
    name = base.rsplit(".", 1)[0]
    if "_" in name:
        prefix, suffix = name.split("_", 1)
        if suffix in KNOWN_STATES:
            return prefix
    return STATE.get("skin") or "orb"


def resolve_local(img_path):
    """img=/image/waifu_error.gif -> assets/desktop/waifu/error.gif (override, hi-res)
                                  -> assets/waifu/error.gif (cube source fallback).
       img=/image/alert.gif       -> assets/desktop/orb/alert.gif (override)
                                  -> assets/orb/alert.gif (fallback).
    desktop/ overrides are overlay-only; never uploaded to cube hardware."""
    base = os.path.basename(img_path or "")
    m = re.match(r"^([a-z0-9]+)_(.+\.gif)$", base)
    if m:
        skin, fname = m.group(1), m.group(2)
        for sub in (os.path.join("desktop", skin), skin):
            p = os.path.join(ASSETS_DIR, sub, fname)
            if os.path.isfile(p):
                return p
    for sub in (os.path.join("desktop", "orb"), "orb"):
        p = os.path.join(ASSETS_DIR, sub, base)
        if os.path.isfile(p):
            return p
    return None


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
        q = parse_qs(u.query)
        if u.path == "/set":
            if "img" in q:
                STATE["img"] = q["img"][0]
                STATE["state"] = derive_state(STATE["img"])
                STATE["ts"] = time.time()
            if "theme" in q:
                STATE["theme"] = int(q["theme"][0])
            if "brt" in q:
                STATE["brt"] = int(q["brt"][0])
            if "skin" in q:
                # Route skin-change through cube.sh in a daemon thread so the
                # HTTP response returns immediately. cube.sh skin writes
                # ~/.claude/.cube-skin (WSL source of truth) and cube.sh
                # redisplay mirrors the new GIF back via CUBE_MIRROR —
                # STATE.img updates on its own once the redisplay-push lands.
                # Update STATE['skin'] optimistically so /dashboard.json
                # reflects the new palette on the very next poll, without
                # waiting for the redisplay round-trip.
                STATE["skin"] = q["skin"][0]
                threading.Thread(target=_proxy_set_skin,
                                 args=(q["skin"][0],), daemon=True).start()
            return self._send("OK")
        if u.path == "/state.json":
            return self._json(STATE)
        if u.path == "/dashboard.json":
            payload = dict(STATE)
            payload["skin"] = derive_skin(STATE["img"])
            payload["cwd"] = _read_displayed_cwd()
            payload["usage_5h_pct"] = _read_usage_pct()
            payload["sessions"] = _read_sessions_list()
            return self._json(payload)
        if u.path == "/current.gif":
            p = resolve_local(STATE["img"])
            if p:
                with open(p, "rb") as f:
                    data = f.read()
                return self._send(data, "image/gif")
            self.send_response(404)
            self.end_headers()
            return
        if u.path == "/v.json":
            return self._json({"version": "mock-9.0.0", "device": "mock-cube"})
        if u.path == "/app.json":
            return self._json({"theme": STATE["theme"], "brt": STATE["brt"]})
        if u.path == "/space.json":
            return self._json({"total": 3145728, "used": 0, "free": 3145728})
        if u.path == "/filelist":
            files = []
            for skin in sorted(os.listdir(ASSETS_DIR)):
                d = os.path.join(ASSETS_DIR, skin)
                if not os.path.isdir(d) or skin == "240":
                    continue
                for f in sorted(os.listdir(d)):
                    if f.endswith(".gif"):
                        name = f if skin == "orb" else f"{skin}_{f}"
                        files.append(name)
            html = "<html>" + "".join(f"<a href='/image/{f}'>{f}</a><br>" for f in files) + "</html>"
            return self._send(html, "text/html")
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/doUpload":
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            return self._send("OK")
        self.send_response(404)
        self.end_headers()


def main():
    ap = argparse.ArgumentParser()
    # Default bind: env override (set in ~/.config/cube/config for systemd unit)
    # then 127.0.0.1. Use 0.0.0.0 to expose to Windows-host (WSL-IP route) for
    # bin/win/cube-overlay-win.pyw.
    ap.add_argument("--host", default=os.environ.get("CUBE_MOCK_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("CUBE_MOCK_PORT", "8765")))
    ap.add_argument(
        "--assets",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets"),
    )
    a = ap.parse_args()
    global ASSETS_DIR
    ASSETS_DIR = os.path.abspath(a.assets)
    print(f"mock-cube on http://{a.host}:{a.port}  (assets: {ASSETS_DIR})", file=sys.stderr)
    print(f"  CUBE_MIRROR={a.host}:{a.port}", file=sys.stderr)
    ThreadingHTTPServer((a.host, a.port), H).serve_forever()


if __name__ == "__main__":
    main()
