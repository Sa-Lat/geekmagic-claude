# cube — Claude Code Status auf GeekMagic SmallTV-Ultra

Verwandelt einen [GeekMagic SmallTV-Ultra](https://github.com/GeekMagicClock/smalltv-ultra)
(ESP8266, 1.5" IPS, 240×240) in ein Live-Status-Display für Claude Code:

| Claude-Hook | Cube zeigt | Auto-Revert | peon-ping Kategorie |
|---|---|---|---|
| `SessionStart` | `idle.gif` | — | `session.start` |
| `UserPromptSubmit` (Prompt rein, denkt) | `thinking.gif` | — | `task.acknowledge` |
| `Stop` (Antwort fertig) | `idle.gif` | — | `task.complete` |
| `Notification` | `alert.gif` | 30 s → idle | (varies) |
| `PermissionRequest` | `alert.gif` (permission) | 0 (forever, bis User handelt) | `input.required` |
| `PostToolUseFailure` (Bash) | `alert.gif` (error) | 30 s → idle | `task.error` |
| `PreCompact` (Kontext voll) | `alert.gif` (compact) | 30 s → idle | `resource.limit` |
| `SessionEnd` | `idle.gif` | — | (cleanup) |

Permission revert ist absichtlich 0 — Claude ist bis zur User-Reaktion blockiert,
ein Auto-Revert auf `idle` wäre irreführend. Hooks-Set spiegelt 1:1 das von
[peon-ping](https://github.com/) (Audio-Sibling), so dass Cube und Sound im
Gleichschritt feuern.

### Skin-Preview

| Skin | thinking | alert | idle |
|---|:---:|:---:|:---:|
| **orb** | <img src="assets/240/thinking.gif" width="140" alt="orb thinking"> | <img src="assets/240/alert.gif" width="140" alt="orb alert"> | <img src="assets/240/idle.gif" width="140" alt="orb idle"> |
| **waifu** | <img src="assets/240/waifu_thinking.gif" width="140" alt="waifu thinking"> | <img src="assets/240/waifu_alert.gif" width="140" alt="waifu alert"> | <img src="assets/240/waifu_idle.gif" width="140" alt="waifu idle"> |

`cube.sh skin <orb|waifu>` schaltet zwischen den Maskottchen-Sets. Files für
beide bleiben auf dem Cube, switch ist client-seitiges Filename-Prefixing.

Die Animationen sind Pixel-Art Maskottchen, generiert per [PixelLab.ai](https://www.pixellab.ai)
(Prompts in `prompts/`).

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
│   ├── resize.sh         ← 128×128 → 240×240 via gifsicle
│   ├── upload.sh         ← POST GIFs an Cube /doUpload
│   ├── deploy.sh         ← Sync bin/cube.sh* → ~/.claude/bin/
│   ├── cycle.sh          ← Visueller Smoke-Test
│   └── clear-old.sh      ← Räumt Cube auf (Dry-run + --force)
├── assets/
│   ├── thinking.gif      ← 128×128 Source (von PixelLab)
│   ├── alert.gif         ← 128×128 Source
│   ├── idle.gif          ← 128×128 Source
│   └── 240/              ← 240×240 hochskaliert (was auf Cube läuft)
└── prompts/
    ├── 00-style-guide.md ← Maskottchen-Design + Palette
    ├── 01-thinking.md    ← Asset-Prompts für thinking-Animation
    ├── 02-alert.md
    ├── 03-idle.md
    └── 04-workflow.md    ← End-to-End Frames → GIF → Cube
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
   - Action Descriptions und Style-Anchor aus `prompts/01-thinking.md` etc. übernehmen
   - 64×64 oder 128×128 (Credits sparen)
   - Export als GIF nach `assets/<name>.gif`
2. **Resize**: `make resize` → erzeugt `assets/240/<name>.gif`
3. **Upload**: `make upload` → schickt an Cube `/image/`
4. **Test**: `make cycle` oder `bin/cube.sh img <name>.gif`

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
- `gifsicle` — für Resize 128 → 240 (`sudo apt install gifsicle`)
- `python3-pil python3-requests` — nur falls `cube-gen.py` benutzt wird (optional)
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
| Bild nur ¼ des Displays | GIF ist 128×128, `make resize` ausführen |
| Hooks feuern nicht | Neue Claude-Session starten — Hooks werden bei Session-Start gelesen |
| "Auto Switch Themes" überschreibt Hook-Bilder | http://$CUBE_IP/ → Auto-Switch deaktivieren |
| Upload-curl bricht mit "duplicate Content-Length" ab | Cube-FW-Bug, Upload klappt trotzdem — `-f` flag bei curl entfernt sich beschwert nicht |
| Cube hängt nach großer GIF | Datei <50KB, max 8 Frames |

## Quellen / Inspiration

- Community-Reverse-Engineering: [adrienbrault/geekmagic-hacs](https://github.com/adrienbrault/geekmagic-hacs)
- HA-Integration mit text/note-Endpoints: [aydarik/hass-geekmagic](https://github.com/aydarik/hass-geekmagic)
- Original-Firmware: [GeekMagicClock/smalltv-ultra](https://github.com/GeekMagicClock/smalltv-ultra)
- Pixel-GIF-Sammlung: [GeekMagicClock/gif](https://github.com/GeekMagicClock/gif)
