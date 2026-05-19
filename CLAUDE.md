# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Bash-and-curl glue that turns a GeekMagic SmallTV-Ultra (ESP8266, 240×240 IPS) into a live status display for Claude Code itself. Claude Code hooks (`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `Stop`, `Notification`, `PermissionRequest`, `PostToolUseFailure`, `PreCompact` — see synergy table below) shell out to `bin/cube.sh <state>`, which fires a `GET /set?img=/image/<state>.gif` at the device. No daemon, no server — pure HTTP from hook to firmware.

The README is in German; this file is the English working reference.

## Architecture, in five pieces

1. **`bin/cube.sh`** — the only runtime component. Single bash script that hooks invoke. Designed to never block Claude: 2s curl timeout, swallows all errors, always `exit 0`. **Multi-session aware:** reads `session_id` from hook stdin JSON (jq), tracks per-session state in `/tmp/.cube-sessions-$UID.json` (atomic via flock + python3 + temp+rename), and aggregates across sessions by priority: `permission > error > compact > done > thinking > alert > start > idle`. Per-session `seq` counter makes auto-revert TOCTOU-safe — a stale revert never stomps an active session. **Revert target:** `alert`/`error`/`compact`/`permission` restore the session's `prev_state` (last stable thinking/idle, captured on transient entry) so a Bash failure during thinking returns to thinking, not idle. `done`/`start` revert to `idle` hardcoded — they represent task-ended / session-greeting. Stale sessions (>`CUBE_SESSION_TTL`s, default 3600) pruned on every write. **Skins** (`orb` / `waifu`) are a client-side selector stored in `~/.claude/.cube-skin`; locally each skin's source GIFs live in `assets/<skin>/`, on the cube they coexist as flat files using the legacy prefix convention (orb keeps unprefixed names, others get `<skin>_<state>.gif`).
2. **Asset pipeline** — pixel-art source GIFs from PixelLab.ai live in **per-skin subdirs**: `assets/<skin>/<state>.gif` (typically 128×128 or 256×256). `resize.sh` (gifsicle `--resize-method=sample`, nearest-neighbor) normalizes them to 240×240 in `assets/240/<skin>/<state>.gif`. `upload.sh` then POSTs multipart to `/doUpload?dir=/image/` and **translates the filename** — orb files upload as `<state>.gif` (no prefix, legacy), others as `<skin>_<state>.gif` — because the firmware does not navigate subdirectories under `/image/`. Sample-resize is deliberate — pixel art must not be smoothed. `bin/contrast-fix.py` (Pillow Sat/Con/Sharp per-frame + no-dither quantize) optionally rescues 1-2px dark detail (eyebrows, eyelashes) from cube-quantization loss in mono-palette skins like `waifu`. Asset-prompt docs per skin live in `prompts/` (`waifu-skin.md`, `yuri-skin.md`). **Desktop-only overrides:** `assets/desktop/<skin>/<state>.gif` is a parallel hi-res layer for the overlay — no size/frame/quantization limits (typical 256×256, 7–16 frames). `mock-cube.py:resolve_local()` probes `assets/desktop/<skin>/` before falling back to `assets/<skin>/`, so the overlay automatically renders the smoother variant when present. `resize.sh`/`upload.sh` skip the `desktop/` dir by name — these files never reach the cube. Per-state, partial coverage is fine: missing entries fall through to the cube source (same filenames).
3. **Deploy** — `deploy.sh` copies `bin/cube.sh`, `bin/cube-gen.py`, `bin/cube-watchdog.sh`, `bin/mock-cube.py`, and `bin/cube-overlay.py` into `~/.claude/bin/` where the hooks reference them, and installs `cube-watchdog.service` + `mock-cube.service` + `cube-overlay.service` into `~/.config/systemd/user/`. The repo is the source of truth; the deployed files are artifacts.
4. **Watchdog** — `bin/cube-watchdog.sh` is an optional long-running process that polls cube reachability every 15 s and calls `cube.sh redisplay` on offline → online transitions, so the cube returns to a Claude-driven state (or `idle`) after a firmware reboot/crash. Install via the shipped systemd --user unit (`bin/cube-watchdog.service`) or `nohup`. The `redisplay` subcommand reads the sessions map and pushes the current aggregated winner without mutating session state — safe to call from cron, watchdogs, or after manual recovery.
5. **Dev mode without hardware** — `bin/mock-cube.py` is a stdlib HTTP server that mimics the cube's endpoints; `bin/cube-overlay.py` is a frameless Tk window (WSLg-friendly) that polls the mock and shows the active state's raw PixelLab GIF on the desktop, hidden when state=`idle`. Overlay resamples GIFs to `args.size` with PIL `Image.LANCZOS` (high-quality sinc filter) — smoother than NEAREST for the hi-res `assets/desktop/<skin>/` overrides; the cube-pipeline's `gifsicle --resize-method=sample` remains nearest because firmware quantization benefits from crisp pixel boundaries. cube.sh fans every state-mutation to `$CUBE_IP` **and** every host in `$CUBE_MIRROR` (comma-separated), so once `CUBE_MIRROR=127.0.0.1:8080` is set in `~/.config/cube/config`, the overlay shows hook activity whether the real cube is reachable (home) or not (office) — no config change between locations. Install via `make dev-install` (systemd --user units mirror the watchdog pattern). The mock-cube unit loads `~/.config/cube/config` via `EnvironmentFile=-…` so plan-specific overrides (see below) reach the subprocess; systemd --user PATH excludes nvm so mock-cube scans `~/.nvm/versions/node/*/bin/npx` as fallback and injects that directory into the ccusage subprocess PATH (npx shebang resolves `node` via PATH). Per-machine overlay position lives in `~/.config/cube/overlay.env` (`CUBE_OVERLAY_X=…`, `CUBE_OVERLAY_Y=…`, `CUBE_OVERLAY_SIZE=…`, `CUBE_OVERLAY_WIDTH=…`). The overlay is a compact dashboard: above the animation it shows the **project basename** (cwd of the session whose state currently wins the priority resolution — captured from hook stdin `.cwd`, persisted in the sessions JSON as per-session `cwd` and top-level `displayed_cwd`) and the **5h-window token usage %** (mock-cube spawns `ccusage blocks --json --active --token-limit max` in a background thread, caches the result for 30s in `_USAGE`, and exposes it via the new `/dashboard.json` endpoint — `usage_5h_pct` is `null` while the first refresh is in flight or if ccusage is unavailable). The percentage = `totalTokens / limit` where `limit` comes from `CUBE_USAGE_TOKEN_LIMIT` (env, set in `~/.config/cube/config`) if present, else ccusage's `tokenLimitStatus.limit` (= highest historical 5h block). Anthropic does not publish exact Max-plan token limits, so the env override is the only way to make the overlay match the Anthropic web dashboard — pick a value empirically (Max(5x) lands around 155M in practice, but YMMV). Color thresholds (<50 green / <80 yellow / ≥80 red) mirror `~/.claude/statusline-command.sh`.

