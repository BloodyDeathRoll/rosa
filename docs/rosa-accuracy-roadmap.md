# Rosa Accuracy Roadmap - the most accurate free surf forecast

*Supersedes `rosa-forecast-improvements.md` as the actionable plan (that file stays as the
Surfline-methodology source study). This is the full, staged path to a complete solution - not
a quick pass. It keeps every CLAUDE.md non-negotiable (precompute-static, free, legal red lines)
and is explicit about where we **keep**, **join**, or **replace** what we've already built.*

---

## 1. What "accuracy" means here (and why we measure before we build)

"Most accurate" is not a claim - it is a **number we drive down over time**. A surf forecast is a
chain, and the output is only as accurate as its weakest link:

```
offshore wave field  →  propagation to nearshore  →  nearshore transform  →  break quality  →  rating
 (global wave model)     (grid → spot's approach)   (shoal/refract/break)   (wind/tide/spot)   (0-100)
```

We measure accuracy at two points in that chain:

1. **Physical skill** - forecast vs. buoy observations (NDBC `.spec`/`.swdir`, CDIP, ISRAMAR for
   validation only). Metrics per variable (Hs, Tp, peak direction, and - once we have spectra -
   directional spread): **bias, RMSE, scatter index, directional error**. This scores links 1-3.
2. **Surfer-perceived skill** - the rating and height-phrase vs. what a human saw (in-app 👍👎 +
   the calibration log in `docs/CALIBRATION.md`). This scores links 4-5, which no buoy can.

**Every stage below has acceptance criteria stated in these metrics.** A change ships only if it
moves the number the right way on the backtest. That discipline - not any single model - is what
makes the forecast "the most accurate."

Where Rosa is today (baseline to beat): offshore = Open-Meteo's blended 3-partition + windsea
readout; propagation = none (grid-cell value at an offshore point); transform = a single per-spot
`height_coeff` × period-quality `q(T)`; quality = wind class + hard swell-window arc; **no tide in
the rating, no spectra, no directional spread, no confidence, no bathymetry, no verification loop.**

---

## 2. Source strategy - keep, join, replace

| Link | Today | Target | Decision |
|------|-------|--------|----------|
| Offshore field (primary) | **DONE 2026-08-26:** GFS-Wave partitions + GFS/ECMWF 50/50 totals (`blend.py`), worldwide; Open-Meteo is the `--wave-source om` fallback | Raw **NOAA WW3 / GFS-Wave** partitioned + **2-D spectra**; **ECMWF open-data** WAM | **Replaced** as primary everywhere (product decision, CALIBRATION.md 2026-08-26); Open-Meteo is the global fallback arm |
| Offshore field (ensemble) | none | Multi-model spread (GFS-Wave, ECMWF, MeteoFrance-WAM, ICON-EWAM) + GEFS-Wave | **Join** - new confidence axis |
| Weather (wind/temp/pressure) | Open-Meteo Weather | Open-Meteo Weather (+ ensemble for wind confidence) | **Keep** - it's good and cheap; no reason to replace |
| Bathymetry | none | **EMODnet** (~115 m, Med/Europe) + **GEBCO 2024** (~450 m, global fallback) | **New** - the missing link that makes physics possible |
| Nearshore transform | `height_coeff` constant | Analytic shoaling+refraction ray (Stage 2) → nested **SWAN/WW3** model (Stage 4) | **Replace** `height_coeff`; keep a small residual correction term |
| Tides | not wired to rating | **EOT20** harmonics via pyTMD (CC-BY) + per-spot ideal-tide window | **New / activate** |
| Validation truth | none | **NDBC** (500+ directional-spectra buoys), **CDIP**, **ISRAMAR** (validation only, partnership pending) | **New** - the backbone |
| Rating formula | v1 (size/period/wind + wind-gate) | Recalibrated over all new axes (spread, consistency, tide, confidence) | **Evolve**, not scrap - v1 stays the fallback |

**Guiding rule for join-vs-replace:** replace a component only when the backtest shows the
replacement beats it on buoy skill or user 👍👎. Until then the old path stays as the fallback, so
we never regress a region while improving another.

---

## 3. Architectural decisions (the non-negotiables still hold)

- **Precompute-static stays absolute.** No request-time forecast backend, ever. Every stage - even
  running SWAN - happens in the scheduled pipeline; the output is still static per-spot JSON +
  map frames on the CDN. What grows is the *precompute box*, never the serving model.
