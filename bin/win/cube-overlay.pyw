#!/usr/bin/env python3
r"""cube-overlay — thin launcher for the cube status overlay.

The window machinery lives in the reusable `webview-overlay` package
(pip install). This file only supplies cube's identity, palette, and the
voxel entity renderer, then hands off to webview_overlay.run().

Setup (one-time, on the Windows host):
  py -3.13 -m pip install --user "webview-overlay @ git+https://github.com/Sa-Lat/webview-overlay.git"
  py -3.13 -m pip install --user pywebview

Per-machine config lives under %APPDATA%\cube\ (overlay.env, overlay-layouts.json)
— same keys as before (CUBE_OVERLAY_*).
"""
import argparse
import os
import sys
from pathlib import Path

# .pyw has no console — log an import failure (e.g. package not installed in
# this Python) somewhere visible before it dies silently.
try:
    from webview_overlay import OverlayConfig, run
except Exception as e:  # pragma: no cover
    try:
        log = os.path.join(os.environ.get("TEMP", os.path.expanduser("~")),
                           "cube-overlay-import.log")
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"import webview_overlay failed: {e!r}\n"
                    f"  exe={sys.executable}\n"
                    f"  install with: py -3.13 -m pip install --user webview-overlay\n")
    except Exception:
        pass
    raise

HERE = Path(__file__).resolve().parent
HTML = HERE / "html"


def main():
    default_port = os.environ.get("CUBE_OVERLAY_PORT", "8765")
    default_mock = os.environ.get("CUBE_OVERLAY_MOCK")

    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", default=default_mock,
                    help="full URL override; if omitted, derived from wsl.exe hostname -I")
    ap.add_argument("--port", default=default_port)
    ap.add_argument("--instance", default=None,
                    help="instance id for a second, independent cube overlay window")
    args = ap.parse_args()

    run(OverlayConfig(
        app_name="cube",
        instance_id=args.instance,
        window_title="cube-overlay",
        env_prefix="CUBE_OVERLAY_",
        url=args.mock,                 # None => auto-resolve WSL IP
        port=int(args.port),
        default_theme="light",
        brand_text="cube",
        # Window paint before CSS loads — match cube-theme.css --card per theme.
        background_colors={"light": "#e6eef2", "dark": "#0d1015"},
        font_href="https://fonts.googleapis.com/css2?family=Quicksand:wght@500;600;700;800&display=swap",
        font_family="'Quicksand', system-ui, sans-serif",
        assets=[str(HTML / "cube-entity.js"), str(HTML / "cube-theme.css")],
        ageless_states=("idle", "done", "start"),
        pulse_states=("permission", "error", "compact", "alert", "thinking"),
        state_labels={
            "permission": "wait", "thinking": "thinking", "done": "done",
            "idle": "idle", "error": "error", "compact": "compact",
            "alert": "alert", "start": "start",
        },
        frontend_config={
            "entityGlobal": "CubeEntity",
            "stateToEmotionGlobal": "CUBE_STATE_TO_EMOTION",
            "defaultEmotion": "idle",
            "usageThresholds": [[80, "#e85555"], [50, "#d7a04a"]],
        },
    ))


if __name__ == "__main__":
    main()
