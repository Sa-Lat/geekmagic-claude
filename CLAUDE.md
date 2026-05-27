# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Claude-Code multi-session overlay with a voxel cube-entity animation. Claude
Code hooks (`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `Stop`,
`Notification`, `PermissionRequest`, `PostToolUseFailure`, `PreCompact` —
mapping table below) shell out to `bin/cube.sh <state>`, which writes a
per-session record into a shared JSON file. A local HTTP service
(`mock-cube.py`) aggregates the active sessions by priority and exposes
`/dashboard.json`. A frameless WebView2 overlay on the Windows host polls
that endpoint and renders the winning state as one of 8 emotions on a vanilla
JS `<canvas>` entity.

No hardware. No GIFs. No background daemons except mock-cube. The whole
runtime is `cube.sh` (single bash script) + `mock-cube.py` (single Python
stdlib HTTP server) + a Windows-native overlay (`cube-overlay-win-html.pyw`
with pywebview/WebView2).

## Architecture, three pieces

1. **`bin/cube.sh`** — Claude-Code hook receiver + per-session state machine.
   Designed to never block Claude: every error path silently exits 0.
   Multi-session aware: reads `session_id` + `cwd` from hook stdin JSON
   (single python3 inline call in `parse_hook` — no jq), tracks per-session
   state in `/tmp/.cube-sessions-$UID.json` (atomic via flock + python3 +
   temp+rename), and aggregates across sessions by priority:
   `permission > error > compact > done > thinking > alert > start > idle`.
   Per-session `seq` counter makes auto-revert TOCTOU-safe.

   **Revert target:** `alert`/`error`/`compact`/`permission` restore the
   session's `prev_state` (last stable thinking/idle, captured on transient
   entry) so a Bash failure during thinking returns to thinking, not idle.
   `done`/`start` revert to `idle` hardcoded — they represent task-ended /
   session-greeting.

   **Recap suppression:** the `Stop` hook fires right after a `PreCompact`
   recap message; if `done` lands within `CUBE_RECAP_WINDOW`s (default 60)
   of the session's last `compact`, the mutation is skipped — the existing
   `compact → prev_state` revert handles the return cleanly. Set
   `CUBE_RECAP_WINDOW=0` to disable.

   **Error debounce:** `PostToolUseFailure` fires the instant a Bash tool
   fails, but Claude usually retries successfully in the same turn —
   without debounce the user sees an error flash for an issue that resolved
   itself. `CUBE_ERROR_GRACE` (default 3s) defers the mutate+revert;
   any non-error state for the same session (or `SessionEnd`) during the
   window drops the pending entry — silent no-op. Pending entries live in
   `/tmp/.cube-pending-errors-$UID.json` keyed by sid with a `ts` token, so
   re-armed errors invalidate old deferred jobs by ts-mismatch. Set
   `CUBE_ERROR_GRACE=0` to disable.

   Stale sessions (>`CUBE_SESSION_TTL`s, default 3600) pruned on every
   write. Idle sessions additionally drop at `CUBE_IDLE_TTL`s (default 600)
   so crashed Claude instances that never fired SessionEnd don't linger an
   hour. Set `CUBE_IDLE_TTL=0` to disable.

2. **`bin/mock-cube.py`** — local HTTP aggregator. Stdlib
   `ThreadingHTTPServer` exposing exactly one meaningful endpoint:
   `/dashboard.json`. On each GET it reads `/tmp/.cube-sessions-$UID.json`
   fresh, applies the same `SESSION_PRIO` map as `cube.sh` to pick the
   winner, returns `{state, cwd, ts, usage_5h_pct, sessions}` as JSON. The
   sessions list is split into two phases: every non-idle state by PRIO
   desc + age asc, then idle alphabetically by cwd at the bottom.

   `usage_5h_pct` comes from `ccusage blocks --json --active --token-limit
   max` (Anthropic 5h-window). mock-cube spawns ccusage in a daemon thread,
   caches the result for 30s in `_USAGE`, returns `null` while refreshing
   or if ccusage is unavailable. `CUBE_USAGE_TOKEN_LIMIT` (env) overrides
   ccusage's historical-max heuristic with the Anthropic-plan-specific
   value (Max(5x) ≈ 155M empirically).

   Bind defaults to `127.0.0.1:8765`. For the Windows overlay set
   `CUBE_MOCK_HOST=0.0.0.0` so the WSL-host IP route works.

3. **`bin/win/cube-overlay-win-html.pyw`** + `bin/win/html/` —
   Windows-native frameless WebView2 window driven by pywebview. Polls
   `/dashboard.json` every 500 ms, renders rows + usage + voxel-cube
   canvas. `cube-entity.js` is the renderer: 33 voxel cubes in 3
   concentric rings with a cyan core, 8 emotions mapped from dashboard
   states (`thinking→thinking`, `permission→listening`, `done→happy`,
   `idle→idle`, `error→error`, `compact→focused`, `alert→surprised`,
   `start→curious`). `setEmotion` swaps the config atomically with a
   ~600 ms tween on color + radial-pulse envelope; motion-language params
   (orbitSpeed, shake, flash) snap instantly because the eye latches onto
   continuous change.

   WebView2 can't load `file://` from UNC paths
   (`\\wsl.localhost\...`), so the pyw inlines `overlay.css`,
   `cube-entity.js`, and `overlay.js` into the `index.html` document at
   startup and passes the resulting string as `html=...` to
   `webview.create_window`. pywebview's transient HTTP server handles
   inlined HTML fine.

   Per-machine settings live in `%APPDATA%\cube\overlay.env`
   (`CUBE_OVERLAY_THEME`, `_WIDTH`, `_POSITION_LOCKED`, `_HIDE_ENTITY`) +
   `overlay-layouts.json` (per-monitor bottom-right anchor, written by
   drag-end + Reset menu).

Hooks themselves are configured in `~/.claude/settings.json` outside this
repo. Wire each hook to `~/.claude/bin/cube.sh <state>`:

| Hook | cube.sh arg |
|---|---|
| `SessionStart` | `start` |
| `SessionEnd` | `end` |
| `UserPromptSubmit` | `thinking` |
| `Stop` | `done` |
| `Notification` | `alert` |
| `PermissionRequest` | `permission` |
| `PostToolUseFailure` matcher `Bash` | `error` |
| `PreCompact` | `compact` |

## Common commands

```bash
make deploy           # install cube.sh + mock-cube.py + mock-cube.service to ~/.claude/
make dev-install      # deploy + enable systemd --user mock-cube unit
make mock             # foreground run of mock-cube.py (Ctrl-C to stop)

bin/cube.sh thinking|alert|permission|error|compact|done|idle|start
bin/cube.sh end       # evict current CLI session
bin/cube.sh info      # live sessions + aggregated winner
```

Direct dashboard read (also works deployed at `~/.claude/bin/`):

```bash
curl -s http://127.0.0.1:8765/dashboard.json | jq .
```

## When changing `cube.sh`

- Keep it non-blocking. New states should follow the `show <label>` pattern
  and write per-session state so auto-revert logic stays coherent.
- Auto-revert delays are env-driven (`CUBE_{ALERT,PERMISSION,ERROR,COMPACT,
  DONE,START}_REVERT`); when adding a new revertable state, extend
  `schedule_revert` and the env list together rather than hard-coding a delay.
- Revert target rule: interruptions of active work
  (`alert`/`error`/`compact`/`permission`) pass `@prev` to
  `schedule_revert` so the session resumes the last stable state
  (`thinking`/`idle`) captured in `prev_state`. End-of-task or greeting
  states (`done`/`start`) pass nothing — default `idle`. `prev_state` is
  captured in `mutate update`'s `TRANSIENT` branch; carries forward across
  chained transients (error → alert keeps thinking).
- After editing, run `make deploy` — the live hook script is
  `~/.claude/bin/cube.sh`, not the repo copy.

## When changing `mock-cube.py`

- Keep `SESSION_PRIO` map in sync with `cube.sh`'s PRIO map — they need to
  agree on the winner.
- `/dashboard.json` is the only contract the overlay depends on. New fields
  fine; renaming existing ones breaks the JS poll loop.
- ccusage subprocess is intentionally async + cached. Don't make
  `_read_usage_pct` block on the subprocess.

## When changing the overlay (`bin/win/html/`)

- `overlay.js` polls `pywebview.api.dashboard()` every `POLL_MS` (500).
  Heavy work belongs in the JS — Python bridge is for OS-level things
  (drag/menu/window).
- `cube-entity.js` is self-contained (IIFE + window exports). Its
  emotions are pruned to the 8 dashboard states; do not mix in editor-only
  presets without confirming they map to a dashboard state.
- Cube-entity tweens between emotions (~600 ms) by lerping color + radial-
  pulse-envelope; motion-language params snap. If you add a new emotion,
  decide which bucket each param belongs to.
- All three assets (`overlay.css`, `cube-entity.js`, `overlay.js`) are
  inlined by `cube-overlay-win-html.pyw` at startup. External `<script
  src="…">` tags in `index.html` don't resolve under pywebview's
  no-base-URL `html=` mode — they must inline through the pyw.

## Peon-ping synergy (audio sibling)

`~/.claude/hooks/peon-ping/` is the user's audio-notification system. It
fires on the **same 8 hook points** the overlay uses and uses a similar
event taxonomy. The two are paired: every state the overlay shows visually,
peon-ping sounds for. When extending the overlay, **mirror peon-ping's
coverage** rather than diverging — they share `~/.claude/settings.json`.

Peon-ping has features the overlay does not (yet): runtime enable/disable
toggle, per-category mute, pack rotation, IDE/path rules. Don't port these
blindly — visual signal is binary in a way audio isn't. Add only if a real
workflow asks.

## Requirements

`bash`, `curl`, `python3` (hook payload parse + atomic JSON mutation),
`flock` (concurrent hook locking). `node` + `npx` only if you want the
overlay's usage line populated (mock-cube spawns `ccusage` on demand;
absence simply leaves `usage_5h_pct=null` → overlay shows `Use —`).

Windows host: Python 3.13 + `pywebview` (pythonnet wheels not yet built
for 3.14), WebView2-Runtime (preinstalled on Win11; otherwise via Edge or
Edge-WebView2-Standalone-Installer).
