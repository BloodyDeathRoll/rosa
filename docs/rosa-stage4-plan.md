# Stage 4 Plan - Nested nearshore SWAN, Southern California Bight pilot

> Implementation plan for accuracy-roadmap Stage 4 (`docs/rosa-accuracy-roadmap.md` §4),
> authored 2026-09-14. Mirrors the Stage-2/3 plan format. Nothing here is BUILT beyond the
> scaffolding listed in §1; every step is gated by a Stage-0 scorecard diff, same as the
> earlier stages. Live infra was inspected before writing (rosa-arm, 2026-09-14).

**Goal:** replace the *propagation* link (offshore grid node -> nearshore) with a real
spectral model over fine bathymetry, one region at a time, behind a per-region flag. The
breaker march (`physics.surf_height_over_profile`) stays as the last-stretch transform and as
the fallback everywhere the model does not run. Output JSON is unchanged; serving stays static.

**Why the SoCal Bight first:** 89 of California's 149 spots sit south of Point Conception; the
Channel Islands shadow the bight in a way a single ray per spot cannot represent, so it is
where SWAN should show the largest measurable gain; and CDIP runs a dense Waverider network
inside it, so the verdict comes from buoys, not eyes. (CALIBRATION.md: keep CDIP Waverider and
NDBC discus classes apart when scoring.)

---

## 1. What already exists (2026-09-14, verified on the box)

- **SWAN 41.51** built on `rosa-arm` (`~/bin/swan-omp.exe`, `~/bin/swan-ser.exe`, built by
  `~/setup-arm.sh`). A synthetic Israel proof run (`~/swan/israel/INPUT`: 1.5 m / 8 s / W
  JONSWAP on the west edge, 5 m/s wind, stationary, 120 x 170 cells at 0.01 deg) converged in
  3 iterations and tabled Hs/Tp/Dir at 41 Israeli points. Not a forecast.
- **`tools/swan-grid/build_grid.py`** cuts `bot.grd` / `points.loc` / `meta.json` for a region
  box from GEBCO via OpenTopoData (~450 m source, ~1 km grid). Israel constants hard-coded.
- **Boundary reality (Stage 3 plan §2):** no free 2-D spectra exist for download - NOAA
  `spec_tar` is dead, ECMWF open data has none. GFS-Wave 0.25 gives 3 swell partitions +
  windsea at every grid node (`gfswave.py`); that is the boundary source.
- **Wind over the grid:** `gfsatmos.py` already fetches GFS 0.25 10 m wind by box and step
  (plan C3b) - the same shape SWAN needs for `INPGRID WIND`.
- **Box budget:** the publish cycle takes 3.5-4.3 h of each 6 h slot (publish.log,
  2026-09-13/14), so about 2 h is free. SWAN must fit inside that or the cycle overlaps.
- **Buoys registered in the bight:** only 46218 Harvest and 46225 Torrey Pines
  (`data/buoys/cdip.yaml`). Everything else in the bight is unregistered.

## 2. Steps

### 4.0 - Register bight buoys + baseline *(1 day + ~1 week of archive)*
- Add the CDIP Waveriders inside the bight (Oceanside, Santa Monica Bay, San Pedro, Long
  Beach, San Nicolas, Anacapa, Mission Bay and the rest) to `data/buoys/cdip.yaml`. **Ids and
  coordinates come from NDBC's live station list, never from memory.**
- Let the archive run so `verify --archive` has a march scorecard at those stations before
  anything else moves. This is the number Stage 4 has to beat.

### 4.1 - Bathymetry *(2-3 days)* - ✅ BUILT 2026-09-14
- `tools/swan-grid/build_grid.py <region>` reads `tools/swan-grid/regions/<region>.yaml`
  (source, outer grid, nests, spot selection, handoff depth) and writes
  `data/swan/<region>/{outer,<nest>}/bot.grd` + `meta.json` (IDLA=3) and `points.loc` /
  `points.json`. Sources: `crm` (NCEI THREDDS NetCDF subset service, netCDF-3 read by scipy)
  and `gebco-local`. Every grid is a **block mean** of the source cells inside each target
  cell, never a nearest pick. Native cuts cache under `data/swan/<region>/src/` (gitignored).
- SoCal: outer 401x271 at 0.01 deg (32.0-34.7 N, 121-117 W) from **CRM SoCal v2 3 arc-second**;
  five nests at 0.002 deg (~200 m) from **CRM SoCal v2 1 arc-second** (~30 m): santa-barbara,
  ventura, los-angeles, orange-county, san-diego. 3.1 MB committed. **CUDEM is not available
  here**: the 1/9 arc-second tiles cover California only from Monterey Bay north (checked
  2026-09-14), so the CRM 1as is the finest public-domain seabed in the bight.
