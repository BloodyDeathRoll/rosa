# Calibration Log

Method: CLAUDE.md §Calibration. Log every dogfood session below; adjust height_coeff / score weights only from accumulated evidence.

## Scope & honesty (read first)
**This calibration is Israel/Med-only, not global - do not claim otherwise.** The numeric
knobs (`PERIOD_EXP`/`q(T)`, wind-gate denominator, per-spot `height_coeff`) are fit against a
handful of Israeli beaches (user's eyes + cam) and one buoy (ISRAMAR Hadera). That regime is
short-period windswell + micro-tides. It is **untested** for macro-tidal, long-period
groundswell spots (Costa Rica, Sri Lanka).

Split what generalizes from what doesn't:
- **Structural fixes generalize** - period-aware breaker height, the wind gate (offshore wind
  can't invent surf), daylight-only day-max. These are physics, true everywhere.
- **The constants do not** - they are tuned to the Med and are guesses everywhere else.

### Validation strategy (the real fix)
Ground truth for the whole world cannot come from human eyes - the user watches only a few
beaches. **Primary global validation is buoy-only:** compare Rosa's predicted `Hs`/`Tp` (model
input) and `h_break` against measured **NDBC / CDIP** buoys worldwide. No eyes needed; catches
whether the height/period math is sane **per region**. It validates *size*, not *rideability* -
that's an accepted limit.

### Admin/manual per-beach calibration (allowed, but NOT the basis)
For specific beaches we actively watch, an optional admin/manual `height_coeff` (or similar
per-spot override) may refine that **individual** spot. Strict rule: **the global formula knobs
(`PERIOD_EXP`, wind gate, defaults) are NEVER driven by these eye-based per-beach observations.**
Manual tuning is a local override on top of a buoy-validated global formula - never the
foundation of it. (Consistent with CLAUDE.md's rejection of ad-hoc user corrections as the moat.)

| Date | Time | Spot | Rosa pred (h, rating) | Observed (eyes) | Buoy (source, Hs, T) | Notes |
|------|------|------|------------------------|-----------------|----------------------|-------|
| 2026-07-19 | ~10:00 | beit-yanai | 0.5-0.8 m waist-high, GOOD 56 (day max FIRING 73) | ankle-high at best, ~0.1-0.2 m (user, cam) - Surfline forecast said 0-0.3 POOR | ISRAMAR Hadera #80 @ 07:00 UTC: Hs 0.56 m, Tp 6.5 s (OM input 0.66 m = +18% hot, minor) | **Calibration fix #1**: pred was pre-fix. Root causes: h_break ignored period; additive wind pts made night land breeze FIRING. Fixed: `q(T)=clamp(T/10,0.4,1.2)` height transform, wind gate `min(1,(size+period)/30)`, daylight-only day max. Post-fix same day: knee-high 0.3-0.4 m, FAIR 35 (day max 37) - still one bucket above Surfline's POOR; if pattern repeats, tighten wind-gate denominator (30→~60) or q floor before touching height_coeff. Cam recheck (user): ankle at best → linear q still ~2× hot. Buoy confirmed input is real (0.56 m measured) → transform was the culprit; **q steepened to quadratic `clamp((T/10)², 0.15, 1.2)`**. Final same-day output: shin-high 0.1-0.2 m, POOR 18 (day max 19) - matches cam + Surfline. Watch next: OM +18% Hs bias vs Hadera buoy (recheck on future entries before correcting); verify quadratic q doesn't under-call genuine 8-9 s Med swell days. |
| 2026-07-20 | ~12:00 | beit-yanai (+ all IL) | Fri 2026-07-24: was 0.1-0.2 m POOR 17 | Surfline LOTUS: Fri 0.3-0.6 m "poor to fair, almost surfable"; user directed heights up | - | **Calibration row 2**: quadratic q under-called Med windswell ~2-3× vs Surfline. With a ~5 s dominant period, *height* (not period) separates a flat day from a rideable one - the steep penalty erased that. Reverting fully to linear q over-called Fri to FAIR and re-opened the night-land-breeze inflation (clean knee-high night → GOOD). Settled on **q(T)=clamp((T/10)^1.4, 0.3, 1.2)** + **wind-gate denominator 30→60** (the fix-#1 pre-registered next lever). Result: Fri 0.3-0.5 m POOR 25 (poor-to-fair, not FAIR), today 0.1-0.2 m POOR, Sat 0.5-0.8 m GOOD; a clean knee-high night stays POOR (can't fire). Tension logged: this favors Surfline agreement over the single buoy-anchored 7-19 cam frame; `PERIOD_EXP` in transform.py is the dial (2.0 old → 1.0 linear). Also: breaker range widened to a real ≥0.1 m spread ("0.1-0.1" isn't a range). |

## 2026-07-23 - first multi-region buoy sweep (Pacific + Atlantic)

First buoy-only validation beyond Israel, per the strategy above. Ran the nowcast `verify` path
(`rosa-pipeline verify --buoy <id>`) against 6 active NDBC stations - model (Open-Meteo total
sea state, sampled at the buoy) vs the buoy's recent obs (Hs; mean period paired with buoy APD;
direction). No eyes involved.

| Buoy  | Climate         | n | Hs bias | Hs SI | Tp bias | dir bias |
|-------|-----------------|---|---------|-------|---------|----------|
| 46042 | CA Pacific      | 7 | +0.23 m | 0.18  | +3.5 s  | +30°     |
| 46022 | CA Pacific      | 7 | +0.25 m | 0.16  | +2.8 s  | −85°     |
| 51201 | HI groundswell  | 6 | +0.41 m | 0.37  | +3.1 s  | +42°     |
| 41013 | NC Atlantic     | 7 | +0.12 m | 0.10  | +0.9 s  | +2°      |
| 44013 | MA Atlantic     | 6 | +0.03 m | 0.11  | −0.4 s  | +65°     |
| 41008 | GA Atlantic     | 6 | +0.04 m | 0.06  | +0.7 s  | −13°     |

**Findings (directional - not yet actionable on global knobs):**
- **OM Hs runs hot everywhere, worse in the Pacific** (+0.23-0.41 m, SI 0.16-0.37) than the
  Atlantic (+0.03-0.12 m, SI ≤0.11). Same sign as the +18% Israel/Hadera note (row 1).
- **OM mean period runs ~+3 s hot in the Pacific**, ±1 s in the Atlantic. Because
  `q(T)=clamp((T/10)^1.4,0.3,1.2)` feeds on period, a hot Pacific Tp inflates q → inflates
  `h_break`. So **Pacific-groundswell spots (Costa Rica) are over-called on size on both axes
  (Hs and Tp), which compounds.** Fits the generous "Epic" seen at Tamarindo.
- **Direction inconclusive** - ±30-85°, no clean pattern; circular + tiny n.

**Per-region status after this sweep:**
- Israel (Med windswell): calibrated (rows 1-2), ISRAMAR-anchored.
- Costa Rica (E-Pacific groundswell): **no buoy in range to register; Pacific-proxy buoys say
  the input is hot on Hs + Tp → forecasts likely over-called.**
- Sri Lanka (Indian Ocean): **no buoy coverage anywhere near - cannot be buoy-validated.**

**Decision: no global-knob change on this evidence.** n=6-7 (nowcast overlap only), July is the
Pacific's small season (inflates relative Hs error), and mean-vs-APD period definitions can
diverge under long-period groundswell. Per CLAUDE.md, constants move on accumulated evidence,
not a single sweep.

**Next, in order:**
1. Accumulate lead-time truth: run `rosa-pipeline archive` daily (belongs in the cron/Oracle
   stage) so the Pacific-hot Hs/Tp pattern is confirmed over many days, not 6 hours.
2. If it holds, the safe lever is an **input-side de-bias in extract** (not a q/PERIOD_EXP
   change) - but **re-verify Israel first**: the Med constants were fit *with* the hot OM input,
   so de-biasing globally would double-correct Israel unless its knobs are refit together.
3. Interim allowed local override: a per-spot `height_coeff < 1.0` on the Costa Rica spots
   (local refinement only - must not drive the global knobs).

## 2026-07-23 - Stage-3b spectra validation, first pass (measured spectra vs assumptions)

New harness (`verify --spectra`, this session): NDBC realtime2 1-D spectra (`.data_spec`)
+ directional r1 (`.swr1`), ~45 days hourly per buoy. Measured σ = √(2(1−r1)) at the
spectral peak; narrowness truth = Goda peakedness Qp; the consistency formula is fed the
*measured* Tp/Tm-1,0/Tm02 and rank-correlated against Qp.

| Buoy | n hrs | proxy↔Qp (Spearman) | windsea σ (asm 35°) | <10s σ (asm 25°) | 10-14s σ (asm 20°) | ≥14s σ (asm 15°) |
|------|-------|---------------------|---------------------|------------------|--------------------|------------------|
| 51201 (HI) | 1091 | +0.38 | 22.5° (n=559) | 24.5° (n=415) | 30.8° (n=49) | 35.9° (n=68) |
| 46042 (CA) | 2178 | +0.49 | 22.9° (n=194) | 23.5° (n=710) | 31.4° (n=528) | 45.9° (n=746) |

**Findings:**
- **`swell <10s` assumption is excellent** (bias +0.5°/+1.5°, MAE 5-7°).
- **Long-swell (≥14 s) measured σ@peak is 36-46°, NOT the ~15° literature value** - the
  measured ordering *inverts* the parametric table (long swell reads broadest). Two candidate
  explanations, unresolved: (a) buoy r1 spread estimates are noise-broadened, worst at
  low-frequency bins (known NDBC/CDIP caveat), so σ@peak overstates true spread for
  groundswell; (b) the table is simply wrong for these climates. Single-bin σ@peak is the
  simplest defensible metric; an energy-weighted peak-region σ may be more stable - candidate
  refinement, only alongside evidence it tracks truth better.
- **Windsea measures narrower than assumed** (~22.5° vs 35°) - at the *peak* of a windsea
  spectrum, which is its most organized region; the 30-40° literature number describes the
  spectrum overall/high-frequency tail, not the peak bin.
- **Consistency proxy correlates positively with Qp (+0.38/+0.49)** - right direction,
  moderate strength. Good enough for a displayed 0-100 that never touches the rating; not
  good enough to call validated. Model-side leg (are ECMWF's pp1d/mwp/mp2 right at the buoy)
  now accumulates in `<buoy>.ecmwf.jsonl` (mwp/mp2 added to rows this session).

**Decision: no knob change; label stands.** The payload already labels spread
"parametric (modeled)" (`spectral_meta`). Publishable bound from this pass: **spread MAE
5-13° for windsea/short-swell classes, up to 21-31° for ≥14 s groundswell (assumption
unreliable there)**. Re-run across more buoys (Atlantic set has fewer long-period peaks;
CDIP stations would arbitrate the r1-noise question) before touching SPREAD_* constants.

## 2026-07-23 - Stage-3b spectra sweep #2: CDIP arbitration (12 stations, ~22k hrs)

Added 4 CDIP Datawell Waverider stations (46218 Harvest, 46225 Torrey Pines, 51202
Mokapu, 51205 Pauwela - `data/buoys/cdip.yaml`) and swept `verify --spectra` across the
whole registry. Waverider vs discus-hull comparison resolves the ≥14 s question from
this morning's entry:

| Station (hull) | n ≥14s | measured σ ≥14s | proxy↔Qp r |
|---|---|---|---|
| 46225 Torrey Pines (**Waverider**) | 937 | **23.5°** | +0.36 |
| 46218 Harvest (**Waverider**) | 534 | **25.4°** | +0.48 |
| 51201 Waimea (Waverider) | 68 | 35.9° (weak summer N-Pac peaks, small n) | +0.38 |
| 46042 Monterey (discus) | 747 | 45.9° | +0.49 |
| 46026 SF (discus) | 699 | 38.9° | +0.41 |
| 46059 W-CA (discus) | 469 | 60.4° | +0.51 |
| 46022 Eel River (discus) | 255 | 61.7° | +0.72 |
| 44013 / 41008 / 41013 (discus, Atlantic) | 5-34 | 50-64° (tiny n) | +0.47-0.72 |

**Verdict - both hypotheses were partly right:**
- **Discus σ is instrument-broadened** (39-64° vs Waverider 23-26° for the same class):
  never tune spread from discus stations.
- **The literature 15° was still too narrow**: clean Waverider truth converges on ~24°
  for ≥14 s peaks. → `SPREAD_LONG_SWELL_DEG` 15 → **24** (the one knob moved; the sweep
  IS the accumulated evidence: two independent instruments, 1471 hrs of ≥14 s peaks).
- Other classes measured within a few degrees of assumptions on Waveriders
  (10-14 s: 19.8-25.5° vs 20; <10 s: 23-32° vs 25; HI trade windsea 32-34° vs 35) - stand.
- **Consistency proxy↔Qp positive at every one of 12 stations** (+0.34…+0.72, median
  ~+0.48). Good enough for the displayed, non-rating 0-100; formula-level validation done.
  Model-side leg (ECMWF periods at buoys) still accumulates in the `.ecmwf` archive.
- Ops fix: 51101 publishes no spectral files → harness now reports that honestly
  instead of crashing (404 → "met-only or non-spectral buoy").

## 2026-07-25 - dogfood: Hilton (TLV), Stage-2 hybrid **under**-called

First eye-check of an autonomously-pushed swell (the swell-event push flagged as
calibration-suspect in the handoff).

| Date | Time | Spot | Rosa pred (h, rating) | Observed (eyes) | Buoy | Notes |
|------|------|------|------------------------|-----------------|------|-------|
| 2026-07-25 | day (hour not recorded) | hilton | 0.5-0.8 m, GOOD 50-53 (run 2026-07-25T02:36Z; the 07-23 run that fired the push said 0.5-0.9 m, GOOD 61) | **1.0-1.2 m** (user) | - (ISRAMAR not pulled) | Under-call ≈ **1.6×** on the range midpoint (0.65 m vs ~1.1 m). Model input at the offshore point: in-window swell **Hs 1.4-1.5 m, Tm 5.8-6.0 s, Tp 8.4 s, dir ~291°**, wind 11-15 kph cross-shore. So the hybrid transform attenuated 1.5 m → 0.65 m (≈0.43×) - the suspect term is `period_rideability`, which is doing most of that work at Tm ~6 s despite a genuine 8.4 s peak. |

**Reading:** this is the *opposite* sign to rows 1-2 (which over-called Med windswell and
drove `PERIOD_EXP` up to 1.4 / the quadratic-then-1.4 saga). Those rows were small,
short-period days; this is a real 1.5 m / 8.4 s Med swell. Working hypothesis: the
rideability attenuation is tuned on the flat end and is too aggressive once actual swell
energy shows up - i.e. Rosa may be compressing the whole Med height range toward the
middle. One observation is not evidence; **no knob touched.**

**Pre-registered for Stage 2E (~07-30, when the VM archive matures):** check whether
rideability keyed on **Tm** (5.9 s) rather than **Tp** (8.4 s) is the under-call mechanism
at Hilton, and whether a Tp-aware (or spectral-band-aware) rideability fixes this day
*without* re-inflating the 2026-07-19/20 flat-day frames. Both regimes must be satisfied
by whatever lands - do not fit one and break the other.

## 2026-07-26 - dogfood: Hilton (TLV) again, **under**-called ~2x on a SMALL day

Second eye-check at Hilton, user standing on the beach ~12:00 local. First data point
on Hilton's corrected pin (moved ~200 m SW this morning, `user-verified 2026-07-26`)
and its freshly re-cut depth profile, so the bathymetry is not the stale-profile bug.

| Date | Time | Spot | Rosa pred (h, rating) | Surfline | Observed (eyes) | Notes |
|------|------|------|------------------------|----------|-----------------|-------|
| 2026-07-26 | 12:00 local (09:00Z) | hilton | **0.2-0.3 m** (mid 0.3), POOR 21 (run 2026-07-26T08:36Z) | 0.3-0.6 m | **0.5-0.6 m** (user: "even 0.5-0.6") | Under-call ~**2x** on the midpoint. Model input at the offshore point: in-window swell **Hs 0.82 m, Tp 7.0 s, Tm 5.0 s, dir 301**, wind 15.8 kph onshore (315), tide -0.25 m. Transform took 0.82 m -> 0.25 m = **0.30x**; the observation implies ~**0.67x**. Surfline's top of range was right, its bottom was not. |

**Why this one matters more than a repeat:** the 07-25 entry under-called a *big*
day (Hs 1.5 m, Tp 8.4 s) and the working hypothesis was that `period_rideability` is
"tuned on the flat end and too aggressive once real energy shows up". This day is the
opposite end - Hs 0.82 m, Tp 7.0 s, Tm 5.0 s, an ordinary Med windswell - and it still
under-calls, by *more* (2x vs 1.6x). So the error is **not** confined to big swells:
the attenuation looks too aggressive across the range, not just at the top.

Note the Tm/Tp gap is even wider here (5.0 vs 7.0 s) than on 07-25 (5.9 vs 8.4 s), and
the under-call is worse - consistent with, though not proof of, the pre-registered
suspicion that rideability keyed on **Tm** is the mechanism.

Rows 1-2 (2026-07-19/20) over-called Med windswell; these two under-call it. Between
them sits Stage 2B (hybrid physics + rideability), so the transform, not the input,
is the thing that flipped sign. **No knob touched** - two observations, and Stage 2E
tuning is gated on the VM archive maturing (~07-30). When it lands, this row and the
07-25 row are the two Med frames any candidate must satisfy together with the
07-19/20 flat-day frames.

## 2026-07-26 - Stage-2E harness built; first pre-registered run (no knobs moved)

The 2E experiment is now executable: `rosa-pipeline experiment` grades candidate
rideability transforms against machine-readable frames (`data/calibration/frames.yaml`,
distilled from this log: 07-19 flat, 07-24 windswell, 07-25 + 07-26 Hilton under-calls).
Candidates inject via a `rideability` hook on `breaker_height_from_profile`; the shipping
path is untouched and a regression test pins the baseline to the published 07-26 output.
Inputs for the two 2026-07-19/24 frames were reconstructed from the OM historical archive
(hindcast); 07-25/26 are as logged. All frames grade on today's committed profiles
(hilton = the corrected 2026-07-26 pin).

First run, grid = {mean, peak, energy(Te)} x exp {1.0, 1.2, 1.4, 1.6}:

- **Shipping (mean^1.4)**: passes both small-day frames, under-calls both Hilton frames
  (-0.36 m / -0.22 m). Reproduces reality - the harness is faithful.
- **Tp-keyed candidates (peak^1.0-1.4) fix BOTH Hilton frames and hold the 07-24
  windswell frame** - the pre-registered mechanism is confirmed as *a* mechanism.
- **But every Tp/Te candidate over-calls the 07-19 flat frame** (+0.10 to +0.20 m,
  band 0.1-0.2 m). That day also had a wide Tm/Tp gap (5.05/6.95) yet was ankle-high.
- **No candidate passes all four frames.** Least-bad: energy^1.4 (max |err| 0.11 m).

**Reading:** switching the period key alone trades the under-call for a flat-day
over-call - the same tension rows 1-2 fought from the other side. The unresolved axis is
likely *input* error, not transform: OM ran +18% hot on Hs on the 07-19 day (Hadera
buoy), and the archive de-bias (2E's other half, ~07-30) is exactly the missing term.
Candidate for the full 2E fit: de-biased inputs + Tp/Te-keyed rideability, re-run this
harness, require all four frames plus no regression on the buoy-validated regions.
**No knob moved today.**

## 2026-07-27 - dogfood: Poleg, **under**-called again (third Med frame, no knobs moved)

Dawn session, user in the water (reported ~07:20 local, "was just in").

| Date | Time | Spot | Rosa pred (h, rating) | Observed (eyes) | Buoy | Notes |
|------|------|------|------------------------|-----------------|------|-------|
| 2026-07-27 | ~05:30-07:00 | poleg | 0.4-0.6 m, GOOD 56 @ 06:00 (FAIR 43 by 09:00) | **0.8-1.0 m** (user) | - (not pulled; VM archive has the cycle) | Under-call ≈ **1.8x** on the range midpoint (0.5 m vs ~0.9 m). Model input at the offshore point (06:00): in-window swell **Hs 1.08 m, Tm 6.2 s, Tp 7.7 s, dir 292°**, wind 4 kph offshore. Same signature as the two Hilton rows: transform attenuates ~1.1 m offshore to ~0.5 m breaking, wide Tm/Tp gap (6.2 vs 7.7 s). |

**Reading:** third consecutive Israel under-call with the same mechanism fingerprint
(rideability keyed on Tm while a genuinely longer Tp carries the energy), now at a
second spot (poleg, not just hilton) - this rules out a bad Hilton bathy profile as
the sole cause. Pattern is now 3 under-call frames vs the 2 flat-day frames; still
**no knob touched** - Stage 2E (input de-bias + re-run `rosa-pipeline experiment`,
~07-30) owns the fit. Add this day as a fifth frame to
`data/calibration/frames.yaml` when 2E runs (inputs above; grade on poleg's
committed profile).

## 2026-07-29 - exposure rebuilt: a swell is a fan, not a pencil beam (structural)

User-reported, with a Surfline side-by-side: **"we CANNOT have a 0-0.1 range on spot when
there is over a meter in the deep. That DOES NOT HAPPEN AND CANNOT HAPPEN."** Correct - and
Rosa was doing it at 419 of ~24,000 published hours.

| Date | Time | Spot | Rosa pred (h) | Surfline (same hour) | Buoy | Notes |
|------|------|------|---------------|----------------------|------|-------|
| 2026-07-28 | 06:00 | pipeline | **0.0-0.1 m** | 0.6-0.9 m | - | offshore 1.8 m @ 6.8 s from 65° |
| 2026-07-28 | 09:00 | pipeline | **0.0-0.1 m** | 0.3-0.6 m | - | offshore 1.8 m @ 7.5 s from 67° |
| 2026-07-28 | 12:00-21:00 | pipeline | 0.1-0.2 m | 0.3-0.6 m | - | offshore 1.8-2.0 m, ENE trade windswell all day |
| 2026-07-29 | all day | fishermen | **0.0-0.1 m** 69% of hours | - | - | in-window 18.8 s swell present and still zeroed |

**Three faults, one mistake: the model treated each partition as a single bearing.**

1. **Exposure** evaluated `exposure_weight` at the partition's mean direction only, so a swell
   whose mean sat outside the arc was deleted whole - even though a real partition's energy
   fans over ±20-35°. Now `spread_exposure()` integrates the existing window/shoulder curve
   over a Gaussian of the partition's own spread (`spectral.parametric_spread_deg`, the values
   the CDIP Waverider arbitration already fixed on 2026-07-23), truncated at ±3σ, 41-point
   quadrature, `lru_cache`d on whole degrees. Energy units - callers take `sqrt()` for an
   amplitude weight.
2. **Refraction** then measured that same swell from its mean too, so what the fan delivered
   was cancelled again as "arriving from behind the beach" (incidence ≥ 90° returns 0). The
   energy that gets in arrives over the window's edge, so `arriving_direction()` now supplies
   the incidence. **Without this second half, Pipeline was still 3x under-called** - the fix is
   only complete with both.
3. A **window reaching past the shore normal** (wrapping points, bay mouths: whiskey-point's
   arc sits 99-111° off its normal) is the spot's own local knowledge that the arc reaches the
   break. That now marches at `GRAZING_INCIDENCE_DEG = 85°` rather than being cancelled by a
   derived normal. Refraction leaves very little there - but not nothing.

Also: `energy_kj_per_m`/`energy_in_window`/`height_in_window`/`effective_height_in_window` were
still on the **hard** window while the height used the soft one, so rows showed real surf beside
**0 kJ** (visible in the user's 07-28 screenshots). All four now use the same spread-aware
exposure.

**Result (199 spots, 24,216 hours compared against the previously published payloads):**

- impossible zeros (≥1 m offshore, ~0 at the spot): **419 → 2** (both at ingrina, an Algarve
  cove whose swell arrives more than a fan-width behind its headland).
- height on hours that already had surf: **median x1.00**, 10th x0.90, 90th x1.00.
- **Israel, the coast every constant in this log was fit against: x1.00 at every percentile.**
  The five calibration frames and the open Stage-2E question are therefore untouched - this
  changes which swells *reach* a spot, not how a reaching swell is transformed.
- pipeline now tracks Surfline hour by hour (0.3-0.5 / 0.4-0.6 vs their 0.3-0.6).

**No calibration constant moved**: `PERIOD_EXP`, `RIDEABILITY_EXP`, `BREAK_GAMMA`, the wind gate
and every per-spot `height_coeff` are as they were. This is a structural fix in the sense of
§Scope - it is geometry, true everywhere, not a Med-fit number.

**Data faults found in the same hunt** (they compounded the above, and were separately fatal):

- **Ten spots aimed their depth ray up to 102° away from the sea they face.** `shore_normal`
  defaults to `offshore_direction + 180`; where `offshore_direction` was osm-seeded wrong, the
  bathymetry ray went with it. **fishermen** ran ENE inland with six of nine samples on dry
  land (deep end +7 m *above* sea level), which zeroed its breaker height regardless of swell.
  Explicit `shore_normal` set and profiles re-cut for all ten; fishermen's ray now reaches
  1742 m of open ocean and the spot reads a steady 0.9-1.5 m.
- **fishermen `offshore_direction: 258`** called the SW monsoon *offshore* at a south-facing
  bay (it rated FIRING 91 while claiming zero surf). Corrected to 0; the DB-wide median
  disagreement between a spot's wind direction and its own coastline is 0°, so 102° was a true
  outlier. Now cross-shore, rating 77.

**Guards added** (`test_spots.py`) so none of this can rot back in silently: the depth ray and
the sample point must aim at the same sea (≤45°); a profile's deep end must be underwater;
offshore wind must blow from the land (<90° from `shore_normal + 180`). Six tests in
`test_transform.py` pin the fan itself, including the literal rule this entry opens with.

**Caveats / watch items:**

- The spreads are **modeled per partition class, not measured hourly**. The same CDIP sweep
  found ≥14 s measured σ of 36-46° against the assumed 24° - unresolved, and if anything means
  real fans are *wider* than assumed, so this fix is conservative.
- The Gaussian is truncated at ±3σ; a swell arriving from behind the coast still leaks ~0.5% of
  its energy (≈7% of amplitude) where the tail grazes the arc. Deliberate - it is what keeps
  the "never zero with a real sea offshore" rule true - but it is a floor, not a measurement.
- Three spots still sit 65-73° between wind direction and coastline (matapalo-osa, okanda,
  peanut-farm) - under the new guard's 90° bound, but worth local-knowledge review.
- The partition **direction wander** that first drew attention here (hiriketiya's 12 s
  groundswell reported at 189° → 224° → 276° → 255° → 192° across one day) is *not* fixed by
  this. The fan absorbs it where the wander is within a fan-width; beyond that it remains an
  Open-Meteo partition-quality issue, and temporal smoothing of long-period partition direction
  is the next candidate if it recurs.

## 2026-07-29 (PM) - Stage-2E dry run: the period "hot bias" is mostly a harness artifact

Dry run of the Stage-2E sweep a day before the archive matures, to smoke-test the path and
preview the numbers. It changed the plan. **No knobs moved; no code changed.** Archive pulled
from rosa-instance: 7.1 d of Open-Meteo (~40 runs/buoy), 5.7 d of GFS-Wave, 5.6 d of ECMWF
across 13 stations; obs captured once per buoy and replayed so all three sources score the
same truth.

### 1. Open-Meteo `wave_period` is Tm-1,0, and we have been scoring it against Tm02

`verify.py` pairs OM's `wave_period` with the buoy's **APD** on the reasoning that both are
"mean" periods. NDBC's APD is **Tm02** = √(m0/m2); OM's field is the **energy period Tm-1,0** =
m-1/m0. For any real spectrum Tm-1,0 > Tm02, so the pairing manufactures a positive bias.

Settled empirically against NDBC spectral files (the Session-7 `spectra.py` harness), pairing
the archived 0-1 d OM period to the *same buoy-hour's* measured moments:

| OM period minus... | n | bias | mae | rmse |
|--------------------|---|------|-----|------|
| Tm-1,0 (energy period) | 1158 | **+0.54 s** | 0.99 s | 1.24 s |
| Tm02 (= NDBC APD)      | 1158 | +2.67 s | 2.67 s | 2.94 s |
| Tp (peak)              | 1158 | −2.52 s | 3.27 s | 4.56 s |

Six of seven stations land closest to Tm-1,0 (51201 Waimea is closest to Tp - narrow
groundswell, where Tm-1,0 ≈ Tp). Per-station the measured Tm-1,0−Tm02 gap tracks the apparent
bias almost exactly where the sea is simple: 44013 gap 1.35 s vs apparent bias 1.36 s; 46225
gap 3.69 vs 3.68. The residual - the honest model error - is **+1.1 s at 46042, +0.5 at 46022,
−0.05 at 46059, −0.03 at 44013**.

**Consequence: the planned Stage-2E period de-bias would have been wrong.** The 2026-07-23
entry's "OM mean period runs ~+3 s hot in the Pacific" is ~80% definitional. Subtracting the
APD-paired number would have driven the input **~2 s cold**, and period feeds shoaling *and*
`period_rideability` - it would have corrupted `h_break` fleet-wide in the name of calibration.
Fix the harness pairing before fitting anything to it. (Israel is unaffected either way: no
NDBC/CDIP station is in range of the Med.)

### 2. Hs: the fleet mean hides a sign flip by station class

Fleet Hs bias is now **−0.04 m @0-1 d** (n=9774), which reads like "OM is unbiased" and is
misleading. Per station, the offshore discus buoys run hot and the CDIP Waveriders run cold:

- discus: 46042 +0.12, 46026 +0.11, 46022 +0.17, 46059 +0.05, 41013 +0.07, 51201 +0.16,
  41008 −0.01, 44013 −0.09
- Waverider: 46218 −0.12, 46225 −0.15, **51202 −0.49, 51205 −0.53**

The split tracks the instrument, not the basin (51201 Waimea and 51205 Pauwela are both Hawaii,
opposite signs). Session 7 already found discus-hull directional spread is instrument-broadened;
this is the same lesson on Hs. **A single global Hs de-bias is not defensible** - the per-station
spread (−0.53…+0.17) dwarfs the fleet mean. Also note the 07-23 "Pacific +0.23-0.41 m hot"
figure roughly halves under proper sampling (46042 +0.23→+0.12, 51201 +0.41→+0.16): it was
n=6-7 nowcast hours.

### 3. Three-way A/B (Stage 3a/3b), matched hours

Scored over the **identical** (buoy, valid-hour, lead) triples for all three sources, so the
4×/day vs 00z/12z cadence difference cannot drive it (n=284 @0-1 d; small - the intersection is
sparse until ECMWF matures, but the ranking is the same as the unmatched full-sample run):

| var | lead | om | gfswave | ecmwf |
|-----|------|----|---------|-------|
| Hs bias / mae | 0-1d | −0.06 / 0.20 | −0.16 / 0.25 | **+0.05 / 0.21** |
| period bias / mae | 0-1d | +2.45 / 2.45 (vs APD - see §1) | **+0.44 / 1.73** | −0.93 / 2.04 |
| dir bias / mae | 0-1d | +15.1 / 34.1 | **−5.9 / 28.7** | +12.5 / 32.7 |

- **GFS-Wave does not beat Open-Meteo on Hs** - it is ~0.15 m low at every lead. That answers
  the open 3a question: no source swap for height.
- GFS-Wave is the best **direction** source (MAE 28.7° vs 34.1°), and OM carries a consistent
  **+15…+18° clockwise** direction bias at all leads. That is a live candidate for an input-side
  correction because it feeds `spread_exposure()` directly - but it is measured against total-sea
  `mwd`, not per-partition directions, so it does **not** transfer to the partition fields the
  transform actually consumes. Do not apply it blind.
- The period column is not a fair three-way race: OM is scored against APD and the others
  against DPD. §1 must land before this row means anything.

### 4. Station health

**51101 (NW Hawaii) has been contributing nothing.** It responds (no longer 404, cf. sweep #2)
but reports `MM` for WVHT/DPD/APD/MWD back to at least 2026-06-14 - met-only, wave sensor down.
It produced **zero pairs in all three sources** while we archive it 4×/day. ✅ **Removed from
`data/buoys/ndbc.yaml` same day** (registry 13 → 12 stations), with its coordinates left in a
comment there so it can be restored the moment NDBC brings the wave payload back. Note the
failure mode for the next registry review: a station that answers with met data still looks
healthy from the outside - only the pair count reveals it.

### Actions

1. ✅ **DONE same day - the OM period pairing is fixed.** `verify.py` now pairs the model
   period against **Tm-1,0 measured from the station's own spectrum**
   (`ENERGY_PERIOD_VARIABLES` + `with_energy_period()`, wired for the `om` source in both the
   nowcast and archive paths). Stations that publish no spectra fall back to the APD pairing,
   but loudly: the row is labelled `Mean per. vs APD`, the CLI says which station degraded and
   why, and both renderers append "report it, never calibrate against it". Hours with no
   spectrum inside the tolerance drop out of period scoring rather than silently reverting to
   APD. Re-run over the same archive, same n: **fleet period bias +2.81 s → +0.51 s**, RMSE at
   46042 3.71 s → 1.51 s, per-station 46042 +1.07, 46022 +0.40, 46059 −0.14, 41013 +0.41,
   44013 −0.07, 51201 +1.40, 46225 +0.46. GFS-Wave and ECMWF pairings are untouched (they
   genuinely publish peak periods and were already correctly matched to DPD). 284 tests green,
   4 new - including one that pins the definitional bias itself so this cannot rot back in.
2. ✅ **DONE same day - `render_lead_scorecard` now prints bias and MAE, not rmse alone.**
   This is *why* the period fault survived six days of archive: rmse is unsigned, so a +2.8 s
   systematic offset and random scatter look identical on an rmse-only card. The lead card is
   now one row per lead × variable with bias first, matching `render_scorecard`. Reading it
   immediately shows something the old card could not: at 46042 the Hs bias **grows with lead**
   (+0.12 m @0-1 d → +0.23 m @3-5 d) and so does the direction bias (+19.7° → +35.0°). Rule for
   any future skill metric: **if it cannot show sign, it cannot show a bias - publish both.**
3. Any de-bias must be per-station-class (or per-source) - never one global constant.
4. Keep 51201/51202/51205 apart when judging Hawaii: they disagree by 0.7 m.
5. Unchanged by this entry: the Tm-vs-Tp under-call question (CLAUDE.md §UI) and whether
   `period_rideability` should key on Tp - if anything §1 sharpens it, since the input period is
   an *energy* period, further still from the Tp shown on screen.

## 2026-07-29 (PM) - partition direction wander: quantified, and NOT worth smoothing

Closes the SESSION-9 watch item ("temporal smoothing of long-period partition direction is
the next candidate **if it recurs**"). Measured across the whole fleet: 203 published payloads,
**24,531 consecutive 3 h transitions**, ~62,700 partition-slot transitions. No code changed.

### It recurs - but almost all of it is in partitions that do not matter

Slot-wise (following `swells[i]` across the step, as a naive smoother would):

| period band | n | median | p90 | p99 | >45 deg |
|---|---|---|---|---|---|
| <8 s windsea | 32,674 | 3 deg | 37 | 116 | 8.02% |
| 8-12 s | 18,986 | 1 deg | 35 | 97 | 6.06% |
| >=12 s groundswell | 11,037 | 1 deg | 27 | 93 | 4.78% |

The median step is 1-3 deg: the field is quiet, and the wander lives entirely in the tail.
And the tail is concentrated in **weak** partitions - median height 0.24 m when a slot jumps
>45 deg vs 0.52 m when it does not, and the jumping partition carries a median **4.2%** of the
hour's H^2*T energy.

### A third of the "wander" is not wander at all - it is the labels moving

Matching each hour's partitions to the next hour's over all permutations (direction + period),
**13.0%** of transitions have a best match that is *not* the identity: Open-Meteo's
primary/secondary/tertiary slots reshuffle, so following a slot index follows a *different
physical swell*. Following the matched swell instead:

| period band | p90 slot-wise | p90 matched | >45 deg slot-wise | matched |
|---|---|---|---|---|
| 8-12 s | 35 deg | 25 deg | 6.06% | 3.73% |
| >=12 s | 27 deg | **13 deg** | 4.78% | 3.15% |

**This is why slot-wise temporal smoothing would have been a bug, not a fix.** It would blend
two unrelated swells in 13% of transitions - degrading a calculation that is currently correct.

### And the labels cannot affect the forecast anyway

Everything downstream is **order-independent**: `energy_in_window` sums over partitions,
`h_break` combines them RMS, and `dominant_partition` picks by max exposure-weighted energy.
Slot order changes only which swell the UI lists first. So the 13% reshuffle has *zero*
forecast impact, and the honest wander figure is the matched one (>=12 s: p90 13 deg).

### What actually reaches the forecast: 1.80% of transitions

The dominant partition jumped >45 deg in **441 of 24,531** transitions (1.80%), mostly in the
8-12 s band (218) rather than true groundswell (50). By region - the tropics' multi-swell seas,
not the Med:

| region | rate | | region | rate |
|---|---|---|---|---|
| hawaii | 5.88% (n=119) | | portugal | 1.72% |
| sri-lanka | 3.62% | | costa-rica | 0.94% |
| philippines | 3.36% | | nicaragua | 0.90% |
| japan | 3.19% | | **israel** | **0.06%** |

Downstream effect on the published rows, big-jump steps vs the rest:

- rating: median 3.0 pts either way; **p90 17 vs 10**
- h_mid: median 0.000 m either way; **p90 0.30 vs 0.10 m**

The medians are *identical* - SESSION 9's spread-aware exposure is absorbing the ordinary case
exactly as claimed, because a fan that spans 40-70 deg does not care about a 20 deg wobble.
Only the tail survives, as visible jitter in the hourly table.

### Decision: no smoothing. Watch item closed.

1. Slot-wise smoothing is **wrong** (blends different swells 13% of the time).
2. Any smoothing is **unnecessary** for the physics - the transform is order-free and the fan
   already absorbs the median case.
3. The residual is **1.8% of rows, tail-only**, in genuinely ambiguous tropical multi-swell
   conditions. That is real model uncertainty, and we already surface it: `spectral.consistency`
   is exactly the "is this sea state coherent?" signal.

If it is ever revisited, the principled route is partition **tracking** (match by
direction+period across hours, as this analysis does) for **display** stability only - never a
filter on the directions the physics consumes.

Footnote: hiriketiya's original excursion (189 -> 224 -> 276 -> 255 -> 192 deg) is **absent** in
the current run - its 12 s swell holds 191-199 deg all day. The 07-29 case was transient, which
is itself the argument against tuning a constant to it.
