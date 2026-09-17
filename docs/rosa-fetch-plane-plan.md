# Fetch-plane migration plan - off the Open-Meteo quota, one download per cycle

> Authored 2026-08-14 (session 27), from the measurements in `docs/CALIBRATION.md`
> 2026-08-14 and open item 14. Mirrors the Stage-3 plan's format. **Goal:** spot count
> stops costing anyone's API quota. Every input becomes either a global grid downloaded
> once per cycle or a per-spot precompute, so 199 spots and 10,000 spots cost the same
> fetch. This is the missing scale posture for the fetch plane (roadmap §9 covers every
> other plane) and the prerequisite for the worldwide spot-DB scale-up (open item 11).
>
> **Relationship to Stage 3a:** 3a built the raw GFS-Wave source, the GRIB readers and
> the dual-source buoy archive, and its promotion gate ("raw-source skill >= OM at the
> proxy buoys") has correctly stayed shut - a single raw model loses to OM's blend at
> every lead. This plan is what opens it: blend the free global grids ourselves, and
> migrate the non-wave fields 3a deliberately left on Open-Meteo.

## Evidence base (2026-08-14, 15 buoys, shipped harness - do not re-derive)

- **GFS-Wave alone fails the gate**: Hs MAE worse than OM at every lead (0.248 vs
  0.194 m at 0-1d). Promoting a single raw model is off the table.
- **An untuned 50/50 GFS-Wave+ECMWF blend reaches parity on Hs** (worst case -1.6 cm at
  0-1d, ahead across 3-7d) **and wins direction at 5 of 6 leads** (up to -3.9 deg).
- The period comparison from that run is **VOID** (energy-period-vs-APD against
  peak-period-vs-DPD - the like-for-like rule). Re-run before quoting any Tp claim.
- Quota reality, measured: ~8.8 marine-host units per spot per cycle, 65 spots per
  minute bucket; repeated same-day `run --all` passes exhausted the per-IP daily cap
  and a fleet run died at 168/199 (2026-08-14).

## What must stay true throughout

- Precompute-static unchanged; all fetching is scheduled VM work; serving stays CDN.
- `ForecastSource` is the seam (CLAUDE.md's designed swap) - every phase lands behind
  it, fixtures per source, tests offline.
- **pb_0049 gates every promotion**: anything that moves published ratings or
  confidence fleet-wide needs a same-input A/B scored with the shipped harness + a
  CALIBRATION.md entry in the same change. No exceptions for "it's just the source".
- OM remains the fallback until a region's evidence clears, and the code path stays
  (roadmap §2: never regress a region while improving another).
- Legal: NOAA public domain; ECMWF open data CC-BY (attribute in footer); EOT20 CC-BY.
  Completing phases A-C removes the OM non-commercial constraint from the launch path.

---

> **Known handicap in the blend arm, measured 2026-08-16 - read before scoring any A/B.**
> GFS-Wave gridded publishes no PER-PARTITION peak period (`shts/mpts/swdir` and
> `shww/mpww/wvdir` are mean periods; the file's only Tp is `perpw`, the whole sea's), so
> every partition the blend arm produces reaches the transform with `peak_period_s = None`
> and both `rideability_period` and `energy_period` fall back to the mean - the regime
> CALIBRATION.md 2026-07-30 measured as a 1.6-2x under-call, and the reason gwam was added
> to the OM arm at all. Measured cost by stripping Tp from the OM arm over Beit Yanai's real
> profile: 78 of 384 hours move rating, 41 change bucket, worst height ratio 0.44, and the
> effect is one-directional (dropping Tp can only lower the breaker). `BlendedSource` now
> prints the count once per run so an A/B cannot silently attribute this to source skill.
> It is NOT repaired: there is no honest per-partition Tp in the source, and synthesising one
> from `perpw` would move published heights, which is a tuning change.

## Phase A - prove the blend (evidence only, no pipeline changes)

Everything here runs offline against the dual-source archive; the A/B script shape is
in the 2026-08-14 CALIBRATION entry.

- **A1. Valid period comparison.** Score all arms' periods against ONE obs column,
  like-for-like (Tp<->DPD for every arm; OM's Tm-1,0 leg via the spectra-derived
  energy period where the station has spectra).
- **A2. Tuned blend weights**, per lead bucket, fitted on one half of the archive and
  scored on the other. Equal weights are the floor to beat; a tuned weight that loses
  to 50/50 out-of-sample is overfit - keep 50/50.
- **A3. Per-region scorecard.** The acceptance bar is per-region. Break the fleet out
  (US West/East, Hawaii, Portugal; note which regions have NO buoy - Israel, Costa
  Rica, Sri Lanka, Japan, Nicaragua, Philippines) and DECIDE the no-buoy rule:
  promote on pooled-fleet evidence + the 👍👎 feedback stream, or hold OM there.
  Write the decision down in CALIBRATION.md; it is a policy, not a measurement.
  **DECIDED 2026-08-26: promote WORLDWIDE, verify after. See Status.**
- **A4. Equal samples.** The raw arms hold ~6x fewer rows than OM (archive starts
  2026-07-23). Let the dual-source archive mature to >=8 weeks of rows before the
  promotion A/B, or the arms are not the same weather.
- **Acceptance:** blended Hs MAE >= OM's per lead in every buoyed region (within
  noise), direction no worse, a valid Tp story, and the no-buoy policy written.

## Phase B - build the blended wave source

- **B1. Whole-globe fetch mode.** The existing readers fetch per-cluster boxes via
  the grib-filter CGI - request count grows with spot spread. Add a mode that pulls
  the global `gfswave.global.0p25` file per step + the ECMWF wave stream (index-driven
  byte ranges already built in `ecmwf.py`) and samples every spot from the same
  files. Measure first (see D1); fall back to per-basin boxes if the globe doesn't
  fit the VM.
- **B2. `BlendedSource` behind `ForecastSource`.** GRIB partitions (windsea + 3
  swells - the same schema OM exposes, verified in the Stage-3 spike) -> the existing
  partitioned `RawForecast`; blend the two grids per hour with A2's weights; capture/
  replay fixtures like the OM source.
- **B3. The 10-16 day tail.** ECMWF open data stops at ~10 days; past that the blend
  degrades to GFS-Wave alone. Label it honestly (the horizon ceiling already prices
  the tail low; keep the per-hour internal-consistency rule from `_merge_models`).
- **B4. Peak period.** ECMWF `pp1d` replaces the OM `gwam` join globally (already
  fetched; already the Tp source in the ecmwf archive rows).
- **Acceptance:** offline `run --spot` fixture runs bit-stable; the report tests and
  repo suite green; payload diff vs OM reviewed by hand at 3 spots in 3 regions.

## Phase C - the non-wave fields still riding a per-spot OM call

Without this phase, waves migrate and the quota ceiling REMAINS (weather+SST+tide are
the same per-spot request family). Order: easiest first, each independently shippable.

- **C1. Tide -> EOT20 via pyTMD** (roadmap §2 already says "New / activate").
  Per-spot harmonic constants precomputed once, evaluated locally forever; zero
  runtime downloads. Verify against OM's `sea_level_height_msl` at the 199 spots
  for one cycle before switching (amplitude+phase, not just correlation).
- **C2. SST -> NOAA OISST** (approved list), one 0.25-deg file per day, carried into
  the tail exactly as today.
- **C3. Weather -> decide, then migrate. DECIDED 2026-08-26: NOT migrating - weather
  stays on Open-Meteo on the measured wind scorecard. See Status.** Re-open §2's "keep weather on OM" against
  the scale goal. Two candidates: GFS 0.25 global GRIB (one download, same pattern as
  B1) or keep OM weather and MEASURE that host's own cap (it becomes the new ceiling
  - the 8.8-unit arithmetic above is the marine host only). Wind feeds the wind gate,
  so this migration gets its own buoy/station A/B before promotion; do not bundle it
  with the wave swap.
