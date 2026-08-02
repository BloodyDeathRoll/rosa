# Session Handoff - 2026-08-02

## Goal
User saw surfers on the Santa Teresa cam putting the face over 1 m against a published
0.5-0.7 m. Chasing that gap found the largest correction to `h_break` the project has made.

## Current State
- Committed and pushed, main at `dde4451`, tree clean apart from this file. **347 tests green**,
  ruff clean, fleet `run --all` clean (199 spots, 0 warnings).
- Web deployed and verified live (`index-CMnE8iKi.js`, new `#/about/reading` text confirmed in
  the served bundle).
- **Forecast data is NOT live yet.** Only the VM writes rosa-data; the **20:20 UTC cycle** is the
  first to carry this work. Until then: new wording, old numbers.
- Santa Teresa now reads 0.9-1.5 m. `height_coeff` still 1.0 at all 199 spots.

## Active Files
- `physics.py` - `breaker_height_komar_gaughan`, `deep_water_equivalent`; the march's fallback
  branch now closes instead of returning a mid-shelf height.
- `transform.py` - `RIDEABILITY_EXP` 1.4 -> 2.2.
- `fetch.py` - `TP_MODEL = "gwam"` in `MARINE_MODELS`; `MARINE_BATCH_SIZE` 90 -> 65.
- `extract.py` - `_merge_models` falls `*_peak_period` through to gwam only.
- `horizon.py` + `test_horizon.py` - NEW, derives `swell_window` from GEBCO ray fans.
- `publish.py` - `prune_index` sweeps the payload dir, not just the index.
- `cli.py` - `rosa-pipeline horizon`. `data/spots/*.yaml` - 183 windows, santa-teresa cam.
- `docs/CALIBRATION.md` (4 entries), `CLAUDE.md` (SESSION 12 + NEXT), `AboutPage.tsx`.

## Changes Made This Session
1. **The march never reached the surf zone.** With no `gamma*d` hit inside the profile it
   returned the most-shoaled height reached - true in **97-100% of published hours** (GEBCO's
   shallowest sample is a median 7 m; a wave needs ~5.5 m to break in-profile). That point is
   inside the shoaling dip with refraction already taken, so waves arrived *smaller* than they
   left (0.69 fleet median vs offshore). Closed with **Komar & Gaughan (1972)**.
2. **`RIDEABILITY_EXP` 1.4 -> 2.2** in the same change: 1.4 had been fitted on top of the
   truncated march. The 5 frames cannot separate 1.8 from 2.2; the fleet can, because rideability
   caps at 1.0 above 10 s, making the exponent an Israel/Portugal knob and the closure a
   long-period correction. Same-input A/B, 24,795 hours: **fleet x1.39**, Israel x1.19.
3. **peak_period was 0.0% outside Israel/Portugal** (`best_match` = `meteofrance_wave`, no Tp).
   `gwam` now rides the same request as a Tp-only source. Safe: Tp feeds rideability and display,
   never the march or `period_score`.
4. **183 of 199 swell windows adopted** from `horizon`. Rule: adopt where the YAML window excludes
   its own shore normal (13 spots, an objective fault - 14 of 199 were in that state) or where the
   height moves <10% (170). Held 16. Window impact alone is **x1.01 median**.
5. **`prune_index` fixed** - drove off index.json only, so 4 payloads orphaned since 2026-07-23
   were invisible to it and shipped in every deploy.

## Failed Attempts
- **"Exponent 2.5 makes all five frames pass" - wrong, withdrawn.** My scratchpad tested whether
  the displayed *range* overlapped; the harness tests whether the *midpoint* sits inside. No
  candidate passes all five, before or after. **Score with the shipped harness, never a
  reimplementation.**
- **First fleet-impact measurement was meaningless** - taken against the 07-30 snapshot, mixing
  the code change with 3 days of weather. Only a same-input A/B is valid.
- **"185 windows disagree, so adopt them" - no.** 39 were narrower than 90 deg, which no open
  beach is. Two threshold faults had to be fixed first: sampling started 0.5 km out, *inside* one
  GEBCO cell of the spot (at `miramar` only +3 vs +4 m decided the window), and -50 m "open water"
  is unreachable on a broad shelf. Now `HORIZON_MIN_BLOCKER_KM` and -20 m.
- **Dropping the ordering test broke santa-teresa** - one +5 m bar cell at 3 km walled off its
  southern sector. **Open-water-BEFORE-land is load-bearing.**
- **Appending invented shallow samples was rejected** - the answer becomes exactly `gamma x` the
  made-up depth.
- **A block-style YAML edit overwrote the wrong spot** (`praia-do-meco`); caught and reverted.
  3 spots are block style: `kugenuma`, `shirahama-izu`, `costa-caparica`.
- **`cd pipeline` then `--project pipeline`** resolved to `pipeline/pipeline`, published nothing.
- **gwam caused two live 429s** - quota weight 4.9 -> 7.3/point broke batch size 90. It degrades
  silently (drops the confidence ensemble), so it would have rotted unseen on the cron. Now 65.

## Next Step
1. **Check the 20:20 UTC cycle** - first run with gwam, batch 65 and the new windows:
   `ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 'grep -E "^=== |FAILED at:|warn:" ~/rosa/publish.log | tail -6'`
   A 429 shows as `warn: open-meteo 429 on the ensemble request` and does not page.
2. **More eye frames in a long-period region.** The x1.39 rests on one such observation plus five
   Med frames. Re-check Santa Teresa over several days; its 1.5-1.7 m hours are least supported.
3. **16 held windows want eyes**: `calicoan-abcd`, `zavial`, `kodomonokuni` (large movers), 10
   NARROW-flagged, and `pavones`/`panga-drops`/`miura` (blocked normal, genuinely in gulfs).
   `playa-cocles` still excludes its own shore normal.
4. `horizon` is blind below ~450 m, so a derived window is an **upper bound on exposure**
   (`arugam-bay` too generous, `pottuvil-point` too tight).
5. Unchanged: de-bias plan stays retired; do not scale partitions to close `closure`; no partition
   temporal smoothing; `verify --resolve --apply` unsafe unattended; the ~+16 deg `mwd` bias needs
   a per-partition measurement first; "should a blown-out sea read smaller?" still unmade.
6. Untouched question: should `period_score` and the shoaling march follow rideability onto Tp?
   Would move the rating fleet-wide. Its own experiment.
