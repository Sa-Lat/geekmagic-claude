# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Bash-and-curl glue that turns a GeekMagic SmallTV-Ultra (ESP8266, 240×240 IPS) into a live status display for Claude Code itself. Claude Code hooks (`UserPromptSubmit`, `Stop`, `Notification`, `PermissionRequest`) shell out to `bin/cube.sh <state>`, which fires a `GET /set?img=/image/<state>.gif` at the device. No daemon, no server — pure HTTP from hook to firmware.

The README is in German; this file is the English working reference.

## Architecture, in three pieces

1. **`bin/cube.sh`** — the only runtime component. Single bash script that hooks invoke. Designed to never block Claude: 2s curl timeout, swallows all errors, always `exit 0`. **Multi-session aware:** reads `session_id` from hook stdin JSON (jq), tracks per-session state in `/tmp/.cube-sessions-$UID.json` (atomic via flock + python3 + temp+rename), and aggregates across sessions by priority: `permission > error > compact > thinking > alert > idle`. Per-session `seq` counter makes auto-revert TOCTOU-safe — a stale revert never stomps an active session. Stale sessions (>`CUBE_SESSION_TTL`s, default 3600) pruned on every write. **Skins** (`orb` / `waifu`) are a client-side filename prefix stored in `~/.claude/.cube-skin`; both skins' GIFs live on the cube simultaneously.
2. **Asset pipeline** — 128×128 source GIFs from PixelLab.ai live in `assets/`. `resize.sh` (gifsicle nearest-neighbor) blows them up to `assets/240/`, then `upload.sh` POSTs multipart to `/doUpload?dir=/image/`. Resize uses `--resize-method=sample` deliberately — pixel art must not be smoothed.
3. **Deploy** — `deploy.sh` copies `bin/cube.sh` (+ optional `cube-gen.py` Pillow fallback) into `~/.claude/bin/` where the hooks reference it. The repo is the source of truth; `~/.claude/bin/cube.sh` is a deployed artifact.

Hooks themselves are configured in `~/.claude/settings.json` outside this repo (README §"Claude-Code Hook-Setup" shows the JSON).

## Peon-ping synergy (audio sibling)

`~/.claude/hooks/peon-ping/` is the user's audio-notification system. It fires on the **same 8 hook points** the cube uses and uses a similar event taxonomy. The two are paired: every state the cube shows visually, peon-ping sounds for. When extending cube, **mirror peon-ping's coverage** rather than diverging — they share `~/.claude/settings.json`.

Hook → cube subcommand → peon category:

| Hook | cube.sh arg | peon category |
|---|---|---|
| `SessionStart` | `idle` | `session.start` |
| `SessionEnd` | `end` (evicts session_id) | cleanup |
| `UserPromptSubmit` | `thinking` | `task.acknowledge` |
| `Stop` | `idle` | `task.complete` |
| `Notification` | `alert` (30s revert) | (varies) |
| `PermissionRequest` | `permission` (no revert) | `input.required` |
| `PostToolUseFailure` matcher `Bash` | `error` (30s revert) | `task.error` |
| `PreCompact` | `compact` (30s revert) | `resource.limit` |

`error` and `compact` are distinct **state labels** sharing `alert.gif`. Distinct labels matter so the auto-revert background job doesn't stomp a newer state with `idle` when reverts overlap. When adding dedicated assets, give them their own GIF and keep the label as-is.

When adding new states or hooks: only the six `show`-routed states (`thinking|alert|permission|error|compact|idle`) and `end` touch the sessions map. `img`/`theme`/`brt`/`list`/`skin`/`info`/`ping` are session-agnostic passthroughs — don't route them through `update_session`. Manual invocations from a terminal map to session_id `cli`, which behaves like any other session.

Peon-ping has features the cube does not (yet): runtime enable/disable toggle, per-category mute, pack rotation, IDE/path rules. Don't port these blindly — visual signal is binary in a way audio isn't. Add only if a real workflow asks.

## CUBE_IP config lookup

Every script resolves `CUBE_IP` in this order: env var → `~/.config/cube/config` → `<repo>/.env`. Missing value = hard error with the same message everywhere. When editing scripts, preserve this order — the deployed `cube.sh` runs from `~/.claude/bin/` so the `.env` fallback only works for local dev, not deployed.

## Common commands

```bash
make ping              # is the cube reachable at $CUBE_IP?
make info              # device version, theme, free space, current skin/state
make status            # local assets/ + assets/240/ + remote /image/ listing
make resize            # 128→240 for everything in assets/
make upload            # push assets/240/*.gif to cube
make all               # resize + upload
make deploy            # install cube.sh + cube-gen.py to ~/.claude/bin/
make cycle             # visual smoke-test: thinking → alert → idle (5s each)
make clear-old         # dry-run cleanup (keeps thinking/alert/idle.gif)
make clear-old FORCE=1 # actually delete
```

Direct cube control (also works deployed as `~/.claude/bin/cube.sh`):
```bash
bin/cube.sh thinking|alert|permission|idle    # state GIFs (skin-aware)
bin/cube.sh skin [orb|waifu]                  # get/set mascot
bin/cube.sh img <file>                        # show arbitrary uploaded file
bin/cube.sh theme <1-7>                       # 3 = Photo Album (what we need)
bin/cube.sh brt <-10..100>                    # -10 = off
bin/cube.sh info | list | ping
```

## Cube HTTP-API gotchas

Firmware v9.0.40-ish. These work:
- `GET /v.json`, `/app.json`, `/space.json`
- `GET /filelist?dir=/image/` (returns HTML, parsed with grep in scripts)
- `GET /set?img=/image/FILE`, `?theme=1..7`, `?brt=N`, `?reboot=1`
- `GET /delete?file=/image/FILE`
- `POST /doUpload?dir=/image/` (multipart, field `file`)

These **all fail** on current firmware — don't bother adding features that use them: `/set?msg=`, `/set?note=`, `/set?cnt=`.

Other gotchas:
- "Auto Switch Themes" in the device web-UI will overwrite hook-set images. Must be disabled in the cube settings, not workaroundable in code.
- Upload curl emits a "duplicate Content-Length" warning — firmware bug, upload succeeds anyway. Don't try to silence with `-f` cleverness.
- Max practical GIF: ~50 KB, ≤8 frames. Bigger and the cube hangs.

## When changing `cube.sh`

- Keep it non-blocking. New states should follow the `show <label> <file>` pattern and write to `$STATE_FILE` so auto-revert logic stays coherent.
- Adding a third auto-revert state? Generalize `schedule_revert` rather than copy-pasting the alert/permission branches.
- After editing, run `make deploy` — the live hook script is `~/.claude/bin/cube.sh`, not the repo copy.

## Requirements

`bash`, `curl`, `jq` (hook session_id), `python3` (atomic JSON mutation), `flock` (concurrent hook locking), `gifsicle` (for resize). `python3-pil python3-requests` only if using `cube-gen.py` (placeholder generator, not part of normal flow).
