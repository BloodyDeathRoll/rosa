# CLAUDE.md — Rosa

Rosa is a **worldwide, mobile-first PWA surf forecast app**: free, lean, fast, shareable. A daily-use tool replacing Surfline for dedicated surfers, minus the bloat and paywall.

## Where the detail lives — read the doc for the area you're touching

| Working on | Read first |
|---|---|
| `pipeline/` — transform, score, physics, spectral, extract | `docs/ALGORITHM.md` |
| `data/spots/`, `tools/spot-verify/`, `bathy` / `horizon` commands | `docs/SPOT-DB.md` |
| `web/` | `docs/UI.md` |
| Tuning a constant, running a sweep, grading a frame | `docs/CALIBRATION.md` (method rules at top) |
| "What's still open?" | `docs/OPEN-ITEMS.md` |
| "Why is it like this?" | `docs/SESSIONS.md` (session log) |
| Live machine / deploy state | `handoff.md`, `deploy/oracle/README.md` |
| Product plan · competitor teardown | `docs/rosa-build-plan.md` · `docs/rosa-surfline-teardown.md` |

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

## Standing prohibitions
Each was learned the hard way and each has a rationale in the linked doc. **Do not re-litigate from first principles — read the doc.**

- **Never import competitor spot data.** (`docs/SPOT-DB.md`)
- **Never append invented shallow samples** to a bathy profile — the answer becomes γ × a made-up depth. (`docs/ALGORITHM.md`)
- **Combine partitions by wave field, never `sqrt(Σ Hb²)`.** (`docs/ALGORITHM.md`)
- **Do NOT scale partitions to close `closure`** — it is diagnostic only, nothing scores on it. (`docs/ALGORITHM.md`)
- **Period display ≠ scoring is deliberate — do not "fix" it by unifying.** (`docs/ALGORITHM.md`)
- **Do not build temporal smoothing for partition direction wander** — closed, the transform is order-independent. (`docs/CALIBRATION.md`)
- **The `horizon` and cam tools report, never apply.** `verify --resolve --apply` is not safe unattended. (`docs/SPOT-DB.md`)
- **Swell events surface ONLY as push** — do not rebuild in-app event banners, cards, or alert strips. (`docs/UI.md`)
- **Tune knobs only from `docs/CALIBRATION.md` + the Stage-0 scorecard.** `height_coeff` is 1.0 at all 199 spots. Fleet impact is only valid as a same-input A/B, scored with the shipped harness.
- **Inspect live infra before designing for it.** A session once built a competing scheduler off a stale handoff while another had already provisioned the box.

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

**Scheduler:** Oracle VM `rosa-instance`, cron 4×/day (02:20/08:20/14:20/20:20 UTC) → `deploy/oracle/publish.sh` = git pull → buoy archive → `run --all` → prebuilt Vercel deploy of `data/out` to the separate `rosa-data` project. **NO GitHub Actions, NO systemd.** `rosa-backup` VM runs an hourly freshness watchdog (pages if `fetched_at` > 8 h). Crash alerts go to the admin push snapshot, never the public list.

**Spot DB: 199 spots** — israel 42, costa-rica 25, sri-lanka 32, japan 24, portugal 42, nicaragua 15, philippines 16, california 2, hawaii 1. One committed bathy profile each. Changing the count updates `docs/SPOT-DB.md` AND `test_loads_israel_seed` — no approval needed.

## Conventions
- Python: uv, ruff, pytest; type hints everywhere; pipeline stages pure functions (input → output, no hidden state) so fixtures test everything offline.
- TS strict; Preact if bundle size threatened; no UI framework bloat; PWA via vite-plugin-pwa.
- Fixtures: `pipeline/tests/fixtures/` holds captured responses so tests never need network.
- Commits small, conventional (feat:/fix:/data:). Data outputs are build artifacts — never committed.
- Vercel Git integration stays **DISCONNECTED**; deploys are CLI-only (forecast data is gitignored, so a Git-triggered build ships a dataless app).

## Doc precedence
CLAUDE.md and `data/spots/*.yaml` are authoritative. The area docs above are current spec. `docs/SESSIONS.md` and `docs/CALIBRATION.md` are history and rationale; other `docs/` are historical context. **When docs disagree, stop and reconcile before implementing.**

At the end of every working session: append to `docs/SESSIONS.md`, and update `docs/OPEN-ITEMS.md` if the open list moved.