- **C3b. Weather -> GFS 0.25 atmos GRIB, measured first (OPEN-ITEMS 34, opened
  2026-09-12).** C3 kept OM weather on accuracy, but the comparison it rested on was
  ICON-era OM vs the wave file's ocean-masked wind, and OM's weather model has been GFS
  itself since 2026-08-30 - so the migration is now an interpolation question, not a
  model question. And since the marine-light leg went (2026-09-12) the weather host is
  the LAST per-spot OM call, past the 10,000/day line since the 2254-spot South America pass
  (2026-09-16). Steps: add a
  `gfs_grib` member to the station wind archive and score it for ~2 weeks; if the
  short-lead sign holds, a `WeatherSource` behind `BlendedSource.weather` on the same
  26 boxes / 3-hourly steps as `GfsFullSource` (NOMADS `filter_gfs_0p25_1hr.pl`,
  UGRD/VGRD/GUST 10 m + PRMSL + TMP 2 m, subregion), OM kept as `--weather-source om`.
  Rating-critical (wind gate) -> pb_0049: fleet A/B + CALIBRATION.md entry in the same
  change. After it, spot count costs zero Open-Meteo units anywhere on the publish path.
  **Step 1 BUILT 2026-09-12** (`gfsatmos.py`, archive key `<station>.gfs_grib`,
  `verify --stations --wind-model gfs_grib`); cards readable from ~2026-09-26.
