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
- ISRAMAR (isramar.ocean.org.il) data/imagery is all-rights-reserved: use only for manual validation during calibration; pursue partnership before any integration.
- Open-Meteo: free tier is non-commercial, attribution required — fine for a free app, add attribution in footer; re-verify terms before public launch.
- CMEMS/Copernicus: free with registration; attribution required.
- Open data we build on freely: NOAA (WW3/GFS/OISST/NDBC/CO-OPS), ECMWF open data, EOT20 tides (CC-BY), GEBCO, OSM.

## Architecture
```
pipeline/ (Python 3.11+, uv)          web/ (Vite + React/Preact PWA, TS)
  fetch    → Open-Meteo Marine+Weather APIs (v1)   MapLibre GL for maps
             (swap layer later: NOMADS GRIB via     Static hosting (CF Pages/Netlify)
              xarray+cfgrib, ECMWF, CMEMS)          Reads /data/spots/{id}.json
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
- **Rating v1 (0–100)**: size 0–40 (ramp of transformed height vs. spot `ideal.size_m`, peak inside range, taper above), period 0–20 (linear 6 s → 0 pts to 14 s → 20 pts, dominant in-window partition), wind 0–40 (offshore ≤ 15 kph = 40; scale down with speed and with angle; onshore ≥ 25 kph = 0). Buckets: 0–9 FLAT, 10–29 POOR, 30–49 FAIR, 50–69 GOOD, 70+ FIRING.
- **Breaker height v1**: `h_break = swell_H_in_window × height_coeff` (per-spot scalar, default 1.0). Display as range h±20%, snapped to 0.1 m. Nearshore physics (GEBCO refraction) is v2 — don't start it before calibration data exists.
- **Human phrase**: map h_break midpoint → [<0.3 shin-high, 0.3–0.5 knee, 0.5–0.8 waist, 0.8–1.2 chest, 1.2–1.5 head-high, 1.5–2 overhead, 2–3 well overhead, >3 double-overhead+]. Wetsuit from SST: >24° rashguard, 20–24 spring/2 mm, 17–20 3/2, 14–17 4/3, 11–14 5/4+boots, <11 6/5 hooded.
- **Swell-event detection** (feeds alerts + swell stories): a contiguous ≥ 12 h window where in-window energy ≥ 2× trailing 48 h median and rating ≥ GOOD at peak. Emit {start, peak, end, peak_height, direction}.
- **Tides**: EOT20 via pyTMD, harmonics precomputed per spot at build time → cheap runtime evaluation in pipeline. Med spots: micro-tidal, show sparkline only.
- **Sun**: `astral` lib; show first light/sunrise/sunset/last light.

## Spot database
`data/spots/*.yaml` — one file per region. Schema in `data/spots/israel.yaml` (seeded, coordinates need field verification — marked TODO). This DB is the long-term moat: design every addition to be community-contributable. Derive `offshore_direction` from OSM coastline geometry when adding regions in bulk. Never import competitor spot data.

## UI (web/)
Screens, in build order: SpotPage (hero: current card + 7-day 3-hourly collapsible table + tide/sun) → Home (favorites w/ rating chips, localStorage first, near-me via geolocation) → Search → 16-day outlook strip → SwellMap (v0.2: scrubbable animated basin map, frames pre-rendered by pipeline). Rating colors: FLAT gray, POOR amber, FAIR yellow-green, GOOD green, FIRING teal/cyan. Dark default. Surfline's table density is the benchmark — match its information density, drop its chrome/upsells/tabs.

## Conventions
- Python: uv, ruff, pytest; type hints everywhere; pipeline stages pure functions (input → output, no hidden state) so fixtures test everything offline.
- TS strict; Preact if bundle size threatened; no UI framework bloat; PWA via vite-plugin-pwa.
- Fixtures: `pipeline/tests/fixtures/` holds captured Open-Meteo responses so tests never need network.
- Commits small, conventional (feat:/fix:/data:). Data outputs are build artifacts — never committed to main repo.

## Current state & session-1 tasks
Nothing built yet. Repo starts from this kit. Git initialized 2026-07-19 — conventional commits from the very first scaffold commit. Session 1 (in order):
1. `pipeline/`: scaffold uv project; Open-Meteo fetch module (marine + weather, hourly, 16 d) with on-disk fixture capture; transform + score per spec above; unit tests; CLI: `rosa-pipeline run --spot beit-yanai` → writes `data/out/spots/beit-yanai.json`.
2. Run live for all Israel seed spots; eyeball Beit Yanai output vs. surfline.com and isramar.ocean.org.il (manual check only) — record discrepancies in `docs/CALIBRATION.md`.
3. `web/`: Vite PWA scaffold, SpotPage rendering the JSON (current card + forecast table), Home favorites. Deploy preview to CF Pages.
4. GitHub Action: cron pipeline → publish JSON to Pages/bucket.
Stretch: 16-day strip; share-card edge function; swell-event detection wired to JSON output.
Roadmap beyond: `docs/rosa-build-plan.md` §8.
Update this section at the end of every working session before stopping.

## Calibration methodology (ongoing, log in docs/CALIBRATION.md)
For each dogfood session: date/time, spot, Rosa predicted height+rating, observed reality (user's eyes), ISRAMAR/NDBC buoy reading if available. Adjust `height_coeff` and score weights from accumulated log, not single sessions. Add in-app one-tap "was this accurate? 👍👎" early (v0.2) — it feeds the same log.

## General
When docs disagree, stop and reconcile before implementing
For any doc conflict, CLAUDE.md and data/spots/*.yaml are authoritative; docs/ are historical context.