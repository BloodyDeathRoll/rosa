# Rosa Accuracy Roadmap — the most accurate free surf forecast

*Supersedes `rosa-forecast-improvements.md` as the actionable plan (that file stays as the
Surfline-methodology source study). This is the full, staged path to a complete solution — not
a quick pass. It keeps every CLAUDE.md non-negotiable (precompute-static, free, legal red lines)
and is explicit about where we **keep**, **join**, or **replace** what we've already built.*

---

## 1. What "accuracy" means here (and why we measure before we build)

"Most accurate" is not a claim — it is a **number we drive down over time**. A surf forecast is a
chain, and the output is only as accurate as its weakest link:

```
offshore wave field  →  propagation to nearshore  →  nearshore transform  →  break quality  →  rating
 (global wave model)     (grid → spot's approach)   (shoal/refract/break)   (wind/tide/spot)   (0–100)
```

We measure accuracy at two points in that chain:

1. **Physical skill** — forecast vs. buoy observations (NDBC `.spec`/`.swdir`, CDIP, ISRAMAR for
   validation only). Metrics per variable (Hs, Tp, peak direction, and — once we have spectra —
   directional spread): **bias, RMSE, scatter index, directional error**. This scores links 1–3.
2. **Surfer-perceived skill** — the rating and height-phrase vs. what a human saw (in-app 👍👎 +
   the calibration log in `docs/CALIBRATION.md`). This scores links 4–5, which no buoy can.

**Every stage below has acceptance criteria stated in these metrics.** A change ships only if it
moves the number the right way on the backtest. That discipline — not any single model — is what
makes the forecast "the most accurate."

Where Rosa is today (baseline to beat): offshore = Open-Meteo's blended 3-partition + windsea
readout; propagation = none (grid-cell value at an offshore point); transform = a single per-spot
`height_coeff` × period-quality `q(T)`; quality = wind class + hard swell-window arc; **no tide in
the rating, no spectra, no directional spread, no confidence, no bathymetry, no verification loop.**

---

## 2. Source strategy — keep, join, replace

| Link | Today | Target | Decision |
|------|-------|--------|----------|
| Offshore field (primary) | Open-Meteo Marine (blended, 3 partitions) | Raw **NOAA WW3 / GFS-Wave** partitioned + **2-D spectra**; **ECMWF open-data** WAM | **Replace** as primary where spectra exist; Open-Meteo becomes the global fallback + the day 10–16 tail |
| Offshore field (ensemble) | none | Multi-model spread (GFS-Wave, ECMWF, MeteoFrance-WAM, ICON-EWAM) + GEFS-Wave | **Join** — new confidence axis |
| Weather (wind/temp/pressure) | Open-Meteo Weather | Open-Meteo Weather (+ ensemble for wind confidence) | **Keep** — it's good and cheap; no reason to replace |
| Bathymetry | none | **EMODnet** (~115 m, Med/Europe) + **GEBCO 2024** (~450 m, global fallback) | **New** — the missing link that makes physics possible |
| Nearshore transform | `height_coeff` constant | Analytic shoaling+refraction ray (Stage 2) → nested **SWAN/WW3** model (Stage 4) | **Replace** `height_coeff`; keep a small residual correction term |
| Tides | not wired to rating | **EOT20** harmonics via pyTMD (CC-BY) + per-spot ideal-tide window | **New / activate** |
| Validation truth | none | **NDBC** (500+ directional-spectra buoys), **CDIP**, **ISRAMAR** (validation only, partnership pending) | **New** — the backbone |
| Rating formula | v1 (size/period/wind + wind-gate) | Recalibrated over all new axes (spread, consistency, tide, confidence) | **Evolve**, not scrap — v1 stays the fallback |

**Guiding rule for join-vs-replace:** replace a component only when the backtest shows the
replacement beats it on buoy skill or user 👍👎. Until then the old path stays as the fallback, so
we never regress a region while improving another.

---

## 3. Architectural decisions (the non-negotiables still hold)

- **Precompute-static stays absolute.** No request-time forecast backend, ever. Every stage — even
  running SWAN — happens in the scheduled pipeline; the output is still static per-spot JSON +
  map frames on the CDN. What grows is the *precompute box*, never the serving model.