- **The raw-grid migration lives behind the existing `ForecastSource` interface** (`fetch.py`).
  CLAUDE.md already designed for this ("Open-Meteo → raw-grid migration touches one module"). New
  sources become new `ForecastSource` implementations; `extract`/`transform`/`score` stay pure and
  fixture-tested. Spectra flow as a richer `RawForecast`, not a schema rewrite everywhere.
- **Compute-budget reality.** Raw GRIB (GB-scale/run) and a nested SWAN run exceed a stock GitHub
  Actions runner (6 h / 7 GB). The precompute moves to a **scheduled cheap VM or self-hosted
  runner** (spot instance, runs minutes-~1 h, 4×/day → cents/day). Still free to *users*; still
  static serving. This is the one new operating cost and it is small - flagged per stage.
- **Region-by-region rollout.** Fine bathymetry + nearshore model land per region behind a
  capability flag. A spot without a fine model transparently falls back to the analytic transform,
  and a spot without that falls back to Open-Meteo. Accuracy improves in waves, never all-or-nothing.
- **Everything attributed, nothing scraped.** NOAA/ECMWF/EMODnet/GEBCO/EOT20 are open with
  attribution; ISRAMAR stays validation-only until partnership; no competitor data ever. §8 tracks it.
- **Always consider scale - separate the read-path from the write-path.** Forecast serving stays
  static/CDN and gets *cheaper per user* as it grows; dynamic per-user/community data (accounts,
  alerts, feedback, contributed spots) is what earns a managed database. Never cross the two. This
  is a standing design lens for every addition - full posture in §9.

---

## 4. The staged plan

Each stage is independently shippable, measured against Stage 0's harness, and ordered so
dependencies come first and the biggest early accuracy per unit effort lands soonest.

### Stage 0 - Verification & calibration harness *(measure first - unlocks everything)* - ✅ BUILT (2026-07-22/23)
*Status: `verify` (nowcast + `--archive` lead-time), `archive`, `feedback`, NDBC registry all
live; the archive accumulates 4×/day on the Oracle VM (seeded with the retired GH-Actions rows,
2026-07-23). First multi-region sweep logged in CALIBRATION.md (OM hot in the Pacific).
Remaining: let the archive mature (~1 week), then the backtest scorecard becomes meaningful.*
**Accuracy lever:** none directly; makes every later lever *provable*. Do not skip.
- Ingest buoy observations near spots: **NDBC** realtime `.spec`/`.swdir`/`.txt` (Hs, Tp, Dir,
  directional spread), **CDIP**, and **ISRAMAR** (Hadera/Ashdod - validation only, never shipped).
- Build a **backtest**: replay captured forecasts against buoy truth → bias, RMSE, scatter index,
  directional error per variable, per lead-time, per spot. Store as a versioned scorecard.
- Wire the in-app **👍/👎 "was this accurate?"** (CLAUDE.md v0.2 item) into `docs/CALIBRATION.md`
  as structured rows, joined to the same scorecard.
- Output: a one-command `rosa-pipeline verify` that prints the current skill scorecard.

**Acceptance:** baseline scorecard exists for all Israel spots with a nearby buoy; every subsequent
stage's PR includes a before/after scorecard diff. *(This is the gate for calling anything "more accurate.")*
**Effort:** M · **Compute:** trivial · **Data:** NDBC/CDIP open; ISRAMAR validation-only.

### Stage 1 - Multi-model boundary + confidence + peak period *(cheap offshore win, still Open-Meteo)*
**Accuracy lever:** better boundary condition + honest uncertainty; no infra change.
- Fetch multiple wave models via Open-Meteo (`ncep_gfswave016`, `ewam`, `gwam`, `meteofrance_wave`)
  and weather ensemble (`gfs`, `ecmwf_ifs`, `icon`, `gem`) - all confirmed available.
