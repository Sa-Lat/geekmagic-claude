# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Bash-and-curl glue that turns a GeekMagic SmallTV-Ultra (ESP8266, 240×240 IPS) into a live status display for Claude Code itself. Claude Code hooks (`UserPromptSubmit`, `Stop`, `Notification`, `PermissionRequest`) shell out to `bin/cube.sh <state>`, which fires a `GET /set?img=/image/<state>.gif` at the device. No daemon, no server — pure HTTP from hook to firmware.

The README is in German; this file is the English working reference.

## Architecture, in three pieces

1. **`bin/cube.sh`** — the only runtime component. Single bash script that hooks invoke. Designed to never block Claude: 2s curl timeout, swallows all errors, always `exit 0`. **Multi-session aware:** reads `session_id` from hook stdin JSON (jq), tracks per-session state in `/tmp/.cube-sessions-$UID.json` (atomic via flock + python3 + temp+rename), and aggregates across sessions by priority: `permission > error > compact > thinking > alert > idle`. Per-session `seq` counter makes auto-revert TOCTOU-safe — a stale revert never stomps an active session. Stale sessions (>`CUBE_SESSION_TTL`s, default 3600) pruned on every write. **Skins** (`orb` / `waifu`) are a client-side selector stored in `~/.claude/.cube-skin`; locally each skin's source GIFs live in `assets/<skin>/`, on the cube they coexist as flat files using the legacy prefix convention (orb keeps unprefixed names, others get `<skin>_<state>.gif`).
2. **Asset pipeline** — pixel-art source GIFs from PixelLab.ai live in **per-skin subdirs**: `assets/<skin>/<state>.gif` (typically 128×128 or 256×256). `resize.sh` (gifsicle `--resize-method=sample`, nearest-neighbor) normalizes them to 240×240 in `assets/240/<skin>/<state>.gif`. `upload.sh` then POSTs multipart to `/doUpload?dir=/image/` and **translates the filename** — orb files upload as `<state>.gif` (no prefix, legacy), others as `<skin>_<state>.gif` — because the firmware does not navigate subdirectories under `/image/`. Sample-resize is deliberate — pixel art must not be smoothed. `bin/contrast-fix.py` (Pillow Sat/Con/Sharp per-frame + no-dither quantize) optionally rescues 1-2px dark detail (eyebrows, eyelashes) from cube-quantization loss in mono-palette skins like `waifu`. Asset-prompt docs per skin live in `prompts/` (`waifu-skin.md`, `yuri-skin.md`).
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
| `Stop` | `done` (5s revert) | `task.complete` |
| `Notification` | `alert` (30s revert) | (varies) |
| `PermissionRequest` | `permission` (no revert) | `input.required` |
| `PostToolUseFailure` matcher `Bash` | `error` (30s revert) | `task.error` |
| `PreCompact` | `compact` (30s revert) | `resource.limit` |

`gif_for` in `cube.sh` is **skin-aware**: the `waifu` skin has dedicated GIFs for all seven states (`waifu_permission.gif`, `waifu_error.gif`, `waifu_compact.gif`, `waifu_done.gif`). The `orb` skin still falls back — `permission|error|compact` all resolve to `alert.gif`. Distinct state labels matter regardless of asset: they keep the auto-revert background job from stomping a newer state with `idle` when reverts overlap. When adding dedicated orb assets, drop them next to the others and extend the waifu-branch of `gif_for` to cover orb as well.

When adding new states or hooks: only the seven `show`-routed states (`thinking|alert|permission|error|compact|done|idle`) and `end` touch the sessions map. `img`/`theme`/`brt`/`list`/`skin`/`info`/`ping` are session-agnostic passthroughs — don't route them through `update_session`. Manual invocations from a terminal map to session_id `cli`, which behaves like any other session.

Peon-ping has features the cube does not (yet): runtime enable/disable toggle, per-category mute, pack rotation, IDE/path rules. Don't port these blindly — visual signal is binary in a way audio isn't. Add only if a real workflow asks.

## CUBE_IP config lookup

Every script resolves `CUBE_IP` in this order: env var → `~/.config/cube/config` → `<repo>/.env`. Missing value = hard error with the same message everywhere. When editing scripts, preserve this order — the deployed `cube.sh` runs from `~/.claude/bin/` so the `.env` fallback only works for local dev, not deployed.

## Common commands

```bash
make ping              # is the cube reachable at $CUBE_IP?
make info              # device version, theme, free space, current skin/state
make status            # local assets/ + assets/240/ + remote /image/ listing
make resize            # 128/256 → 240 per-skin (assets/<skin>/ → assets/240/<skin>/)
                       # bin/resize.sh <skin> to scope to one skin
make upload            # push assets/240/<skin>/*.gif to cube (flat, prefix-translated)
                       # bin/upload.sh <skin> to scope to one skin
make all               # resize + upload
make deploy            # install cube.sh + cube-gen.py to ~/.claude/bin/
make cycle             # visual smoke-test: thinking → alert → idle (5s each)
make clear-old         # dry-run cleanup (keeps thinking/alert/idle.gif)
make clear-old FORCE=1 # actually delete
```

Direct cube control (also works deployed as `~/.claude/bin/cube.sh`):
```bash
bin/cube.sh thinking|alert|permission|error|compact|done|idle    # state GIFs (skin-aware)
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
- GIF budget is soft: docs target ≤50 KB / ≤8 frames, but the cube has handled 100–160 KB / 12–18 frames per file in practice. Total `/image/` storage is ~3 MB — `make info` to check free space before bulk uploads, `make clear-old` to prune.

## When changing `cube.sh`

- Keep it non-blocking. New states should follow the `show <label> <file>` pattern and write per-session state so auto-revert logic stays coherent.
- Auto-revert delays are env-driven (`CUBE_{ALERT,PERMISSION,ERROR,COMPACT,DONE}_REVERT`); when adding a new revertable state, extend `schedule_revert` and the env list together rather than hard-coding a delay.
- When adding a new skin: create `assets/<skin>/` with the seven state-named GIFs (or fewer + accept the alert.gif fallback like `orb`), extend both `prefix()` and the waifu-branch of `gif_for()`. `resize.sh` and `upload.sh` discover skins automatically by directory scan — no script change needed.
- After editing, run `make deploy` — the live hook script is `~/.claude/bin/cube.sh`, not the repo copy.

## Requirements

`bash`, `curl`, `jq` (hook session_id), `python3` (atomic JSON mutation), `flock` (concurrent hook locking), `gifsicle` (for resize). `python3-pil python3-requests` only if using `cube-gen.py` (placeholder generator, not part of normal flow).
