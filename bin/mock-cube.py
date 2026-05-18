#!/usr/bin/env python3
"""Mock Geekmagic SmallTV-Ultra — local HTTP server that mimics the cube's
endpoints so cube.sh / hooks can run without the physical device.

Endpoints:
  GET  /set?img=&theme=&brt=   state-set (mirrors what cube.sh push() sends)
  GET  /state.json             current state (for cube-overlay polling)
  GET  /current.gif            resolved local source asset for STATE.img
  GET  /v.json /app.json /space.json   minimal mock JSON
  GET  /filelist?dir=/image/   HTML list of available assets
  POST /doUpload               200 OK, body discarded

Run:
  python3 bin/mock-cube.py [--host 127.0.0.1] [--port 8080]

Then point cube.sh at it (parallel to real cube):
  CUBE_MIRROR=127.0.0.1:8080
"""
import argparse
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

STATE = {"img": "/image/idle.gif", "state": "idle", "theme": 3, "brt": 50, "ts": 0.0}
ASSETS_DIR = None  # set in main()
KNOWN_STATES = {"idle", "thinking", "alert", "permission", "error", "compact", "done"}


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


def resolve_local(img_path):
    """img=/image/waifu_error.gif -> assets/waifu/error.gif (raw PixelLab source).
       img=/image/alert.gif       -> assets/orb/alert.gif"""
    base = os.path.basename(img_path or "")
    m = re.match(r"^([a-z0-9]+)_(.+\.gif)$", base)
    if m:
        skin, fname = m.group(1), m.group(2)
        p = os.path.join(ASSETS_DIR, skin, fname)
        if os.path.isfile(p):
            return p
    p = os.path.join(ASSETS_DIR, "orb", base)
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
            return self._send("OK")
        if u.path == "/state.json":
            return self._json(STATE)
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
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
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
