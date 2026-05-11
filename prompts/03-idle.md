# Asset: `idle.gif` — gelangweilter Claude

Trigger: `Stop`-Hook. Claude hat fertig geantwortet → Cube zeigt entspanntes
Idle-Maskottchen bis nächster Prompt.

## Konzept

Maskottchen sleepy/bored, Auge halb-geschlossen, kleines weißes "z"
Partikel steigt von Antenne auf und verblasst. **6 Frames, 250ms each**,
Loop 1.5s. Beruhigend, nicht ablenkend.

## Style-Anchor

Aus `00-style-guide.md` + Sleep-Erweiterung:
```
Plus: half-closed sleepy eye (pixel eyelid covering upper half of cyan eye),
slight slouch posture, small white pixel 'z' particle floating upward and
fading, lazy bored mood
```

## PixelLab.ai

**Base-Sprite:**
```
Round cream orb-bot mascot with half-closed bored cyan eye (pixel eyelid
sprite covering top half), slight slouch posture, single small white pixel
letter 'z' floating upward from antenna, lazy bored sleepy expression,
16-bit pixel art JRPG style, deep navy background, 64x64, no anti-aliasing
```

**Animation-Frames (6):**
- **F1**: eye half-lidded, body slight slouch, no `z` particle
- **F2**: eye half-lidded, no `z`
- **F3**: eye **fully closed** (1-frame blink/yawn), tiny `z` at antenna level
- **F4**: eye half-lidded, `z` mid-air above head
- **F5**: eye half-lidded, `z` higher and faded (semi-transparent pixel)
- **F6**: eye half-lidded, no `z`, slight body slump (=Frame 1 for loop)

## Retro Diffusion / Pixel Art XL

6 Frames, gleicher Seed, sanfte Variation:

**Frame 1:**
```
{{STYLE_ANCHOR}}, cream orb-bot mascot, half-closed sleepy cyan eye with
pixel eyelid on upper half, slight slouch, no particles, neutral lazy pose
```

**Frame 2:**
```
{{STYLE_ANCHOR}}, same orb-bot, half-closed eye, slight slouch, no particles
(near-identical to frame 1)
```

**Frame 3:**
```
{{STYLE_ANCHOR}}, same orb-bot, eye FULLY closed (single horizontal pixel
line for closed eye, yawn moment), tiny white pixel letter 'z' above
antenna at low position
```

**Frame 4:**
```
{{STYLE_ANCHOR}}, half-closed eye returns, small white pixel 'z' mid-air
above head, drifting up
```

**Frame 5:**
```
{{STYLE_ANCHOR}}, half-closed eye, white pixel 'z' high above head, slightly
faded (lighter shade, semi-transparent effect)
```

**Frame 6:**
```
{{STYLE_ANCHOR}}, half-closed eye, no 'z' particle, slight body slump,
neutral lazy pose (loops back to frame 1)
```

**Negative prompt:**
```
alarmed, alert, exclamation mark, bright red, active pose, waving arms,
multiple characters, anti-aliasing, smooth gradient, photorealistic, mouth,
3d render
```

## Midjourney

```
bored sleepy cute cream pixel-art orb-bot mascot, half-lidded cyan eye,
small white 'z' particle drifting up from antenna, lazy slouch, deep navy
background, 16-bit JRPG idle animation sprite --style raw --ar 1:1 --stylize 80
```

Variationen für 6 Frames mit `--vary subtle` und Pose-Hints: "eye fully
closed yawn", "z particle low", "z particle high faded", "no particle".

## DALL-E 3 / GPT Image

**Frame 1/2/6 (Idle ohne Partikel):**
```
Pixel art 16-bit retro game sprite: small round cream-colored robot orb
character looking bored and sleepy. Its single large cyan eye is HALF-CLOSED
with a small pixel eyelid drawn over the upper half. Slightly slouched lazy
posture. No particles. Deep navy blue solid background hex #0d1530. No
anti-aliasing, crisp blocky pixels, 4 colors per region. Square 1:1.
```

**Frame 3 (Yawn):**
```
Same pixel art mascot but with eye FULLY CLOSED (single horizontal dark
pixel line representing closed eye). Tiny white pixel letter 'z' floats
just above the small orange antenna. Lazy slouched posture. Deep navy
background. Crisp pixels.
```

**Frame 4 (Z mid):**
```
Same pixel art mascot, eye half-closed sleepy. A small white pixel letter
'z' floats in the middle area above its head, drifting upward. Lazy pose.
Deep navy background. Crisp pixels.
```

**Frame 5 (Z high faded):**
```
Same pixel art mascot, eye half-closed. A small white pixel letter 'z'
floats HIGH above its head, slightly faded (pale white, semi-transparent
appearance). Lazy pose. Deep navy. Crisp pixels.
```

## Lokales SD + PixelArtRedmond

```
<lora:PixelArtRedmond:1> Pixel Art, {{STYLE_ANCHOR}}, sleepy bored cream
orb-bot mascot, half-lidded cyan eye, small z particle above antenna,
slouch pose, JRPG idle animation sprite
```

## Assembly

```bash
# 6 Frames @ 250ms = 1.5s gentle loop
convert frame1.png frame2.png frame3.png frame4.png frame5.png frame6.png \
  -filter point -resize 240x240 -delay 25 -loop 0 -dispose Background idle.gif

# Aggressiv optimieren — Idle ist ruhig, 8-16 Farben reichen
gifsicle -O3 --colors 12 idle.gif -o idle-final.gif
ls -la idle-final.gif  # Ziel <30KB
```

## Ziel-Specs

| Param | Wert |
|---|---|
| Auflösung | 240×240 |
| Frames | 6 |
| Frame-Delay | 250 ms |
| Loop | infinite |
| Dateigröße | **≤ 30 KB** |
| Palette | 8–16 Farben |

## Bonus: Day-Cycle (optional)

Sehr ruhige Variante als `idle-night.gif`: Hintergrund noch dunkler
(`#050a18`), Auge geschlossen permanent (echtes Schlafen), kein `z`.
Hook könnte je nach Uhrzeit eine andere Idle-GIF zeigen.
