# CLAUDE.md — Rosa

Rosa is a **worldwide, mobile-first PWA surf forecast app**: free, lean, fast, shareable. A daily-use tool replacing Surfline for dedicated surfers, minus the bloat and paywall.

## Where the detail lives — read the doc for the area you're touching

| Working on | Read first |
|---|---|
| `pipeline/` — transform, score, physics, spectral, extract | `docs/ALGORITHM.md` |
| `data/spots/`, `tools/spot-verify/`, `bathy` / `horizon` commands | `docs/SPOT-DB.md` |
| `data/stations/`, `stations.py`, `verify --stations --wind-model` (coastal wind truth, GFS vs ICON A/B) | `docs/CALIBRATION.md` 2026-08-29 + 2026-08-30, `docs/OPEN-ITEMS.md` 25 |
| `web/` | `docs/UI.md` |
| Tuning a constant, running a sweep, grading a frame | `docs/CALIBRATION.md` (method rules at top) |
| "What's still open?" | `docs/OPEN-ITEMS.md` |
| "Why is it like this?" | `docs/SESSIONS.md` (session log) |
| Live machine / deploy state | `handoff.md`, `deploy/oracle/README.md` |
| **Where forecast data comes from, what replaces it, scale** | `docs/rosa-accuracy-roadmap.md` (§2 keep/join/replace, §4 stages, §9 scale) · `docs/rosa-stage3-plan.md` · `docs/rosa-fetch-plane-plan.md` (off the OM quota) · `docs/rosa-peak-period-plan.md` (Tp for the blend arm, from DWD GWAM) |
| Product plan · competitor teardown | `docs/rosa-build-plan.md` · `docs/rosa-surfline-teardown.md` |

**Do not re-derive the data-source strategy from first principles.** Stage 3a (raw NOAA GFS-Wave source + dual-source buoy A/B) and Stage 3b (ECMWF spectral-lite) are BUILT — `gfswave.py`, `ecmwf.py`, `verify --archive --source {om,gfswave,ecmwf}`, and a dual-source archive that has been accumulating since 2026-07-23. **Since 2026-08-26 the GFS-Wave+ECMWF blend (`blend.py`) IS the primary wave source, worldwide** - `run --wave-source` defaults to `blend`; `om` is the explicit fallback arm. The promotion was a product decision (`docs/CALIBRATION.md` 2026-08-26): buoys covered 45 of the 265 spots the fleet had when the call was made (2026-08-26; it is 624 now, and the added regions registered no buoys) and never will cover the rest, so a per-region buoy gate was a decision never to scale. Weather stays on Open-Meteo (plan C3, measured); **its 10 m wind model is GFS (`fetch.WEATHER_MODEL`) since 2026-08-30** - ICON (`best_match`) damped the beach wind and the beach was graded by eye (`docs/CALIBRATION.md` 2026-08-30); ICON is still archived at the stations as the A/B member. Do not re-open either without new buoy evidence.

## Non-negotiable principles
1. Every screen answers "should I surf, when, where?" — cut anything that doesn't.
2. **Precompute everything, serve static.** Pipeline runs on schedule → per-spot JSON + map frames on CDN. No request-time forecast backend, ever. This is what keeps the app free.
3. Always display run timestamp and confidence. Rating formula is public ("why this rating" in-app) — transparency vs. Surfline's black box is a core differentiator. **No model name**: the payload is stitched per hour from several models, so one label was wrong on ~40% of rows and nothing rendered it (retired 2026-08-14). Re-introduce it only as per-hour provenance, never as a constant.
4. Mobile-first, dark-first, < 2 s first load on 4G, forecast readable in a 20-second pre-dawn check. Installable PWA, offline-cache last forecast.
5. Every forecast state and swell animation has a shareable URL + auto share card.

