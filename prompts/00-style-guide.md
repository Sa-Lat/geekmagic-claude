# Claude-Cube Maskottchen — Style Guide

Geteilte visuelle Sprache für alle drei Assets (`thinking`, `alert`, `idle`).
**Erst diesen File lesen, bevor die einzelnen Asset-Prompts genutzt werden.**

## Subject

Cute round mascot named "Claude" — friendly cream-colored orb-bot with single
soft cyan eye, small antenna with orange tip on top, no mouth (expression only
through eye + body posture). Two short stubby pixel arms. Vaguely reminiscent
of a friendly AI assistant. Not creepy, not childish — calm, warm, competent.

## Style Anchor (in JEDEN Prompt einfügen)

```
16-bit pixel art, JRPG mascot sprite style, soft cream body #f4e4cf,
cyan eye #6bb6ff, warm orange accent antenna tip #d97757, deep navy
background #0d1530, 4-color limited palette per element, crisp pixels,
no anti-aliasing, no gradients, no smooth shading, 128x128 canvas
```

## Farbpalette (Hex)

| Rolle | Hex | Hinweis |
|---|---|---|
| Body cream (Haupt) | `#f4e4cf` | warm, freundlich |
| Body shadow | `#c9b89a` | nur 1px Schatten unten/rechts |
| Eye cyan | `#6bb6ff` | weich, nicht neon |
| Eye highlight | `#d1ebff` | 1-2px Glanzpunkt oben-links |
| Eye pupil dark | `#1a3a5c` | nur falls Pupille gezeichnet |
| Accent orange | `#d97757` | Antenne-Tip, Anthropic-Vibe |
| Background base | `#0d1530` | deep navy, FLÄCHIG, kein Verlauf |
| Background hint | `#1a2540` | optional 1-2px Vignette für Tiefe |

**Wichtig**: Hintergrund IMMER solid `#0d1530`, keine Sterne, kein Verlauf,
keine Textur. So komponieren die Frames sauber im Cube.

## Render-Target

- Final-Größe: **240×240** auf 1.5" IPS TFT
- Generierung bei **64×64 oder 128×128** in Pixel-KI
- Hochskalieren via **nearest-neighbor** (kein Bilinear/Lanczos!) auf 240×240
- Lesbarkeit aus 50cm Entfernung — Hauptmotiv min. 40% der Fläche

## Anti-Aliasing

`anti-aliasing OFF` in jeden Prompt eintragen. Falls KI trotzdem AA macht:
- ImageMagick Nachbearbeitung: `convert in.png -posterize 8 -filter point -resize 240x240 out.png`
- Oder Quantize: `convert in.png -colors 16 -dither None out.png`

## Konsistenz zwischen Frames

- **Gleicher Seed** über alle Frames einer Animation
- **Gleicher Style-Anchor-Text** wortgleich
- Nur **kleinster nötiger Delta** pro Frame (Augenlid, Arm-Pose, Partikel)
- Bei Multi-Tool-Workflow: Style-Anchor strikt einhalten, sonst Style-Drift
