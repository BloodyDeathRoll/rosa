# Session Handoff - 2026-07-26

## Goal
Big infra + product day: get the A1 (Stage-4 box), build the Stage-2E calibration
harness and SWAN scaffolding while archives mature, and ship SwellMap v0.2 - a
Surfline-style Charts tab with animated basin wave fields for every region.

## Current State
- **All committed, pushed, deployed.** Working tree clean at `6bc0761`. Web live on
  rosa-rust.vercel.app; six basin frame-sets live on rosa-data-opal (/data/swellmap/).
  257 pipeline tests green, ruff clean.
- **rosa-arm is RUNNING**: A1.Flex 4 OCPU/24 GB, public 82.70.253.255, private
  10.0.0.35, Jerusalem AD-1 - launched first try after the Israeli tenancy upgraded
  to PAYG (2,834 free-tier attempts had failed; it was deprioritisation, not missing
  hardware). Quota policy `rosa-free-tier-cap` (A1 4/24 + 200GB storage) is ACTIVE on
  BOTH tenancies and verified binding (`effective-quota-value: 4`); usage sits at
  exactly 4/4 + 24/24 → $0, nothing more can provision. Frankfurt + Jerusalem A1
  watchers all stopped. SWAN 41.51 built on it (`~/bin/swan-omp.exe`, OpenMP; MPI
  deliberately not built - switch.pl emits a serial binary); smoke + Israel-grid
  synthetic run verified (Haifa-bay sheltering reproduced, 3 s wall).
- **Charts tab live**: 5th tab (Today|Spots|Map|Charts|Profile). Basin chips
  (All regions + 6), four charts from one payload (Height/Period/Energy/Wind),
  play/scrub timeline, per-variable single-hue themed ramps, GFS-Wave run attribution.
  Map tab is spot-finding only again (in-map layer removed by user direction).
- **SwellMap pipeline**: `rosa-pipeline swellmap` in publish.sh (non-fatal step);
  frames regenerate 4x/day. Wind rides in the same GRIBs (zero extra requests).
- **Stage-2E harness built and run** (`rosa-pipeline experiment`): Tp-keyed
  rideability fixes both Hilton under-calls and holds the windswell frame, but every
  Tp/Te candidate over-calls the 07-19 flat frame; NO candidate passes all 4; no
  knob moved. Logged in docs/CALIBRATION.md. 07-26 Hilton entry added (~2x under-call
  on a small day, first data point on the corrected pin).
- Hilton/Gordon moved to user-verified pins, bugrashov removed (Israel 41, total 192);
  bathy = 192/192 profiles, origin-stamped, guard test enforces no orphans/stale;
  `offshore_point` absolute field removed (pin-relative offshore_bearing/km).
- Web UX shipped today: launch always lands on Today; region section labels
  (home region first, A-Z; Spots A-Z; chip persisted); swipeable extended-card
  carousel on Today; auto-reload on SW update; install prompt (Chromium dialog,
  iOS-Safari + Firefox-Android instructions); dark manifest background; cam embed
  stripped to play bar; offshore swell height shown under the surf range (bolder).

## Active Files
- `pipeline/src/rosa_pipeline/swellmap.py` - basin frame fetch/quantize/publish.
- `pipeline/src/rosa_pipeline/experiment.py` + `data/calibration/frames.yaml` - 2E harness.
- `pipeline/src/rosa_pipeline/transform.py` - `rideability` injection hook (prod default unchanged).
- `web/src/pages/ChartsPage.tsx` - the Charts tab (multi-basin canvas renderer).
- `web/src/pages/TodayPage.tsx` - card carousel; `web/src/components/GroupChips.tsx` - sectionsOf.
- `deploy/oracle/setup-arm.sh` - rosa-arm provisioning (idempotent, self-verifying).
- `data/swan/israel/` + `tools/swan-grid/build_grid.py` - SWAN Israel grid + deck.
- `docs/CALIBRATION.md` - 07-26 Hilton entry + 2E harness first-run entry.