## Legal red lines
- NEVER fetch, proxy, or reproduce Surfline API output, spot guide text, cams, or their spot database. The teardown is for structural understanding only.
- NEVER scrape third-party camera streams (any provider). Cams enter Rosa only as officially embeddable/permitted public streams (per-spot `cam_url`) or via partnerships.
- ISRAMAR (isramar.ocean.org.il) is all-rights-reserved: manual validation during calibration only; partnership before any integration.
- Open-Meteo: free tier non-commercial, attribution required (in footer); re-verify before public launch. CMEMS/Copernicus: free with registration, attribution required. **CMEMS coastal SDB** (`sdb.py`, DOI 10.48670/mds-00364): royalty-free, commercial use permitted, attribution required, free of charge only **to 2028-06-30 - re-verify before then**. **ICESat-2 ATL24** (`atl24.py`): NASA CC0, citation requested.
- Free to build on: NOAA (WW3/GFS/OISST/NDBC/CO-OPS), ECMWF open data, EOT20 tides (CC-BY), GEBCO, OSM.

## Standing prohibitions
Each was learned the hard way and each has a rationale in the linked doc. **Do not re-litigate from first principles — read the doc.**

- **Never import competitor spot data.** (`docs/SPOT-DB.md`)
- **Never append invented shallow samples** to a bathy profile — the answer becomes γ × a made-up depth. (`docs/ALGORITHM.md`) Patching a ray point from a *measured* grid (`sdb`) is a source swap, not this — but it moves published heights, so it needs the A/B in OPEN-ITEMS 23 first.
- **Combine partitions by wave field, never `sqrt(Σ Hb²)`.** (`docs/ALGORITHM.md`)
- **Do NOT scale partitions to close `closure`** — it is diagnostic only, nothing scores on it. (`docs/ALGORITHM.md`)
- **Period display ≠ scoring is deliberate — do not "fix" it by unifying.** (`docs/ALGORITHM.md`)
- **Do not build temporal smoothing for partition direction wander** — closed, the transform is order-independent. (`docs/CALIBRATION.md`)
- **The `horizon`, `atl24`, `sdb` and `aim_normal` tools report, never apply.** `sdb --apply` is not safe unattended. (`docs/SPOT-DB.md`) **The cam tool is the exception since 2026-08-28**: `verify --resolve --apply` runs in every publish cycle, because it only ever swaps a dead id for a same-TITLE replacement and its patch is reset before the next `git pull`. Committing the new id is still the durable fix.
- **Swell events surface ONLY as push** — do not rebuild in-app event banners, cards, or alert strips. (`docs/UI.md`)
- **Tune knobs only from `docs/CALIBRATION.md` + the Stage-0 scorecard.** `height_coeff` is 1.0 at all 1947 spots. Fleet impact is only valid as a same-input A/B, scored with the shipped harness.
- **Inspect live infra before designing for it.** A session once built a competing scheduler off a stale handoff while another had already provisioned the box.

## Architecture
```
pipeline/ (Python 3.11+, uv)              web/ (Vite + Preact PWA, TS strict)
  fetch    → GFS-Wave + ECMWF global files   MapLibre GL for maps
             blended 50/50 (blend.py);       Static hosting: Vercel
             weather: Open-Meteo; SST: OISST Reads /data/spots/{id}.json via VITE_DATA_BASE
             (--wave-source om = fallback)
  extract  → sample at derived offshore_point (+ tide from committed EOT20 constants)
  transform→ spread exposure; hybrid physics breaker
  score    → rating 0-100 → bucket
  publish  → data/out/spots/{id}.json (~5 KB), index.json, share-card data
```
Frontend never computes forecasts; it renders pipeline JSON. Keep the fetch layer behind an interface so a raw-grid migration touches one module.

