# Rosa Forecasting Algorithm — Improvement Recommendations

*Derived from a study of Surfline's PUBLIC forecasting methodology (help-center Forecasting Fundamentals + Forecast Features articles only). No proprietary Surfline data — API output, spot database, per-spot numbers, ratings, cam imagery, or spot-guide text — was scraped or reproduced. Method and principles only.*

## Guardrails respected
- Studied how Surfline **models and presents**, not what they output.
- Every recommendation below is implementable in a **precompute-static pipeline on free/open data**: Open-Meteo Marine + Weather, NOAA WW3 / GFS-Wave / GEFS-Wave / NDBC, ECMWF open data, GEBCO bathymetry, EOT20 tides, OSM. Rosa never calls a forecast backend at request time.

---

## What Surfline's public methodology tells us

Load-bearing facts from their help center that drive the recommendations:

- **Nearshore model (LOTUS, successor to LOLA):** built on NOAA WavewatchIII source code plus high-resolution bathymetry and near-shore wave models, validated against buoys/satellites (source: "What is LOTUS?"). Same open foundation Rosa already has.
- **Surf height** = spot orientation + swell height/period/direction + how concurrent swells interact (source: "Difference between swell and surf"). They describe shoaling explicitly: long-period waves "feel the bottom deeper," start shoaling earlier, move more water volume — so 2ft@20s produces more surf than 5ft@6s.
- **Wave Energy** = "height squared multiplied by period (and some coefficients)," summed over partitions, weighted by "the relative direction of the swell to the beach"; exposed spots read higher than sheltered neighbors on identical offshore swell (source: "Wave Energy").
- **Model condition rating** uses only "wind speed, wind direction, and breaking wave height" and explicitly "does not include tide or wave shape" (source: "Observation Clarity", "Surf Ratings & Colors"). Tide/shape come from human forecasters + per-spot "Ideal Conditions" guides.
- **Swell Spectra**: energy distributed across period AND direction, with a per-band **directional spread** value; warns of the "missed swell" failure mode where partition-sorting drops a real low-period peak (source: "Advanced Swell — Swell Spectra").
- **Forecast Probability** = agreement across a 21-member ensemble, given only for the first 9 days (source: "Forecast Probability").
- **Wave Consistency** = predicted fraction of waves exceeding a spot's set threshold; windswell scores higher than groundswell (source: "Wave Consistency").

---

## Prioritized improvements (ranked by impact × feasibility)

### 1. Replace the single `height_coeff` with physics-based shoaling + refraction from GEBCO
**Impact: highest · Feasibility: medium**