Hooks themselves are configured in `~/.claude/settings.json` outside this repo (README §"Claude-Code Hook-Setup" shows the JSON).

## Peon-ping synergy (audio sibling)

`~/.claude/hooks/peon-ping/` is the user's audio-notification system. It fires on the **same 8 hook points** the cube uses and uses a similar event taxonomy. The two are paired: every state the cube shows visually, peon-ping sounds for. When extending cube, **mirror peon-ping's coverage** rather than diverging — they share `~/.claude/settings.json`.

Hook → cube subcommand → peon category:

| Hook | cube.sh arg | peon category |
|---|---|---|
| `SessionStart` | `start` (5s revert → idle; visual alias for done.gif) | `session.start` |
| `SessionEnd` | `end` (evicts session_id) | cleanup |
| `UserPromptSubmit` | `thinking` | `task.acknowledge` |
| `Stop` | `done` (5s revert → idle) | `task.complete` |
| `Notification` | `alert` (5s revert → prev_state) | (varies) |
| `PermissionRequest` | `permission` (5s revert → prev_state; set `CUBE_PERMISSION_REVERT=0` for forever) | `input.required` |
| `PostToolUseFailure` matcher `Bash` | `error` (5s revert → prev_state) | `task.error` |
| `PreCompact` | `compact` (5s revert → prev_state) | `resource.limit` |

