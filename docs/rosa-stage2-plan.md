# Stage 2 Plan — Bathymetry physics + tide + soft window

> Implementation plan for accuracy-roadmap Stage 2 (`docs/rosa-accuracy-roadmap.md` §4).
> File-level design + validation approach. No code yet — build order agreed at kickoff.
> Authored 2026-07-22.

**Goal:** retire the two biggest transform hacks — the single per-spot `height_coeff` and the
`q(T)` period fudge (`transform.py` `period_quality`/`PERIOD_EXP`, which double-counts period) —
replacing them with real nearshore physics, then add tide and soften the hard swell window. Every
sub-step is gated by a **Stage 0 scorecard diff** (`rosa-pipeline verify`).

**Validation reality:** offshore buoy truth exists only in **California (NDBC)** and **Israel
(ISRAMAR Hadera, local-only)**. Costa Rica / Sri Lanka have no buoys, so they validate via the
👍👎 feedback loop + eyeball. The *physics* is proven on CA/Israel; CR/SL inherit the stack
automatically.

---

## 2A — Bathymetry ingest *(foundation)*
- **New `bathymetry.py`**: load GEBCO 2024 (~450 m global) + EMODnet (~115 m, Med/Europe overlay);
  `depth_profile(offshore_point, bearing_to_shore)` samples depth along the approach ray. Ray
  bearing = `offshore_direction` (already the inland-pointing normal — reuse it).
- **New build command** `rosa-pipeline bathy --all`: per spot, sample the profile → compact derived
  record (`offshore_depth`, nearshore breaking-depth reference / slope) at
  `data/spots/derived/bathy/{id}.json`. Deterministic + small → commit it; raw GEBCO/EMODnet tiles
  are large → gitignore + document download.
- **Deps:** `xarray` + `rasterio`/`netCDF4`. **Attribution:** EMODnet + GEBCO → footer (legal §8,
  flag for UI session).
- **Validate:** depths sane (monotonic-ish shoreward); spot-check a steep reef vs a shelving beach.

## 2B — Analytic nearshore transform *(the headline accuracy lever)* — DONE (hybrid)
- **New `physics.py`** (DONE): dispersion solver (k from T,d via ω²=gk·tanh kd, Newton), group
  celerity Cg(T,d), **shoaling** Ks=√(Cg_ref/Cg), **refraction** (Snell, Kr from approach angle =
  partition dir vs `shore_normal`), **depth-limited breaking** — a march over the depth profile
  breaking at the first depth where the transformed height reaches γ·d (γ=0.78). Unit-tested
  against the deep/shallow-water limits.
- **CORRECTION (2026-07-22): q(T) is NOT fully retired — it's reframed.** Naive linear
  shoaling + depth-limited breaking *over-calls* short-period Med windswell ~3× (0.6 m/4 s →
  0.58 m physics vs 0.17 m field truth), reproducing the exact problem `q(T)` was built to fix.
  Bottom friction is the wrong sign (it dissipates *long*-period groundswell more). The real
  cause is **wave power / rideability** (P ~ H²·T): short windswell is weak and disorganised,
  "surfs" far below its physical height. So the transform is a **HYBRID**: physics for the
  *geometry* (retires the single `height_coeff` — now a small residual), times a **period-power
  rideability factor** (`transform.period_rideability`, the grounded reframing of `q(T)`, capped
  at 1.0 so it only attenuates, never amplifies past the depth-limited break). Fully retired at
  **Stage 3** when spectral directional-spread + power replace the proxy.
- **`transform.py`** (DONE): `breaker_height_from_profile(partitions, window, shore_normal,
  wet_depths)` = RMS of per-partition (physics × rideability). `period_quality`/`effective_height`
  kept as the no-profile fallback.
- **`bathymetry.py`** (DONE): `DepthProfile.from_dict` + `load_profile` + `wet_depths_deep_to_shallow`.
- **`score.py` / `cli.py`** (DONE): `score_hour(spot, hour, wet_depths=None)` — physics path when the
  spot's profile loads, q(T) fallback otherwise; `run` loads each spot's committed profile.
- **Validated:** Beit Yanai 0.6 m/4 s windswell back to 0.17 m POOR (matches CALIBRATION.md);
  groundswell/CR points now physics-shaped; 81-spot run clean. 145 tests green.
- **STILL TODO (folds into 2E):** breaker-height bias/RMSE vs. ISRAMAR + NDBC-derived across spots;
  tune γ, residual `height_coeff`, and the rideability exponent from the scorecard.

## 2C — Soft exposure window *(falls out of 2B)*
- Replace the hard `in_window` boolean (`transform.py`) with a cosine-power angular response
  centred on the spot's optimal direction — refraction Kr already encodes angular loss, so nearly
  free.
- Touches `transform.py` (weighted energy/height), `score.py`, `publish.py` (`in_window` badge →
  soft exposure weight). Spot schema: `optimal_dir` + `exposure_power` (default `optimal_dir` =
  window centre → back-compatible across israel/costa-rica/sri-lanka YAMLs).
- **Validate:** real energy just outside the old arc no longer fully dropped; scorecard
  neutral-or-better.

## 2D — Tide (EOT20 / pyTMD)
- **New `tides.py`**: pyTMD + EOT20 → precompute per-spot harmonic constants at build
  (`data/spots/derived/tides/{id}.json`); cheap runtime `tide_height(spot, t)` → m rel. MSL + stage.
- **Wire in:** breaking depth `d_break = bathy_depth + tide` (2B consumes it); per-spot
  `ideal_tide_window` multiplier on rating, **gated by tidal range** (EOT20 amplitude) so micro-tidal
  Med barely moves but macro-tidal **CR** does. `HourForecast` gains `tide_m`; `publish.py` emits a
  real tide series — **replaces the web's mock M2 sine** (emit data only; UI session consumes it).
- **Deps:** `pyTMD` + EOT20 constituents (CC-BY, vendor/document).
- **Validate:** improves skill at a macro-tidal test spot (CR near a CO-OPS gauge) without harming
  Med; tide heights checked vs a known gauge.

## 2E — Recalibration
- Re-tune γ, residual coeff, `exposure_power`, `ideal_size_m` over the new transform from
  `docs/CALIBRATION.md` + Stage 0 scorecard + 👍👎. Update the public "why this rating" numbers
  (CLAUDE.md principle #3).

---

## Cross-cutting
- **"Precompute, serve static" preserved** — all bathy/tide work is one-time offline per spot;
  runtime stays cheap.
- **Test standard held** — unit + offline fixture + live smoke (bathy/tide fixtures keep tests
  offline); currently 96 green.
- **Data artifacts:** derived per-spot bathy + tide files are small & deterministic → commit under
  `data/spots/derived/`. Raw GEBCO/EMODnet/EOT20 sources are large → gitignore + download README.
- **Open spikes to resolve at kickoff** (roadmap §7): EMODnet vs GEBCO resolution for point breaks;
  single shore-normal ray vs a refraction fan; γ per `break_type`; commit-vs-regenerate for derived
  artifacts; EOT20 file size/vendoring.

## Proposed build order
**2A → 2B → 2C → 2D → 2E** — physics foundation first (the accuracy thesis), soft window rides on
it, tide next (biggest CR payoff + kills the web mock), recalibrate last.
- Alt: pull **2D tide forward** for a fast, visible CR win + mock-replacement before the heavier
  transform work.

**Effort:** L · sequenced sub-PRs, each carrying a before/after Stage 0 scorecard diff.