- **Confidence score (#7)** = inverse of normalized multi-model spread in Hs/Tp/Dir per timestep;
  shown for days 0-9, degraded/flagged for the GFS-Wave-only day 10-16 tail.
- **Bias-correct** the offshore field where a buoy is close (learned offset from Stage 0).
- Add **peak period** fields (`*_peak_period`) - surf-relevant; we only fetch mean today.
- Display model name + run + confidence (CLAUDE.md principle #3 - already required, now real).

**Acceptance:** offshore Hs/Tp scatter index drops vs. Stage 0 baseline where a buoy exists;
confidence correlates with observed error (high confidence ⇒ lower error).
**Effort:** M · **Compute:** low (a few more API calls) · **Data:** Open-Meteo, free non-commercial.

### Stage 2 - Spot-transform overhaul: bathymetry physics + tide + soft exposure *(the biggest transform win)* - ✅ MOSTLY DONE (2026-07-22; see docs/rosa-stage2-plan.md)
*Status: 2A bathy profiles, 2B hybrid physics breaker (q(T) reframed as capped
`period_rideability`, NOT fully retired until Stage 3), 2C soft window, 2D tide (Open-Meteo
`sea_level_height_msl`, NOT EOT20 - approach changed) all DONE. 2E recalibration OPEN -
blocked on Stage-0 archive maturity.*
**Accuracy lever:** replaces the single `height_coeff` with real physics; activates tide worldwide.
This is where a spot's *own coastline* finally shapes its forecast.
- **Bathymetry ingest:** EMODnet (~115 m, Med/Europe) with GEBCO 2024 (~450 m) global fallback;
  per-spot depth profile along the swell-approach ray (reuse the OSM shore-normal already computed).
- **Analytic nearshore transform (#1, #5):** per partition, from period → celerity/group velocity
  via the dispersion relation, apply shoaling `Ks = √(Cg_off/Cg_near)`, refraction (Snell) `Kr`,
  and depth-limited breaking `H_break ≈ min(shoaled H, 0.78·depth)`. **Retire `q(T)`** - period now
  enters once, physically, through Cg (kills the double-count flagged in improvements #5). Keep a
  small per-spot residual coefficient for sandbar-scale error GEBCO/EMODnet can't resolve.
- **Soft exposure window (#8):** replace the hard swell-window arc with a cosine-power angular
  response centered on the spot's optimal direction - falls straight out of the refraction math.
- **Tide (#4):** EOT20 harmonics via pyTMD precomputed per spot; feed tide height/stage into
  `H_break` (breaking depth) and add a per-spot **ideal-tide-window** multiplier. Gate by tidal
  range (EOT20 gives it) so it barely moves micro-tidal Med ratings but drives Atlantic/Pacific spots.
- **Recalibrate** height + rating over the new transform against Stage 0.

**Acceptance:** breaker-height bias/RMSE vs. buoy-derived + eye observations beats the
`height_coeff` baseline across spots (not just the one it was tuned on); tide term measurably
improves skill at a macro-tidal test spot without harming Med spots.
**Effort:** L · **Compute:** medium (bathy preprocessing per spot, one-time) · **Data:** EMODnet
(attribution), GEBCO (open), EOT20 (CC-BY). *Per-spot ideal-tide window needs local input - crowd/observe.*

### Stage 3 - Raw spectral migration: kill "missed swell," add spread & consistency *(the offshore ceiling)*
**Accuracy lever:** the offshore input Open-Meteo can't give - full energy distribution. This is the
Mediterranean short-period-windswell fix Surfline said it invested most in, and it's impossible on
the current API (directional spread is not exposed - verified).
- **New `ForecastSource`:** raw **NOAA WW3 / GFS-Wave** partitioned fields + **2-D frequency-
  direction spectra** (NOMADS/AWS open buckets) via `xarray` + `cfgrib`; **ECMWF open-data** WAM as
  a second member. Behind the existing interface - `extract`/`transform`/`score` largely unchanged.
- **True in-window energy integration (#2):** integrate spectral energy over the spot's directional
  window instead of sorting into 3 partitions - no more dropping a real low-period peak.
- **Directional spread quality term (#3):** per-band spread → a cleanliness axis independent of
  height; narrow = organized groundswell, wide = messy windsea. Modulates the quality rating.
- **Set-consistency metric (#6):** from spectral bandwidth/grouping, a separate 0-100 "setty vs.
  lully" number - shown, **not** folded into the rating (kept orthogonal, like Surfline).
- Validate spread/consistency directly against NDBC `.swdir` directional spectra from Stage 0.

**Acceptance:** windswell height/period skill in the Med improves vs. Stage 2; the "missed swell"
failure mode (real low-period energy absent from the readout) no longer reproduces on backtest;
directional-spread error vs. NDBC is bounded.
**Effort:** XL · **Compute:** high - GRIB download + spectral processing; **moves precompute to the
scheduled VM/self-hosted runner.** · **Data:** NOAA (open), ECMWF open-data (open, attribution).

### Stage 4 - Nested nearshore spectral model *(the accuracy ceiling - Surfline-LOTUS class)*
**Accuracy lever:** the true nearshore transform. The analytic ray (Stage 2) is a good
approximation; a real spectral model on fine bathymetry is what actually separates a great forecast
from a good one - this is what LOTUS/LOLA is.
- Run **SWAN** (open-source, Delft) or **WW3 unstructured** nested per region, forced at the
  boundary by Stage-3 spectra, propagating over EMODnet/GEBCO bathymetry with wind input.
- Replaces the analytic transform where a fine model exists; analytic ray remains the fallback for
  un-modeled regions. Output is still static: per-spot nearshore spectra → the same JSON.
- Rolled out **region by region**, highest-traffic coasts first; each region validated on Stage 0
  before it goes live.

**Acceptance:** in a modeled region, nearshore Hs/Tp/Dir skill beats the Stage-2 analytic transform
on buoy validation; no regression where the model isn't yet run (fallback intact).
**Effort:** XL (per region) · **Compute:** high - SWAN runs on the VM/runner; bounded by keeping
grids regional and coarse-nested. · **Data:** SWAN/WW3 free; bathymetry as above.

### Stage 5 - Full rating recalibration, worldwide rollout & ongoing ops *(make it complete, keep it honest)*
**Accuracy lever:** integrate every axis into one coherent, recalibrated rating; scale globally;
keep accuracy improving after launch.
- Recalibrate the **0-100 rating** over all axes now available (physical height, period, wind,
  directional spread, consistency, tide window, confidence) against the full Stage-0 corpus - the
  public "why this rating" formula updated to match (CLAUDE.md principle #3).
- **Sea-breeze / thermal-wind refinement** and gust/lull from the weather ensemble (coastal wind is
  a top error source and is cheap to improve once the harness can score it).
- **Worldwide spot DB scale-up** on the ODbL open dataset (CLAUDE.md spot-DB strategy) - each new
  region inherits the full physics stack + fallbacks automatically.
- **Continuous ops:** the Stage-0 scorecard runs every cycle; drift alerts; the 👍👎 stream keeps
  feeding calibration. Accuracy becomes a monitored, published metric - the transparency moat.

**Acceptance:** the composite rating agrees with user 👍👎 above a target rate across regions and
seasons; the published skill scorecard is stable or improving cycle over cycle.
**Effort:** L, then continuous · **Compute:** as Stage 3-4 steady-state · **Data:** all above.

---

## 5. Dependency & sequencing summary

```
Stage 0 (measure) ──┬─> Stage 1 (multi-model + confidence)         [Open-Meteo, cheap]
                    ├─> Stage 2 (bathymetry physics + tide + soft window)  [replaces height_coeff]
                    └─> Stage 3 (raw spectra: missed-swell, spread, consistency)  [heavy infra]
                                     └─> Stage 4 (nested SWAN/WW3 nearshore)  [ceiling, per region]
                                                    └─> Stage 5 (recalibrate + worldwide + ops)
```
Stages 1 and 2 can proceed in parallel (independent links). Stage 3 unlocks the spread/consistency
axes Stage 5 recalibrates over. Stage 4 depends on Stage 3's boundary spectra. **For the current
Med/Israel calibration region, Stages 2 + 3 deliver the most** (windswell + nearshore physics);
tide (Stage 2) and Stage 4 pay off most as the app goes worldwide.

## 6. Compute & cost reality (kept honest)

- Stages 0-2: fit inside GitHub Actions cron - no new cost.
- Stages 3-4: exceed a stock runner → **scheduled cheap VM or self-hosted runner**, 4×/day, minutes
  to ~1 h/run → cents/day. Users still pay nothing; serving is still static CDN. This is the only
  new operating expense and it is small and bounded. Regional grids keep SWAN tractable.

**Scheduling host - LIVE 2026-07-23: Oracle VM `rosa-instance` (x86_64, il-jerusalem-1).**
ARM A1.Flex capacity never materialized (Frankfurt grabber retired); the x86 box runs the whole
cycle via **cron 4×/day → `deploy/oracle/publish.sh`** (git pull → buoy archive → `run --all` →
prebuilt Vercel deploy to the `rosa-data` project). The persistent disk holds the archive
(seeded with the retired GH-Actions rows). **GitHub Actions and systemd variants were removed -
the VM cron is the single scheduler** (see deploy/oracle/README.md). Watch-item for Stages 3-4:
the x86 free shape is small (~1 GB RAM) - heavy GRIB/SWAN work may need a bigger box or a
self-hosted runner when those stages start.

## 7. Open spikes (resolve at each stage's kickoff, don't front-load)

1. Exact NOAA product for 2-D spectra vs. partitioned GRIB (grid coverage over the Med; NOMADS vs.
   AWS open-data bucket; refresh cadence) - Stage 3 spike.
2. ECMWF open-data wave-spectra availability in the free tier (params + resolution) - Stage 3 spike.
3. EMODnet Med tile resolution/coverage at the exact Israel spots vs. GEBCO - Stage 2 spike.
4. SWAN vs. WW3-unstructured for regional nesting on the target runner (build, runtime, grid size) -
   Stage 4 spike.
5. Buoy coverage per region for validation - NDBC is sparse in the Med; ISRAMAR is validation-only
   and needs a partnership for anything shipped. Confirm truth sources per region - Stage 0 spike.

## 8. Legal / attribution checklist (per CLAUDE.md red lines)

- **NOAA** (WW3/GFS-Wave/GEFS-Wave/NDBC): open, no restriction. ✅
- **ECMWF open data**: open, attribution. ✅
- **EMODnet Bathymetry**: open, attribution required. ✅
- **GEBCO**: open. ✅
- **EOT20**: CC-BY, attribution. ✅
- **SWAN / WAVEWATCH III**: open-source models. ✅
- **Open-Meteo**: *data* is CC-BY-4.0 (commercial OK, attribution), but the *free API service* is
  **non-commercial** - a subscription or ads on Rosa would require a paid plan or self-hosting.
  Stage 3's migration to raw NOAA (public domain) + ECMWF (CC-BY-4.0) removes this constraint
  entirely and makes the stack commercial-clean. Keep Open-Meteo for weather-only until then. ⚠️
- **ISRAMAR**: all-rights-reserved - **manual validation only**; pursue partnership before any
  integration. Never shipped. 🚫→🤝
- **Never**: Surfline API/spots/cams/guide text, or any scraped third-party cam. 🚫

---

## 9. Scale posture - always consider scale

*Standing direction: every addition is judged against "what does this do at 10,000 spots and
100,000 users?" The answer is not one store - it's **splitting the system by access pattern**.
Scale pulls the two halves in opposite directions, so treat them as two planes.*

### The read-path (forecasts) - static gets *stronger* at scale, not weaker
Forecast JSON, map frames, spot pages: **read-heavy, identical for every viewer, precomputed.**
A CDN serving static files is the *ideal* shape for this - it scales to millions of readers at
~zero marginal cost, no rate limit, global edge latency. Putting forecasts behind a database at
scale would be strictly worse: request-time compute, egress/query cost per read, a bottleneck to
shard, and **it's exactly what would make Rosa stop being free.** So scale does not weaken the
precompute-static rule - it is the *reason* for it. Worldwide just means *more files* (10k spots ≈
10k small JSON + a precomputed spatial-index tile set for "spots near me"); files scale flat.

### The write-path (users + community) - this is where a database earns its place
Static files genuinely *cannot* do the things "thousands of users" implies, and no amount of
precompute fixes that. These are dynamic, per-user, authenticated, write-ish:
- accounts + favorites **synced across devices** (localStorage only covers one anonymous device)
- **alert subscriptions** ("notify me when Beit Yanai hits GOOD") + push tokens
- the **👍👎 accuracy feedback** stream (feeds the Stage-0 calibration loop)
- **community spot contributions** + edits + moderation (the long-term spot-DB moat)

This plane wants a managed **Postgres + Auth**, and **Supabase is a sensible default pick** -
Postgres + **PostGIS** (geo "nearby spots" at 10k+ scale), Row-Level Security, Auth, Realtime, and
Edge Functions, with a free tier and nothing to run. It fits the lean/free ethos *precisely because
it stays off the forecast read-path* - it serves the (far lower-volume) user-write traffic only.

### The worldwide spot catalog - DB as source-of-truth, compiled to static for serving
At 40 hand-authored YAML spots, files are fine. At 10k+ contributed, moderated, geo-queried,
versioned spots the catalog is a *writable dataset* → **Postgres/PostGIS is the source of truth**,
and the pipeline **compiles it to static `index.json` + spatial tiles** at build time. Best of both:
DB where you write and query, static where the world reads.

### The verification/forecast archive - object storage, *not* a transactional DB
The archive (roadmap Stage 0) is append-only time-series, internal, low-QPS analytics. It does
**not** belong in Supabase - it belongs in **object storage as Parquet/JSONL + DuckDB** for cheap,
flat-scaling time-series queries. (Even if Supabase is adopted for the write-path, the archive stays
in object storage; only the small 👍👎 feedback rows live in the DB.) This reinforces last call:
the durable archive store is an S3-compatible bucket, not a database.

### Data-plane map (the whole system at scale)
| Data | Access pattern | Store at scale |
|------|---------------|----------------|
| Forecast JSON / map frames / spot pages | read-heavy, identical per user, precomputed | **Static files on CDN** - never a DB |
| Spot catalog (worldwide, contributed, geo-queried) | writable + moderated; read via compiled artifact | **Postgres + PostGIS** (Supabase) → compiled to static index/tiles |
| Accounts, favorites-sync, alert subscriptions | per-user, dynamic, authenticated | **Managed DB + Auth** (Supabase) |
| 👍👎 feedback / calibration rows | append, low-QPS, feeds pipeline | Small DB table (Supabase) *or* object storage |
| Verification / forecast archive | append-only time-series, internal analytics | **Object storage (Parquet/JSONL) + DuckDB** - not a transactional DB |
| Precompute (fetch → … → publish, incl. SWAN) | batch, scheduled | GitHub Actions → **scheduled VM/runner** (§6) |

**Verdict on "would Supabase be better?":** yes - as the **write-plane backbone** (auth, user data,
spot catalog, feedback) once the product grows past anonymous single-device use. **No** - for
forecast serving and the archive, where static-CDN and object-storage scale better *and* cheaper.
The principle that keeps Rosa free at scale is not "avoid databases," it's **"never put the
read-path behind one."**

### Free-tier stack (the concrete plan to stay free) - verified 2026-07-21
| Need | Free option | Ceiling / watch-item |
|------|-------------|----------------------|
| Data sources | NOAA (public domain), ECMWF/EMODnet/EOT20/GEBCO (CC-BY), NDBC/CDIP, OSM, SWAN/WW3 | Open-Meteo free tier is non-commercial → Stage 3 raw-NOAA/ECMWF migration is the commercial-clean exit; ECMWF 9 km delivery may carry service charges, 25 km stays free |
| **Read-path serving** (forecast JSON, maps, spot pages) | **Cloudflare Pages (unlimited bandwidth, soft) + R2 (10 GB, $0 egress always)** | Vercel Hobby caps at 100 GB/mo bandwidth - the known scaling wall; Cloudflare is the free migration target, not a paid Vercel plan |
| Basemap tiles | MapLibre + **Protomaps PMTiles self-hosted on R2** (one file, no tile server) | CARTO free tier fine now; self-host before it bites |
| Light pipeline (Stages 0-2) | **GitHub Actions cron** (2,000 min/mo private; unlimited if repo public) | Fine at 4×/day short runs |
| Heavy pipeline (Stages 3-4: GRIB + SWAN) | **Oracle Always Free ARM (now 2 OCPU / 12 GB)** or a **self-hosted runner** (home box) | Oracle *halved* the free ARM tier June 2026 + capacity can be scarce → self-hosted runner is the fallback; keep SWAN grids regional |
| Forecast/verification archive | **R2 as Parquet/JSONL + DuckDB** | 10 GB free covers years (archive self-prunes to scored rollups) |
| **Write-plane** (accounts, favorites-sync, feedback, spot catalog) | **Supabase free** (500 MB DB, 50k MAU, 1 GB storage, 5 GB egress, PostGIS) | Pauses after **7 days inactivity** → a cron keep-alive ping fixes it; 500 MB DB → Pro ($25/mo) only once real user/community data grows |
| Alerts / push | **Web Push (VAPID)** - standards-based, no vendor; alert evaluation runs in the free pipeline | none meaningful |
| Domain | - | the one unavoidable cost (~$10-15/yr) |

**Through-line:** with the Cloudflare ecosystem (Pages + R2 + Workers) + open data + open-source
models, the **read-path is free at essentially any scale** - R2's zero egress is the linchpin, since
egress is what detonates most free tiers. The *only* place Rosa eventually pays is the **write-plane**
(Supabase Pro), and only once it has enough users/community data that paying is proportional - never
for serving forecasts.

---

*Bottom line: the fast wins (Stage 1) are worth taking, but the accuracy the user is asking for
lives in Stages 2-4 - real bathymetry physics and raw spectra - with Stage 0's verification harness
underneath the whole thing so "most accurate" is a measured fact, not a slogan.*
