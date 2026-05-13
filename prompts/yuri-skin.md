# Skin: Yuri (Doki-Doki-Vibes)

Zweiter Maskottchen-Skin neben Magical-Girl-Pink. Yuri-Style: shy academic,
dark purple hair, ein Auge von Pony verdeckt, gentle violet gaze, Schuluniform.

Wenn fertig: Files `thinking.gif` / `alert.gif` / `idle.gif` (+ optional alle
7 states) in `assets/yuri/` ablegen. `resize.sh` und `upload.sh` entdecken den
neuen Ordner automatisch; nur `bin/cube.sh` muss um `skin yuri` Option erweitert
werden (siehe unten).

## Base-Prompt (PixelLab Character Creator, 128×128 bust-up)

```
16-bit JRPG anime portrait, bust-up shot from chest up, very long flowing
dark purple hair (#3d2851) flowing past shoulders with darker shadow strands
(#211532), thick straight hair bangs covering right eye partially, pale
porcelain skin (#f5e7d8), single large gentle deep violet eye visible
(#7d5a9e) with subtle eyelash detail in near-black (#0a0613), small shy
mouth, white school blouse with red ribbon at collar visible at bottom of
frame, dark navy-purple sweater vest hint (#2a1f3d), bust-up close-up where
head fills 60% of frame, soft warm cream background (#f4e4cf), no
anti-aliasing, crisp pixels, anime style, 128x128, 32-color limited palette
```

## Farbpalette

| Rolle | Hex | Note |
|---|---|---|
| Hair main | `#3d2851` | dark purple, hauptkörper |
| Hair shadow | `#211532` | depth/strand-tips |
| Skin | `#f5e7d8` | pale porcelain |
| Eye violet | `#7d5a9e` | gentle iris |
| Eyelash | `#0a0613` | near-black, kontrast-kritisch |
| Blouse | `#ffffff` | white |
| Collar ribbon | `#c1272d` | red school-ribbon |
| Sweater vest | `#2a1f3d` | navy-purple hint |
| **BG cream** | `#f4e4cf` | warm academic — Pflicht für Silhouette |

## Warum Cream-BG (`#f4e4cf`) statt Navy

- Yuri-Haar ist dunkel-lila → BG muss HELL sein für Silhouette-Lesbarkeit
- Cream warm passt zu Library/Academic-Vibe
- Maximum-Kontrast zu dark-purple Haar → keine Detail-Merge-Probleme wie
  bei Pink-Mono-Komposition (Magical-Girl)

## Style-Anchors die kritisch sind

- `single eye visible, other hidden by bangs` — Yuri-Signature
- `eyelash detail in near-black (#0a0613)` — wichtig wegen Cube-Quantization
- `gentle shy expression` — nicht happy/wide-eyed
- `thick straight hair bangs` — Anime-Yuri Frisur-Merkmal

## Action Descriptions (für PixelLab Animate)

### thinking
```
Eyes glance downward shyly, single visible eye half-closes thoughtfully,
fingers visible at chin holding pen tip, hair sways subtly, small "..."
bubble appears briefly above her head.
```

### alert
```
She looks up suddenly, single visible eye widens, hair bangs lift slightly
revealing the second eye briefly, small "!" appears above her head, soft
blush spreads on pale cheeks. Head tilts curious.
```

### idle
```
Eyes lower to read an invisible book, head tilts down slightly, hair
strands sway calmly, occasional slow blink. A small purple sparkle or
white feather drifts gently in the background.
```

## Frame-Count + Delay

| Asset | Frames | Delay/frame | Total loop |
|---|---|---|---|
| thinking | 4 | 150ms | 600ms |
| alert | 4 (A-B-A-B) | 200ms | 800ms |
| idle | 6 | 250ms | 1.5s |

## Post-Process (ezgif)

Yuri's Komposition ist kontrastreicher als Magical-Girl-Pink (dunkles Haar
auf hellem BG) → vermutlich kein Sat/Con-Boost nötig. Standard-Recipe:

1. https://ezgif.com/effects → Replace transparency mit `#f4e4cf`
2. Apply, Export
3. In `assets/` ablegen

Falls Wimpern dennoch zu schwach: Sat −5, Con +15 (weniger aggressiv als
Magical-Girl wegen schon vorhandenem Kontrast).

## Cube-Skin Integration (TODO morgen)

Nach Asset-Erstellung in `bin/cube.sh` erweitern:

```bash
prefix() {
  case "$(skin_get)" in
    waifu) echo "waifu_" ;;
    yuri)  echo "yuri_"  ;;
    *)     echo "" ;;
  esac
}
```

Und im skin-subcommand:
```bash
orb|waifu|yuri) ... ;;
```

Plus README + Memory updaten.
