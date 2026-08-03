# CLAUDE.md — Rosa

Rosa is a **worldwide, mobile-first PWA surf forecast app**: free, lean, fast, shareable. A daily-use tool replacing Surfline for dedicated surfers, minus the bloat and paywall.

This file is **current truth only**. History lives in `docs/SESSIONS.md` (session log) and `docs/CALIBRATION.md` (why every constant moved). Live machine state lives in `handoff.md`. Product plan: `docs/rosa-build-plan.md`; competitor teardown: `docs/rosa-surfline-teardown.md`.

## Non-negotiable principles
1. Every screen answers "should I surf, when, where?" — cut anything that doesn't.
2. **Precompute everything, serve static.** Pipeline runs on schedule → per-spot JSON + map frames on CDN. No request-time forecast backend, ever. This is what keeps the app free.
3. Always display model name, run timestamp, and confidence. Rating formula is public ("why this rating" in-app) — transparency vs. Surfline's black box is a core differentiator.
4. Mobile-first, dark-first, < 2 s first load on 4G, forecast readable in a 20-second pre-dawn check. Installable PWA, offline-cache last forecast.
5. Every forecast state and swell animation has a shareable URL + auto share card.

## Legal red lines
- NEVER fetch, proxy, or reproduce Surfline API output, spot guide text, cams, or their spot database. The teardown is for structural understanding only.
- NEVER scrape third-party camera streams (any provider). Cams enter Rosa only as officially embeddable/permitted public streams (per-spot `cam_url`) or via partnerships.
- ISRAMAR (isramar.ocean.org.il) is all-rights-reserved: manual validation during calibration only; partnership before any integration.
- Open-Meteo: free tier non-commercial, attribution required (in footer); re-verify before public launch. CMEMS/Copernicus: free with registration, attribution required.
- Free to build on: NOAA (WW3/GFS/OISST/NDBC/CO-OPS), ECMWF open data, EOT20 tides (CC-BY), GEBCO, OSM.

## Architecture
```
pipeline/ (Python 3.11+, uv)              web/ (Vite + Preact PWA, TS strict)
  fetch    → Open-Meteo Marine+Weather      MapLibre GL for maps
             + gwam (Tp only) + ECMWF       Static hosting: Vercel
             + GFS-Wave (archive/A-B)       Reads /data/spots/{id}.json via VITE_DATA_BASE
  extract  → sample at derived offshore_point (+ tide via sea_level_height_msl)
  transform→ spread exposure; hybrid physics breaker
  score    → rating 0-100 → bucket
  publish  → data/out/spots/{id}.json (~5 KB), index.json, share-card data
```
Frontend never computes forecasts; it renders pipeline JSON. Keep the fetch layer behind an interface so a raw-grid migration touches one module.

**Scheduler:** Oracle VM `rosa-instance`, cron 4×/day (02:20/08:20/14:20/20:20 UTC) → `deploy/oracle/publish.sh` = git pull → buoy archive → `run --all` → prebuilt Vercel deploy of `data/out` to the separate `rosa-data` project. **NO GitHub Actions, NO systemd.** See `deploy/oracle/README.md`. `rosa-backup` VM runs an hourly freshness watchdog (pages if `fetched_at` > 8 h). Crash alerts go to the admin push snapshot, never the public list.

**RULE: inspect live infra before designing for it.**

## Algorithm specs (implement exactly, unit-test all)

**Wind classification.** θ = smallest angle between wind *source* direction and `offshore_direction`. θ ≤ 45° → Offshore; 45–135° → Cross-shore; > 135° → Onshore.

**Swell energy in window.** Per partition with direction inside `swell_window`: E += H² × T. Partitions outside contribute 0 to score but still display.

**Rating v1 (0–100).** size 0–40 (ramp of transformed height vs spot `ideal.size_m`, peak inside range, taper above) + period 0–20 (linear 6 s → 0 pts, 14 s → 20 pts, dominant in-window partition) + wind 0–40 (offshore ≤ 15 kph = 40; scales down with speed and angle; onshore ≥ 25 kph = 0). **Wind gate:** wind points scale by `min(1, (size_pts + period_pts)/60)` — offshore wind polishes waves that exist, it never creates rating alone. Day-strip `rating_max` uses daylight hours only (dawn–dusk via astral). Buckets: 0-9 FLAT, 10-29 POOR, 30-49 FAIR, 50-69 GOOD, 70+ FIRING.

