# Session Handoff — 2026-07-20

## Goal
Polish the Rosa PWA (splash screen, header brand lockup, Spots tab favorites/star,
daylight sessions) and — the big one — make per-spot forecasts actually differ:
neighbouring spots were showing byte-identical data. Then gather + record Surfline-informed
algorithm improvements for tomorrow.

## Current State
All committed, pushed, and deployed to https://rosa-rust.vercel.app (verified live:
hilton ≠ kontiki data now differs). 60 pipeline tests + web tsc green. Nothing dangling.
- **Per-spot forecasts differ** (root fix): each spot samples its own offshore point and
  orients to its own coastline shore-normal. Whole coast currently FLAT (real summer Med),
  but wind/class/rating vary per spot; heights differ across marine-grid cells.
- **4 headland/peninsula angles are flagged `TODO-verify`** in israel.yaml (akko-argaman 70,
  kiryat-yam 114, bat-galim 164, backdoor-haifa 163) — coastline averaging is unreliable
  where the shore curves ~90°. Need user's local values to pin. UNRESOLVED.
- **Splash** holds until initial data loads (no empty "Loading…" flash), min 1s, blinking
  "loading" text under the wordmark.
- Surfline improvement report saved at `rosa-forecast-improvements.md` (untracked) — the
  plan for tomorrow. Not yet acted on.
- `todo.md` (untracked) is the user's scratch list — deliberately NOT committed.

## Active Files
- `data/spots/israel.yaml` — dropped shared offshore_points/point + uniform 90°; per-spot
  explicit `offshore_direction` (82–126° coastline-derived); 4 spots flagged TODO-verify.
- `pipeline/src/rosa_pipeline/fetch.py` — added `fetch_many()` batched multi-location fetch
  (Open-Meteo returns per-location array; full run = 2 requests).
- `pipeline/src/rosa_pipeline/spots.py` — per-spot offshore_point (own coord − 0.06° lon);
  offshore_direction explicit-else-neighbour-tangent fallback.
- `pipeline/src/rosa_pipeline/cli.py` — batched fetch of unique points; skip-and-warn dry cells.
- `pipeline/tests/{test_cli,test_spots}.py`, fixture renamed → `32.3817_34.8035.json` (beit-yanai pt).
- `web/index.html`, `web/src/main.tsx`, `web/src/splash.ts` — splash + readiness signal.
- `web/src/components/parts.tsx`, `web/src/styles.css` — header brand lockup, dot, favorites width.
- `web/src/pages/{SpotsPage,TodayPage,SpotPage,MapPage,SettingsPage}.tsx` — star toggle,
  favorites cards, date-bar dots, daylight sessions, per-page signalReady().
- `web/vite.config.ts` — PWA icon = icon-maskable (any maskable).
- `rosa-forecast-improvements.md` — Surfline-methodology-derived improvement plan (untracked).

## Changes Made This Session
1. Live-drag date highlight (committed earlier d97cb8c) + merged a divergent parallel branch
   (spot polish + refreshed icons) — resolved DateBar conflict keeping both dots + live highlight.
2. Date-bar dots: removed on Home (multiple spots = misleading), kept borderless on spot screen.
3. Spots tab: rows → `<a>` links with real StarButton (tap star = fav, tap row = open);
   Favorites now render the same compact SpotCard as Home; fixed double-inset width via
   `.spots-page .rank-list { padding:0 }`.
4. Daylight sessions: `sessionChips` in SpotPage.tsx gated to slots between first/last light
   (spot-local minutes via fmtClock) — killed the pre-dawn 03:00 "best session".
5. Splash screen (index.html/main.tsx/splash.ts): red bg + white mark (favicon as CSS mask) +
   wordmark; holds until appReady (each page fires signalReady on data-load/err, 10s cap) +
   fonts + min 1s; blinking "loading" under wordmark.
6. Header brand lockup: red favicon mark + "rosa" + baseline circular dot (icon red #d82619),
   icon 0.72em (a bit taller than text), spacing = one dot-width via --brand-dot (2.5px).
7. PWA app icon → icon-maskable (any maskable) + apple-touch-icon.
8. **Per-spot differentiation** (the main work): diagnosed that ~22 spots shared offshore point
   `il_central` + identical params → byte-identical forecasts (proved via CDP DOM read; frontend
   was NOT the bug). Implemented per-spot sampling (batched fetch, validated Open-Meteo array
   response) + coastline-derived offshore_direction (pulled full OSM coastline in 1 Overpass query,
   computed shore-normal per spot with land-on-left convention, length-weighted over ~600m to
   outvote jetties/marinas). Baked explicit into DB. Regenerated all 40 spots live, synced to web.
9. Committed in 2 groups (d1c0c40 pipeline, 97dea12 web), pushed, deployed.
10. Produced a Surfline-research prompt for the user's Claude Chrome extension; results saved
    to rosa-forecast-improvements.md.

## Failed Attempts
- **Neighbour-spot bearing for offshore_direction** — first approach derived coast tangent from
  bearing between adjacent spots in the N→S list. Fails at Haifa Bay: sparse spots + ~90° coast
  bend → the spot-to-spot vector cuts across the bay mouth (bat-galim came out 168°). Replaced
  with OSM coastline shore-normal.
- **Coastline nearest-segment, inverse-distance weighted** — over-favours a 3m marina/jetty
  segment (tel-baruch 157°, herzliya-marina 57°). Fixed with length-weighted average over a
  ~600–1300m window so short man-made features get outvoted.
- **Flex `align-items:baseline` for the header dot** — empty flex-item baseline synthesis put the
  dot mid-height, not on the text baseline. Switched to inline-block + `vertical-align:baseline`.
- **Flex `gap` on `.brand`** — spaced "rosa" from its accent dot ("rosa ."). Wrapped word+dot in
  a sub-span so gap only separates mark from word.
- Coastline averaging still can't resolve true headlands/peninsulas (Carmel tip, Akko) — those 4
  spots left flagged for local knowledge (not a fixable-by-geometry problem).

## Next Step
1. **Pin the 4 flagged angles** once the user gives correct offshore_direction for akko-argaman,
   kiryat-yam, bat-galim, backdoor-haifa — edit israel.yaml, `run --all`, `cd web && npm run deploy`.
2. **Start the algorithm improvements** in `rosa-forecast-improvements.md` (build order: #1+#2+#3
   first — they target Med windswell and unlock the rest). FIRST concrete move: a ~10-min probe of
   what spectral/directional-spread fields Open-Meteo Marine + NOAA GFS-Wave actually expose —
   that decides how far #2 (spectral bands, "missed swell" fix) and #3 (directional-spread quality
   term) can go before touching code. #1 = GEBCO shoaling+refraction in transform.py (replaces the
   single height_coeff; needs a bathymetry ray per spot + dispersion relation).
3. Watch item: #5 in the report notes the current `q(T)=clamp((T/10)^1.4,…)` may double-count
   period once #1 (physics-based) lands — fold period into the energy/shoaling path, don't stack.