- Handoff points: the first cell at or past 15 m **walking the spot's ray on the finest built
  grid** (100 m steps), not the GEBCO profile - the profile put lunada-bay in 90 m at 0.25 km
  where the 1as nest reads 5 m. All 89 bight spots land inside a nest, 0.3-4.9 km out,
  median 1.1 km.
- Side finding: 14 bight profiles crossed land past 0.25 km. Three were objective faults
  and were re-aimed with `aim_normal` + re-cut (`bathy`, `tide`): mission-beach 353 -> 255
  (the ray ran north over Mission Bay to La Jolla canyon), redondo-breakwater 190 -> 260,
  lunada-bay 151 -> 220. The other 11 are land only at 0.5 km (a GEBCO cell straddling the
  waterline) - spot-DB watch items, not touched.

### 4.2 - Boundary from our own feed *(3-4 days)*
- Along the outer grid's west, north and south edges, take the GFS-Wave node values already
  fetched by `gfswave.py` (3 swell partitions + windsea: Hs, Tp, dir per partition) and rebuild
  a 2-D spectrum per node per step: JONSWAP in frequency x cos-power in direction per
  partition, summed. Write SWAN `.sp2` boundary files per forecast step.
- Wind: `INPGRID WIND` from the `gfsatmos.py` box fetch at the same steps.
- No new data source and no new quota - both feeds are already in the cycle.

### 4.3 - Grid + runtime spike *(2-3 days, on rosa-arm)*
- Outer ~1 km grid, Point Conception to Ensenada, seaward past San Nicolas Island; 100-200 m
  nests at the spot clusters. Stationary run per 3 h step, days 0-7 (57 steps) first.
- Measure wall time with 4 OpenMP threads. **Budget: under 60 min per cycle**, or it does not
  fit. Fallbacks in order: 2 km outer + nests; days 0-5 only. Days 8-15 stay on the march
  regardless.
- Record convergence (the Israel scaffold needed 3 iterations at 98 %) and the failure mode
  when a step does not converge - a missing step must fall back to the march, never publish
  a blank.

### 4.4 - Plumbing *(3-4 days)*
- New `NearshoreSource` behind a per-region flag in the spot YAML / region config. SWAN
  tables Hs / Tp / Dir / spread at each spot's **output point (~15 m depth on its own ray)**;
  the breaker march then runs from that point inward instead of from the offshore point.
  Region not modelled -> today's path, byte-identical.
- `run --nearshore {march,swan}` and `verify --archive --nearshore {march,swan}` so both arms
  archive side by side from the same inputs (the fleet A/B rule in CLAUDE.md).
- `publish.sh`: SWAN runs after fetch and before the spot loop, inside the cycle lock.
- Payload: no schema change. Per-hour provenance may name the nearshore arm later (principle
  #3 allows per-hour provenance, never a constant model label).

### 4.5 - A/B and gate *(2-3 weeks of archive)*
- Same-input A/B at the bight buoys on the Stage-0 scorecard: bias, RMSE, scatter index,
  direction error for Hs / Tp / Dir, per lead time, CDIP and NDBC scored apart.
- **SWAN ships for the region only if it beats the march on that card.** No knob is moved
  to close a gap; a loss is a finding, and the march keeps publishing.
- On a win: flip the region flag, log the verdict in `docs/CALIBRATION.md`, then the next
  region uses the same recipe (Central California next - Monterey 46042 and SF 46026 are
  already registered).

### 4.6 - Docs
- This file, `docs/OPEN-ITEMS.md` 11, `docs/SESSIONS.md`, `docs/ALGORITHM.md` (the
  propagation link) and `deploy/oracle/README.md` (the SWAN step in the cycle).

## 3. Risks

- **Runtime.** The bight at 1 km may not fit 60 min; the fallbacks above are the answer, not
  a bigger box.
- **The last 15 m.** SWAN hands off at ~15 m depth; sandbar and reef detail inside that
  stays with the march and the committed profile (OPEN-ITEMS 23 for the profile source).
- **Box contention.** Two long jobs on one cron lock - SWAN must live inside `publish.sh`,
  not beside it.
- **Boundary fidelity.** A spectrum rebuilt from 4 parametric partitions is not a measured
  spectrum; the A/B is what says whether it is good enough.

## 4. Effort

Roughly 3 weeks of build (4.0-4.4) plus 2-3 weeks of archive before a verdict (4.5).
