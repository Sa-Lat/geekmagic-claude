# Skin: Waifu (Magical-Girl-Pink)

Erster Maskottchen-Skin neben `orb`. Sailor-Moon-Vibes: lange pinke Haare,
großes Augenpaar (deep purple iris), kleiner gelber Mondsichel-Stirnschmuck,
weiße Schuluniform mit Sailor-Kragen. Bust-up Komposition, Kopf füllt 60%.

Files in `assets/`: `waifu_<state>.gif`. Resize→Upload via Make-Pipeline.

## Base-Prompt (PixelLab Character Creator, 128×128 bust-up)

```
16-bit JRPG anime portrait, bust-up shot from chest up, very long flowing
hot-pink hair (#ff6fb5) flowing past shoulders with darker pink shadow
strands (#c44a8c), straight bangs framing forehead, small golden crescent
moon ornament (#f7c948) centered on forehead, pale porcelain skin
(#fff0e6), large round deep purple-pink eyes (#a35dc7) with bright pink
highlight (#ffd1f3) upper-left, near-black eyelash line (#1a0612),
small soft mouth, white sailor-blouse with light-pink collar accents
visible at bottom of frame, bust-up close-up where head fills 60% of
frame, soft mono-pink background (#ffd1f3), no anti-aliasing, crisp
pixels, anime style, 128x128, 32-color limited palette
```

## Farbpalette

| Rolle | Hex | Note |
|---|---|---|
| Hair main | `#ff6fb5` | hot pink hauptkörper |
| Hair shadow | `#c44a8c` | strand depth |
| Skin | `#fff0e6` | pale porcelain |
| Eye iris | `#a35dc7` | deep purple-pink |
| Eye highlight | `#ffd1f3` | upper-left glint |
| Eyelash | `#1a0612` | near-black, kritisch wegen Quantize |
| Moon ornament | `#f7c948` | golden crescent stirnschmuck |
| Blouse | `#ffffff` | white sailor |
| Collar accent | `#ffb3d9` | light pink |
| **BG pink** | `#ffd1f3` | mono-pink, Pflicht für Silhouette |
| Alert red | `#e53935` | nur für !/× |
| Done sparkle | `#fff04d` | yellow star |
| Compact violet | `#8b6fc4` | swirl-purple |

## Style-Anchors die kritisch sind

- `large round eyes, both visible` — Magical-Girl-Signature
- `golden crescent moon on forehead` — Sailor-Moon Marker
- `eyelash line near-black (#1a0612)` — sonst frisst Mono-Pink-Palette
- `mono-pink BG (#ffd1f3)` — kein navy, kein cream
- `Sat −10 / Con +30` post-process Pflicht (siehe `04-workflow.md`)

## Action Descriptions pro State

Style-Anchor in JEDEN Prompt einfügen. Nur **kleinster Delta** pro Frame,
**gleicher Seed** über die Frame-Serie eines States.

### thinking (existing, refresh-fähig)
```
Eyes glance up-left thoughtfully, one slim finger raised to chin, head
tilts subtly side-to-side, small "..." bubble appears above head. Hair
sways gently.
```
4 Frames, 150ms.

### alert (existing)
```
Both eyes widen, mouth opens small "oh!", hands raise near shoulders
defensive-cute, large bright red "!" (#e53935) appears above head, soft
red vignette on frame edges. A-B-A-B blink.
```
4 Frames, 200ms.

### idle (existing)
```
Slow blink, eyes half-closed dreamy, head tilts down softly, hair
strands drift, occasional pink sparkle (#ffd1f3) floats up-right behind
hair.
```
6 Frames, 250ms.

---

### permission — wartet höflich auf User-Erlaubnis
**Konzept**: Höfliches Fragen, NICHT alarmiert. Differenzierung zu `alert`
ist wichtig — permission ist freundlich-erwartungsvoll, alert ist urgent.

```
Both hands clasped together at chest in polite "onegai" pose, head
tilts to the side curious, eyes large and looking up directly at viewer,
small light-blue question mark "?" (#5db8ff) gently bobbing above head,
soft warm smile. Hair frames face still.
```

Frames: 4 (A-B-A-B), Delay 250ms.
- F1: hands clasped, `?` small, slight head tilt left
- F2: hands clasped, `?` larger pulse, head tilt right
- Sanftes pulsieren, KEIN rotes Vignette, KEIN aggressives blink.

Palette-extra: `#5db8ff` question-mark blau (kontrast zu pink).

### error — Bash-Command failed
**Konzept**: Verschreckt + Schuldgefühl, NICHT katastrophal. Sweat-drop
+ kleines `×` markieren "etwas ging schief".

```
Eyes wide and watery looking down-left guiltily, mouth pursed small,
single anime sweat-drop (#5db8ff) on temple, large red cross "×"
(#e53935) appears top-right above head, both hands raised palms-up
near cheeks apologetic-flustered pose, soft red blush spreads.
```

Frames: 4, Delay 200ms.
- F1: sweat-drop forms, `×` faint
- F2: `×` bright, sweat-drop slides down
- F3: blush peaks, eyes shimmer
- F4: returns to F1 (loop)

Palette-extra: `#5db8ff` sweat-drop, `#e53935` cross, `#ffb3c8` blush.