**User plane (since 2026-09-07):** `deploy/user-api/` = Cloudflare Worker + D1 (`rosa-user-api.einhanamer.workers.dev`): Google sign-in (Identity Services in the browser, ID token verified in the Worker), one `users` row per Google `sub` with favorites as a JSON column, `GET /admin/stats` for "how many users". Saving a favorite needs sign-in; the forecast never does. `deploy/push-api/` (Vercel Blob) keeps push subscriptions, contact and feedback. Cloudflare over Supabase on price at scale (per request, not per MAU) - see `deploy/user-api/README.md`; do not re-open.

**Scheduler:** Oracle VM `rosa-arm` (A1.Flex 4 OCPU/24 GB, since 2026-08-30; `rosa-instance` is the idle micro it replaced), cron 4×/day (02:20/08:20/14:20/20:20 UTC) → `deploy/oracle/publish.sh` = git pull → buoy archive → `run --all` → prebuilt Vercel deploy of `data/out` to the separate `rosa-data` project. **NO GitHub Actions, NO systemd.** `rosa-backup` VM runs an hourly freshness watchdog (pages if `fetched_at` > 8 h). Crash alerts go to the admin push snapshot, never the public list.

**Spot DB: 1947 spots** - california 149, hawaii 80, sao-paulo 56, galicia 55, rio-de-janeiro 52, peru 49, santa-catarina 46, canary-islands 45, mexico 43, israel 42, morocco 42, portugal 42, bali 39, oregon 37, cornwall-devon 36, sydney 35, perth 34, sri-lanka 34, bahia 33, el-salvador 32, ceara 31, victoria 30, espirito-santo 29, landes 28, margaret-river 28, byron-bay 26, cadiz 25, costa-rica 25, new-jersey 25, asturias 24, basque-country 24, brittany 24, japan 24, maldives 23, panama 23, cyprus 22, sunshine-coast 22, south-africa-east 21, algeria 20, gold-coast 20, long-island 20, washington 20, cantabria 19, south-australia 19, rio-grande-do-norte 18, french-polynesia 17, tanegashima-amami 17, lombok 16, outer-banks 16, philippines 16, mentawai 15, nicaragua 15, rio-grande-do-sul 14, wales 14, mozambique 13, tasmania 13, east-java 12, florida-space-coast 12, wa-midwest 12, wa-south 12, fiji 11, okinawa 11, rhode-island 11, wa-north 11, mauritius 10, north-east-england 10, angola 9, parana 9, pernambuco 9, sumbawa 9, fernando-de-noronha 8, north-scotland 8, senegal 8, bunbury 7, cape-verde 6, esperance 6, west-java 6, madagascar 5, ghana 3, exmouth 2, zanzibar 2, kenya 1. One committed bathy profile each. Changing the count updates `docs/SPOT-DB.md` AND `test_every_committed_spot_picks_the_same_oisst_cell_as_before` - no approval needed.

## Conventions
- Python: uv, ruff, pytest; type hints everywhere; pipeline stages pure functions (input → output, no hidden state) so fixtures test everything offline.
- TS strict; Preact if bundle size threatened; no UI framework bloat; PWA via vite-plugin-pwa.
- Fixtures: `pipeline/tests/fixtures/` holds captured responses so tests never need network.
- Commits small, conventional (feat:/fix:/data:). Data outputs are build artifacts — never committed.
- Vercel Git integration stays **DISCONNECTED**; deploys are CLI-only (forecast data is gitignored, so a Git-triggered build ships a dataless app).

## Doc precedence
CLAUDE.md and `data/spots/*.yaml` are authoritative. The area docs above are current spec — **including `docs/rosa-accuracy-roadmap.md` and the stage plans, which are LIVE spec for every stage not yet marked BUILT, not history** (`gfswave.py` cites `rosa-stage3-plan.md` as its live-verified source). `docs/SESSIONS.md` and `docs/CALIBRATION.md` are history and rationale; the remaining `docs/` are historical context. **When docs disagree, stop and reconcile before implementing.**

At the end of every working session: append to `docs/SESSIONS.md`, and update `docs/OPEN-ITEMS.md` if the open list moved.