- **Gap:** Rosa collapses all nearshore transformation into one per-spot constant; deep-water swell is scaled but never transformed. Surfline's edge is "high-res bathymetry + nearshore wave model."
- **Principle:** Entering shallow water, waves shoal (height grows as they slow) and refract (crests bend parallel to depth contours), per linear wave theory — the shoaling process described in "Difference between swell and surf."
- **Implementation:** From GEBCO, extract a depth profile along a ray from each spot's offshore sample point to the break. Per partition, compute celerity/group velocity from period via the dispersion relation, then apply:
  - Shoaling coefficient `Ks = sqrt(Cg_offshore / Cg_nearshore)`
  - Refraction coefficient (Snell's law) `Kr = sqrt(cos(theta_offshore) / cos(theta_nearshore))`
  - Breaker height per partition `H_break ≈ H_offshore · Ks · Kr`, capped by depth-limited breaking `H_break ≈ 0.78 · depth`.
  - Per-spot params: break depth / contour orientation (from GEBCO + existing OSM shore-normal).
- **Expected impact:** Large. Period and swell direction physically drive height; naturally reproduces "same offshore swell, more surf at exposed spots."
- **Calibration:** NDBC/ISRAMAR buoy-to-eye observations to fit the breaker index.
- **Flag:** GEBCO ~450 m resolution — good for regional shoaling/refraction trends, too coarse for sandbar-scale detail. Keep a residual per-spot correction term.

### 2. Move from 3 sorted partitions to a spectral / energy-band representation ("missed swell" fix)
**Impact: high (esp. Mediterranean) · Feasibility: medium**

- **Gap:** Rosa uses up to 3 partitions + windsea. Surfline warns partition-sorting drops real energy: "a small change in the energy at seven second mark would cause a huge change in the swell overview readout." Short-period wind-swell is exactly where this bites — Rosa's tuning region.
- **Principle:** Sea state is a continuous 2D energy density over period and direction; significant height derives from total energy `Hs = 4·sqrt(m0)`; "5ft" = average of the largest third.
- **Implementation:** Pull the full frequency/period fields (and directional partitions where available) from Open-Meteo Marine and NOAA GFS-Wave / WW3; bin energy into period bands instead of forcing 3 discrete swells. Sum in-window band energy directly. If full spectra aren't exposed, at minimum stop discarding windsea / low-period bands in the Med.
- **Expected impact:** High for wind-swell accuracy; low elsewhere.
- **Calibration:** ISRAMAR buoy spectra if available; otherwise buoy Hs/Tp vs derived value.

### 3. Add a directional-spread penalty to the quality rating
**Impact: high · Feasibility: high**

- **Gap:** Rosa scores period and size but has no notion of how organized/clean the swell is. Surfline treats directional spread as first-class ("higher number = waves from a wider range of directions … more disorganised").
- **Principle:** Narrow spread = organized, uniform sets (distant groundswell); wide spread = messy, less rideable faces — a quality axis independent of height.
- **Implementation:** Use the directional-spread field per partition from Open-Meteo/WW3 (or compute from the spectrum in #2). Add a rating term rewarding narrow spread / penalizing wide spread; use it to modulate period-quality `q(T)`.
- **Expected impact:** High. Cheap, well-supported quality axis currently missing entirely; Med wind-swell is typically wide-spread, so it correctly tempers over-optimistic ratings.

### 4. Add tide-window weighting to the rating via EOT20
**Impact: medium-high · Feasibility: high**

- **Gap:** Tides planned but not wired into the rating. Even Surfline's *model* rating omits tide (deferring to forecasters + per-spot "Ideal Conditions"). Rosa can exceed Surfline's automated tier here.
- **Principle:** Tide changes breaking depth and break quality; each spot has an optimal tide window.
- **Implementation:** Compute tide height/stage from EOT20 at precompute; add a per-spot tide-suitability multiplier keyed to an "ideal tide window" parameter (mirroring Surfline's Ideal Conditions).
- **Expected impact:** Medium-high generally; low on current Med calibration (micro-tidal). Gate it so it barely moves ratings where tidal range is small — EOT20 gives the range directly.
- **Calibration / Flag:** Needs per-spot ideal-tide params → requires local knowledge/observation. Main data dependency.

### 5. Refine the energy/breaker formula to match the validated height-vs-period weighting
**Impact: medium · Feasibility: high**

- **Gap:** Rosa uses `E += H^2 · T` plus `q(T) = clamp((T/10)^1.4, 0.3, 1.2)`. Surfline: power = "height squared multiplied by period (and coefficients)," "height has proportionally more effect than period." Rosa's `H^2·T` is structurally correct, but the separate `q(T)` may double-count period.
- **Principle:** Energy flux ∝ `H^2·T` (deep-water group velocity ∝ T); period enters once, linearly, via the energy term.
- **Implementation:** Fold period influence into the energy/shoaling terms (#1) rather than also multiplying height by `q(T)`. Keep a single physically-motivated period pathway.
- **Expected impact:** Medium; correctness/calibration cleanup.
- **Calibration:** Re-fit against buoy + eye once #1 lands.

### 6. Add a set-consistency metric
**Impact: medium · Feasibility: high**

- **Gap:** Rosa outputs height + rating but nothing about "setty" vs lully. Surfline derives Wave Consistency from how often waves exceed a spot's set threshold; windswell is more consistent than groundswell.
- **Principle:** Consistency comes from spectral bandwidth and grouping — narrow-band long-period swell is pulsy; broadband windsea is steadier.
- **Implementation:** From spectral energy (#2) and directional spread (#3), compute a consistency proxy (fraction of energy above a per-spot threshold, or spectral narrowness). Present as a separate 0–100 metric — NOT folded into the rating (Surfline keeps them separate; "not a measure of surf quality").
- **Expected impact:** Medium (UX/informational).

### 7. Add an ensemble-agreement confidence score and cap it at the right horizon
**Impact: medium · Feasibility: medium**

- **Gap:** Rosa shows a single deterministic forecast, no confidence. Surfline's Forecast Probability = 21-member model agreement, days 0–9 only.
- **Principle:** Skill degrades with lead time; spread across initial-condition estimates uncertainty.
- **Implementation:** Pull multiple models (GFS, ECMWF, ICON via Open-Meteo) and/or NOAA GEFS-Wave at precompute; derive an agreement score (inverse of normalized spread in Hs/Tp/direction) per timestep. Show confidence for near range; degrade/flag the day-10–16 GFS-Wave-only tail.
- **Expected impact:** Medium — improves trust; matches Rosa's calibrate-against-reality ethos.
- **Flag:** True ensemble members increase precompute cost; multi-model agreement is a cheaper approximation.

### 8. Make the swell window a soft, exposure-weighted response instead of a hard arc
**Impact: medium · Feasibility: high**

- **Gap:** Rosa's `swell_window` is a binary in/out filter. Surfline weights every swell continuously by "relative direction to the beach" (exposed-vs-sheltered energy difference).
- **Principle:** Exposure falls off smoothly with angle off shore-normal (~cosine-like, modified by headlands), not as a step.
- **Implementation:** Replace the hard arc with a per-spot angular response function — a cosine-power window centered on the optimal swell direction, width from the spot's opening. Pairs naturally with refraction (#1).
- **Expected impact:** Medium — removes abrupt rating jumps as swell direction rotates; better handles marginal-angle swells common in enclosed basins like the Med.

---

## Data dependencies to flag
Two items need data not yet available programmatically, both mirroring Surfline's human-authored "Ideal Conditions" guides — populate via local observation or crowd input:
- Per-spot **ideal-tide windows** (#4)
- Per-spot **exposure / response-function widths** (#8)

Everything else runs on GEBCO, Open-Meteo Marine/Weather, NOAA WW3 / GFS-Wave / GEFS-Wave, NDBC/ISRAMAR, and EOT20 in a static precompute.

## Suggested build order
1. **#1 and #2 first** — they unlock #3, #5, #6.
2. Then **#8**.
3. Then **#4 and #7**.

`#1 + #2 + #3` together directly target Mediterranean short-period wind-swell — where Surfline itself said it invested most ("particular effort … for low and mid-period swells").

---

*Sources (Surfline public help center, methodology/presentation only): "What is LOTUS?", "Difference between swell and surf", "Wave Energy", "Wave Consistency", "Advanced Swell — Swell Spectra", "Surf Ratings & Colors", "Observation Clarity", "Forecast Probability", "Understanding the Spot Forecast Page on the Surfline Website".*