- **The raw-grid migration lives behind the existing `ForecastSource` interface** (`fetch.py`).
  CLAUDE.md already designed for this ("Open-Meteo → raw-grid migration touches one module"). New
  sources become new `ForecastSource` implementations; `extract`/`transform`/`score` stay pure and
  fixture-tested. Spectra flow as a richer `RawForecast`, not a schema rewrite everywhere.
- **Compute-budget reality.** Raw GRIB (GB-scale/run) and a nested SWAN run exceed a stock GitHub
  Actions runner (6 h / 7 GB). The precompute moves to a **scheduled cheap VM or self-hosted
  runner** (spot instance, runs minutes–~1 h, 4×/day → cents/day). Still free to *users*; still
  static serving. This is the one new operating cost and it is small — flagged per stage.
- **Region-by-region rollout.** Fine bathymetry + nearshore model land per region behind a
  capability flag. A spot without a fine model transparently falls back to the analytic transform,
  and a spot without that falls back to Open-Meteo. Accuracy improves in waves, never all-or-nothing.
- **Everything attributed, nothing scraped.** NOAA/ECMWF/EMODnet/GEBCO/EOT20 are open with
  attribution; ISRAMAR stays validation-only until partnership; no competitor data ever. §8 tracks it.

---

## 4. The staged plan

Each stage is independently shippable, measured against Stage 0's harness, and ordered so
dependencies come first and the biggest early accuracy per unit effort lands soonest.

### Stage 0 — Verification & calibration harness *(measure first — unlocks everything)*
**Accuracy lever:** none directly; makes every later lever *provable*. Do not skip.
- Ingest buoy observations near spots: **NDBC** realtime `.spec`/`.swdir`/`.txt` (Hs, Tp, Dir,
  directional spread), **CDIP**, and **ISRAMAR** (Hadera/Ashdod — validation only, never shipped).
- Build a **backtest**: replay captured forecasts against buoy truth → bias, RMSE, scatter index,
  directional error per variable, per lead-time, per spot. Store as a versioned scorecard.
- Wire the in-app **👍/👎 "was this accurate?"** (CLAUDE.md v0.2 item) into `docs/CALIBRATION.md`
  as structured rows, joined to the same scorecard.
- Output: a one-command `rosa-pipeline verify` that prints the current skill scorecard.

**Acceptance:** baseline scorecard exists for all Israel spots with a nearby buoy; every subsequent
stage's PR includes a before/after scorecard diff. *(This is the gate for calling anything "more accurate.")*
**Effort:** M · **Compute:** trivial · **Data:** NDBC/CDIP open; ISRAMAR validation-only.

### Stage 1 — Multi-model boundary + confidence + peak period *(cheap offshore win, still Open-Meteo)*
**Accuracy lever:** better boundary condition + honest uncertainty; no infra change.
- Fetch multiple wave models via Open-Meteo (`ncep_gfswave016`, `ewam`, `gwam`, `meteofrance_wave`)
  and weather ensemble (`gfs`, `ecmwf_ifs`, `icon`, `gem`) — all confirmed available.
