# cube — Claude-Code multi-session overlay

Frameless always-on-top WebView2 window that shows what every active Claude
Code session is doing right now, with a voxel cube-entity that morphs
between 8 emotions tied to Claude's hook events.

| Claude hook | dashboard state | entity emotion | revert |
|---|---|---|---|
| `SessionStart` | `start` | curious | 5 s → idle |
| `UserPromptSubmit` | `thinking` | thinking (ripple + synapse flashes) | — |
| `Stop` | `done` | happy (green pulse) | 5 s → idle |
| `Notification` | `alert` | surprised (magenta shake) | 5 s → prev_state |
| `PermissionRequest` | `permission` | listening (lavender) | 5 s → prev_state |
| `PostToolUseFailure` (Bash) | `error` | error (red shake, high-freq pulse) | 3 s grace + 5 s → prev_state |
| `PreCompact` | `compact` | focused (electric blue) | 5 s → prev_state |
| `SessionEnd` | (eviction) | — | — |

`prev_state` = the last stable state of the session (`thinking` or `idle`),
so a Bash failure during `thinking` reverts to `thinking`, not `idle`.
`done`/`start` always revert to `idle`.

Multiple parallel Claude sessions are aggregated by priority
(`permission > error > compact > done > thinking > alert > start > idle`).
The overlay shows one row per active session (state dot + cwd + age) above
the cube-entity canvas; the entity itself renders the winning session's
state.

## Architecture

```
~/.claude/settings.json hook ─→ cube.sh <state>            (WSL)
                                  │  writes
                                  ▼
                       /tmp/.cube-sessions-$UID.json
                                  │  read fresh on each poll
                                  ▼
                        mock-cube.py /dashboard.json      (WSL service)
                                  │  http://<wsl-ip>:8765
                                  ▼
            cube-overlay.pyw (Windows, webview-overlay + pywebview)
                                  │  cube-entity.js canvas + DOM rows
                                  ▼
                            you see the overlay
```

Two runtime components on the WSL side (`cube.sh` script + `mock-cube`
systemd unit), one runtime component on the Windows side
(`cube-overlay.pyw` started from `shell:startup`). The overlay window itself
is the reusable [`webview-overlay`](../webview-overlay) package — `cube-overlay.pyw`
is a thin launcher supplying cube's entity, palette and config.

## Setup (WSL side)

```bash
# Optional: pin a token-limit for the 5h-window usage bar.
# Anthropic does not publish exact Max-plan limits; pick empirically.
mkdir -p ~/.config/cube
cat >> ~/.config/cube/config <<'EOF'
CUBE_MOCK_HOST=0.0.0.0           # required so Windows-host can reach mock-cube
CUBE_USAGE_TOKEN_LIMIT=155000000 # Max(5x) lands here in practice; YMMV
EOF

make dev-install                 # deploys cube.sh + mock-cube.py + enables systemd unit
```

Then wire `~/.claude/settings.json` hooks:

```jsonc
{
  "hooks": {
    "SessionStart":       [{"hooks": [{"type": "command", "command": "~/.claude/bin/cube.sh start"}]}],
    "SessionEnd":         [{"hooks": [{"type": "command", "command": "~/.claude/bin/cube.sh end"}]}],
    "UserPromptSubmit":   [{"hooks": [{"type": "command", "command": "~/.claude/bin/cube.sh thinking"}]}],
    "Stop":               [{"hooks": [{"type": "command", "command": "~/.claude/bin/cube.sh done"}]}],
    "Notification":       [{"hooks": [{"type": "command", "command": "~/.claude/bin/cube.sh alert"}]}],
    "PermissionRequest":  [{"hooks": [{"type": "command", "command": "~/.claude/bin/cube.sh permission"}]}],
    "PostToolUseFailure": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/bin/cube.sh error"}]}],
    "PreCompact":         [{"hooks": [{"type": "command", "command": "~/.claude/bin/cube.sh compact"}]}]
  }
}
```

## Setup (Windows side)

See [`bin/win/README.md`](bin/win/README.md) for the full Windows-host
guide. Short version:

```powershell
py -3.13 -m pip install --user pywebview
py -3.13 -m pip install --user "webview-overlay @ git+https://github.com/Sa-Lat/webview-overlay.git"
copy bin\win\cube-overlay-win-html.cmd "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\"
```

Right-click the overlay for theme/size/window menu. Drag with left mouse
button. Bottom-right anchor is per-monitor-layout, persisted in
`%APPDATA%\cube\overlay-layouts.json`.

## Browser-only preview (no pywebview, no WSL)

The base overlay shell can be previewed in any browser from the
`webview-overlay` repo — open `tests/preview/preview.html`, which falls back to
`OVERLAY_CONFIG.sampleData`. Add `?theme=light` or `?theme=dark` to override the
palette. (Cube's palette + entity load only inside the real overlay; the
preview shows the package's base look.)

## Configuration

All env vars are optional. See `.env.example` for the full list; the most
common ones:

```bash
CUBE_MOCK_HOST=0.0.0.0           # bind for Windows-host access (default 127.0.0.1)
CUBE_MOCK_PORT=8765              # mock-cube port
CUBE_USAGE_TOKEN_LIMIT=155000000 # override ccusage historical-max
CUBE_ERROR_GRACE=3               # defer Bash error display (cancelled on retry)
CUBE_RECAP_WINDOW=60             # suppress post-compact `done` blip
```

Per-machine overlay state (Windows): `%APPDATA%\cube\overlay.env` +
`overlay-layouts.json`. Touch via the right-click menu, no manual editing
needed.

## Requirements

**WSL side:** bash, curl, python3, flock. Optional: node + npx for ccusage
usage display.

**Windows side:** Python 3.13 (pythonnet has no 3.14 wheels yet),
`pywebview`, WebView2-Runtime (preinstalled on Win11, otherwise via Edge
Update or the standalone installer).