- **C4. Confidence ensemble.** Today: a 4-model OM ensemble request. Rebuild
  agreement + `dir_span` from members we already download (GFS-Wave, ECMWF, and the
  blend spread itself). The member set changes, so `dir_n` era-tagging applies AGAIN
  (third era; see 2026-08-11). Recorded-not-scored until calibrated, per pb_0049.
- **Acceptance per item:** same-input A/B on the affected published fields; C1/C2
  are display/physics inputs (height, tide window) so they ride the Stage-0
  scorecard; C3 is rating-critical (wind gate) and needs its own entry.

## Phase D - ship it

- **D1. VM feasibility, measured FIRST** (gates B1): global-file download size and
  time on the 1 GB `rosa-instance`, pygrib parse memory, disk headroom next to the
  swellmap frames. If the globe doesn't fit, per-basin subsets cover the 9 regions
  and still hold the O(1)-in-spots property (requests grow with BASINS, not spots).
- **D2. Cycle timing.** VERIFIED on paper 2026-08-14: at the four crons the GFS cycle
  is 6.3-8.3 h old and the ECMWF cycle 14-20 h old (00z/12z only, 9 h lag) - the same
  staleness the dual-source archive fetches with, so the measured A/B skill already
  includes it; nothing to change. Original text: NOAA lands ~3.5-4 h after cycle time; the cron at HH+2:20
  uses the previous cycle - `pick_cycle` already encodes this; ECMWF 00z/12z with
  9 h lag likewise. Verify the four dailies each get a fresh-enough cycle.
- **D3. Promotion, per region, OM fallback retained.** Flip a region when its Phase-A
  evidence clears; the full-pipeline same-input A/B (old source vs new through
  `run --all`) is the pb_0049 artifact for each flip.
- **D4. Ops + legal sweep.** publish.sh integration; footer attribution (NOAA +
  ECMWF CC-BY + EOT20 CC-BY); drop the OM non-commercial re-verify from the launch
  checklist once no OM call remains on the promoted path; update roadmap §2/§9 and
  this doc's status lines as phases land.

## Build order

**C1 (tide - independent, easiest, immediate quota relief) → A1-A4 while the archive
matures → D1 → B1-B4 → C2 → C3 → C4 → D2-D4 region by region.**

## Status

- 2026-08-14: plan authored. A-blend parity measured (untuned); A1-A4 not started;
  C1 not started; D1 not measured. Nothing promoted; OM is primary everywhere.
- 2026-08-14 (same day, executed - full numbers in CALIBRATION.md 2026-08-14 part 2):
  **A1 CLOSED, negative** - OM's `wave_peak_period` is null from every model (verified live), so no OM peak race can ever accumulate; the raw-arm Tp race is the period evidence.
  **A2 DONE for now** - tuned weights do not beat 50/50 out-of-sample on a 5-week
  archive; keep 50/50, re-fit after A4 matures. **A3 MEASURED** - us-west: blend ahead
  5/6 leads (first region past the bar); us-east parity; hawaii OM clearly ahead (stays
  OM); portugal measured on the VM: blend ahead at EVERY lead (0.031-0.076 m) - the strongest region and second past the bar; us-east slightly behind; hawaii behind (stays OM). No-buoy policy still
  undecided. **C1 BUILT, not consumed** - 199/199 EOT20 constants committed, fleet
  verification median corr 0.969; the consume-switch is pb_0049-gated (tide feeds
  score depths) and sequenced tail-fill-first. **D1 DONE** - whole-globe parse peaks at
  168 MB RSS / 3 s per step, 1.5 GB/cycle; per-basin subsets ~100x cheaper in bytes;
  B1 defaults per-basin, whole-globe is the scale mode. Portugal A/B done (VM). **B BUILT same day**
  (CALIBRATION.md part 3): `blend.py` + `run --wave-source blend`, partitions GFS-only,
  totals blended 50/50, ECMWF fetched once per run, hourly interpolation (the Hawaii
  UTC-10 whole-day bug, caught by the smoke), live-smoked at 3 spots in 3 regions.
  **C2 + C4 BUILT same day** (part 4): SST from
  OISST daily files with OM fallback; blend-arm ensemble = own two members (raw GFS +
  ECMWF), dir_n=2 era. **C3 evidence collection BUILT same day**
  (part 5): both sources' 10 m wind now archives at every buoy each cycle, paired
  against the anemometers - the C3 decision becomes a measurement in a few weeks.
  Interim C3 posture: keep OM weather (1.2 units/pt; ceiling ~3,000 spots).
  **C1-switch FLIPPED 2026-08-15** on its
  fleet A/B (max rating delta 1, 10,283 tail hours gain tide - CALIBRATION.md
  2026-08-15): tide is EOT20 by default, quota-free, full-horizon.