- **Confidence score (#7)** = inverse of normalized multi-model spread in Hs/Tp/Dir per timestep;
  shown for days 0–9, degraded/flagged for the GFS-Wave-only day 10–16 tail.
- **Bias-correct** the offshore field where a buoy is close (learned offset from Stage 0).
- Add **peak period** fields (`*_peak_period`) — surf-relevant; we only fetch mean today.
- Display model name + run + confidence (CLAUDE.md principle #3 — already required, now real).

**Acceptance:** offshore Hs/Tp scatter index drops vs. Stage 0 baseline where a buoy exists;
confidence correlates with observed error (high confidence ⇒ lower error).
**Effort:** M · **Compute:** low (a few more API calls) · **Data:** Open-Meteo, free non-commercial.

### Stage 2 — Spot-transform overhaul: bathymetry physics + tide + soft exposure *(the biggest transform win)*
**Accuracy lever:** replaces the single `height_coeff` with real physics; activates tide worldwide.
This is where a spot's *own coastline* finally shapes its forecast.
- **Bathymetry ingest:** EMODnet (~115 m, Med/Europe) with GEBCO 2024 (~450 m) global fallback;
  per-spot depth profile along the swell-approach ray (reuse the OSM shore-normal already computed).
- **Analytic nearshore transform (#1, #5):** per partition, from period → celerity/group velocity
  via the dispersion relation, apply shoaling `Ks = √(Cg_off/Cg_near)`, refraction (Snell) `Kr`,
  and depth-limited breaking `H_break ≈ min(shoaled H, 0.78·depth)`. **Retire `q(T)`** — period now
  enters once, physically, through Cg (kills the double-count flagged in improvements #5). Keep a
  small per-spot residual coefficient for sandbar-scale error GEBCO/EMODnet can't resolve.
- **Soft exposure window (#8):** replace the hard swell-window arc with a cosine-power angular
  response centered on the spot's optimal direction — falls straight out of the refraction math.
- **Tide (#4):** EOT20 harmonics via pyTMD precomputed per spot; feed tide height/stage into
  `H_break` (breaking depth) and add a per-spot **ideal-tide-window** multiplier. Gate by tidal
  range (EOT20 gives it) so it barely moves micro-tidal Med ratings but drives Atlantic/Pacific spots.
- **Recalibrate** height + rating over the new transform against Stage 0.

**Acceptance:** breaker-height bias/RMSE vs. buoy-derived + eye observations beats the
`height_coeff` baseline across spots (not just the one it was tuned on); tide term measurably
improves skill at a macro-tidal test spot without harming Med spots.
**Effort:** L · **Compute:** medium (bathy preprocessing per spot, one-time) · **Data:** EMODnet
(attribution), GEBCO (open), EOT20 (CC-BY). *Per-spot ideal-tide window needs local input — crowd/observe.*

### Stage 3 — Raw spectral migration: kill "missed swell," add spread & consistency *(the offshore ceiling)*
**Accuracy lever:** the offshore input Open-Meteo can't give — full energy distribution. This is the
Mediterranean short-period-windswell fix Surfline said it invested most in, and it's impossible on
the current API (directional spread is not exposed — verified).
- **New `ForecastSource`:** raw **NOAA WW3 / GFS-Wave** partitioned fields + **2-D frequency–
  direction spectra** (NOMADS/AWS open buckets) via `xarray` + `cfgrib`; **ECMWF open-data** WAM as
  a second member. Behind the existing interface — `extract`/`transform`/`score` largely unchanged.
- **True in-window energy integration (#2):** integrate spectral energy over the spot's directional
  window instead of sorting into 3 partitions — no more dropping a real low-period peak.
- **Directional spread quality term (#3):** per-band spread → a cleanliness axis independent of
  height; narrow = organized groundswell, wide = messy windsea. Modulates the quality rating.
- **Set-consistency metric (#6):** from spectral bandwidth/grouping, a separate 0–100 "setty vs.
  lully" number — shown, **not** folded into the rating (kept orthogonal, like Surfline).
- Validate spread/consistency directly against NDBC `.swdir` directional spectra from Stage 0.

**Acceptance:** windswell height/period skill in the Med improves vs. Stage 2; the "missed swell"
failure mode (real low-period energy absent from the readout) no longer reproduces on backtest;
directional-spread error vs. NDBC is bounded.
**Effort:** XL · **Compute:** high — GRIB download + spectral processing; **moves precompute to the
scheduled VM/self-hosted runner.** · **Data:** NOAA (open), ECMWF open-data (open, attribution).

### Stage 4 — Nested nearshore spectral model *(the accuracy ceiling — Surfline-LOTUS class)*
**Accuracy lever:** the true nearshore transform. The analytic ray (Stage 2) is a good
approximation; a real spectral model on fine bathymetry is what actually separates a great forecast
from a good one — this is what LOTUS/LOLA is.
- Run **SWAN** (open-source, Delft) or **WW3 unstructured** nested per region, forced at the
  boundary by Stage-3 spectra, propagating over EMODnet/GEBCO bathymetry with wind input.
- Replaces the analytic transform where a fine model exists; analytic ray remains the fallback for
  un-modeled regions. Output is still static: per-spot nearshore spectra → the same JSON.
- Rolled out **region by region**, highest-traffic coasts first; each region validated on Stage 0
  before it goes live.

**Acceptance:** in a modeled region, nearshore Hs/Tp/Dir skill beats the Stage-2 analytic transform
on buoy validation; no regression where the model isn't yet run (fallback intact).
**Effort:** XL (per region) · **Compute:** high — SWAN runs on the VM/runner; bounded by keeping
grids regional and coarse-nested. · **Data:** SWAN/WW3 free; bathymetry as above.

### Stage 5 — Full rating recalibration, worldwide rollout & ongoing ops *(make it complete, keep it honest)*
**Accuracy lever:** integrate every axis into one coherent, recalibrated rating; scale globally;
keep accuracy improving after launch.
- Recalibrate the **0–100 rating** over all axes now available (physical height, period, wind,
  directional spread, consistency, tide window, confidence) against the full Stage-0 corpus — the
  public "why this rating" formula updated to match (CLAUDE.md principle #3).
- **Sea-breeze / thermal-wind refinement** and gust/lull from the weather ensemble (coastal wind is
  a top error source and is cheap to improve once the harness can score it).
- **Worldwide spot DB scale-up** on the ODbL open dataset (CLAUDE.md spot-DB strategy) — each new
  region inherits the full physics stack + fallbacks automatically.
- **Continuous ops:** the Stage-0 scorecard runs every cycle; drift alerts; the 👍👎 stream keeps
  feeding calibration. Accuracy becomes a monitored, published metric — the transparency moat.

**Acceptance:** the composite rating agrees with user 👍👎 above a target rate across regions and
seasons; the published skill scorecard is stable or improving cycle over cycle.
**Effort:** L, then continuous · **Compute:** as Stage 3–4 steady-state · **Data:** all above.

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

- Stages 0–2: fit inside GitHub Actions cron — no new cost.
- Stages 3–4: exceed a stock runner → **scheduled cheap VM or self-hosted runner**, 4×/day, minutes
  to ~1 h/run → cents/day. Users still pay nothing; serving is still static CDN. This is the only
  new operating expense and it is small and bounded. Regional grids keep SWAN tractable.

## 7. Open spikes (resolve at each stage's kickoff, don't front-load)

1. Exact NOAA product for 2-D spectra vs. partitioned GRIB (grid coverage over the Med; NOMADS vs.
   AWS open-data bucket; refresh cadence) — Stage 3 spike.
2. ECMWF open-data wave-spectra availability in the free tier (params + resolution) — Stage 3 spike.
3. EMODnet Med tile resolution/coverage at the exact Israel spots vs. GEBCO — Stage 2 spike.
4. SWAN vs. WW3-unstructured for regional nesting on the target runner (build, runtime, grid size) —
   Stage 4 spike.
5. Buoy coverage per region for validation — NDBC is sparse in the Med; ISRAMAR is validation-only
   and needs a partnership for anything shipped. Confirm truth sources per region — Stage 0 spike.

## 8. Legal / attribution checklist (per CLAUDE.md red lines)

- **NOAA** (WW3/GFS-Wave/GEFS-Wave/NDBC): open, no restriction. ✅
- **ECMWF open data**: open, attribution. ✅
- **EMODnet Bathymetry**: open, attribution required. ✅
- **GEBCO**: open. ✅
- **EOT20**: CC-BY, attribution. ✅
- **SWAN / WAVEWATCH III**: open-source models. ✅
- **Open-Meteo**: *data* is CC-BY-4.0 (commercial OK, attribution), but the *free API service* is
  **non-commercial** — a subscription or ads on Rosa would require a paid plan or self-hosting.
  Stage 3's migration to raw NOAA (public domain) + ECMWF (CC-BY-4.0) removes this constraint
  entirely and makes the stack commercial-clean. Keep Open-Meteo for weather-only until then. ⚠️
- **ISRAMAR**: all-rights-reserved — **manual validation only**; pursue partnership before any
  integration. Never shipped. 🚫→🤝
- **Never**: Surfline API/spots/cams/guide text, or any scraped third-party cam. 🚫

---

*Bottom line: the fast wins (Stage 1) are worth taking, but the accuracy the user is asking for
lives in Stages 2–4 — real bathymetry physics and raw spectra — with Stage 0's verification harness
underneath the whole thing so "most accurate" is a measured fact, not a slogan.*
