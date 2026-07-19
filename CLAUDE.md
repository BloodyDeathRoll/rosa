# CLAUDE.md — Rosa

Rosa is a **worldwide, mobile-first PWA surf forecast app**: free, lean, fast, shareable. A daily-use tool replacing Surfline for dedicated surfers, minus the bloat and paywall. Full context: `docs/rosa-surfline-teardown.md` (competitor analysis + data schema findings) and `docs/rosa-build-plan.md` (product plan). Read both once before major architectural work; this file alone is enough for routine tasks.

## Non-negotiable principles
1. Every screen answers "should I surf, when, where?" — cut anything that doesn't.
2. **Precompute everything, serve static.** Pipeline runs on schedule → per-spot JSON + map frames on CDN. No request-time forecast backend, ever. This is what keeps the app free.
3. Always display model name, run timestamp, and confidence. Rating formula is public ("why this rating" in-app) — transparency vs. Surfline's black box is a core differentiator.
4. Mobile-first, dark-first, < 2 s first load on 4G, forecast readable in a 20-second pre-dawn check. Installable PWA, offline-cache last forecast.
5. Every forecast state and swell animation has a shareable URL + auto share card.

## Legal red lines
- NEVER fetch, proxy, or reproduce Surfline API output, spot guide text, cams, or their spot database. The teardown is for structural understanding only.
- NEVER scrape third-party camera streams (any provider, not just Surfline). Cams enter Rosa only as officially embeddable/permitted public streams (per-spot `cam_url`, v0.3+) or via partnerships.
- ISRAMAR (isramar.ocean.org.il) data/imagery is all-rights-reserved: use only for manual validation during calibration; pursue partnership before any integration.
- Open-Meteo: free tier is non-commercial, attribution required — fine for a free app, add attribution in footer; re-verify terms before public launch.
- CMEMS/Copernicus: free with registration; attribution required.
- Open data we build on freely: NOAA (WW3/GFS/OISST/NDBC/CO-OPS), ECMWF open data, EOT20 tides (CC-BY), GEBCO, OSM.

## Architecture
```
pipeline/ (Python 3.11+, uv)          web/ (Vite + React/Preact PWA, TS)
  fetch    → Open-Meteo Marine+Weather APIs (v1)   MapLibre GL for maps
             (swap layer later: NOMADS GRIB via     Static hosting: Vercel (user choice
              xarray+cfgrib, ECMWF, CMEMS)          2026-07-19; watch free-tier 100 GB/mo
                                                    bandwidth cap as spots/maps scale)
                                                    Reads /data/spots/{id}.json
  extract  → sample at spot's offshore_point
  transform→ swell-window filter, height_coeff
  score    → rating 0-100 → bucket
  publish  → data/out/spots/{id}.json (~5 KB), index.json, share-card data
Scheduler: GitHub Actions cron 4×/day (per model run) → commit/upload to CDN bucket.
```
Frontend never computes forecasts; it renders pipeline JSON. Keep the fetch layer behind an interface so Open-Meteo → raw-grid migration touches one module.