- **2026-08-26: C3 DECIDED - weather STAYS on Open-Meteo** (CALIBRATION.md 2026-08-26).
  The interim posture is now the verdict, measured: pooled wind-speed MAE over the 7 NDBC
  stations carrying an anemometer has OM ahead at every lead before day 4 (1.056 vs 1.187
  m/s at 0-1d) and GFS-Wave ahead at every lead after it, so a migration would trade
  accuracy exactly where the wind gate is consumed. Direction is noise. Both arms scored
  identical n, so this is not a sample artifact. Thin where it is thin: 12 days, 7
  stations, all mid-latitude US - Hawaii and the CMEMS buoys pair no wind at all. Re-run
  at the A4 gate; it flips only if the short-lead sign flips. **C3 was never the ceiling**
  - weather is a separate host at ~1.2 units/pt.
  **Remaining: A4 wait + the blend-vs-OM A/B, then D2-D3.**
- **2026-08-26: A3's no-buoy policy DECIDED - promote WORLDWIDE** (CALIBRATION.md
  2026-08-26). The buoy registry covers 45 of 265 spots; the other 220 have no station,
  and public buoys cluster in US/European waters so registration cannot close that. A
  per-region gate would promote Portugal alone, buy ~35 spots, and leave every future
  spot on the expensive call - a gate that never opens for the regions being added. A
  buoy validates the MODEL, not the spot. Accepted risk, raised and overruled: the
  evidence is four buoyed regions and the only tropical one (hawaii) favours OM, while
  220 spots are tropical. D3's per-region OM fallback stays in the code for reverts.
  **This decides WHERE a cleared source applies, not WHETHER it cleared** - the
  blend-vs-OM A/B is still the gate.
- **2026-08-26: D3 FLIPPED - `run --wave-source` defaults to `blend`, worldwide**
  (CALIBRATION.md 2026-08-26, the fleet A/B). 265 spots, same cycle window: mean
  |Δrating| 6.64, 24.7% of hours change bucket, h_mid +0.115 m - the source, not the Tp
  handicap (which pulls DOWN). NOMADS took 1,032 requests with no pushback; 1h42m wall,
  338 MB peak; ledger +320.6 = `marine_light_units(265)`. `om` stays as the fallback and
  replay arm. Two open items came out of the run: the blend series has no back-reach
  (today's first 1-6 rows missing on 157 spots, worst far-east) and the per-partition
  Tp gap is now live fleet-wide. B3's tail label (`tail_from`) is null on this arm.
  **Remaining: A4 re-fit of the 50/50 weights at 8 weeks; back-reach; D4 footer sweep.**
- **2026-08-26: the ceiling, measured from the live ledger.** 265 points x 7.69 = 2,037.9
  per cycle; four cycles 8,152 against a 9,400 budget / 10,000 cap. **The current fetch
  plane tops out at ~305 spots - ~40 more than today.** Only the blend promotion
  (7.69 -> 1.21 units/pt, BUILT) lifts it, and it is gated on A4 (2026-09-17).
- **2026-09-12: the marine host is OFF the publish path - the blend arm's last marine
  request, the SST/tide fallback leg, is removed.** At 1947 spots (seeded 2026-09-11) it
  cost 1.21 x 1947 = 2,355.9 units a cycle, 9,423.6 a day against the 9,400 budget, and
  the 20:20Z cycle was refused on 2026-09-11 (Dream 2026-09-12 HIGH; VM ledger confirmed).
  EOT20 constants are committed for all 1947 spots, OISST maps every spot, and the
  fallback had fired 0 times in the whole publish.log, so it is deleted rather than
  skipped-when-broke: `blend.fetch_weather_many` (weather host only), `compose_raw`
  without a marine body, `cli` meters the om arm only. Nothing published moves. **The
  ceiling is now the weather host** (1.21/pt, ~9,900-11,200 a day with the station
  archive, against the same 10,000 cap) - plan C3b above / OPEN-ITEMS 34 is the exit.
- **2026-09-17: A4 CLEARED - the gate ran on 8 weeks of equal-span archive** (CALIBRATION.md
  2026-09-17). Blend vs OM, 15 buoys: Hs within 0.007 m at every lead and ahead past day 5,
  direction ahead by 3.0-4.6 deg everywhere, hawaii now parity - the 08-26 promotion stands. A2
  re-fit: tuned weights hold out-of-sample this time (w ~0.25-0.3 near, 0.5 far) but buy
  <= 0.009 m and cost 0.4-0.8 deg of direction - **`W_GFS` stays 0.5, A2 closed**. C3 re-run: OM
  wind still ahead at 0-1d (+0.064 m/s), so weather stays on OM until C3b reads (2026-09-26).
  **Remaining: back-reach; D4 footer sweep; C3b.**