**Breaker height — hybrid physics.** Per in-window partition, march the spot's committed depth profile (`data/spots/derived/bathy/{id}.json`): dispersion → shoaling `Ks` → Snell refraction `Kr` → depth-limited breaking at γ=0.78·d (tide added to breaking depth). **The profile runs out before the wave breaks in 97–100% of published hours** — close that last stretch with the Komar & Gaughan (1972) breaker index `Hb = 0.39 g^0.2 (T H0'^2)^0.4` (`breaker_height_komar_gaughan`; H0 de-shoaled first via `deep_water_equivalent`, refraction iterated to breaking depth). Then multiply by `period_rideability` — power-based, **capped at 1.0, attenuates only** (naive physics over-calls short-period Med windswell ~3×). Then combine partitions **by wave field — never RMS** (see below).
- **Field combine.** `field_coherence(Δdir, spread_a, spread_b)` = `cos²` taper, 1.0 at zero separation → 0 once Δdir reaches the sum of the two partitions' own spreads. Coherent partitions add their energy in `Hb^2.5` (`FIELD_ENERGY_EXP`, the exact inverse of K&G's 0.4 exponent, so the sum *is* "add offshore energy, apply the index once"); partitions past that arc taper toward the dominant one alone. **`sqrt(Σ Hb²)` was wrong twice over** — it ran the sublinear index (`Hb ~ H0^0.8`) once per partition, so N small partitions beat the one sea they are, and it merged trains crossing at 55° into a single bigger wave. Cost Santa Teresa 1.0–1.8 m vs Surfline 0.6–1.1 (2026-08-03). A single in-window partition is bit-identical to the old path, so the Israel eye frames are untouched. The taper must stay **smooth**: a hard threshold jitters the published height 0.18 m on a 3° direction wander.
- `period_rideability` keys on the partition's **PEAK** period (`rideability_period()`; mean only as a no-Tp fallback). `RIDEABILITY_EXP = 2.2`.
- Because rideability saturates above ~10 s, the exponent is in practice an **Israel/Portugal knob**; the breaker-index closure is a **long-period-region correction**. They separate cleanly.
- **Never append invented shallow samples** to a profile — the answer becomes γ × whatever depth was made up.
- Display as range h±20%, snapped to 0.1 m, widened to a real ≥0.1 m spread ("0.1–0.1" isn't a range).
- Tune γ / rideability exponent / residual coeff from `docs/CALIBRATION.md` + the Stage-0 scorecard only. **`height_coeff` is 1.0 at all 199 spots.**
- No-profile fallback only: `q(T) = clamp((T/10)^1.4, 0.3, 1.2)` (`PERIOD_EXP`).

**Spread-aware exposure.** A partition is not one bearing — its energy fans over ±20–35° (`spectral.parametric_spread_deg`, CDIP-tuned; `SPREAD_LONG_SWELL_DEG` 24). `spread_exposure()` integrates the soft window (flat 1.0 inside `swell_window`, cosine taper to 0 over a 25° shoulder, `EXPOSURE_SHOULDER_DEG`) over that fan and returns the ENERGY fraction reaching the spot (amplitude = sqrt). The incidence fed to refraction is `arriving_direction()` — the window edge the energy comes in over, not the fan's mean — capped at `GRAZING_INCIDENCE_DEG` (85°) so windows reaching past the shore normal are honoured, not cancelled. Energy/kJ uses the same exposure as the height, so a row can't show surf beside 0 kJ.

> **Invariant:** a metre offshore can never read ~0 at the spot *when it arrives from a direction the coastline can see*. Any zero-audit must also require an in-window partition, or it re-flags lee shores forever.

**Peak period source.** `best_match` resolves to `meteofrance_wave`, which serves **no** Tp. `gwam` (DWD global WAM) rides the same marine request as a **Tp-only** source (`fetch.TP_MODEL`, ~7.3-day coverage) — it must never become the horizon tail. Coverage ~25–40% per region; secondary/tertiary partitions have none (the API has no such variable).

**Display ≠ scoring — deliberate, do not "fix" by unifying.** All swell readouts show the **PEAK** period `peak_period ?? period` (surf-report convention, and what the kJ column derives from). `h_break`'s rideability factor also keys on peak. Still on the **MEAN** period: the dispersion/shoaling/refraction march inside `breaker_height_over_profile`, and `period_score` (the rating's Period component + the web's Period bar). Disclosed to users at `#/about/reading` — **keep it in sync**.

