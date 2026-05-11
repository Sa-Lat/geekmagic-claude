# Asset: `thinking.gif` — Claude denkt

Trigger: `UserPromptSubmit`-Hook. User schickt Prompt ab → Cube zeigt diese Animation.

## Konzept

Maskottchen tilted Kopf, kleine Thought-Bubble mit drei pulsierenden Punkten
darüber. Mood: fokussiert, aufmerksam, "Ohren-perked". **4 Frames cycling,
150ms each.** Insgesamt 600ms Loop.

## Style-Anchor

Aus `00-style-guide.md` übernehmen (Body cream, cyan eye, orange antenna, navy bg).

## PixelLab.ai (empfohlen für Animation)

**Base-Sprite-Prompt:**
```
Round cream orb-bot mascot, single large cyan eye centered, small antenna
with orange tip, head tilted slightly right, three small white thought-dot
pixels above head, 16-bit pixel art JRPG sprite style, solid deep navy
background #0d1530, 64x64 sprite, 4-color limited palette body, no
anti-aliasing, crisp pixels
```

**Animation-Setup:**
- PixelLab "Skeleton + Idle Animation" aktivieren
- Head-Tilt: left → center → right → center (4 keyframes)
- Zweite Ebene: 3 weiße Punkte über Antenne, animate "fade-in cascade" 0→1→2→3 Punkte über 4 Frames

## Retro Diffusion / Pixel Art XL (Replicate)

4 separate Prompts, **gleicher Seed**, variiere nur Punktanzahl + Tilt:

**Frame 1:**
```
{{STYLE_ANCHOR}}, head tilted slightly left, one small white thinking dot
above antenna, calm focused expression, single cyan eye
```

**Frame 2:**
```
{{STYLE_ANCHOR}}, head straight up, two small white thinking dots above
antenna in horizontal row, calm focused expression
```

**Frame 3:**
```
{{STYLE_ANCHOR}}, head tilted slightly right, three small white thinking
dots above antenna in horizontal row, calm focused expression
```

**Frame 4:**
```
{{STYLE_ANCHOR}}, head straight up, no thinking dots above antenna,
calm focused expression, single cyan eye
```

**Negative prompt (für alle Frames):**
```
anti-aliasing, smooth gradient, blurry, 3d render, photorealistic, text,
watermark, signature, mouth, teeth, scary, dark expression, multiple
characters, human face, realistic eyes
```

## Midjourney

Base:
```
cute cream pixel-art orb-bot mascot with single cyan eye and orange antenna,
thinking pose, three pulsing dots overhead, deep navy background, 16-bit JRPG
sprite, --style raw --ar 1:1 --stylize 100
```

Frame-Variation: gleicher Job-Seed, variiere "thinking pose 1/2/3/4" und
"one/two/three thinking dots above head / no dots". Mit `--seed <N>` und
`--vary subtle` arbeiten.

## DALL-E 3 / GPT Image

Pro Frame separater Prompt (DALL-E vergisst Style sonst):

```
Pixel art 16-bit retro game sprite style mascot character: a small round
cream-colored robot orb with one large soft cyan eye in the center and a
tiny orange antenna on top. The character has its head tilted slightly to
THE LEFT, looking thoughtful and focused. ONE tiny white pixel dot floats
above its antenna. Solid deep navy blue background, hex color 0d1530, no
gradient, no stars. No anti-aliasing, crisp blocky pixels, 4 colors per
region, limited palette retro game sprite style. Square 1:1 composition,
128x128 sprite scaled up.
```

Frame 2/3/4: ersetze "tilted slightly to THE LEFT" → "straight up" /
"tilted slightly to THE RIGHT" / "straight up", und "ONE" → "TWO" / "THREE"
/ "NO" Dots.

## Lokales SD + PixelArtRedmond LoRA

```
<lora:PixelArtRedmond:1> Pixel Art, {{STYLE_ANCHOR}}, cream orb-bot mascot
with cyan eye and orange antenna, thinking pose with white dots above head,
JRPG sprite, navy background
```

CFG 7, Sampler Euler a, 30 Steps, 128×128 Resolution, Hires-Fix off.

## Assembly

4 Frames als PNG sichern (64×64 oder 128×128, transparent oder mit
solid `#0d1530` Hintergrund).

```bash
# Upscale + GIF zusammenbauen
cd /pfad/zu/frames/
for f in frame*.png; do
  convert "$f" -filter point -resize 240x240 "up-$f"
done
convert up-frame*.png -delay 15 -loop 0 -dispose Background thinking.gif

# Optimieren auf <40KB
gifsicle -O3 --colors 16 thinking.gif -o thinking-final.gif
ls -la thinking-final.gif  # check size
```

**Alternative**: Frames auf https://ezgif.com/maker hochladen, Delay 15
(=150ms), Loop forever, dann auf https://ezgif.com/optimize → Lossy GIF 35,
Color reduction 16 colors.

## Ziel-Specs

| Param | Wert |
|---|---|
| Auflösung | 240×240 |
| Frames | 4 |
| Frame-Delay | 150 ms |
| Loop | infinite |
| Dateigröße | **≤ 40 KB** |
| Palette | 16-24 Farben |
