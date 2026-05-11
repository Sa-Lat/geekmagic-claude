# Workflow: Pixel-Frames → Cube-GIF

End-to-End-Anleitung: von leerem Canvas zur fertigen Animation auf dem Cube.

## Schritt 1: Tool wählen

Nimm **ein** Tool und nutze es konsistent für alle drei Assets. Style-Drift
zwischen verschiedenen KIs ist hässlich.

| Tool | Stärken | Schwächen | URL |
|---|---|---|---|
| **PixelLab.ai** | Echte Pixel-Animation (Skeleton-Rig), 4-8 Frames in einem Job | Kostet, nur Online | https://www.pixellab.ai |
| **Retro Diffusion** | SD-basiert, schnell, viele LoRAs | Manuelle Frame-Konsistenz | https://www.retrodiffusion.ai |
| **Pixel Art XL (Replicate)** | Frei nutzbar, gute Qualität | Einzel-Frames, manuelle Animation | https://replicate.com/nerijs/pixel-art-xl |
| **Midjourney** | Stilistisch sehr stark, Seed-Variations | Pixel-Art-Treue nicht 100% | https://midjourney.com |
| **DALL-E 3** | Direkt im ChatGPT, einfach | Anti-Aliasing-Probleme, Frame-Konsistenz schwach | ChatGPT |
| **Lokales SD + LoRA** | Frei, volle Kontrolle, reproduzierbar | Setup-Aufwand, GPU nötig | A1111/ComfyUI + PixelArtRedmond |

**Empfehlung: PixelLab.ai** — einziges Tool das echte Multi-Frame-Animation
direkt rendert. Spart enorm viel Nacharbeit für Frame-Konsistenz.

## Schritt 2: Frames generieren

1. Style-Guide (`00-style-guide.md`) lesen, Anchor-Text kopieren
2. Asset-spezifischen File öffnen (`01-thinking.md`, `02-alert.md`, `03-idle.md`)
3. Prompt für gewähltes Tool nehmen
4. **Gleichen Seed über alle Frames eines Assets** verwenden
5. Frames als PNG sichern: `frame1.png`, `frame2.png`, ...

## Schritt 3: Upscale 64/128 → 240

**KRITISCH**: nearest-neighbor, KEIN bilinear/lanczos, sonst Pixel werden matschig.

```bash
cd /pfad/zu/frames/
mkdir up
for f in frame*.png; do
  convert "$f" -filter point -resize 240x240 "up/$f"
done
```

Web-Alternative: https://www.iloveimg.com/resize-image → "Pixel-Perfect-Mode"
oder https://ezgif.com/resize → "Resampling method: nearest neighbor"

## Schritt 4: GIF zusammenbauen

```bash
cd up/

# thinking: 4 frames @ 150ms
convert frame1.png frame2.png frame3.png frame4.png \
  -delay 15 -loop 0 -dispose Background thinking.gif

# alert: 2-4 frames @ 200ms (Alternation A-B-A-B)
convert frameA.png frameB.png frameA.png frameB.png \
  -delay 20 -loop 0 -dispose Background alert.gif

# idle: 6 frames @ 250ms
convert frame1.png frame2.png frame3.png frame4.png frame5.png frame6.png \
  -delay 25 -loop 0 -dispose Background idle.gif
```

**Web-Alternative**: https://ezgif.com/maker — Frames hochladen in Reihenfolge,
Delay setzen (15/20/25 → 150/200/250ms), "Loop forever" ON, "Make a GIF!"

## Schritt 4.5: Transparenz + Kontrast (bei Anime-Pixel-Art kritisch)

PixelLab exportiert oft mit transparentem BG. Auf Cube zeigen transparente
Frames unkontrollierte Farben → Flackern. Plus: niedrige globale Palette frisst
subtile Details (Anime-Wimpern in Mono-Pink-Komposition).

**Recipe für Anime-Pixel-Art (z.B. Pink-Magical-Girl, getestet auf Cube)**:

1. https://ezgif.com/effects → GIF hochladen
2. **Replace transparency**: BG-Farbe die zur Komposition passt
   (z.B. `#ffd1f3` für Pink-Anime — bewahrt Look statt navy-Frame zu zerschießen)
3. **Adjustments**: **Saturation −10, Contrast +30** — Pink-Töne werden
   abgeflacht, dunkle Konturen (Wimpern/Brauen) bleiben sichtbar nach
   Cube-Quantization
4. Apply → Export → in `assets/` ablegen

**Warum Contrast +30**: Cube nutzt global color table (oft 32-64 Indices). Bei
Mono-Farb-Anime quetscht das dunkle 1-2px Details (z.B. obere Wimpernlinie) in
den dominanten BG-Index. Contrast-Boost rettet die Linien-Pixel.

