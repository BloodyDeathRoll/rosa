# Stage 3 Plan — Raw-source migration + spectral-lite

> Implementation plan for accuracy-roadmap Stage 3 (`docs/rosa-accuracy-roadmap.md` §4),
> authored 2026-07-23 at kickoff, after resolving the §7 spikes with live evidence (below).
> Mirrors the Stage-2 plan's format. Every sub-step is gated by a Stage-0 scorecard diff.

**Goal:** replace Open-Meteo as the primary offshore source with raw NOAA GFS-Wave (public
domain — removes the non-commercial constraint, roadmap §8) + ECMWF open data as the second
member, and recover as much of the spectral information (missed swell, spread, consistency)
as the free world actually publishes. **Scope-truth up front: full 2-D spectra are NOT freely
available where our spots are** — Stage 3 delivers a spectral-*lite*; the real heatmap arrives
when Stage 4 runs WW3/SWAN ourselves.

---

## Spike results (2026-07-23, live-verified — the §7 gates)

1. **NOAA gridded product: RESOLVED.** `filter_gfswave.pl` (NOMADS grib-filter CGI) serves
   regional subsets of `gfswave.tHHz.global.0p25/0p16.fHHH.grib2`. A Med box
   (30–36N, 30–37E) for one forecast hour = **9.5 KB (0p25) / 17 KB (0p16)** → a 16-day
   3-hourly regional pull ≈ **1–2 MB**. Trivial for the 1 GB VM. Contents verified with
   pygrib: wind (ws/wdir/u/v), combined swh + primary period/dir, **windsea (shww/mpww/wvdir)
   + THREE swell partitions (shts/mpts/swdir ×3)** — the same partition schema Open-Meteo
   exposes, so extract/transform/score are largely untouched by the source swap.
   Notes: raw `pub/` dir *listing* is 403 (use the filter CGI or direct file GETs, which
   work); the tHHz run lands ~3.5–4 h after cycle time (the VM cron at HH+2:20 must use the
   *previous* cycle — same as today).
2. **NOAA station 2-D spectra: DEAD for our regions.** The 00z `bull_tar` lists **918
   stations**; parsed all coordinates: **0 in the E-Med/Israel, 0 near Pacific Costa Rica,
   1 near Sri Lanka (23173 @ 8.2N 78.6E — Gulf of Mannar, Indian side, ~350 km from our
   east-coast spots, wrong exposure)**. (Hawaii has 17 — the product works, just not for us.)
3. **ECMWF open data (0.25°, `wave` stream): NO 2-D spectra / NO spread param, BUT** the free
   param list is `swh, mwd, mwp, pp1d, mp2, cdww, wmb` **+ six period-banded heights
   `h1012, h1214, h1417, h1721, h2125, h2530`** (Hs of all waves with period 10–12 s …
   25–30 s) — a coarse **1-D spectrum over the whole groundswell range**, which neither
   Open-Meteo nor NOAA gridded expose. Index files at
   `data.ecmwf.int/forecasts/{date}/{run}/ifs/0p25/wave/…-wave-fc.index`.