`gif_for` in `cube.sh` is **skin-aware**: the `waifu` skin has dedicated GIFs for all seven states (`waifu_permission.gif`, `waifu_error.gif`, `waifu_compact.gif`, `waifu_done.gif`). The `orb` skin still falls back — `permission|error|compact` all resolve to `alert.gif`. Distinct state labels matter regardless of asset: they keep the auto-revert background job from stomping a newer state with `idle` when reverts overlap. When adding dedicated orb assets, drop them next to the others and extend the waifu-branch of `gif_for` to cover orb as well.

When adding new states or hooks: only the eight `show`-routed states (`thinking|alert|permission|error|compact|done|idle|start`) and `end` touch the sessions map. `img`/`theme`/`brt`/`list`/`skin`/`info`/`ping` are session-agnostic passthroughs — don't route them through `update_session`. Manual invocations from a terminal map to session_id `cli`, which behaves like any other session.

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
make deploy            # install cube.sh + cube-gen.py + watchdog + mock-cube + overlay to ~/.claude/bin/ + systemd units
make cycle             # visual smoke-test: thinking → alert → idle (5s each)
make clear-old         # dry-run cleanup (keeps thinking/alert/idle.gif)
make clear-old FORCE=1 # actually delete
```

Direct cube control (also works deployed as `~/.claude/bin/cube.sh`):
```bash
bin/cube.sh thinking|alert|permission|error|compact|done|idle|start   # state GIFs (skin-aware)
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
- Auto-revert delays are env-driven (`CUBE_{ALERT,PERMISSION,ERROR,COMPACT,DONE,START}_REVERT`); when adding a new revertable state, extend `schedule_revert` and the env list together rather than hard-coding a delay.
- Revert target rule: interruptions of active work (`alert`/`error`/`compact`/`permission`) pass `@prev` to `schedule_revert` so the session resumes the last stable state (`thinking`/`idle`) captured in `prev_state`. End-of-task or greeting states (`done`/`start`) pass nothing — default `idle`. `prev_state` is captured in `mutate update`'s `TRANSIENT` branch; carries forward across chained transients (error → alert keeps thinking). When adding a new revertable state, decide which bucket it belongs to and wire the case in `show()` accordingly.
- When adding a new skin: create `assets/<skin>/` with the seven state-named GIFs (or fewer + accept the alert.gif fallback like `orb`), extend both `prefix()` and the waifu-branch of `gif_for()`. `resize.sh` and `upload.sh` discover skins automatically by directory scan — no script change needed.
- After editing, run `make deploy` — the live hook script is `~/.claude/bin/cube.sh`, not the repo copy.

## Requirements

`bash`, `curl`, `jq` (hook session_id), `python3` (atomic JSON mutation + hook payload parse), `flock` (concurrent hook locking), `gifsicle` (for resize). `python3-pil python3-requests` only if using `cube-gen.py` (placeholder generator, not part of normal flow). `python3-tk` + `python3-pil.imagetk` only for dev mode (`cube-overlay.py`). `node` + `npx` only if you want the overlay's 5h-usage line populated (mock-cube spawns `ccusage` on demand; absence simply leaves `usage_5h_pct=null` → overlay shows `5h —`).