**Human phrase** (h_break midpoint): <0.3 shin-high · 0.3–0.5 knee · 0.5–0.8 waist · 0.8–1.2 chest · 1.2–1.5 head-high · 1.5–2 overhead · 2–3 well overhead · >3 double-overhead+.
**Wetsuit** (from SST): >24° rashguard · 19–24 spring/2 mm · 17–19 3/2 · 14–17 4/3 · 12–14 5/4+boots · 9–12 5/4 hooded+gloves · <9 6/5 hooded.

**Swell-event detection.** A contiguous ≥12 h window where in-window energy ≥ 2× trailing 48 h median and rating ≥ GOOD at peak. Emit `{start, peak, end, peak_height, direction}`.

**Tides.** Open-Meteo Marine `sea_level_height_msl` (MeteoFrance SMOC, ~8 km hourly) — **total** water level (astronomical + surge). Feeds the breaking depth (`d_break = profile_depth + tide`) and publishes as a per-hour series. Med spots micro-tidal (~0.15 m, sparkline only); macro-tidal spots (Costa Rica ~1.5–2 m) genuinely move the forecast.

**Sun.** `astral`; show first light / sunrise / sunset / last light.

**`closure`** (`transform.partition_closure`, per-hour payload key) = partition RMS ÷ Open-Meteo's own total `wave_height`. **Diagnostic only — nothing scores on it.** A low ratio says energy is missing but not its direction or period, and inventing those is against the premise. **Do NOT scale partitions to close it** — a confidence penalty is the honest option. Fleet by region: israel 1.00 · japan 0.97 · philippines 0.96 · nicaragua/hawaii 0.95 · portugal/costa-rica 0.94 · california 0.91 · sri-lanka 0.90.

## Spot database
`data/spots/*.yaml`, one file per region — **199 spots: israel 42, costa-rica 25, sri-lanka 32, japan 24, portugal 42, nicaragua 15, philippines 16, california 2, hawaii 1** — plus committed depth profiles in `data/spots/derived/bathy/`, one per spot, no gaps and no orphans (`test_committed_bathy_profiles_match_their_spots` enforces both). **Keep these counts current: any spot added/removed updates this line AND `test_loads_israel_seed`'s assertion — no approval needed.**