## 3a — Raw GFS-Wave source + dual-source A/B *(build now; unblocked)*
- **New `ForecastSource`** (`fetch.py` interface, per CLAUDE.md's designed swap): regional
  grib-filter subsets per unique-offshore-point cluster, pygrib parse → the existing
  partitioned `RawForecast` shape. Capture/replay fixtures like the OM source (tests offline).
- **Weather stays Open-Meteo** (roadmap: keep — it's good and cheap); only waves migrate.
- **Dual-source archive**: extend `rosa-pipeline archive` to record BOTH OM and GFS-Wave at
  every registered buoy each cycle → a continuous like-for-like A/B against measured truth,
  accumulating on the VM alongside the existing archive. This is the acceptance evidence for
  the primary-source decision, and it runs itself while we build.
- **Acceptance:** GFS-Wave nowcast + lead-time skill ≥ OM's at the proxy buoys per region
  before it becomes primary anywhere; OM stays the global fallback + the day-10–16 tail.

## 3b — Spectral-lite via ECMWF *(reduced, honest scope)*
> **BUILT 2026-07-23** (`ecmwf.py` + `spectral.py`): index-driven byte-range fetches (our
> 11 params coalesce to ONE ~10 MB range/step; 41×6-hourly steps to 240 h; 00z/12z cycles,
> 9 h lag) → `SpectralSea` joined per published hour (nearest ≤3 h). Missed-swell guard,
> consistency proxy and parametric spread live in the payload (`spectral` per hour,
> `spread` per swell, `spectral_meta` labels spread modeled); ECMWF swh joins the Stage-1
> agreement pool (5 members); `archive --wave-source all` (new default — VM auto-adopts)
> writes `<buoy>.ecmwf.jsonl` (hs/pp1d/mwd, ~46 s/cycle) and `verify --archive --source
> ecmwf` scores it (pp1d↔DPD). Live-smoked at Beit Yanai (+~2 min/run; guard already
> surfaced an unaccounted 10–12 s band on 07-25) and Waimea.
>
> **Spectra harness BUILT same day** (`spectra.py`, `verify --spectra`): NDBC
> `.data_spec`/`.swr1` → moments (Tp/Tm-1,0/Tm02, Qp) + σ=√(2(1−r1))@peak; reports the
> spread error bound per class and the proxy↔Qp Spearman. First pass (51201 + 46042,
> CALIBRATION.md 2026-07-23): short-swell spread assumption excellent (±1.5°), ≥14 s
> assumption unreliable (measured 36–46° — r1 noise vs wrong table, unresolved), proxy↔Qp
> r=+0.38/+0.49. ECMWF archive rows now carry mwp/mp2 for the model-side leg.
> **Remaining for 3b acceptance:** the missed-swell backtest + the model-side consistency
> check once archives mature; more buoys (ideally CDIP) to arbitrate the ≥14 s spread
> question before touching SPREAD_* constants.
- **Second member:** fetch ECMWF wave stream (swh/mwp/mwd/pp1d/mp2 + period bands) at the
  offshore points — this is also the Stage-1 multi-model confidence axis (two birds).
- **Missed-swell guard:** if a period band ≥10 s carries height that no partition accounts
  for, surface it (display + energy) — banded energy cannot hide from the sorter.
- **Consistency proxy:** spectral-bandwidth estimate from mwp/mp2/pp1d ratios → the "setty
  vs. lully" 0–100, shown, never folded into the rating (roadmap: orthogonal, like Surfline).
- **Spread: parametric only** — assumed cos²ˢ per partition class (windsea wide, old swell
  narrow). **Validate the assumption against NDBC measured `.spec`/`.swdir` at the proxy
  buoys and publish the error bound**; label spread-derived quality as modeled, not observed.
- **Acceptance:** missed-swell failure mode no longer reproduces on backtest days where a
  ≥10 s band was present; consistency/spread proxies correlate with buoy-spectra truth within
  the stated bound.

## Stage 4 pointer *(not in scope here)*
True 2-D spectra for our regions exist only if we compute them: nested SWAN/WW3 forced by 3a
partitions (+3b bands) as boundary. Per-region, after 3 lands; the current 1 GB VM is the
known constraint (roadmap §6 watch-item).

## Cross-cutting
- Precompute-static preserved; all fetching is scheduled VM work; serving stays CDN.
- Legal: NOAA public domain ✅; ECMWF open data CC-BY-4.0 (attribute in footer) ✅ — this
  migration is what makes the wave stack commercial-clean (roadmap §8).
- Open-Meteo remains: weather (all stages), waves fallback + far tail.
- Fixtures for both new sources; ruff/pytest discipline unchanged.

## Build order
**3a-fetch → 3a-archive-A/B → (archive matures ~1 wk, joint with Stage-2E gate) → 3b-ECMWF
member → 3b missed-swell/consistency/spread-bound → promote primary source per region on
scorecard evidence.**