**Negative**: keine Tränen-Stream (zu dramatisch), kein Blut, kein wütender
Ausdruck.

### compact — PreCompact, Context-Limit nah
**Konzept**: Überfordert / "Kopf voll", mehrere swirly Gedanken kreisen.
Sleepy-overwhelmed Hybrid, KEIN Schmerz, KEIN Alarm. Reads als
"sortiert Speicher gerade".

```
Eyes half-closed dazed, slight x_x or @_@ pupils swirling, head tilts
forward slightly tired, three small purple thought-swirls (#8b6fc4)
orbiting clockwise above and around head, soft violet hue tints the
background corners (#e6d4f5), tiny zZ or "..." optional. Hands relaxed.
```

Frames: 6, Delay 200ms.
- Swirls rotieren um Kopf, jeder Frame um 60° versetzt.
- Augen-Pupille pulst Schwirl-Muster (clockwise spiral pixel-pattern).

Palette-extra: `#8b6fc4` swirl-purple, `#e6d4f5` violet bg-tint.

**Negative**: kein Erbrechen, keine grünen Schmerz-Effekte, kein Schock.

### done — Task complete (dediziert, ersetzt alert-dupe)
**Konzept**: Pure cheerful celebration. Großes Lächeln + Peace-Sign +
goldener Stern-Funkel. Belohnung, fühlt sich gut an.

```
Eyes closed in happy-arc smile shape (^_^), wide cheerful open-mouth
smile, one hand raised peace-sign "V" near cheek, soft pink blush on
both cheeks, large bright yellow sparkle star (#fff04d) bursting top-
right above head with 4-point cross-glint, two smaller sparkles
(#ffd1f3) drift up. Hair flows celebratory.
```

Frames: 4 (A-B-A-B), Delay 200ms.
- F1: smile + peace, big star small
- F2: smile + peace, big star LARGE with cross-glint + small sparkles ascend
- A-B-A-B Funkel-Loop.

Palette-extra: `#fff04d` star-yellow, `#ffb3c8` blush.

**Negative**: kein Trauer-Ausdruck, keine roten Alert-Vibes, kein `!`.

## Frame-Count + Delay Übersicht

| State | Frames | Delay | Total | Auto-Revert |
|---|---|---|---|---|
| thinking | 4 | 150ms | 600ms | — |
| alert | 4 | 200ms | 800ms | 30s → idle |
| permission | 4 | 250ms | 1000ms | none (bleibt) |
| error | 4 | 200ms | 800ms | 30s → idle |
| compact | 6 | 200ms | 1200ms | 30s → idle |
| done | 4 | 200ms | 800ms | 5s → idle |
| idle | 6 | 250ms | 1500ms | — |

## Post-Process (ezgif, kritisch wegen Mono-Pink-Quantize)

Aus `04-workflow.md` Recipe für alle waifu-Assets:

1. https://ezgif.com/effects → Replace transparency mit `#ffd1f3`
2. **Saturation −10, Contrast +30** — rettet Wimpernlinien
3. Apply, Export
4. `assets/waifu/<state>.gif` ablegen (per-skin Ordner)
5. **Optional** `bin/contrast-fix.py` (Sat-15 / Con+45 / Sharp+50) wenn Brauen
   beim Cube-Quantize wegfallen — siehe README §Workflow
6. `make resize && make upload` (upload.sh übersetzt zu `waifu_<state>.gif` auf cube)

**Achtung error/compact/permission**: Diese haben Zweitfarbe (blau / violett /
rot-cross) — Color-Reduction auf min. **32 Indices** bei `gifsicle -O3
--colors 32`, sonst frisst Mono-Pink-Palette den Kontrast.

## Ziel-Specs pro File

| Param | Wert |
|---|---|
| Auflösung Source | 128×128 |
| Auflösung Cube | 240×240 (sample-resize) |
| Dateigröße | ≤ 50 KB |
| Palette | 24–32 |
| Loop | infinite |

## Workflow

```bash
# Pro neuem State:
# 1. PixelLab → 128×128 PNG-Frames mit Base-Prompt + Action-Description
# 2. ezgif.com/maker → GIF mit Delay aus Tabelle
# 3. ezgif post-process (transparency replace + Sat/Con)
# 4. Ablage:
cp ~/Downloads/permission.gif assets/waifu/
# 4b. Optional contrast-fix (rettet 1-2px Brauen/Wimpern bei mono-pink):
bin/contrast-fix.py assets/waifu/permission.gif /tmp/fixed.gif && \
  mv /tmp/fixed.gif assets/waifu/permission.gif
# 5. Resize + upload:
make resize        # → assets/240/waifu/permission.gif
make upload        # → cube /image/waifu_permission.gif (prefix-translation)
bin/cube.sh skin waifu
bin/cube.sh permission   # smoke-test
```

## Integration-Check

`bin/cube.sh` löst alle 7 States für skin `waifu` zu `waifu_<state>.gif` auf
und lädt sie via `/set?img=/image/<file>`. `upload.sh` macht beim Push die
prefix-translation von `assets/240/waifu/<state>.gif` zur cube-flat-Konvention
automatisch. Solange Source-Files genau `assets/waifu/{thinking,alert,permission,
error,compact,done,idle}.gif` heißen, kein Code-Change nötig.