## Changes Made This Session
1. PAYG upgrade path: quotas FIRST (compute-core/compute-memory/block-storage
   families - plain `compute` is invalid), orphan 47GB boot volume deleted, then
   upgrade, then `oci compute instance launch` worked immediately. Boot volume min
   is 50GB (47 rejected).
2. SwellMap: basins derived from spot DB extents (+3 deg pad); u8 quantization
   (0.1m/2deg/0.2s/0.25m/s, 255=missing); one JSON per basin (~30-70KB gz);
   client-side colormap (dataviz method: single-hue sequential, no rainbow -
   also keeps distance from ISRAMAR's all-rights-reserved imagery).
3. Charts tab per user direction ("Map = locating spots"); Energy derived
   client-side (0.49*H^2*Te, Te=0.9*Tp); arrows follow variable (wind vs swell dir).
4. Western-hemisphere fix: grib-filter returns 0-360 lons → Portugal/CA payloads
   carried lon_first ~347 → MapLibre drew a world-copy off-screen. Fixed canonical
   in pipeline + normalize-on-load in client (covers already-published files).
5. "All regions" chip stitches all basins, aligned by frame timestamp, one shared
   scale per variable.
6. Memory rules saved: "commit" = commit+push+DEPLOY unless told otherwise;
   spot-DB hygiene (bathy follows the pin, counts self-update).

## Failed Attempts
- **JSON frames die at global scale**: 1-deg world = 65k cells x 5 fields x 57
  frames ≈ 28MB/cycle. Do NOT try to extend the current JSON format to a world
  chart - it needs PNG-channel encoding (see Next Step).
- **SSH-wrapped long VM jobs get orphaned**: my `timeout 1500 ssh ...` killed the
  connection mid-generation; the remote chain survived but would have died on
  SIGPIPE at its next print, and index.json was never written. Always run long VM
  work detached with a log (`nohup setsid ~/script.sh > log 2>&1`), as
  `~/swellmap-finish.sh` on rosa-instance now models.
- **pgrep/pkill -f self-matching bit twice** (killed own script; false "cycle
  running"). Use `pgrep -f "[p]attern"` bracket trick.
- **SWAN `make mpi` silently produces a serial binary** (switch.pl doesn't enable
  MPI paths); `make clean` wipes macros.inc so platform.pl+config must rerun before
  every target. OpenMP is the correct mode on one box anyway.
- **`.env.production` bakes VITE_DATA_BASE into every `vite build`** - local
  layer tests must build with `VITE_DATA_BASE=` (empty) or they silently hit live
  rosa-data and 404.
- 2E: no single rideability-key/exponent candidate satisfies all 4 eye frames -
  input de-bias (archive half of 2E) is the missing term; do not hand-fit.

## Next Step
**Global world chart (user-requested, spec'd, not started):** encode each frame's
quantized fields into PNG channels (pure zlib, no new dep) - 1-deg world frame
≈ 15-40KB PNG; client fetches frames lazily while scrubbing, decodes via offscreen
canvas, colormaps as today. Pipeline: `swellmap --global` fetching global 0.25
subsampled to 1 deg (~200MB/cycle from NOMADS on the VM - acceptable). Add a
"World" chip in ChartsPage. Start in `swellmap.py` + `ChartsPage.tsx`.

Then:
1. ~07-30 archives mature → Stage 2E: de-bias inputs (verify --archive per region),
   re-run `rosa-pipeline experiment`, require all 4 frames + no buoy regression.
   Also the 3a A/B + 3-way ECMWF verdicts.
2. Watch the 20:20Z+ cron cycles: publish.sh now runs swellmap - confirm
   `publish.log` stays clean and frames refresh (`index.json` run timestamp).
3. Backlog: Period bar rescale (min(1,per/9)→~/13 in SpotPage DayBars); 11 bay
   spots want hand-drawn map arrows (fishermen worst: derived 78 vs osm 258, 6/9
   land samples); pressure overlay would need GFS atmospheric - optional.
4. rosa-arm next real work: Stage-4 region grid forced by Stage-3 spectra
   (gated on 3b acceptance); `deploy/oracle/setup-arm.sh` reprovisions from scratch.
