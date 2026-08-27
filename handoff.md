# Session Handoff — 2026-08-27 (sessions 38-40)

## Goal
Three things landed: the basemap moved off CARTO, five regions were seeded (DB 469 -> 601),
and the pb_0049 wind-sea A/B was read and the fix merged.

## Current State
- **Working tree carries sessions 38, 39 and 40** — none of it was committed until the end
  of session 40. `windsea-dedup` merged to `main`.
- **Spot DB = 601 spots.** morocco 42, angola 9 (session 38); peru 49, panama 23,
  el-salvador 23->32 (session 39). Every pin rendered at z16 and judged; every move
  re-rendered and re-read. Bathy + EOT20 committed for all 132 new spots.
- **501 tests green, ruff clean, `npm run build` clean.**
- **pb_0049 is CLOSED.** `blend.drop_duplicate_windsea()` is on `main`. Full A/B table in
  `docs/CALIBRATION.md` 2026-08-27; the residual is OPEN-ITEMS 22.
- **Basemap is OpenFreeMap** (keyless vector), not CARTO — CARTO started stamping
  "API KEY REQUIRED" over every free raster tile.

## Not yet verified on the CDN
The next cron cycle (20:20Z) is the **first** carrying BOTH the de-dup fix and 601 spots.
After it lands, check from the CDN — never by burning local quota:
- `index.json` lists 601 spots.
- A Peru spot (`chicama`) and a Panama Caribbean spot (`playa-bluff`) both publish.
- `closure` on `poleg` for a 2026-08-30-ish hour is ~1.0, not ~1.43.
- The run's `implausible break` warn count did not jump.

## Active Files
- `pipeline/src/rosa_pipeline/tide.py` — new `TideConstants.matches_spot()`.
- `pipeline/tests/test_spots.py` — new `test_committed_tide_constants_match_their_spots`.
- `tools/spot-seed/ca_final.py`, `emit_region.py` — de-Californianised (see below).
- `data/spots/{peru,panama,morocco,angola}.yaml`, `el-salvador.yaml`.
- VM `~/ab-dedup.sh`, `~/abdiff.py` — the A/B runner and diff tool, scratch on the VM.

## What changed in the seeding tools (all general, not one-off)
- `ca_final.py` reads its skip list from `work/<region>/skip.json` instead of a hardcoded
  California dict, and **a rename now re-slugs the id**.
- `emit_region.py`: **a hand town override outranks OSM**, it no longer only fills a null.
  OSM's nearest place node was wrong 11 times in 81 spots.
- Re-aiming a bad shore normal: **sweep bearings against the local GEBCO grid and take the
  mid of the widest unobstructed arc.** Faster and reproducible; this is the default now.

## Failed Attempts / traps
- The pipeline entry point is **`rosa-pipeline`**, not `rosa`. `uv run --project pipeline
  rosa bathy` fails with "Failed to spawn" and a loop around it silently writes nothing.
- **Run `bathy` from the repo root** or `--out` resolves cwd-relative into `pipeline/data/`.
- **A stale `work/<region>/geocode.json` from an earlier session will fool a file-watcher.**
  El Salvador's was 12 days old with 21 rows against the 12 queued.
- Google collapses distinct spot names onto one coordinate — three names on the Paunch pin,
  two on Venao. **Dedup by coordinate before rendering, not only by name.**
- Do not trust an A/B ETA in a handoff. Read `~/ab-dedup.log` and `pgrep` first.

## Next Step
1. **Confirm the 20:20Z cycle on the CDN** (the checks above). This is the only outstanding
   verification for everything in sessions 38-40.
2. **Re-run the OM-vs-blend A/B** — still owed from the 08-26 promotion, and now doubly so:
   that A/B carried BOTH the peak-period handicap and the wind-sea duplicate, so its
   `+0.115 m` fleet `h_mid` was attributed to source skill and part of it was this bug.
3. **Characterise the residual `closure >1.25`** (OPEN-ITEMS 22): 4.53% of hours over 323
   spots, fleet max unchanged at 7.31. It is a lead, not a defect —
   **do not scale partitions to close it.**
4. More regions: British Columbia (separate pbf), then Indonesia, Australia, Chile,
   France/Spain, South Africa.
5. The 2026-09-17 archive-maturity gate: A4 weight re-fit, `d_ref` (item 15), two-GEBCO
   A/B (item 17).