## Schritt 5: Optimieren

Cube hat nur ~311 KB frei. Drei GIFs zusammen sollten **<150 KB** sein.

```bash
# gifsicle ist der Goldstandard
sudo apt install gifsicle   # falls noch nicht da

# Palette reduzieren — Pflicht für klein
gifsicle -O3 --colors 16 thinking.gif -o thinking-final.gif
gifsicle -O3 --colors 32 alert.gif    -o alert-final.gif    # mehr Farben für Rot-Kontrast
gifsicle -O3 --colors 12 idle.gif     -o idle-final.gif     # idle darf simpel

# Check sizes
ls -la *-final.gif
```

**Web-Alternative**: https://ezgif.com/optimize
- Lossy GIF: 30-50
- Color reduction: 16 (thinking/idle), 32 (alert)
- Dithering: OFF (Pixel-Art-Style!)

Falls immer noch zu groß:
- Frames reduzieren (z.B. idle 6→4)
- Auflösung halbieren (120×120) — Cube skaliert hoch, sieht aber chunkier aus
- Frame-Delay erhöhen (weniger Gesamtframes)

## Schritt 6: Größen-Check

```bash
ls -la /pfad/*-final.gif
# Ziel: thinking <40KB, alert <50KB, idle <30KB, gesamt <120KB
```

Cube-Status checken:
```bash
curl -s http://$CUBE_IP/space.json
# {"total":3121152,"free":318988}
# Für unsere 3 GIFs reicht das knapp — vorher alte Files löschen!
```

## Schritt 7: Alte Files löschen, neue hochladen

**Alte Files löschen** (Web-UI oder per CLI):
```bash
# Erst auflisten
curl -s "http://$CUBE_IP/filelist?dir=/image/" | grep -oP "href='/image/[^']+'" | sed "s|href='/image/||;s|'$||"

# Löschen einzeln (Beispiel — vorsicht!)
curl "http://$CUBE_IP/delete?file=/image/3757fcc49d997304.jpg"

# ODER alles auf einmal:
curl "http://$CUBE_IP/set?clear=image"
```

**Hochladen**:
```bash
# Multipart-Field heißt "file" laut HACS-Integration; Web-UI nutzt "update".
# Probieren — beides sollte gehen.
curl -F "file=@thinking-final.gif" "http://$CUBE_IP/doUpload?dir=/image/"
curl -F "file=@alert-final.gif"    "http://$CUBE_IP/doUpload?dir=/image/"
curl -F "file=@idle-final.gif"     "http://$CUBE_IP/doUpload?dir=/image/"
```

**Falls Upload fehlschlägt** mit "duplicate Content-Length": Cube macht
malformed HTTP — Upload klappt aber trotzdem. Mit `-f` ignoriert curl 400er.
Prüfe via Filelist ob File angekommen.

**Web-Alternative**: http://$CUBE_IP/image.html → Choose → UPLOAD

## Schritt 8: Direkt testen

```bash
# Per HTTP direkt anzeigen lassen
curl "http://$CUBE_IP/set?img=/image/thinking-final.gif"
# Cube wechselt auf Album-Theme und zeigt die GIF

# Über CLI-Wrapper (nach Installation von ~/.claude/bin/cube.sh):
~/.claude/bin/cube.sh thinking
~/.claude/bin/cube.sh alert
~/.claude/bin/cube.sh idle
```

## Schritt 9: Hooks aktivieren

Nach erfolgreichem Test: Hook-Einträge in `~/.claude/settings.json` aktivieren
(siehe Plan `~/.claude/plans/rustling-sniffing-planet.md`).

Neue Claude-Session starten → Prompt eingeben → Cube zeigt thinking-Animation.
Bei Permission-Prompt → alert. Bei Fertig-Werden → idle.

## Troubleshooting

| Symptom | Ursache | Fix |
|---|---|---|
| GIF zeigt nur ersten Frame, kein Loop | `-loop 0` fehlt | Mit gifsicle neu bauen |
| Cube zeigt nichts nach Upload | Theme nicht auf Album | `curl ".../set?theme=3"` |
| GIF läuft, aber Farben kaputt | Palette zu klein | gifsicle `--colors 32` |
| Cube zeigt Buchstaben/Kästchen | File-Pfad falsch in `/set?img=` | Pfad muss `/image/NAME.gif` sein, mit führendem Slash |
| Bilinear-Smoothing kaputt Pixelart | `-filter point` vergessen | ImageMagick mit `-filter point -resize` |
| Cube hängt / nicht erreichbar | RAM zu klein bei großer GIF | Datei <50KB, max 8 Frames |
