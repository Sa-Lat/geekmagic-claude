# cube-overlay (Windows WebView2 overlay)

Frameless always-on-top overlay window on the Windows host. Renders the
voxel cube-entity canvas plus the active Claude-Code session list driven by
mock-cube's `/dashboard.json` running inside WSL.

The window machinery (drag, native menu, anchor persistence, poll loop, base
HTML/CSS/JS) lives in the reusable **`webview-overlay`** pip package.
`cube-overlay.pyw` is a thin launcher: it supplies cube's identity, palette
(`html/cube-theme.css`) and the voxel renderer (`html/cube-entity.js`) via
`OverlayConfig`, then calls `webview_overlay.run()`.

## Architektur

```
WSL: mock-cube.py (bind 0.0.0.0:8765) ← cube.sh ← Claude-Code-Hooks
                            │
                            │  http://<wsl-ip>:8765/dashboard.json
                            ▼
Windows: pythonw.exe bin/win/cube-overlay.pyw  (pywebview + WebView2)
```

WSL-IP wird beim Start via `wsl.exe hostname -I` aufgelöst und bei
Connection-Drift (≥3 verfehlte Polls) neu ermittelt.

## Setup

### 1. Python auf Windows

```powershell
py -3.13 --version    # genau 3.13 (pythonnet hat noch keine 3.14-Wheels)
py -3.13 -m pip install --user pywebview
py -3.13 -m pip install --user "webview-overlay @ git+https://github.com/Sa-Lat/webview-overlay.git"
```

`webview-overlay` ist das ausgelagerte, wiederverwendbare Overlay-Package
(eigenes Repo). Es bringt pywebview als Dependency mit; die obige
Pinned-Python-Anweisung sicherstellt, dass beide im selben `py -3.13`
landen, den der `.cmd`-Wrapper auflöst.