## Algorithm specs (implement exactly, unit-test all)
- **Wind classification**: θ = smallest angle between wind *source* direction and `offshore_direction` (shore-normal pointing FROM land TO sea... convention: `offshore_direction` = direction offshore wind comes FROM, e.g. Israel coast faces W → offshore wind is E → offshore_direction: 90). θ ≤ 45° → Offshore; 45–135° → Cross-shore; > 135° → Onshore.
- **Swell energy in window**: for each swell partition with direction inside `swell_window`: E += H² × T. Partitions outside window contribute 0 to score but still display.
- **Rating v1 (0–100)**: size 0–40 (ramp of transformed height vs. spot `ideal.size_m`, peak inside range, taper above), period 0–20 (linear 6 s → 0 pts to 14 s → 20 pts, dominant in-window partition), wind 0–40 (offshore ≤ 15 kph = 40; scale down with speed and with angle; onshore ≥ 25 kph = 0). **Wind gate** (calibration fix #1): wind points scale by `min(1, (size_pts + period_pts)/30)` — offshore wind polishes waves that exist, it never creates rating on its own. Day-strip `rating_max` uses daylight hours only (dawn–dusk via astral). Buckets: 0–9 FLAT, 10–29 POOR, 30–49 FAIR, 50–69 GOOD, 70+ FIRING.
- **Breaker height v1** (calibration fix #1): `h_break = sqrt(Σ (Hᵢ × q(Tᵢ))²) × height_coeff` over in-window partitions, with period quality `q(T) = clamp((T/10)², 0.15, 1.2)` (quadratic shape buoy-confirmed, calibration row 1) — short-period windswell breaks far below its offshore height; a constant coefficient can't capture that (`height_coeff` stays per-spot, default 1.0). Display as range h±20%, snapped to 0.1 m. Tune q's shape and the wind-gate denominator from the calibration log only. Nearshore physics (GEBCO refraction) is v2 — don't start it before calibration data exists.
- **Human phrase**: map h_break midpoint → [<0.3 shin-high, 0.3–0.5 knee, 0.5–0.8 waist, 0.8–1.2 chest, 1.2–1.5 head-high, 1.5–2 overhead, 2–3 well overhead, >3 double-overhead+]. Wetsuit from SST: >24° rashguard, 20–24 spring/2 mm, 17–20 3/2, 14–17 4/3, 11–14 5/4+boots, <11 6/5 hooded.
- **Swell-event detection** (feeds alerts + swell stories): a contiguous ≥ 12 h window where in-window energy ≥ 2× trailing 48 h median and rating ≥ GOOD at peak. Emit {start, peak, end, peak_height, direction}.
- **Tides**: EOT20 via pyTMD, harmonics precomputed per spot at build time → cheap runtime evaluation in pipeline. Med spots: micro-tidal, show sparkline only.
- **Sun**: `astral` lib; show first light/sunrise/sunset/last light.

## Spot database
`data/spots/*.yaml` — one file per region. Schema in `data/spots/israel.yaml` (seeded, coordinates need field verification — marked TODO). This DB is the long-term moat: design every addition to be community-contributable. Derive `offshore_direction` from OSM coastline geometry when adding regions in bulk. Never import competitor spot data.

## UI (web/)
Shell: two tabs, **Spots** (default) | **Map**, bottom tab bar; no taglines anywhere. Screens: SpotPage (verdict hero + why-rating + 7-day 3-hourly collapsible table + tide/sun later) · Spots tab (search w/ autocomplete, Favorites, Near-you via geolocation, All spots **sorted north→south — never alphabetical**) · Map tab (MapLibre, lazy-loaded + excluded from PWA precache; OSM raster tiles for now — light-use policy, swap to vector/self-hosted before launch; markers colored by rating; centers on user location, world-zoomable) → 16-day outlook strip → SwellMap v0.2 (scrubbable animated basin map, frames pre-rendered by pipeline). Rating colors: FLAT gray, POOR amber, FAIR yellow-green, GOOD green, FIRING teal/cyan. **Design direction (user, 2026-07-19, supersedes the old "Surfline density benchmark"): roomy and cozy, generous spacing, no decorative borders on cards; dark AND light themes with in-app toggle, dark default.**

## Conventions
- Python: uv, ruff, pytest; type hints everywhere; pipeline stages pure functions (input → output, no hidden state) so fixtures test everything offline.
- TS strict; Preact if bundle size threatened; no UI framework bloat; PWA via vite-plugin-pwa.
- Fixtures: `pipeline/tests/fixtures/` holds captured Open-Meteo responses so tests never need network.
- Commits small, conventional (feat:/fix:/data:). Data outputs are build artifacts — never committed to main repo.

## Current state & session-1 tasks
Git initialized 2026-07-19 (github.com/BloodyDeathRoll/rosa, private) — conventional commits. Session 1 (in order):
1. ✅ DONE (2026-07-19) `pipeline/`: uv project scaffolded; fetch (Open-Meteo marine+weather, 16 d hourly, capture/replay via `--capture`/`--fixtures`) → extract → transform → score → publish; 41 unit tests green (`cd pipeline && uv run pytest`); CLI works: `uv run --project pipeline rosa-pipeline run --spot beit-yanai` (from repo root) → `data/out/spots/beit-yanai.json` + `index.json`. Fixture captured at `pipeline/tests/fixtures/32.2_34.55.json`. Underspecified formula choices (size taper w/ floor 10 @ 2×ideal-hi, wind v_max 40→25 kph by angle, flat gate h<0.15 m) documented in `pipeline/src/rosa_pipeline/score.py` docstring — tune via calibration log only. Wind-wave partition counts toward in-window energy (Med windswell matters); payload ~20 KB raw (2.5 KB gzipped — under the 5 KB target as served). Calibration fix #1 applied same day (see docs/CALIBRATION.md row 1): period-quality height transform, wind gate, daylight-only day max — 53 tests green.
2. ✅ DONE (2026-07-19) Ran all 20 Israel spots live; Beit Yanai eyeballed vs. Surfline + cam + ISRAMAR Hadera buoy → calibration fix #1 (CALIBRATION.md row 1). Learnings baked in: Open-Meteo throttles rapid per-spot fetching → `run --all` fetches once per unique offshore point (3 fetches for 20 spots; the cron job must use this); marine API pads nulls beyond its ~10-day horizon → extract skips null hours, `days` truncates honestly (no fabricated FLAT). Watch item: 2026-07-25 forecast GOOD 55 @ Beit Yanai — verify quadratic q at longer periods when it arrives.
3. ✅ DONE (2026-07-19) `web/`: Vite + Preact PWA (TS strict, no router lib, vite-plugin-pwa; app shell 8.3 KB gz JS + 1.8 KB CSS). SpotPage (verdict hero + why-rating + 7-day 3-hourly collapsible table with per-day color "spine" strips), Home favorites (localStorage). `npm run dev|build` in web/ (sync-data script copies data/out → public/data; both gitignored). Deployed to Vercel (moved off CF Pages same day, user choice; CF project deleted): https://rosa-rust.vercel.app — redeploy: `cd web && npm run deploy` (prebuilt static deploy; cloud builds would break on sync-data's ../data reference). Vercel Git integration is deliberately DISCONNECTED (CLI auto-connected it at project creation; a push then triggered a doomed root-dir cloud build) — deploys are CLI-only, don't reconnect: forecast data is gitignored so Git-triggered builds ship a dataless app. Data ships inside the deploy for now; task 4's cron should publish data separately from app deploys (needs VERCEL_TOKEN secret in GitHub).
4. GitHub Action: cron pipeline → publish JSON to Pages/bucket.
Stretch: 16-day strip; share-card edge function; swell-event detection wired to JSON output.
Roadmap beyond: `docs/rosa-build-plan.md` §8.
Update this section at the end of every working session before stopping.

## Calibration methodology (ongoing, log in docs/CALIBRATION.md)
For each dogfood session: date/time, spot, Rosa predicted height+rating, observed reality (user's eyes), ISRAMAR/NDBC buoy reading if available. Adjust `height_coeff` and score weights from accumulated log, not single sessions. Add in-app one-tap "was this accurate? 👍👎" early (v0.2) — it feeds the same log.

## General
When docs disagree, stop and reconcile before implementing
For any doc conflict, CLAUDE.md and data/spots/*.yaml are authoritative; docs/ are historical context.