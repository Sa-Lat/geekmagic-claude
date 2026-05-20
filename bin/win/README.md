# cube-overlay-win (Windows-natives Overlay, POC)

Windows-native Variante des Tk-Overlays. Ersetzt `bin/cube-overlay.py` für
Windows-Hosts — kein WSLg-Compositor, kein Focus-Steal, kein
localhost-Forward-Konflikt mit Docker.

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

```powershell
py --version          # ≥ 3.11
py -m pip install --user Pillow
```

Wenn `py` fehlt: Python von [python.org](https://www.python.org/downloads/) oder
aus dem Microsoft Store installieren. Tkinter ist im CPython-Windows-Bundle
enthalten.

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

```powershell
py "\\wsl$\Ubuntu\home\<user>\projects\cube\bin\win\cube-overlay-win.pyw"
```

Oder Datei in einen Windows-Pfad kopieren und per Doppelklick starten
(`.pyw` läuft mit `pythonw.exe`, ohne Konsole).

### 5. Autostart (optional)

Per Startup-Folder-Shortcut: `Win+R` → `shell:startup` öffnet
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\`. Repo-Datei
`bin/win/cube-overlay-win.cmd` dort hin kopieren (oder via Symlink/Verknüpfung).

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
