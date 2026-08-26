# Peak-period plan - give the blend arm back the Tp the OM arm had

> Authored 2026-08-26 (session 37), the afternoon of the D3 flip. Closes OPEN-ITEMS 21.
> Mirrors the fetch-plane plan's format. **Goal:** every primary-swell and wind-sea
> partition the blend arm publishes carries the same peak period the OM arm published
> before the flip, from a free global grid, with no station join and nothing invented.

## The problem, in one paragraph

Rosa's height and rideability key on a partition's PEAK period (`transform.rideability_period`,
`transform.energy_period` - peak-keyed since 2026-07-30, calibrated against eye frames on
the OM arm's Tp). GFS-Wave gridded publishes per-partition MEAN periods only (`mpts` x3,
`mpww`; the file's one Tp is `perpw`, the whole sea's - verified message by message on the
committed fixture 2026-08-26). So since the flip every partition reaches the transform with
`peak_period_s = None` and falls back to the mean: the regime CALIBRATION.md 2026-07-30
measured as a 1.6-2x under-call, one-directional (down), 318,918 slots on the promotion run.

## What the OM arm actually had (so parity is defined, not guessed)

Verified on the committed OM fixture (`32.3817_34.8035.json`, 384 hours):

| key | non-null |
|---|---|
| `swell_wave_peak_period` | 91 / 384 (the first ~7.3 days) |
| `wind_wave_peak_period` | 91 / 384 |
| `wave_peak_period` (total) | 0 / 384 |
| secondary / tertiary swell peak | never published |

Those two columns came from ONE model - DWD's GWAM, via Open-Meteo's `gwam` member
(`fetch.TP_MODEL`), joined per hour onto meteofrance/best_match partitions. A deliberate
cross-model join, documented in `fetch.py` as safe because Tp feeds rideability and display,
never the dispersion march. **Parity = the primary swell's and the wind sea's peak, to ~7.3
days, from GWAM.** Nothing more was ever there.

## Candidates, verified 2026-08-26

### A. DWD GWAM open data, direct - CHOSEN

`https://opendata.dwd.de/weather/maritime/wave_models/gwam/grib/{00,12}/{ppts,ppww}/`

