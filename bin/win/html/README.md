# cube-overlay HTML render layer

CSS/HTML/JS-Implementierung des Mochi-Classic-Designs. Wird vom Python-Wrapper
`bin/win/cube-overlay-win-html.pyw` über pywebview/WebView2 geladen.

## Dateien

- `index.html` — Markup-Gerüst + Font-Preload (Quicksand)
- `overlay.css` — Mochi-Classic-Palette (waifu/orb × light/dark), Dot-Pulse-Keyframes
- `overlay.js` — Poll-Loop, DOM-Patching, Bridge-Aufrufe

## Standalone-Preview (ohne pywebview)

```bash
# Linux/WSLg
xdg-open bin/win/html/index.html

# Windows
start bin\win\html\index.html
```

Wenn `window.pywebview` fehlt, fällt `overlay.js` auf `SAMPLE_DATA` zurück und
zeigt eine statische Mock-Card. Theme/Skin via Query-Parameter:

```
file:///.../index.html?theme=dark&skin=orb
```

Live-GIF wird im Standalone-Mode unterdrückt (keine Bridge → kein
`api.gif()`-Call).

## Bridge-API (Python ↔ JS)

JS ruft synchron Methoden auf `window.pywebview.api`:

| Method            | Returns                                        |
|-------------------|------------------------------------------------|
| `dashboard()`     | mock-cube `/dashboard.json` parsed, plus `theme` |
| `gif()`           | base64-encoded GIF bytes (pywebview cannot pass raw bytes through the bridge) |

Aufruf-Beispiel:

```js
const data = await window.pywebview.api.dashboard();
const b64 = await window.pywebview.api.gif();
```

## Palette ändern

`overlay.css` Top: `#root[data-skin=X][data-theme=Y]` Blöcke. CSS-Variablen
`--card`, `--text`, `--brand`, `--bar-fill`, `--acc-<state>` etc. Designer-
Quelle: `/mnt/c/Users/latzkowski/Downloads/cube/dir-mochi.jsx`.

## Pulse-Animation

`.dot[data-live="true"]` triggert `@keyframes dot-pulse` (1.4 s ease-in-out
infinite). Ring expandiert 2 → 5 px, Halo-Alpha pulsiert mit. Dark mode addiert
ein outer `box-shadow` über `--dot-glow`.

## Feature parity mit Tk

Phase-2 ist durch. HTML-Variante hat:

- Drag-to-move (linker Mouse-Button auf Karte, nur wenn Position nicht locked).
  Drag-end speichert anchor per `save_anchor` in `overlay-layouts.json` (gleicher
  Pfad/Format wie Tk).
- Rechtsklick-Menü: Theme / Skin / Position (Locked + Reset) / Size (140/180/240) /
  Window (Always on Top + Lift on Activity + Bring to Front) / Hide / Quit.
- Skin-Wechsel routet über mock-cube `/set?skin=NAME` → `cube.sh skin` + `redisplay`
  in WSL. `~/.claude/.cube-skin` bleibt Source of Truth.
- Hide → window.hide(); auto-unhide beim nächsten state-Wechsel (gleich Tk).
- Lift on Activity: wenn winner state idle/done/start → pulse-state wechselt, ruft
  `bring_to_front`.

## Tk-Variante als Fallback

`bin/win/cube-overlay-win.pyw` (Tk-Variante) bleibt zunächst neben der HTML-Variante.
Beide teilen `%APPDATA%\cube\overlay.env` und `overlay-layouts.json`. Crash-Logs
laufen in separate Dateien (`cube-overlay-win.log` vs `cube-overlay-win-html.log`).
