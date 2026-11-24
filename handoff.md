# Session Handoff - 2026-11-24

## Goal
Change the Charts tab's swell map from a smooth gradient to a stepped colour map (like a classic surf chart) so a colour can be read back to a value at any moment in time.

## Current State
- Done, committed and pushed to main as `dcbff87a`, web deployed with `npm run deploy` (project `rosa`). rosa.surf's live CSS contains `.chart-probe`, so the new build is live.
- Charts draws 20 flat rainbow bands on a fixed scale for all four layers (height, period, energy, wind), clipped to the basemap's coastline, with a numbered key in the deck card and a tap-to-read label.
- Checked in Firefox then Chrome (headless Playwright): phone 420px, desktop 1400/1600px, rotated map, Height and Wind, tap label. `npx tsc --noEmit` clean, `npx vitest run` 53/53.
- NOT checked: Safari / a real iPhone; the "All basins" and single-basin views (only the world layer was looked at); light vs dark theme side by side (palette is the same in both); real-device pan performance (headless: 30 drag moves in about 1 s at 1400px).
- Worktree `charts-view-assignment-36633f42` is clean except this file. Branch is ahead of nothing: the commit went to `origin main` via `git push origin HEAD:main`.

## Active Files
- `web/src/lib/chartBands.ts` - new. Palette (`BAND_COLORS`, 20), `bandScale(variable, imperial)`, `bandOf`, `bandLabels`, `bandRange`, `BAND_PIXELS`.
- `web/src/lib/chartBands.test.ts` - new. Band edges, legend numbers, tap range text, pixel byte order.
- `web/src/pages/ChartsPage.tsx` - renderer rewritten; legend row; tap probe.
- `web/src/styles.css` - `.deck-scale`, `.deck-scale-bar`, `.deck-legend`, `.deck-nums`, `.deck-unit`, `.chart-probe`.
- `docs/UI.md` (Charts line), `docs/SESSIONS.md` (2026-11-24 entry).

## Changes Made This Session
1. Operator's answers (2026-11-24, history only): palette = rainbow like the reference; scale = fixed; layers = all. The "extras" question got no answer at first; numbers on the legend and value on tap were asked for later in the session, contour lines between bands never were.
2. Replaced the smooth single-hue per-run ramp with 20 flat bands. The old header comment said "never a rainbow"; it was rewritten because the operator chose rainbow. Hex values are our own, not sampled from the reference image.
3. Renderer: every screen pixel is sampled from the value grid (bilinear in lon/lat, mercator-exact) and THEN banded, written through `ImageData` as Uint32. The field is painted in the unrotated plane and composited with the map's rotation; pixel count capped at `FIELD_MAX_PX` (1,000,000), upscaled above that. The strip blit, the 8x pre-upscaled canvas, `rampLUT`, `RAMPS`, `WORLD_SCALE_CAP` and the per-run `maxVal` are gone. `world.json`'s `max` is still published but no longer read.
4. Coast fix (operator saw grey gaps at sea and colour on the Nile delta): the model's land mask is 0.5 deg blocks. Sea values are now carried `SHORE_REACH_CELLS` = 2 cells past it (neighbour mean, per pass), and the field is clipped to the basemap's ocean polygons: `queryRenderedFeatures({layers:["water"], filter: class == ocean})`, each polygon filled on its own with evenodd, then `source-in`. Redraws on map `idle` so the clip follows tile loads; draws unclipped when no water features are loaded yet. Lakes excluded on purpose.
5. Legend: own row in `.deck-card` between head and timeline, one block per band, a number under every second edge, last with "+", unit at the end.
6. Bands moved to round numbers in the reader's units (my call, reported to the operator): height 0.25 m to 5 m or 1 ft to 20 ft; wind 5 km/h to 100 or 2.5 kt to 50; period 1 s to 20; energy 10 kW/m to 200. Wind data is in knots internally, so the metric step is 5/1.852 kt.
7. Tap: `m.on("click")` stores the point if it is on ocean; `draw()` re-reads it with `sampleLayer` and positions `.chart-probe` ("0.75 - 1 m"). A tap on land clears it.

## Failed Attempts
- Banding by colouring cells first, letting the canvas smooth them, then mapping pixels through a stepped table with `getImageData`: bands were flat but edges came out as 3 px stair-steps, because the row strips only interpolate horizontally. Replaced by the per-pixel sampler.
- Legend numbers in a class named `.deck-ticks`: that class already exists for the timeline ruler (absolutely positioned, full width), so the numbers vanished and the layer button stopped taking clicks. Renamed to `.deck-nums`.
- Tap label colours `var(--foreground)` on `var(--background)`: light theme's `--background` is translucent white (`#ffffff1b`). Uses `--tabbar-bg` / `--foreground` now.
- Test harness, not product: headless Playwright Firefox has no WebGL unless launched with `firefoxUserPrefs` `webgl.force-enabled: true`, `gfx.webrender.software: true`; Charts waits on `getPosition()`, so the context needs geolocation granted; `vite` in dev reads no `VITE_DATA_BASE`, so start it with `VITE_DATA_BASE=https://rosa-data-opal.vercel.app npx vite`. Without these the page shows "Charts aren't published yet".
- `git push` from this shell failed the pre-push hook with `uv: command not found`; fixed by `PATH="$HOME/.local/bin:$PATH" git push origin HEAD:main`, hook then passed.
- `pkill -f "vite --port 5199"` in the same command line as other work kills its own shell (exit 144); run it alone.

## Next Step
1. Open https://rosa.surf/charts on a real iPhone (Safari) and check: bands draw, coast clip lines up, panning is smooth, tap label appears. Safari was never tested.
2. Check the "All basins" and a single-basin selection in `ChartsPage.tsx` (non-wrapping grids take the `else` branch in the column setup and in `sampleLayer`).
3. Open decisions for the operator, none approved: contour lines between bands; whether `energy`'s linear 10 kW/m bands are useful (a 1 m / 10 s day is 4.4 kW/m, so small days sit in one band); whether to stop publishing `max` in `world.json` (`pipeline/src/rosa_pipeline/swellmap.py`), now unread.
4. `web/.vercel/project.json` was copied into this worktree from `~/Projects/rosa/web/.vercel/` for the deploy; it is untracked and can stay.
