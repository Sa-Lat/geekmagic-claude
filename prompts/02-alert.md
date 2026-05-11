# Asset: `alert.gif` — Claude braucht Aufmerksamkeit

Trigger: `Notification`-Hook. Claude wartet auf Permission-Erlaubnis oder ist
idle und braucht User-Input → Cube blinkt auffällig.

## Konzept

Maskottchen winkt mit beiden Armen, Auge weit aufgerissen, großes rotes
Ausrufezeichen über dem Kopf. **Hoher Kontrast**, soll im Peripheriebereich
auffallen ohne dass man hinguckt. **2–4 Frames, 200ms each.** Insgesamt
400–800ms Blink-Loop.

## Style-Anchor

Aus `00-style-guide.md` + Notfall-Erweiterung:
```
Plus: large bright red exclamation mark #e53935 above head, optional 4px red
vignette on frame edges, alarm urgency
```

## PixelLab.ai

**Base-Sprite:**
```
Round cream orb-bot mascot with very wide alarmed cyan eye, both stubby pixel
arms raised waving, large red exclamation mark pixel above head, alarm/alert
pose, deep navy background with subtle red vignette edges, 16-bit pixel art,
64x64, no anti-aliasing, crisp pixels
```

**Animation-Frames (4):**
- **F1**: small exclamation mark, arms slightly raised, eye normal width — bg navy
- **F2**: LARGE bright red `!` centered above head, arms HIGH waving, eye WIDE — bg navy + red vignette
- **F3**: small exclamation mark, arms back down, eye normal — bg navy
- **F4**: LARGE red `!` + arms waving high — bg navy + red vignette

Alternation A-B-A-B erzeugt Blinkeffekt.

## Retro Diffusion / Pixel Art XL

Zwei-State-Alternation, gleicher Seed:

**State A (Alarm):**
```
{{STYLE_ANCHOR}}, cream orb-bot mascot, wide alarmed cyan eye, both pixel
arms raised high waving, large bright red exclamation mark #e53935 centered
above antenna, urgent alert pose, 4px red vignette on frame edges
```

**State B (Calm zwischen Blinks):**
```
{{STYLE_ANCHOR}}, same cream orb-bot, eye normal size, both arms at sides
relaxed, no exclamation mark, calm neutral pose, no red vignette
```

Alternierend A-B-A-B als 4-Frame-GIF mit 200ms Delay.

**Negative prompt:**
```
anti-aliasing, smooth gradient, blurry, 3d render, dark gradient background,
multiple characters, photorealistic, text other than single exclamation mark,
mouth, scary monster, demonic
```

## Midjourney

```
alarmed cute cream pixel-art orb-bot mascot, cyan eye wide open shocked,
both arms raised waving for attention, big bright red exclamation mark
floating above head, deep navy background with red urgency glow at edges,
16-bit JRPG alert sprite --style raw --ar 1:1 --stylize 80
```

Variation 2: gleicher Seed, "calm neutral pose, no exclamation, arms down,
no red glow" — für State B.

## DALL-E 3 / GPT Image

**State A:**
```
Pixel art 16-bit retro game sprite: small round cream-colored robot orb
with one large WIDE cyan eye looking alarmed and surprised, two short pixel
arms raised HIGH waving frantically. A big bright red pixel exclamation mark
"!" character floats above its head. Deep navy blue background, hex #0d1530,
with subtle red vignette glow at the four frame edges. No anti-aliasing,
crisp blocky pixels, retro game sprite. Square 1:1, 128x128 scaled up.
```

**State B:**
```
Same pixel art 16-bit cream robot orb mascot character with single cyan eye
and orange antenna. Calm neutral pose. Arms at sides, eye normal size. NO
exclamation mark. Deep navy blue background hex #0d1530, no red glow. No
anti-aliasing, crisp blocky pixels. Square 1:1.
```

## Lokales SD + PixelArtRedmond

```
<lora:PixelArtRedmond:1> Pixel Art, {{STYLE_ANCHOR}}, cream orb-bot mascot
alarmed pose with red exclamation mark above head, arms waving, navy
background with red vignette, JRPG alert sprite
```

## Assembly

```bash
# Wenn 4 separate Frames (A-B-A-B):
convert frameA.png frameB.png frameA.png frameB.png \
  -filter point -resize 240x240 -delay 20 -loop 0 -dispose Background alert.gif

# Optimieren — Rot+Navy braucht mehr Farben als andere Assets
gifsicle -O3 --colors 32 alert.gif -o alert-final.gif
```

**Web-Workflow**: ezgif.com/maker, Delay 20 (=200ms), Loop forever.
Optimize: Lossy 30, Color reduction 32 (Rot-Kontrast erhalten!).

## Ziel-Specs

| Param | Wert |
|---|---|
| Auflösung | 240×240 |
| Frames | 2–4 |
| Frame-Delay | 200 ms |
| Loop | infinite |
| Dateigröße | **≤ 50 KB** |
| Palette | 24–32 Farben (Rot-Kontrast wichtig) |

## Bonus: Multi-Stufe (optional)

Falls Cube auch unterschiedliche Notification-Typen unterscheiden soll, kannst
du Varianten generieren mit:
- `alert-permission.gif` — fragend, gelbes `?`
- `alert-error.gif` — rotes `X`
- `alert-info.gif` — blaues `i`

Hooks können dann `cube.sh alert-permission` / `alert-error` etc. aufrufen.