- Files `GWAM_PPTS_YYYYMMDDHH_SSS.grib2.bz2`, `GWAM_PPWW_...`; **3-hourly, steps 000-174**
  (7.25 days - exactly the ~7.3-day coverage OM's join had); **00Z and 12Z** only.
- Downloaded and parsed one of each with pygrib: `pp1ds` "Peak wave period of total swell"
  and `pp1dw` "Peak wave period of wind waves", seconds; **global regular 0.25 deg, 1440 x
  699, lat 89.25 -> -85.25, lon 0 -> 359.75**, land-masked; values 0-21.76 s. One message
  per file, ~140-360 KB bz2, ~1.2 MB unpacked.
- **Publish lag measured:** the 00Z run's +024 file was last-modified **03:39Z**; the 12Z
  run's at **15:39Z**. So the 08:20Z cron gets 00Z, 14:20Z still 00Z (14 h old), 20:20Z
  and 02:20Z get 12Z - the same staleness D2 already accepted for ECMWF (also 00/12Z).
- **Licence:** CC BY 4.0 (DWD legal notice, checked). No registration; DWD logs the IP
  for 7 days. Attribution required - add to `ATTRIBUTION_BLEND` and the About/Settings
  credits.
- Other fields in the same tree, for later if wanted: `sts/mdts/mpts` (swell H/dir/mean
  period), `sww/mdww/mpww` (wind sea), `mwd`, `tm10`, `sp_10m/dd_10m`. GWAM partitions
  into ONE swell + wind sea, which is why secondaries never had a peak on OM either.

Why it wins: it is literally the same data the calibrated pipeline consumed until this
morning, on a global grid, O(1) in spot count, no station join, no fabrication, zero
Open-Meteo units. The cross-model join it needs is the one `fetch.py` already argues for.

### B. NOAA GFS-Wave station bulletins - LATER, optional

`.../gfs.YYYYMMDD/HH/wave/station/gfswave.tHHz.{bull,cbull}_tar` - verified: `cbull_tar`
26 MB / `bull_tar` 49 MB at 06Z, **918 stations**, per-partition (up to 6) Hs / Tp / dir,
hourly. `cbull` is integer-rounded (Hs to 1 m, Tp to 1 s) - the `bull` files carry
decimals. `spec_tar` (2-D spectra) returned 404 at 00Z/06Z and 403 at 12Z - not usable.
This is the only source with SECONDARY/TERTIARY peaks, but it needs a nearest-station join
plus a coherence-distance rule that must be calibrated, and 49 MB per cycle. Worth it only
if secondary-swell Tp is ever shown to matter; parity does not need it.

### C. ECMWF `pp1d` (already fetched) - REJECTED as redundant

Whole-sea peak only (the open-data wave stream is 13 params: swh, mwd, mwp, pp1d, mp2, the
six period-band heights h1012..h2530, cdww, wmb - listed from the live index). Handing a
whole-sea peak to the dominant partition is a coarser version of A with a 10-day horizon;
once A exists it adds nothing. Keep as the fallback thought if DWD ever goes dark.

### D. Derive Tp from the mean period by a spectral-shape ratio - REJECTED

Tp/Tm ~ 1.1-1.3 for wind sea, ~1.0-1.1 for swell, is standard textbook, but it is a
constant multiplied into a period the physics is calibrated on - a made-up number per
partition, and the fabrication rule in `blend.py`'s docstring. Not taken.

## Design (plan A)

1. **`gwam.py`** - a whole-globe fetcher in the OISST mould, not the grib-filter mould:
   pick the latest 00/12Z cycle with `CYCLE_LAG_H` ~ 4 h (measured 3h39m), download
   `ppts` + `ppww` for every 3-hourly step 0-174 (118 files, ~30 MB/cycle bz2), `bz2`
   decode, pygrib, **sample the nearest wet cell per point and drop the grid** - never hold
   more than one 1440x699 field. Nearest-wet + seam handling reuse `geo.lon360/dlon180`
   and the `oisst.parse_points` pattern (the 2026-08-23 seam work applies here too).
   Fall back one cycle (12 h) if the first step 404s, the way `GfsFullSource` probes its
   first step and `swellmap._resolve_cycle` drops back. Capture
   dir + fixture replay like every other source; a `--gwam-fixtures` is not needed - the
   blend fixture dir gets `gwam_{ppts,ppww}_fSSS.grib2` captures for Beit Yanai.
2. **Join in `blend.compose_raw`**: two new hourly columns on the composed marine body,
   `swell_wave_peak_period` and `wind_wave_peak_period`, interpolated hourly between the
   3-hourly steps exactly as the GFS fields are (`_interp_hourly`), null past 174 h and
   wherever the cell is masked. **No other code moves**: `extract._partition` already
   reads `{prefix}_peak_period` with `.get`, so the primary swell (`swell_wave_*`) and wind
   sea (`wind_wave_*`) pick their peaks up, secondaries stay None as they always were, and
   `partition_peak_period_gap` reports the residual (secondaries only) instead of 318k.
3. **Provenance:** the payload's `swells[].peak_period` becomes non-null again on the first
   two partition kinds; `spectral_meta` or the attribution string names GWAM. No constant
   model label (CLAUDE.md principle 3).
4. **Attribution:** `ATTRIBUTION_BLEND` gains "Peak periods: DWD GWAM (CC BY 4.0)"; About
   page and Settings credits gain DWD.
5. **Ops:** parallel download (4 workers, as `GfsFullSource`); +118 requests/cycle to a
   host that is not NOMADS, so the NOMADS budget is untouched. Disk: none kept. Memory:
   one field at a time, ~4 MB float32.

## Gate (pb_0049 - this MOVES published heights)

Same-input fleet A/B on the VM, the promotion-run pattern: blend-without-GWAM vs
blend-with-GWAM from the same cycle window, `abdiff.py`. Expected: the fleet moves UP,
most on long-period coasts (Costa Rica, Portugal, Sri Lanka), zero movement past day
7.25, zero on secondary partitions. Also **re-run the OM-vs-blend diff** afterwards -
the 2026-08-26 promotion A/B carried this handicap and the plan's own note says an A/B
that carries it attributes it to source skill; with parity restored the honest source
difference can finally be read. CALIBRATION.md entry with both tables in the same change
as the default flip.

## Acceptance

- `partition_peak_period_gap` on a fleet run counts secondaries only (expect ~1/3 of the
  old number, all `secondary_/tertiary_`).
- CDN: a Costa Rica spot's `hours[].swells[0].peak_period` non-null through day 7, null
  after; `wind`-kind partition likewise.
- Offline `run --wave-source blend --fixtures` replays with the captured GWAM files and
  the e2e test asserts a non-null primary peak.
- Repo suite green, ruff, tsc; attribution present in payload and web.

## Build order

**A1 fetcher + fixture -> A2 compose join + tests -> A3 attribution -> A4 fleet A/B on the
VM + CALIBRATION entry + flip in one change -> A5 verify on the CDN after a cron cycle.**
B (bulletins) only if a later calibration shows secondary-swell Tp matters.

## Status

- 2026-08-26: plan authored; every source claim above verified live the same day (file
  listings, one PPTS + one PPWW file parsed, publish lags, licence page, NOMADS bulletin
  tar opened, ECMWF index listed). Nothing built. OPEN-ITEMS 21 points here.
