# cube overlay — project plugin assets

Cube's project-specific frontend assets for the **`webview-overlay`** package.
The generic overlay shell (poll loop, row rendering, drag, native menu, base
structure CSS) lives in that package; this directory holds only what makes the
overlay *cube*. `cube-overlay.pyw` passes both files via `OverlayConfig.assets`.

## Files

- `cube-entity.js` — the voxel cube-entity canvas renderer. 33 cubes in 3
  concentric rings + a cyan core, 8 emotions, painter's-algorithm draw with
  back-face culling. Exports `window.CubeEntity` (constructed as
  `new CubeEntity(canvasEl, {size, emotion})`, methods `setEmotion/setSize/
  pause/resume`) and `window.CUBE_STATE_TO_EMOTION` (dashboard-state → emotion).
- `cube-theme.css` — the cyan "Mochi Classic" light + dark palettes. Defines
  the `--card / --text / --acc-* / --brand / --bar-fill …` tokens that the
  package's `base.css` references with `var(--token, fallback)`, plus the
  per-state `--acc` mapping for the dots.

## How they plug in

`cube-overlay.pyw` wires them through `OverlayConfig.frontend_config`:

```python
frontend_config={
    "entityGlobal": "CubeEntity",
    "stateToEmotionGlobal": "CUBE_STATE_TO_EMOTION",
    "defaultEmotion": "idle",
    "usageThresholds": [[80, "#e85555"], [50, "#d7a04a"]],
}
```

`overlay-base.js` (in the package) discovers the renderer via `entityGlobal`
and maps the dashboard winner state to an emotion via `stateToEmotionGlobal`.
If those keys were absent the overlay would simply render rows + usage with no
canvas.

## Preview

There is no standalone `index.html` here anymore — the HTML template is owned
by the package. To preview the base look in a browser, open
`tests/preview/preview.html` in the `webview-overlay` repo.
