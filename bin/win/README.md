# cube-overlay-win (Windows-natives Overlay)

Windows-native Varianten des Overlays. Ersetzen `bin/cube-overlay.py` für
Windows-Hosts — kein WSLg-Compositor, kein Focus-Steal, kein
localhost-Forward-Konflikt mit Docker.

Zwei Implementierungen koexistieren:

| Datei | Stack | Look | Wahl |
|---|---|---|---|
| `cube-overlay-win.pyw` | CPython + Tk + Pillow | Kompaktes klassisches Dashboard | Default, minimale Deps |
| `cube-overlay-win-html.pyw` | CPython 3.13 + pywebview/WebView2 | Mochi Classic (Quicksand, Glow-Dots, Sonar-Ripple, abgerundete Card, dynamische Höhe) | Für moderneren Look |

Beide teilen sich `%APPDATA%\cube\overlay.env` + `overlay-layouts.json`
(gleiche Keys, gleiche Anchor-Logik), WSL-IP-Resolution, Skin-Routing.
Konfigurationsänderungen aus einer Variante werden von der anderen beim
nächsten Start gelesen.

## Architektur

```
WSL: mock-cube.py (bind 0.0.0.0:8080) ← cube.sh ← Claude-Code-Hooks
                            │
                            │  http://<wsl-ip>:8080/dashboard.json
                            │  http://<wsl-ip>:8080/current.gif
                            ▼
Windows: pythonw.exe bin/win/cube-overlay-win.pyw
```

Die WSL-IP wird beim Start via `wsl.exe hostname -I` aufgelöst und bei
Connection-Drift (≥3 fehlgeschlagene Polls) neu ermittelt.

## Setup

### 1. Python auf Windows

Für die **Tk-Variante** (`cube-overlay-win.pyw`):
```powershell
py --version          # ≥ 3.11
py -m pip install --user Pillow
```

Für die **HTML-Variante** (`cube-overlay-win-html.pyw`):
```powershell
py -3.13 --version    # genau 3.13 (pythonnet hat noch keine 3.14-Wheels)
py -3.13 -m pip install --user pywebview
```