Falls `py` fehlt: Python von [python.org](https://www.python.org/downloads/)
oder Microsoft Store installieren. WebView2-Runtime ist auf aktuellen
Windows-11-Builds vorinstalliert (sonst Edge-Update bzw.
Edge-WebView2-Standalone-Installer).

### 2. mock-cube auf 0.0.0.0 binden (WSL-Seite)

Damit der Windows-Host die WSL-IP erreichen kann:

```bash
echo 'CUBE_MOCK_HOST=0.0.0.0' >> ~/.config/cube/config
systemctl --user restart mock-cube.service
ss -tlnp | grep 8765      # prüfen: bindet auf 0.0.0.0:8765
```

### 3. Connectivity-Check (Windows-Seite)

```powershell
wsl.exe hostname -I                       # liefert WSL-IP, z.B. 172.27.241.123
curl http://172.27.241.123:8765/dashboard.json
```

JSON-Antwort = bereit.

### 4. Start

```powershell
py -3.13 "\\wsl$\Ubuntu\home\<user>\projects\cube\bin\win\cube-overlay.pyw"
```

Oder Datei in einen Windows-Pfad kopieren und per Doppelklick starten
(`.pyw` läuft mit `pythonw.exe`, ohne Konsole).

### 5. Autostart (optional)

`Win+R` → `shell:startup` öffnet
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`. Die
`cube-overlay-win-html.cmd` dort **direkt hinkopieren** (nicht als
`.lnk`-Verknüpfung anlegen):

> ⚠️ **Keine Verknüpfung verwenden.** Eine `.lnk`, die auf eine `.cmd` unter
> `\\wsl.localhost\…` zeigt, markiert Windows via Mark-of-the-Web als "aus
> unbekannter Quelle" und zeigt bei jedem Login eine SmartScreen-Warnung.
> Die `.cmd` **als physische Datei** in den Startup-Folder kopieren — dort
> liegender Pfad gilt als lokal und löst keine Warnung aus.

Wrapper pinnt Python auf `-3.13` via `CUBE_OVERLAY_PY`, nutzt
`CUBE_OVERLAY_UNC_HTML` als UNC-Override (falls Windows-User ≠ Linux-User).

Inhalt der `cube-overlay-win-html.cmd`:

```cmd
@echo off
wsl.exe --exec true >nul 2>&1
for /f "delims=" %%P in ('py -3.13 -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%P
if "%CUBE_OVERLAY_UNC_HTML%"=="" set CUBE_OVERLAY_UNC_HTML=\\wsl.localhost\Ubuntu\home\%USERNAME%\projects\cube\bin\win\cube-overlay.pyw
start "" "%PYW%" "%CUBE_OVERLAY_UNC_HTML%"
```

- `wsl --exec true` bootet die Distro falls noch nicht hochgekommen —
  UNC-Zugriff auf `\\wsl.localhost\` braucht eine laufende WSL.
- `for /f` löst `pythonw.exe` dynamisch via py-Launcher auf — überlebt
  Minor-Upgrades, funktioniert mit Store / python.org / Python Install
  Manager.
- `pythonw.exe` (statt `py`) direkt: py-Launcher ist Console-Subsystem und
  bleibt am pythonw-Child hängen bis dieses exitet — Konsolen-Fenster blieben
  während Overlay-Laufzeit offen (unsichtbar in Taskleiste).
- `%USERNAME%` für UNC: matched Windows-User auf Linux-User. Wenn die User
  abweichen, `CUBE_OVERLAY_UNC_HTML` als System-Env-Var auf den vollen
  UNC-Pfad setzen.

`cube-overlay-win-html.ps1` ist die PowerShell-Variante des Wrappers für
User, die `.ps1` bevorzugen (ExecutionPolicy-Bypass via Verknüpfung mit
`powershell.exe -ExecutionPolicy Bypass -File <pfad>.ps1`).

Voraussetzung: `mock-cube.service` muss nach Login automatisch hochkommen:

```bash
systemctl --user enable mock-cube.service
```

Sonst feuert das Overlay ein paar fehlgeschlagene Polls (Re-Resolve nach 3
Misses), konvergiert aber sobald mock-cube bereit ist.

## Konfiguration

Per-Maschine-Settings unter `%APPDATA%\cube\`:

- `overlay.env` — `KEY=VALUE`-Format. Recognized:
  - `CUBE_OVERLAY_THEME` (`dark` / `light`)
  - `CUBE_OVERLAY_WIDTH` (140 / 180 / 240)
  - `CUBE_OVERLAY_POSITION_LOCKED` (1 / 0)
  - `CUBE_OVERLAY_HIDE_ENTITY` (1 / 0)
- `overlay-layouts.json` — per-Monitor-Setup-Anker, geschrieben durch
  Drag-End + Reset-Menüpunkt.

## Bedienung

- **Linksklick + Drag** verschiebt das Overlay (nur wenn Position-Lock aus).
- **Rechtsklick** öffnet das Menü: Theme / Position / Size / Window / Hide / Quit.
- **Show Animation** im Window-Submenü blendet das Canvas aus (Card bleibt
  sichtbar mit Rows + Usage-Bar).

## Designnotes

- **Mochi Classic** Look — abgerundete Card mit Inset-Shadow, Quicksand,
  Glow-Dots mit Sonar-Ripple-Animation auf Live-States (`permission`/`error`/
  `compact`/`alert`/`thinking`).
- **Voxel Cube-Entity** — `cube-entity.js` rendert 33 Cubes in 3 konzentrischen
  Ringen plus cyan-Core mit Painter's-Algorithm + Back-Face-Culling. 8
  Emotionen bilden auf die Dashboard-States ab; setEmotion swappt Cube-Hue +
  Motion-Language mit Sub-Second-Tween.
- **Native Win32 Popup-Menü** (`TrackPopupMenu`) statt DOM-Context-Menu —
  Submenüs würden sonst bei 180-240 px Card-Breite vom WebView2-Frame
  geclippt.
- **Dynamische Höhe** — JS `ResizeObserver` meldet `.wrap`-Höhe an Python,
  Window resized live mit fixiertem bottom-right-Anchor (Card "wächst nach
  oben"). Keine Black-Space unter Content.
- **Drag** ist JS-gesteuert; Python liest jeweils `GetCursorPos`
  (Physical-Pixel) statt sich auf WebView2 `screenX/Y` (Logical-Pixel) zu
  verlassen — korrekt unter Per-Monitor-DPI.
- **Opaque Window** (kein `transparent=True`) — EdgeChromium-Layered-Window-
  Compositing bricht Painting auf den meisten pywebview-Builds (DWM zeigt
  Content im Taskbar-Preview, eigentliches Fenster bleibt unsichtbar). Body-BG
  matcht Card-Farbe → rechteckige Fensterkanten verschmelzen mit der Card.
- **Inline-Asset-Bundle** — das `webview-overlay`-Package injectet seine
  Base-Assets (`base.css` + `overlay-base.js`) plus cubes Plugin-Assets
  (`cube-entity.js` + `cube-theme.css`) beim Start in `index.html` und übergibt
  `html=...` an `webview.create_window`. WebView2 kann `file://` von UNC-Paths
  (`\\wsl.localhost\...`) nicht laden, pywebviews transienter HTTP-Server
  serviert inlined HTML problemlos. (Package-Option `use_http_server=True`
  schaltet alternativ auf pywebviews HTTP-Server um.)
- **Cube als Plugin** — `cube-entity.js` exportiert `window.CubeEntity` +
  `window.CUBE_STATE_TO_EMOTION`; `overlay-base.js` entdeckt den Renderer über
  `OVERLAY_CONFIG.entityGlobal`. `cube-theme.css` definiert die Palette-Tokens,
  die `base.css` per `var(--token, fallback)` referenziert.
- **HWND-Discovery** — `window.native.Handle.ToInt64()` zuerst; bei Failure
  Fallback auf `EnumWindows` mit PID-Filter (Titel pro Instanz eindeutig).
- **Preview im Browser** — im `webview-overlay`-Repo:
  `tests/preview/preview.html` direkt im Browser öffnen zeigt die Base-Shell
  mit `OVERLAY_CONFIG.sampleData`; `?theme=dark` variiert das Theme ohne
  pywebview.

## Troubleshooting

**Overlay startet, zeigt aber nichts**:
WSL-IP-Routing prüfen. `curl http://<wsl-ip>:8765/dashboard.json` von der
Windows-Seite muss JSON liefern. Falls nicht: `CUBE_MOCK_HOST=0.0.0.0`
gesetzt? mock-cube restart erfolgt?

**`wsl.exe hostname -I` liefert nichts**:
WSL-Distro nicht gestartet. `wsl` einmal von Windows aufrufen, dann erneut.

**IP-Drift nach `wsl --shutdown`**:
Erwartet (NAT-Mode). Overlay re-detected nach 3 verfehlten Polls automatisch.
Permanent-stable über Mirrored Networking (`.wslconfig` →
`networkingMode=mirrored`, Win11 22H2+) — globale Änderung, gut überlegen.

**`ModuleNotFoundError: pythonnet`**:
`py -3.13 -m pip install --user --upgrade pywebview pythonnet`.
Python ≠ 3.13? `CUBE_OVERLAY_PY` in der `.cmd` auf die richtige Version
setzen oder direkt `py -X.Y` testen.

**Window kommt nicht hoch, kein Fehler sichtbar**:
`%TEMP%\cube-overlay.log` lesen — stderr wird dorthin geleitet,
inkl. `sys.excepthook`-Traceback bei Crashes. Häufige Ursachen:
WebView2-Runtime fehlt (Edge installieren), pywebview-Version inkompatibel
(`pip install --upgrade pywebview`), WSL nicht hochgefahren
(`wsl.exe --exec true` läuft die `.cmd` schon vorher).
