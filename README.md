# cube — Claude Code Status auf GeekMagic SmallTV-Ultra

Verwandelt einen [GeekMagic SmallTV-Ultra](https://github.com/GeekMagicClock/smalltv-ultra)
(ESP8266, 1.5" IPS, 240×240) in ein Live-Status-Display für Claude Code:

| Claude-Hook | Cube zeigt | Auto-Revert | peon-ping Kategorie |
|---|---|---|---|
| `SessionStart` | `idle.gif` | — | `session.start` |
| `UserPromptSubmit` (Prompt rein, denkt) | `thinking.gif` | — | `task.acknowledge` |
| `Stop` (Antwort fertig) | `done.gif` | 5 s → idle | `task.complete` |
| `Notification` | `alert.gif` | 30 s → idle | (varies) |
| `PermissionRequest` | `permission.gif` (waifu) / `alert.gif` (orb) | 0 (forever, bis User handelt) | `input.required` |
| `PostToolUseFailure` (Bash) | `error.gif` (waifu) / `alert.gif` (orb) | 30 s → idle | `task.error` |
| `PreCompact` (Kontext voll) | `compact.gif` (waifu) / `alert.gif` (orb) | 30 s → idle | `resource.limit` |
| `SessionEnd` | (Session-Eviction) | — | (cleanup) |

Permission revert ist absichtlich 0 — Claude ist bis zur User-Reaktion blockiert,
ein Auto-Revert auf `idle` wäre irreführend. Hooks-Set spiegelt 1:1 das von
[peon-ping](https://github.com/) (Audio-Sibling), so dass Cube und Sound im
Gleichschritt feuern.

### Skin-Preview

| Skin | thinking | alert | idle | done |
|---|:---:|:---:|:---:|:---:|
| **orb** | <img src="assets/240/orb/thinking.gif" width="120" alt="orb thinking"> | <img src="assets/240/orb/alert.gif" width="120" alt="orb alert"> | <img src="assets/240/orb/idle.gif" width="120" alt="orb idle"> | <img src="assets/240/orb/done.gif" width="120" alt="orb done"> |
| **waifu** | <img src="assets/240/waifu/thinking.gif" width="120" alt="waifu thinking"> | <img src="assets/240/waifu/alert.gif" width="120" alt="waifu alert"> | <img src="assets/240/waifu/idle.gif" width="120" alt="waifu idle"> | <img src="assets/240/waifu/done.gif" width="120" alt="waifu done"> |

Waifu hat zusätzlich dedizierte `permission` / `error` / `compact` GIFs (orb
fällt für diese States auf `alert.gif` zurück):

| Skin | permission | error | compact |
|---|:---:|:---:|:---:|
| **waifu** | <img src="assets/240/waifu/permission.gif" width="120" alt="waifu permission"> | <img src="assets/240/waifu/error.gif" width="120" alt="waifu error"> | <img src="assets/240/waifu/compact.gif" width="120" alt="waifu compact"> |

`cube.sh skin <orb|waifu>` schaltet zwischen den Sets. Files für beide Skins
liegen parallel auf dem Cube; gewählt wird client-seitig in `cube.sh`. Lokal
trennen die Quellen sich in `assets/<skin>/<state>.gif` — beim Upload
übersetzt `upload.sh` auf die flache Cube-Konvention (`<state>.gif` für orb,
`<skin>_<state>.gif` sonst), da die Firmware in `/image/` keine Subdirs
navigiert.

Pixel-Art generiert per [PixelLab.ai](https://www.pixellab.ai), per-Skin
Prompts in `prompts/<skin>-skin.md`, zusätzlich Sat-15 / Con+45 / Sharp+50
Post-Process via `bin/contrast-fix.py` zur Rettung der 1-2px Wimpern/Brauen
durch Cube-Quantize.

## Funktionsweise

Claude Code feuert Hooks (`SessionStart/End`, `UserPromptSubmit`, `Stop`, `Notification`,
`PermissionRequest`, `PostToolUseFailure`, `PreCompact`). Jeder Hook ruft
`cube.sh <state>` auf, welches per HTTP `GET /set?img=/image/<state>.gif` das
passende GIF anzeigt. Non-blocking: bei toter Cube läuft Claude unverändert
weiter (2s curl-Timeout + `exit 0`).

**Multi-Session-aware:** Cube.sh liest `session_id` aus dem Hook-Stdin-JSON
(via `jq`) und tracked Zustand **pro Session** in `/tmp/.cube-sessions-$UID.json`.
Bei mehreren parallelen Claude-Sessions wird der Display-Zustand per Priorität
aggregiert: `permission > error > compact > thinking > alert > idle`. Beispiel:
Session A denkt, Session B beendet — Cube bleibt auf `thinking`. Session A
beendet → Cube auf `idle`. Stale Sessions (>1 h kein Update) werden geprunet.
Auto-Revert ist TOCTOU-sicher via Per-Session Seq-Counter.

```
┌─────────────────────────┐  GET /set?img=...   ┌──────────────────────┐
│ Claude Code Hook        │ ──────────────────► │ SmallTV-Ultra        │
│ ~/.claude/settings.json │                     │ $CUBE_IP             │
└──────────┬──────────────┘                     │ Theme 3 (Photo Album)│
           │ executes                           │ Plays /image/X.gif   │
           ▼                                    └──────────────────────┘
  ~/.claude/bin/cube.sh
```

## Projektstruktur

```
cube/
├── README.md             ← du bist hier
├── Makefile              ← Top-Level Targets (resize, upload, deploy, cycle)
├── bin/
│   ├── cube.sh           ← Haupt-CLI (wird nach ~/.claude/bin/ deployed)
│   ├── cube-gen.py       ← Pillow-Placeholder-Generator (optional)
│   ├── resize.sh         ← 128/256 → 240×240 via gifsicle, per-skin
│   ├── upload.sh         ← POST GIFs an Cube /doUpload, prefix-translation
│   ├── contrast-fix.py   ← Pillow Sat/Con/Sharp pro Frame (Brauen-Rescue)
│   ├── deploy.sh         ← Sync bin/cube.sh* → ~/.claude/bin/
│   ├── cycle.sh          ← Visueller Smoke-Test
│   └── clear-old.sh      ← Räumt Cube auf (Dry-run + --force)
├── assets/
│   ├── orb/              ← orb-skin source GIFs (thinking/alert/idle/done)
│   ├── waifu/            ← waifu-skin source GIFs (alle 7 states)
│   └── 240/
│       ├── orb/          ← orb 240×240 hochskaliert
│       └── waifu/        ← waifu 240×240 hochskaliert
└── prompts/
    ├── 00-style-guide.md ← orb-Maskottchen-Design + Palette
    ├── 01-thinking.md    ← Asset-Prompts für thinking-Animation (orb)
    ├── 02-alert.md       ← (orb)
    ├── 03-idle.md        ← (orb)
    ├── 04-workflow.md    ← End-to-End Frames → GIF → Cube
    ├── waifu-skin.md     ← Magical-Girl-Pink skin: alle 7 states
    └── yuri-skin.md      ← Yuri-Style skin (geplant, noch keine Assets)
```

## Setup

```bash
cp .env.example .env
$EDITOR .env          # CUBE_IP=<deine-cube-ip>
```

Alternativ global für deployten Stand (`~/.claude/bin/cube.sh`):
```bash
mkdir -p ~/.config/cube
echo "CUBE_IP=<deine-cube-ip>" > ~/.config/cube/config
```

Lookup-Reihenfolge: `$CUBE_IP` env → `~/.config/cube/config` → `<projekt>/.env`.
Ohne Wert brechen die Tools mit klarer Meldung ab.

## Quick Start

```bash
make ping             # Cube erreichbar?
make status           # was liegt lokal + auf cube?
make all              # resize + upload (in einem)
make cycle            # visueller Test
```

## Workflow: neue Animation hinzufügen

1. **Generieren** in [PixelLab.ai Character Creator + Animate](https://www.pixellab.ai)
   - Action Descriptions und Style-Anchor aus `prompts/<skin>-skin.md` übernehmen
   - 64×64, 128×128 oder 256×256 (Credits sparen)
   - Export als GIF nach `assets/<skin>/<state>.gif`
     z.B. `assets/waifu/permission.gif`
2. **(Optional) Contrast-fix** falls Brauen/Wimpern bei mono-Palette wegquantizen:
   `bin/contrast-fix.py assets/<skin>/<state>.gif /tmp/out.gif && mv /tmp/out.gif assets/<skin>/<state>.gif`
3. **Resize**: `make resize` → erzeugt `assets/240/<skin>/<state>.gif`
   - oder gezielt: `bin/resize.sh waifu`
4. **Upload**: `make upload` → schickt an Cube `/image/` mit prefix-translation
   - orb: `<state>.gif`, sonst `<skin>_<state>.gif`
5. **Test**: `make cycle` oder `bin/cube.sh <state>` (skin via `cube.sh skin <name>`)

## Manuelle Cube-Steuerung

```bash
bin/cube.sh thinking         # state-gif, gleich für orb/waifu (über skin)
bin/cube.sh alert            # auto-revert nach CUBE_ALERT_REVERT s (default 30)
bin/cube.sh permission       # auto-revert CUBE_PERMISSION_REVERT s (default 0 = forever)
bin/cube.sh error            # PostToolUseFailure-Variante, revert via CUBE_ERROR_REVERT
bin/cube.sh compact          # PreCompact-Variante, revert via CUBE_COMPACT_REVERT
bin/cube.sh idle
bin/cube.sh end              # Session aus Map evicten (für SessionEnd-Hook)
bin/cube.sh skin             # show current skin
bin/cube.sh skin waifu       # switch to waifu (or "orb")
bin/cube.sh img foo.gif      # beliebige Datei in /image/
bin/cube.sh theme 1          # 1=WeatherClock, 3=PhotoAlbum, 7=SimpleWeather
bin/cube.sh brt 60           # Helligkeit -10..100 (-10 = aus)
bin/cube.sh list             # was liegt in /image/
bin/cube.sh info             # Version + Status + Free Space + skin + state
bin/cube.sh ping             # Connectivity-Check (exit 1 on fail)
```

**Env-Tweaks:**
```bash
CUBE_ALERT_REVERT=60 cube.sh alert      # länger (default 30 s)
CUBE_ALERT_REVERT=0 cube.sh alert       # disabled (alert bleibt forever)
CUBE_PERMISSION_REVERT=60 cube.sh permission   # default 0 = forever
CUBE_ERROR_REVERT=10 cube.sh error      # default = CUBE_ALERT_REVERT
CUBE_SESSION_TTL=600 cube.sh ...        # stale-prune nach 10 min (default 3600)
CUBE_SESSIONS_FILE=/tmp/foo.json …      # alternativer State-Store (für Tests)
CUBE_SKIN=orb cube.sh thinking          # einmaliger skin-override
```

`cube.sh info` zeigt alle live Sessions mit State, Seq und Age + den
aggregierten Display-Winner.

Oder in Claude Code via Slash-Command: `/cube thinking|alert|idle|...`

## Cube HTTP-API Cheat-Sheet

Vollständige Liste auch im [Plan](~/.claude/plans/rustling-sniffing-planet.md).

| Endpoint | Zweck |
|---|---|
| `GET /v.json` | Model + Firmware-Version |
| `GET /app.json` | Aktuelles Theme |
| `GET /space.json` | Free Flash in Bytes |
| `GET /filelist?dir=/image/` | HTML-Listing |
| `GET /set?theme=1..7` | Theme wechseln (3 = Photo Album) |
| `GET /set?img=/image/FILE` | Datei direkt anzeigen |
| `GET /set?brt=0..100` | Helligkeit |
| `GET /set?reboot=1` | Reboot (~25s Recovery) |
| `GET /delete?file=/image/FILE` | Löschen |
| `POST /doUpload?dir=/image/` | Multipart Upload (Field: `file`) |

**Nicht verfügbar in v9.0.40** (alle FAIL): `/set?msg=`, `/set?note=`, `/set?cnt=`.

## Claude-Code Hook-Setup

In `~/.claude/settings.json` sind unter `hooks` folgende Einträge **additiv** ergänzt
(bestehende Peon-Ping Hooks bleiben unangetastet):

```json
"SessionStart":      [ ..., {"matcher": "", "hooks": [
  {"type": "command", "command": "~/.claude/bin/cube.sh idle",
   "timeout": 3, "async": true}]}],
"SessionEnd":        [ ..., {"matcher": "", "hooks": [
  {"type": "command", "command": "~/.claude/bin/cube.sh end",
   "timeout": 3, "async": true}]}],
"UserPromptSubmit":  [ ..., {"matcher": "", "hooks": [
  {"type": "command", "command": "~/.claude/bin/cube.sh thinking",
   "timeout": 3, "async": true}]}],
"Stop":              [ ..., {"matcher": "", "hooks": [
  {"type": "command", "command": "~/.claude/bin/cube.sh idle",
   "timeout": 3, "async": true}]}],
"Notification":      [ ..., {"matcher": "", "hooks": [
  {"type": "command", "command": "~/.claude/bin/cube.sh alert",
   "timeout": 3, "async": true}]}],
"PermissionRequest": [ ..., {"matcher": "", "hooks": [
  {"type": "command", "command": "~/.claude/bin/cube.sh permission",
   "timeout": 3, "async": true}]}],
"PostToolUseFailure":[ ..., {"matcher": "Bash", "hooks": [
  {"type": "command", "command": "~/.claude/bin/cube.sh error",
   "timeout": 3, "async": true}]}],
"PreCompact":        [ ..., {"matcher": "", "hooks": [
  {"type": "command", "command": "~/.claude/bin/cube.sh compact",
   "timeout": 3, "async": true}]}]
```

Backup vor Änderungen liegt unter `~/.claude/settings.json.bak-*`.

## Requirements

- `bash`, `curl` — überall da
- `jq` — Session-ID-Extraktion aus Hook-Stdin (`sudo apt install jq`)
- `python3` — Atomic State-File Mutation (i.d.R. vorinstalliert)
- `flock` (`util-linux`, vorinstalliert) — File-Locking für concurrent hooks
- `gifsicle` — für Resize 128/256 → 240 (`sudo apt install gifsicle`)
- `python3-pil` — für `bin/contrast-fix.py` (Sat/Con/Sharp Rescue für mono-Palette skins). `sudo apt install python3-pil`
- `python3-requests` — optional, nur für `cube-gen.py` (Placeholder-Generator)
- Claude Code mit Hooks-Support

## Tweaks (Cube selbst)

- **Firmware-Update** auf v9.0.50 via http://$CUBE_IP/update — neuer Build aus
  https://github.com/GeekMagicClock/smalltv-ultra/tree/main/Ultra-V9.0.50
- **Auto-Theme-Switch deaktivieren** (sonst überschreibt es unsere Hook-Befehle):
  http://$CUBE_IP/ → "Auto Switch Themes" Häkchen aus
- **Nacht-Modus**: http://$CUBE_IP/ → Section "Night Mode" → 22-07 mit brt=10
- **Lokaler NTP**: http://$CUBE_IP/time.html → Router-IP (z.B. Fritzbox-Gateway)
- **Eigener OpenWeatherMap-Key**: http://$CUBE_IP/weather.html

## Troubleshooting

| Symptom | Fix |
|---|---|
| Cube zeigt "no images" trotz Upload | Reboot via `bin/cube.sh` (kein Direkt-Befehl; nutze `curl "http://CUBE/set?reboot=1"`) |
| Bild nur ¼ des Displays | GIF ist 128×128 (oder 256×256 unaligned), `make resize` ausführen |
| Brauen/Wimpern werden weiß bei waifu-Skin | `bin/contrast-fix.py` auf source applizieren, dann resize+upload |
| Hooks feuern nicht | Neue Claude-Session starten — Hooks werden bei Session-Start gelesen |
| "Auto Switch Themes" überschreibt Hook-Bilder | http://$CUBE_IP/ → Auto-Switch deaktivieren |
| Upload-curl bricht mit "duplicate Content-Length" ab | Cube-FW-Bug, Upload klappt trotzdem — `-f` flag bei curl entfernt sich beschwert nicht |
| Cube hängt nach großer GIF | Datei <50KB, max 8 Frames |

## Quellen / Inspiration

- Community-Reverse-Engineering: [adrienbrault/geekmagic-hacs](https://github.com/adrienbrault/geekmagic-hacs)
- HA-Integration mit text/note-Endpoints: [aydarik/hass-geekmagic](https://github.com/aydarik/hass-geekmagic)
- Original-Firmware: [GeekMagicClock/smalltv-ultra](https://github.com/GeekMagicClock/smalltv-ultra)
- Pixel-GIF-Sammlung: [GeekMagicClock/gif](https://github.com/GeekMagicClock/gif)