Wenn `py` fehlt: Python von [python.org](https://www.python.org/downloads/) oder
aus dem Microsoft Store installieren. Tkinter ist im CPython-Windows-Bundle
enthalten. WebView2-Runtime ist auf aktuellen Windows-11-Builds vorinstalliert
(sonst Edge-Update / Edge-WebView2-Standalone-Installer).

### 2. mock-cube auf 0.0.0.0 binden (WSL-Seite)

Damit der Windows-Host die WSL-IP erreichen kann, muss mock-cube nicht nur
auf `127.0.0.1` lauschen:

```bash
echo 'CUBE_MOCK_HOST=0.0.0.0' >> ~/.config/cube/config
systemctl --user restart mock-cube.service
ss -tlnp | grep 8080      # prüfen: bindet auf 0.0.0.0:8080
```

### 3. Connectivity-Check (Windows-Seite)

```powershell
wsl.exe hostname -I                       # liefert WSL-IP, z.B. 172.27.241.123
curl http://172.27.241.123:8080/dashboard.json
```

JSON-Antwort = bereit.

### 4. Start

Tk-Variante:
```powershell
py "\\wsl$\Ubuntu\home\<user>\projects\cube\bin\win\cube-overlay-win.pyw"
```

HTML-Variante:
```powershell
py -3.13 "\\wsl$\Ubuntu\home\<user>\projects\cube\bin\win\cube-overlay-win-html.pyw"
```

Oder Datei in einen Windows-Pfad kopieren und per Doppelklick starten
(`.pyw` läuft mit `pythonw.exe`, ohne Konsole).

### 5. Autostart (optional)

Per Startup-Folder-Shortcut: `Win+R` → `shell:startup` öffnet
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`. Repo-Datei dort hin
kopieren (oder via Symlink/Verknüpfung):

- Tk-Variante: `bin/win/cube-overlay-win.cmd`
- HTML-Variante: `bin/win/cube-overlay-win-html.cmd` (oder `.ps1`)

HTML-Wrapper pinnt Python auf `-3.13` via `CUBE_OVERLAY_PY` (überschreibbar
falls neuere pythonnet-Wheels vorhanden), nutzt `CUBE_OVERLAY_UNC_HTML` als
UNC-Override (analog zu `CUBE_OVERLAY_UNC` für Tk).

Inhalt der `cube-overlay-win.cmd`:

```cmd
@echo off
wsl.exe --exec true >nul 2>&1
for /f "delims=" %%P in ('py -c "import sys,os; print(os.path.join(os.path.dirname(sys.executable),'pythonw.exe'))"') do set PYW=%%P
if "%CUBE_OVERLAY_UNC%"=="" set CUBE_OVERLAY_UNC=\\wsl.localhost\Ubuntu\home\%USERNAME%\projects\cube\bin\win\cube-overlay-win.pyw
start "" "%PYW%" "%CUBE_OVERLAY_UNC%"
```

- `wsl --exec true` bootet die Distro falls noch nicht hochgekommen — UNC-Zugriff
  auf `\\wsl.localhost\` braucht eine laufende WSL.
- `for /f` löst `pythonw.exe` dynamisch via py-Launcher auf — überlebt Python
  Minor-Upgrades, funktioniert mit Store / python.org / Python Install Manager.
- `pythonw.exe` (statt `py`) direkt: py-Launcher ist Console-Subsystem und
  **bleibt am pythonw-Child hängen** bis dieses exit — Konsolen-Fenster blieben
  während der gesamten Overlay-Laufzeit offen (unsichtbar in Taskleiste).
  `pythonw.exe` ist GUI-Subsystem, hat keine Konsole, `start ""` detached
  sauber.
- `%USERNAME%` für UNC: matched Windows-User auf Linux-User. Wenn die User
  abweichen, `CUBE_OVERLAY_UNC` als System-Env-Var auf den vollen UNC-Pfad
  setzen (`Erweiterte Systemeinstellungen` → `Umgebungsvariablen`).

**PowerShell-Variante** (`cube-overlay.ps1`, falls `.cmd` nicht gewollt):

```powershell
wsl.exe --exec true *> $null
Start-Process py -ArgumentList '\\wsl.localhost\Ubuntu\home\<user>\projects\cube\bin\win\cube-overlay-win.pyw'
```

`*> $null` = PowerShell-Äquivalent zu `>nul 2>&1` (alle Streams verwerfen).
`.ps1` im Startup-Folder braucht u.U. `ExecutionPolicy`-Anpassung; Verknüpfung
auf `powershell.exe -ExecutionPolicy Bypass -File <pfad>.ps1` umgeht das.

Voraussetzung: `mock-cube.service` muss nach Login automatisch hochkommen:

```bash
systemctl --user enable mock-cube.service
```

Sonst feuert das Overlay ein paar fehlgeschlagene Polls (Re-Resolve nach 3
Misses), konvergiert aber sobald mock-cube bereit ist.

Robuster mit Auto-Restart-on-Crash: stattdessen Task Scheduler mit Trigger
`AtLogOn` und `-RestartCount 3 -RestartInterval 1m` (siehe
`New-ScheduledTask` in PowerShell). Trigger `AtLogOn` ist wichtig, weil WSL
erst nach User-Login startfähig ist.

## Konfiguration

Per-Maschine-Settings unter `%APPDATA%\cube\`:

- `overlay.env` — `KEY=VALUE`-Format. Recognized:
  - `CUBE_OVERLAY_THEME` (`dark` / `light`)
  - `CUBE_OVERLAY_WIDTH` (140 / 180 / 240)
  - `CUBE_OVERLAY_SIZE` (GIF-Kantenlänge, 0 = auto)
  - `CUBE_OVERLAY_MAX_BLOCKS` (default 5)
  - `CUBE_OVERLAY_POSITION_LOCKED` (1 / 0)
  - `CUBE_OVERLAY_PORT` (default 8080)
  - `CUBE_OVERLAY_MOCK` (volle URL, überschreibt WSL-IP-Auto-Detection)
- `overlay-layouts.json` — per-Monitor-Setup-Anker, geschrieben durch
  Drag-End + Reset-Menüpunkt.

## CLI-Flags

```
--mock URL          komplette URL überschreiben (statt wsl.exe-Detect)
--port N            mock-cube-Port auf WSL (default 8080)
--width N           Fensterbreite (140/180/240)
--size N            GIF-Kantenlänge (0 = auto-fit)
--max-blocks N      Session-Blocks-Cap (default 5)
--decorated         Fensterrahmen anzeigen (Debug; default: frameless)
```

## Bedienung

- **Linksklick + Drag** verschiebt das Overlay (nur wenn Position-Lock aus).
- **Rechtsklick** öffnet das Menü: Theme / Position / Size / Hide / Quit.
- **Escape** beendet das Overlay.

## Funktionsumfang

- **Theme / Position / Size** — lokal mutable via Rechtsklick-Menü, gespeichert
  in `%APPDATA%\cube\overlay.env` und `overlay-layouts.json`.
- **Skin** — Wechsel via Menü routet HTTP `GET /set?skin=NAME` an mock-cube;
  mock-cube proxyt zu `cube.sh skin NAME` + `cube.sh redisplay` in WSL.
  `~/.claude/.cube-skin` bleibt Source of Truth, beide Overlays (Windows +
  WSLg) flippen über ihre poll-loops synchron.

### HTML-Variante: Designnotes

- **Mochi Classic** Look — Port von `dir-mochi.jsx` nach Plain-CSS, Quicksand
  via Google Fonts, abgerundete Card mit Inset-Shadow, Glow-Dots mit
  Sonar-Ripple-Animation auf Live-States (`permission`/`error`/`compact`/
  `alert`/`thinking`).
- **Native Win32 Popup-Menü** (`TrackPopupMenu`) statt DOM-Context-Menu —
  Submenüs würden bei 180-240 px Card-Breite vom WebView2-Frame geclippt.
- **Dynamische Höhe** — JS `ResizeObserver` meldet `.wrap`-Höhe an Python,
  Window resized live mit fixiertem bottom-right-Anchor (Card "wächst nach
  oben"). Keine Black-Space mehr unter Content.
- **Drag** ist JS-gesteuert; Python liest jeweils `GetCursorPos` (Physical-
  Pixel) statt sich auf WebView2 `screenX/Y` (Logical-Pixel) zu verlassen —
  korrekt unter Per-Monitor-DPI.
- **Palette-Tokens** pro `skin × theme` als `:root[data-skin=...][data-theme=...]`-
  Selektoren in `overlay.css`. JS swappt beide Attribute auf `<html>` für
  saubere Cascade-Re-Resolution.
- **Opaque Window** (kein `transparent=True`) — EdgeChromium Layered-Window-
  Compositing bricht das Painting auf den meisten pywebview-Builds (DWM zeigt
  Content im Taskbar-Preview, eigentliches Fenster bleibt unsichtbar). Body-BG
  matcht Card-Farbe → rechteckige Fensterkanten verschmelzen mit der Card.
- **Inline-HTML** — CSS/JS werden beim Start in `index.html` injected und
  `html=...` an `webview.create_window` übergeben. WebView2 kann `file://`
  von UNC-Paths (`\\wsl.localhost\...`) nicht laden, pywebviews transienter
  HTTP-Server hingegen serviert inlined HTML problemlos.
- **HWND-Discovery** — `window.native.Handle.ToInt64()` zuerst; bei Failure
  (pywebviews `__repr__` rekursiert über `AccessibilityObject` und sprengt den
  Stack) Fallback auf `EnumWindows` mit PID-Filter.
- **Preview im Browser** — `bin/win/html/index.html` direkt im Browser öffnen
  zeigt `SAMPLE_DATA`; `?theme=dark&skin=orb`-Query erlaubt Palette-Variation
  ohne pywebview.

## Troubleshooting

**Overlay startet, zeigt aber nichts / kein GIF**: 
WSL-IP-Routing prüfen. `curl http://<wsl-ip>:8080/dashboard.json` von der
Windows-Seite muss JSON liefern. Falls nicht: `CUBE_MOCK_HOST=0.0.0.0`
gesetzt? mock-cube restart erfolgt?

**`wsl.exe hostname -I` liefert nichts**:  
WSL-Distro nicht gestartet. `wsl` einmal von Windows aufrufen, dann erneut.

**IP-Drift nach `wsl --shutdown`**:  
Erwartet (NAT-Mode). Overlay re-detected nach 3 verfehlten Polls automatisch.
Permanent-Stable über Mirrored Networking (`.wslconfig` →
`networkingMode=mirrored`, Win11 22H2+) — globale Änderung, gut überlegen.

**Blurry GIF bei >100% Display-Scaling**:  
Sollte nicht passieren — `SetProcessDpiAwareness(2)` läuft beim Start. Falls
doch: Tk-Version prüfen (`python -c "import tkinter; print(tkinter.TkVersion)"`),
8.6+ erforderlich.

**`where pythonw.exe` liefert nichts**:  
Bei Store-/py-Launcher-Install ist `pythonw.exe` häufig nicht im System-PATH.
`where py` testen — der py-Launcher ist zuverlässig drin und löst `.pyw`
selbst auf `pythonw.exe` auf. `.cmd` auf `start "" py ...` statt
`start "" pythonw.exe ...` umstellen.

**`py` selbst fehlt**:  
Python für Windows nachinstallieren — `winget install Python.Python.3.12` oder
python.org-Installer mit **Add Python to PATH** + **py launcher** aktiviert.
Danach neue PowerShell-Session öffnen (PATH wird beim Start gelesen).

**HTML-Variante: `ModuleNotFoundError: pythonnet`**:  
`py -3.13 -m pip install --user pywebview` läuft nicht durch oder pinnt eine
ältere pywebview-Version. Frische Installation: `py -3.13 -m pip install --user --upgrade pywebview pythonnet`.
Python ≠ 3.13? `CUBE_OVERLAY_PY` in der `.cmd` auf die richtige Version setzen
oder direkt `py -X.Y` testen.

**HTML-Variante: Window kommt nicht hoch, kein Fehler sichtbar**:  
`%TEMP%\cube-overlay-win-html.log` lesen — stderr wird dorthin geleitet,
inkl. `sys.excepthook`-Traceback bei Crashes. Häufige Ursachen: WebView2-Runtime
fehlt (Edge installieren), pywebview-Version inkompatibel (`pip install --upgrade pywebview`),
WSL nicht hochgefahren (`wsl.exe --exec true` läuft die `.cmd` schon vorher).

**HTML-Variante: GIF wird nicht geladen, Cards sichtbar**:  
mock-cube auf `0.0.0.0` gebunden? `/current.gif` antwortet
(`curl http://<wsl-ip>:8080/current.gif -o /dev/null`)? Bei
Connection-Drift nach `wsl --shutdown` re-detected der Bridge die IP nach 3
verfehlten Polls automatisch (siehe Log).