- **Three angles describe the same coastline and are guard-tested against each other**: `shore_normal` aims the depth ray the physics marches, `offshore_bearing` aims the sample point, `offshore_direction` is where OFFSHORE WIND blows from. (A spot whose ray disagreed by 102° marched swell up a hillside and read 0.0–0.1 m all day.)
- **A spot's `lat`/`lon` is the ONLY place its location is written down.** `offshore_point` is derived, never stored (aim it with pin-relative `offshore_km` + `offshore_bearing`); the absolute field now raises.
- **Bathymetry follows the pin.** Move a spot → its profile is stale → delete it and re-cut (`rosa-pipeline bathy --spot <id>`). Remove a spot → its profile is deleted. Never leave an unused profile behind. Profiles record the `origin` pin they were cast from so staleness is detectable.
- **`swell_window` can be DERIVED**: `rosa-pipeline horizon --spot <id>` fans rays over 360° off GEBCO and returns the contiguous open-ocean arc containing the shore normal, clipped to ±90°. **It reports and never applies** (same rule as the cam tool). Thresholds, in order: `HORIZON_MIN_BLOCKER_KM` 1.0 (ignore land the source can't resolve), `HORIZON_LAND_M` 3.0, `HORIZON_DEEP_M` -20. **The ordering test — open water BEFORE land — is load-bearing and must not be dropped.**
- **Adoption rule:** adopt a derived window where the YAML window excludes its own shore normal (an objective fault) or where the height moves <10%; HOLD otherwise. 183/199 adopted 2026-08-02.
- **A derived window is an UPPER BOUND on exposure** — the scan measures ocean visibility at ~450 m, so it cannot see a headland sheltering the break at 50–200 m, nor swell wrapping around a point.
- **Coordinate authority ladder:** user-verified > sat-verified (`tools/spot-verify/`, `docs/spot-mapping-approach.md`) > OSM features (ODbL) > google-geocoded > approximation. Each spot is tagged with its source. **Local knowledge always wins; treat every user pin correction as authoritative.** OSM beach polygons ≠ surf spots.
- **Geocoding:** Google **legacy** Places textsearch — the project key is restricted to legacy APIs, so `tools/spot-verify/geocode.py` tries Places API (New) and falls back. Geocoding/Elevation/Static Maps are NOT enabled. Nominatim/Photon benchmarked far worse on surf POIs (>100 km misses) — don't switch without re-benchmarking. Google returns the named POI, not the peak: seed or flag with it, never overwrite a verified pin.
- This DB is the long-term moat: design every addition to be community-contributable. **Never import competitor spot data.**

## UI (web/)
**Design system: "warm clay"** — warm cream/clay tokens, Inter (@fontsource-variable), light + dark themes (dark default), FIRING displays as **"Epic"**. All hexes confined to the two theme blocks in `styles.css`; tier colors only in the condition layer. Roomy and cozy, generous spacing, no decorative borders on cards. (`docs/rosa-conditions-color-system.md` is the older zine system — HISTORICAL, do not implement from it.)

Shell: **Today | Spots | Map | Profile**.
- **Today** — region chips + `planToday()` (chips from where you are + favorites + the ONE last-viewed spot; ≥5 spots per region; anchor leads; payloads load per region).
- **Map** — full-bleed MapLibre + viewport-synced card carousel (cards are exactly the spots visible on the map, minus those under the sheet), screen-space clustering with tier-blend rings, focused-spot surf-pill dot, search overlaid on the live map, locate + rotating-north fabs. Lazy-loaded, excluded from PWA precache; CARTO raster basemaps by theme (attribution required).
- **Spot page** — one-row header, DayScrubber (date label over that day's 3 bars, one draggable track, leftmost = selected, live re-render on scrub, bars condense on scroll), rating card, hourly grid (wind in knots), TideSection from the real per-hour series, "Other nearby spots" strip.
- All date strips anchor to the spot's real today via `todayIn(tz)` and drop past days.

**DESIGN RULE: swell events surface ONLY as push notifications.** The forecast itself is the in-app surface. Do not rebuild event banners, cards, or alert strips — they were built and killed on review.

**Push.** One swell = ONE notification: same region + peaks ≤12 h + dirs ≤45° cluster into a single push named for the best favorited spot "+N more"; sent-state carries ±1-day peak-drift tolerance; browser tag is a 2nd dedup layer. Notification tap deep-links `#/spot/{id}?ev=YYYY-MM-DD`. Opt-out must be clear and failures surfaced, never silent. iOS needs A2HS + a user gesture.

**Feedback ask is two steps:** "Surfed X?" ✓/✗ first, thumbs only on yes. Selection never crosses regions (the device sends its nearest spot id, never coordinates).

Data-point glossary lives in `AboutPage.tsx` → `ReadingTheForecast` (`#/about/reading`) — **keep in sync when a displayed field changes.**

## Conventions
- Python: uv, ruff, pytest; type hints everywhere; pipeline stages pure functions (input → output, no hidden state) so fixtures test everything offline.
- TS strict; Preact if bundle size threatened; no UI framework bloat; PWA via vite-plugin-pwa.
- Fixtures: `pipeline/tests/fixtures/` holds captured responses so tests never need network.
- Commits small, conventional (feat:/fix:/data:). Data outputs are build artifacts — never committed.
- Vercel Git integration stays **DISCONNECTED**; deploys are CLI-only (forecast data is gitignored, so a Git-triggered build ships a dataless app).

## Calibration method
Log every dogfood session in `docs/CALIBRATION.md`: date/time, spot, Rosa predicted height+rating, observed reality (user's eyes), buoy reading if available. Adjust from the accumulated log, never a single session. Hard-won method rules:

- **A skill metric that cannot show sign cannot show a bias** — always publish bias alongside rmse.
- **Score candidates with the shipped harness, never a scratchpad reimplementation** (the harness grades the predicted MIDPOINT, not the displayed range).
- **Fleet impact is only valid as a same-input A/B** — comparing against an older `data/out` snapshot mixes the code change with the weather.
- **Any cross-source claim needs a control group + a deep-water check.** Three comparison artifacts have been caught this way (APD-vs-Tm-1,0, blended `mwd`, OM's partition closure).
- **Pair periods like-for-like:** Open-Meteo serves the energy period Tm-1,0, NDBC's APD is Tm02, and Tm-1,0 > Tm02 always. Stations without spectra fall back loudly and are never calibrated against.
- **Hs bias tracks the instrument, not the basin** — discus buoys read the model hot, CDIP Waveriders cold; 51201 vs 51202/51205 are the same ocean with opposite signs. No global de-bias is defensible; keep station classes apart.
- **`match on direction and period, never partition slot index`** — partition order is not comparable across providers.
- **Partition direction wander is CLOSED — do not build temporal smoothing.** The transform is order-independent. If ever revisited: partition *tracking* for display order only, never a filter on the directions the physics consumes.
- **`verify --resolve --apply` IS NOT SAFE unattended** — it takes a channel's first live stream with no check it shows the same beach. Always diff old vs new cam TITLE; same title = same camera.

## Open items
1. **The K&G closure still rests on ONE long-period eye frame** (santa-teresa 2026-08-02) plus five Med frames. It over-shot on 2026-08-03 and the field-combine fix pulled it back (×0.93 fleet, ×0.76 at santa-teresa); the closure itself was never re-graded. Grade more frames in a long-period region and re-check santa-teresa across several days.
1b. **Noon at santa-teresa is still above Surfline's band** (1.22 vs 0.6–1.1) and no combination rule can reach it — its single dominant partition transforms to 1.2 m alone. Index-level, +0.12 m, not chased.
1c. **`physics.py`'s march/index handoff has a real discontinuity** — the depth-limited branch and the K&G branch disagree, so a shallow profile steps 1.167 → 1.303 m between 13° and 14° of incidence. Invisible today (real GEBCO profiles bottom out at 7–13 m so 97–100% of hours take the index branch), but it will bite on an unusually shallow profile.
2. `playa-cocles` derived window is NARROW-flagged and needs eyes. Held windows: calicoan-abcd, zavial, kodomonokuni (large movers); pavones, panga-drops, miura (shore normal genuinely blocked — inside gulfs).
3. The 07-19 flat frame is over by +0.15 m under every candidate. Now looks **structural**, not tunable — a breaker index assumes something that breaks as a wave; that frame is a 0.60 m 5.05 s windsea observed ankle-high.
4. Not analysed, would move the rating fleet-wide: should `period_score` and the shoaling march follow rideability onto Tp?
5. Not actionable yet: OM/ECMWF's shared ~+16° clockwise direction bias is measured on total-sea `mwd`, but `spread_exposure()` eats per-partition directions. Needs a per-partition measurement first.
6. Product call nobody has made: **should a blown-out sea read smaller?** Surfline's height appears to absorb wind; ours puts wind in the rating only.
7. Local knowledge needed: ingrina's window ends at 220° while neighbouring zavial reaches 260°; matapalo-osa/okanda/peanut-farm sit 65–73° between wind direction and coastline; `tide_best` unfilled; a chigasaki cam replacement (nearest official is 平塚海岸 `62_twW5uXd4`, ~6 km west); `hagolshim` has always pointed at a stream ~5 km south.
8. Then Stage 4 on `rosa-arm`; worldwide spot-DB scale-up (ODbL seed) after calibration.
9. Housekeeping: 4 orphan payloads in `data/out/spots/` from spots removed 2026-07-23; 79 ruff findings in `tools/` + `deploy/` (untested scripts — needs a deliberate pass).

## Doc precedence
CLAUDE.md and `data/spots/*.yaml` are authoritative. `docs/SESSIONS.md` and `docs/CALIBRATION.md` are history and rationale; other `docs/` are historical context. **When docs disagree, stop and reconcile before implementing.**

Append a section to `docs/SESSIONS.md` at the end of every working session, and update §Open items here when the open list actually changes.
