# Calibration Log

Log every dogfood session below — date/time, spot, Rosa predicted height+rating, observed reality
(user's eyes), buoy reading if available. Adjust `height_coeff` / score weights only from
accumulated evidence, never a single session.

## Method rules (hard-won — read before running any sweep or grading any candidate)

- **A skill metric that cannot show sign cannot show a bias** — always publish bias alongside rmse.
- **Score candidates with the shipped harness, never a scratchpad reimplementation** (the harness grades the predicted MIDPOINT, not the displayed range).
- **Fleet impact is only valid as a same-input A/B** — comparing against an older `data/out` snapshot mixes the code change with the weather.
- **Any cross-source claim needs a control group + a deep-water check.** Three comparison artifacts have been caught this way (APD-vs-Tm-1,0, blended `mwd`, OM's partition closure).
- **Pair periods like-for-like:** Open-Meteo serves the energy period Tm-1,0, NDBC's APD is Tm02, and Tm-1,0 > Tm02 always. Stations without spectra fall back loudly and are never calibrated against.
- **Hs bias tracks the instrument, not the basin** — discus buoys read the model hot, CDIP Waveriders cold; 51201 vs 51202/51205 are the same ocean with opposite signs. No global de-bias is defensible; keep station classes apart.
- **Match on direction and period, never partition slot index** — partition order is not comparable across providers.
- **Partition direction wander is CLOSED — do not build temporal smoothing.** The transform is order-independent. If ever revisited: partition *tracking* for display order only, never a filter on the directions the physics consumes.

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

**Coverage reality (2026-08-04).** NDBC and CDIP are US-only networks, so "worldwide" was
aspirational: the 12 registered buoys are all California / Hawaii / US East Coast, next to 2 of
199 spots. The first fleet run (107,596 paired hours, all 12 buoys, 5 lead bands) said the
height math is sound - rmse 0.25 m at 0-1 d rising to 0.38 m at 7 d+, no outlier station - but
it said it about the wrong ocean. It also reproduced the instrument split from the method rules
above (0-1 d bias: CDIP Waveriders -0.24 m vs NDBC discus +0.05 m, converging to ~0 by 5-7 d;
a real model bias would persist across leads, so this is the instruments) and showed the
"+16° clockwise" direction bias is an average hiding sign flips - per station it runs
**-11.4° (Pauwela) to +28.4° (Mokapu)**. A blanket direction correction is not defensible.

**Portugal now has in-situ truth** (`data/buoys/cmems.yaml`): Leixoes, Sines and Faro, from the
Copernicus in-situ IBI product, north-to-south along the coast. Free/open, **attribution
required**, and the per-platform daily NetCDF files need no account - public S3. These are the
only non-US wave buoys Rosa can reach; japan / sri-lanka / philippines / costa-rica / nicaragua
still have none, and israel's only nearby platform is ISRAMAR's, which stays off-limits.
First live read (small n, nowcast window only - the lead-time archive starts accruing from the
next cycle): Hs bias **+0.01 m Leixoes, -0.04 m Sines, +0.14 m Faro**.

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
5. Unchanged by this entry: the Tm-vs-Tp under-call question (docs/UI.md) and whether
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

## 2026-07-29 (PM) - ingrina's 2 "impossible zeros" are correct physics

Closes the last SESSION-9 watch item. **No bug, no code change.** The audit heuristic that
flagged them is what needs the caveat.

### The two hours

Both are the same event - 2026-08-10 06:00 and 09:00 local, a 1.0-1.1 m / 8 s sea from
313-314 deg with no in-window partition, published as 0.0-0.1 m. Ingrina is a south-facing
Algarve cove (`swell_window [90, 220]`, `offshore_direction 0`), so 314 deg is arriving from
over the land and the transform gives it no exposure.

### Why it is right, in three independent checks

1. **The wind agrees with the waves.** Through the whole event the wind is 18-25 kph from
   346-351 deg - *offshore* at Ingrina - and the sea runs the same way. This is a northerly
   (nortada) generating sea in the Gulf of Cadiz that travels SOUTH, away from a lee shore.
   A surfer standing there sees flat, glassy water. Rating 1 is the honest answer.
2. **The offshore field is real, not a coastal-cell artifact.** Sampling the model at 5, 10,
   20 and 30 km due south returns the same NNW direction (322-351 deg) at every distance, and
   the height GROWS with distance from the coast (0.96 -> 1.04 -> 1.12 -> 1.14 m). That is the
   fetch signature of a locally generated wind sea, exactly as a northerly over the Gulf
   should look. (Noted in passing: the requested 5 km point snaps 4.4 km back to a grid cell
   at 37.0417, effectively on the shoreline - Open-Meteo's marine grid is ~1/12 deg here. It
   does not change the answer, but `offshore_km: 5` buys no separation at this spot.)
3. **The rest of the coastline corroborates.** At the same hour, ranked by window orientation:
   Nazare/Ericeira/Peniche `[235,340]` 1.1-1.4 m -> Supertubos `[180,290]` 0.30 -> Carcavelos
   `[170,270]` 0.10 -> Zavial `[160,260]` 0.10 -> **Ingrina `[90,220]` 0.00**. Monotonic in
   window orientation, and it is the textbook Algarve pattern: NW swell lights the west coast
   while the south coast is flat.

### The lesson is about the audit, not the forecast

The invariant from the exposure rebuild - *"a metre offshore can never read as ~0 at the
spot"* - needs its missing clause: **...when that metre is arriving from a direction the
coastline can actually see.** The SESSION-9 bug was in-window energy being cancelled; this is
out-of-window energy correctly ignored. An audit that flags on offshore height alone cannot
tell the two apart, and will keep re-flagging lee-shore hours forever. Any future zero-audit
should additionally require that some partition is in-window (or that the wind is not offshore)
before calling a zero impossible.

Counter-lesson still standing (SESSION 9): do not declare a zero correct from reasoning alone.
Here it took the wind agreeing with the waves, the fetch gradient offshore, and 42 neighbouring
spots ordered by exposure - not one argument.

### One genuine open question, for local knowledge only

Ingrina's window ends at 220 deg while its neighbour Zavial's reaches 260 deg. Real Ingrina
does pick up some W/SW wrap around Sagres, so the narrower window may be under-calling wrapped
swell there. That is a spot-DB judgement, not a formula one - **user/local knowledge decides**,
per the coordinate-authority ladder. Flagged, not changed.

## 2026-07-30 - Stage 2E resolved: rideability keys on Tp (first knob moved since row 2)

The archive matured. Both halves of 2E ran on the SESSION-10-fixed harness, and they
answered in opposite directions: **the input needs no correction at all, and the transform
needs one.**

### 1. The buoy half: no input de-bias is defensible. 2E's planned fit is off the table.

Full sweep, 12 stations x 3 archived sources, `verify --archive` per source.
Open-Meteo, n = 45,252 pairs (vs the 6-7 nowcast hours the 07-23 sweep drew on):

| var | fleet bias | mae | by class |
|-----|-----------|-----|----------|
| Hs | **-0.005 m** | 0.223 | CDIP Waverider **-0.299**, NDBC discus **+0.088** |
| Energy period (vs measured Tm-1,0) | **+0.209 s** | 0.863 | CDIP +0.078, NDBC +0.250 |
| Direction | **+15.58 deg** | 33.79 | CDIP +11.6, NDBC +16.8 |

- **The period question is closed.** +0.21 s fleet-wide. SESSION 10's "the hot bias was our
  own pairing bug" holds at 7x the sample. The input de-bias that Stage 2E was originally
  built around would have been a pure fabrication.
- **Hs has no global bias to remove** - the -0.005 m fleet mean is *cancellation*, not
  accuracy. It still tracks the instrument, not the basin: Hawaii's 51201 reads **+0.232**
  while 51202/51205 read **-0.498/-0.466**. Confirms 10c at scale.
- Hs bias grows with lead (-0.035 m @0-1d -> +0.125 @7d+), as does direction
  (+12.7 -> +19.9 deg). Only visible because the scorecard prints sign (SESSION 10b).

**Three-way A/B, matched hours.** Open-Meteo stays the height source; GFS-Wave is confirmed
the better direction source but still cannot be applied:

| source | Hs bias | Hs mae | Dir bias | Dir mae |
|--------|---------|--------|----------|---------|
| Open-Meteo | -0.005 | **0.223** | +15.58 | 33.79 |
| GFS-Wave | -0.119 | 0.279 | **-0.700** | **30.05** |
| ECMWF | +0.074 | 0.247 | +16.23 | 33.43 |

GFS-Wave runs ~0.12 m low fleet-wide and loses on Hs mae at every lead - **no source swap**,
same verdict as 07-29 on a far larger sample. Its direction is near-unbiased where OM and
ECMWF share a ~+16 deg clockwise lean. Still NOT actionable: measured on total-sea `mwd`,
not the per-partition directions `spread_exposure()` consumes (SESSION 10d's caveat stands).

### 2. The Israel half: the transform was keying on the wrong period. KNOB MOVED.

Added the 2026-07-27 **Poleg** frame the 07-27 entry earmarked (fifth frame; inputs as
logged, tide -0.27 m reconstructed from the OM marine archive at poleg's offshore point,
which corroborates the logged partitions within 0.04 m / 0.2 s).

Grid {mean, peak, energy} x exp {1.0, 1.2, 1.4, 1.6}, then a wider sweep to exp 3.0:

- **Every mean-keyed row now under-calls three of the five frames** (Hilton x2, Poleg),
  by -0.22 to -0.43 m. Shipping `mean^1.4` was the worst of them on Hilton 07-25 (-0.37).
- **Every peak-keyed row fixes them.** `peak^1.4` puts all three inside their observed band
  or within 0.12 m of it.
- **No candidate satisfies all five, and no exponent can.** Steepening the exponent pulls the
  flat frame into range but drags the under-call frames back down with it - checked out to
  exp 3.0. The split is **by spot, not by period regime**: both Beit Yanai frames resist
  peak-keying, all three Hilton/Poleg frames demand it.

**Decision: `rideability_period()` keys on the partition's peak period** (mean only as a
fallback where the model publishes no Tp). `RIDEABILITY_EXP` stays **1.4** - it is the
min-max-error choice across all five frames, and lowering it inflates the *smallest* hours
most (fleet p10 x1.25 at exp 1.0), which is the false-hope direction.

This also ends an internal contradiction: `energy_period()` / the published kJ column already
keyed off Tp, with a docstring saying that keying off the mean "understates a real swell
badly" - while the height path next to it still used the mean.

### 3. Fleet impact: confined to short-period seas, by construction

Recomputed over all 199 spots x 25,472 published hours. Rideability saturates at its 1.0 cap
above ~10 s, so the key **cannot** matter for groundswell - and doesn't:

| dominant Tm | n | median | p90 |
|-------------|---|--------|-----|
| < 6 s | 6,474 | x1.06 | **x1.26** |
| 6-8 s | 5,333 | x1.04 | x1.00 |
| 8-10 s | 2,765 | x1.00 | x1.00 |
| >= 10 s | 9,650 | x1.00 | x1.00 |

Costa Rica, Nicaragua, Sri Lanka, Japan, Hawaii, Philippines and California are
**bit-identical at every percentile**. Israel moves p90 x1.39 / p99 x1.44; Portugal x1.04-1.07.

Buckets over the same fleet: **3.39% of hours change**, and they move the right way -
POOR->FAIR 734, FAIR->GOOD 55, FLAT->POOR 51, GOOD->FIRING 2, and 2 downgrades total.
Mean rating delta **+0.68 pts**; FIRING count moves by 2 hours in 25k. The ten spots with the
most changes are all Israeli Med beaches - exactly the regime the log has been flagging since
07-25.

### Residual, logged not fixed

Poleg still reads -0.12 m under its observed band, and the 07-19 Beit Yanai flat frame
over-calls +0.15 m. That residual is **per-spot**, which is what `height_coeff` exists for -
and it is still 1.0 at all 199 spots, never once used. Not fitting it now: two thin frames
per spot, and both Beit Yanai frames are hindcast-**reconstructed** inputs while all three
frames demanding peak-keying are **as-logged**. Provenance correlates perfectly with which
candidate each frame favours, which is a real confound on a five-frame set and the honest
reason not to chase the last 0.15 m with a second knob.

**Method note:** the whole fleet impact above is computed offline from published payloads by
injecting candidates through `breaker_height_from_profile`'s existing `rideability` hook, so
production and harness are the same code path - `test_baseline_reproduces_production_path`
now pins that equality against the real function rather than a copied constant.

## 2026-07-30 - Zvulun side-by-side vs Surfline, first outside look after the 2E change

Same-morning comparison (user screenshots, ~09:20 local) against the 08:20-cycle-pending
payload - i.e. **the first Israeli day computed with peak-keyed rideability**. Zvulun is a
one-swell Med day, which makes it a clean read.

**Standing caveat: Surfline is another model, not ground truth.** This says where we differ,
never who is right; only eyes in the water settle that. Nothing here is a calibration input.
Comparison only - no Surfline data enters the spot DB or any fit (CLAUDE.md legal red lines).

| hour | primary swell (SL -> Rosa) | surf (SL -> Rosa) | nearshore kJ (SL -> Rosa) |
|------|---------------------------|-------------------|---------------------------|
| 12am | 0.5 m 6 s 295 -> 0.7 m 6 s 292 | 0-0.3 -> **0.3-0.4** | 11 -> 13 |
| 3am  | 0.7 m 7 s 295 -> 0.7 m 7 s 293 | 0-0.3 -> **0.3-0.5** | 16 -> 20 |
| 6am  | 0.7 m 7 s 297 -> 0.7 m 7 s 294 | 0.3-0.6 -> 0.3-0.5 | 21 -> 20 |
| 9am  | 0.7 m 7 s 299 -> 0.7 m 7 s 295 | - | 24 -> 20 |
| noon | 0.7 m 7 s 300 -> 0.7 m 7 s 296 | - | 19 -> 19 |
| 3pm  | 0.6 m 7 s 299 -> 0.6 m 7 s 295 | - | 15 -> 13 |
| 6pm  | 0.6 m 6 s 299 -> 0.6 m 6 s 292 | - | 12 -> 11 |
| 9pm  | 0.5 m 6 s ~299 -> 0.6 m 6 s 292 | - | 11 -> 10 |

### 1. The offshore sea agrees almost exactly, and so does the energy

Height and period match hour for hour. Our `energy_kj` tracks Surfline's **nearshore** column
row by row (13/11, 20/16, 20/21, 20/24, 19/19, 13/15, 11/12, 10/11); their offshore column
runs ~2x their nearshore throughout. Consistency reads **0% on both**. Pressure matches within
1-2 mb. Two independently-built pipelines landing on the same energy figures is a real check
on the exposure + kJ path, which nothing outside our own tests had ever corroborated.

### 2. Direction: we sit 3-5 deg COUNTER-clockwise of Surfline, all day

Both trend the same way through the day (SL 295->300, Rosa 292->296); we are just offset low.
Worth recording because it is **the opposite sign** from the +15.6 deg clockwise bias we
measured against buoy `mwd` the same week. That does not resolve the direction question - a
second model is not truth - but it is another reason to think the +16 deg is largely a
**blending artifact** of comparing per-partition directions to a single mixed buoy arrow,
rather than a genuine clockwise lean in Open-Meteo. Still gated on the per-partition
measurement; do not apply anything to `spread_exposure()` on the strength of this.

### 3. WATCH ITEM: we now read bigger than Surfline on the small hours

0.3-0.4 against 0-0.3 at midnight and 0.3-0.5 against 0-0.3 at 3am, converging by 6am
(0.3-0.5 vs 0.3-0.6). This is the 2E peak-keying doing what it was built to do - possibly a
touch too much at the bottom of the range. It is **the same direction the 07-19 Beit Yanai
flat frame warned about** (+0.15 m over-call) and the first outside evidence since the change
shipped this morning.

**Do not move a knob on this.** It is one spot, one day, against another model. What it does
is raise the priority of an as-logged flat-morning frame at Zvulun or Beit Yanai: if the water
looks like nothing while we say 0.3-0.5, that is the frame the set is short of, and it lands
on `height_coeff` (still 1.0 at all 199 spots) rather than on the rideability exponent.

### 4. Surfline resolved a secondary swell we did not carry

At 12am they list a secondary 0.2 m **8 s** from 291 deg; Open-Meteo gave us no such partition
(our only extra entries later in the day are 2-3 s windsea, which they do not list). An 8 s
band sitting unaccounted beside a 6 s primary is exactly the Stage-3b **missed-swell guard's**
territory. Worth checking whether the guard fired on Zvulun for that hour when the archives
support it - it would be the first live confirmation the guard catches something a competitor
also sees.

## 2026-07-30 (cont.) - four more spots, and a correction to the entry above

Extended the Surfline side-by-side to Hilton, Beit Yanai, Supertubos, Hikkaduwa and Popoyo
(same morning, user screenshots). Same caveat as above: another model, not truth, comparison
only, nothing enters a fit.

### CORRECTION to §3 of the previous entry - "we read bigger on the small hours" was overstated

It was drawn from **Zvulun alone**. With three Israeli spots on the same swell it does not hold
as written:

| hour | Hilton SL / Rosa | Beit Yanai SL / Rosa | Zvulun SL / Rosa |
|------|------------------|----------------------|------------------|
| 12am | 0-0.3 / 0.2-0.4 | 0-0.3 / 0.3-0.4 | 0-0.3 / 0.3-0.4 |
| 3am | **0.3-0.6 / 0.3-0.5** | **0.3-0.6 / 0.3-0.5** | 0-0.3 / 0.3-0.5 |
| 6am | **0.3-0.6 / 0.3-0.5** | **0.3-0.6 / 0.3-0.5** | **0.3-0.6 / 0.3-0.5** |
| 9am-noon | **0.3-0.6 / 0.3-0.5** | **0.3-0.6 / 0.3-0.5** | - |
| 3pm | 0-0.3 / 0.3-0.4 | 0-0.3 / 0.3-0.4 | - |
| 6-9pm | 0-0.3 / 0.2-0.3 | 0-0.3 / 0.2-0.4 | - |

Through the clean part of the day (3am-noon) **Rosa's 0.3-0.5 sits inside Surfline's 0.3-0.6 at
all three spots** - that is agreement, not an over-call. And note Surfline's own Zvulun reads
0-0.3 at 3am while its Hilton and Beit Yanai read 0.3-0.6 on an identical 0.7 m 7 s 295 deg
swell. **Judging ourselves against one spot of theirs was fragile; their spot-to-spot spread is
as large as the difference we were chasing.**

What survives: two narrower differences.

1. **Afternoon (3pm-9pm) they drop a whole band and we do not.** The swell barely changes
   (0.7 -> 0.6 m, 7 s) but the wind comes up (Hilton 18 kph NW, Beit Yanai 15 kph WNW onshore).
   This looks **structural, not a calibration error**: Surfline's surf height appears to absorb
   wind degradation, whereas Rosa's `h_break` is depth-limited physics x rideability and wind
   enters only the *rating*. Worth deciding deliberately - it is a product question (should a
   blown-out 0.6 m read smaller?), not a knob.
2. **Midnight, light wind, small and clean: we are one band higher** (0.2-0.4 vs 0-0.3). This is
   the only hour where the original watch item still stands, and it is now a much thinner claim.

**Still no knob moved.** The as-logged flat-morning frame remains the thing that would settle it.

### Direction: no sign of the +16 deg clockwise lean on unambiguous swells

Dominant-swell direction, Surfline -> Rosa: Popoyo 221 -> 224, Supertubos' W swell 284 -> 285,
Israel 295 -> 293/294. Agreement is within a few degrees and **the sign is inconsistent**, so
this adds nothing supporting a systematic clockwise bias in our input. Consistent with the
reading that the +15.6 deg measured against buoy `mwd` is largely a blending artifact.

### Partition ORDER is not comparable across providers - do not match by slot

At Supertubos 6am Surfline lists primary 0.3 m 10 s and secondary **0.4 m** 8 s - its "primary"
is not its biggest. Ours sorts differently again. This is the same lesson as our own
partition-label wander finding (2026-07-29): **match partitions by direction and period, never
by slot index.** Any future automated cross-provider comparison has to pair on physics, not on
column position.

### WATCH ITEM (new, significant): Hikkaduwa disagrees structurally

| | Surfline | Rosa |
|---|----------|------|
| dominant | **1.8 m 9-10 s from 267-270** | 1.0 m 4 s from 243-254 |
| mid | 0.7-0.9 m 13 s from 193-198 | 1.0-1.1 m 10-11 s from 181-187 |
| long | 0.5-0.6 m **18-20 s** from 210-212 | 0.6-0.9 m **15-17 s** from 188-196 |

Surfline sees a **1.8 m 9 s west swell**; Open-Meteo gives us a 1.0 m **4 s** west windsea at
nearly the same bearing. Same feature, read as organised swell by one model and as short chop by
the other - and it is the biggest partition in the water either way, so it drives the whole
forecast. Our long-period band is also 3 s shorter and ~18 deg further south than theirs.

This matters more than the Israeli difference: **Sri Lanka has no buoy** (flagged unvalidatable
since 2026-07-23), it is our second-largest region at 32 spots, and this is the first outside
cross-check we have ever had there. It is exactly the regime where a 4 s vs 9 s reading swings
`period_rideability` from the 0.3 floor to ~0.9 - i.e. a factor of ~3 in `h_break`.

Not actionable yet - two models disagreeing does not say which is right, and SW-monsoon seas are
genuinely hard to partition. Next step when someone has time: check the **Stage-3b missed-swell
guard** and the ECMWF period-banded heights (h1012...h2530) for Hikkaduwa this morning - that
member is independent of Open-Meteo and can referee the 4 s vs 9 s question without a buoy.

## 2026-07-30 (cont.) - ECMWF referees Hikkaduwa: Open-Meteo is ~0.8 m low on the monsoon sea

Sri Lanka has no buoy, so the Surfline-vs-us disagreement above had no arbiter. The Stage-3b
ECMWF open-data member is independent of Open-Meteo, so it can referee. Fetched live at
hikkaduwa's offshore point (6.080, 80.103), 00z cycle, steps 0-24.

| valid | swh | pp1d | mwp (Tm-1,0) | mp2 (Tm02) | mwd | h1012 | h1214 | h1417 | h1721 | h2125 | h2530 |
|-------|-----|------|------|------|-----|-------|-------|-------|-------|-------|-------|
| 07-29 12Z | 2.08 | 10.0 | 9.0 | 5.6 | 219 | 0.77 | 0.60 | 0.53 | 0.39 | 0.30 | 0.15 |
| 07-30 00Z | 2.24 | 10.2 | 8.9 | 5.6 | 224 | 0.80 | 0.65 | 0.54 | 0.49 | 0.32 | 0.13 |
| 07-30 06Z | 2.28 | 10.4 | 9.0 | 5.6 | 219 | 0.81 | 0.65 | 0.56 | 0.55 | 0.31 | 0.13 |
| 07-30 12Z | 2.38 | 10.0 | 8.8 | 5.6 | 219 | 0.83 | 0.65 | 0.58 | 0.57 | 0.30 | 0.14 |

### The height: Open-Meteo is low, and it is not a small miss

At 06Z, ECMWF **swh 2.28 m**. Open-Meteo's partitions sum (RMS) to **1.50 m**; Surfline's imply
**~2.10 m**. Splitting ECMWF's own total by its bands:

- energy at >=10 s: **1.34 m** (RMS of the six bands)
- energy below 10 s: **1.84 m** <- the disputed monsoon windsea
- Open-Meteo calls that sea **1.0 m**; Surfline calls it **1.8 m**

So Open-Meteo is carrying roughly **0.8 m of Hs less** than ECMWF in the short-period sea, and
~0.78 m less overall. **Surfline's height is corroborated; ours is not.**

### The period: Surfline is wrong, and Open-Meteo is right

Surfline calls that sea 9 s. Tm02 weights short waves heavily (m2 ~ H^2/T^2), so a sea of this
size at 9 s is arithmetically incompatible with the measured Tm02 of 5.6 s. Reconstructing the
moments from a two-component sea (short component + ECMWF's own bands as the long tail):

| candidate sub-10 s sea | predicted Tm-1,0 | predicted Tm02 |
|------------------------|------------------|----------------|
| **ECMWF measured** | **9.0** | **5.6** |
| 1.84 m @ 4.5 s (OM-like) | 7.9 | 5.4 |
| 1.84 m @ 5.0 s (OM-like) | 8.3 | 6.0 |
| 1.84 m @ 9.0 s (SL-like) | 10.9 | **10.0** |

A 9 s windsea overshoots Tm02 by 4.4 s. The truth is close to **1.84 m at ~4.5-5 s**: Open-Meteo
has the character of the sea right and roughly half its height; Surfline has the height right and
the period badly long.

### Why this matters more than the Israeli difference

`period_rideability` at 4.5 s sits on its **0.3 floor**; at 9 s it is ~0.85. So the two readings
differ by ~3x in `h_break` *before* the height error. We are on the right side of that (short and
slopping, not clean 9 s groundswell) - **but we are feeding it a sea that is ~45% too small**.

This is the **first evidence of a large regional Open-Meteo height deficit in a region we cannot
validate with buoys** - and Sri Lanka is 32 spots, our second-largest region. The 12-station
buoy sweep the same week put OM's fleet Hs bias at -0.005 m, but every one of those stations is
in the Pacific or Atlantic. Nothing in that sweep covers the Indian Ocean or a monsoon sea.

### The missed-swell guard worked, and this is its first live corroboration

The guard was already firing at hikkaduwa all day, flagging unaccounted energy at 12-14 s
(0.6-0.7 m), 17-21 s (0.4-0.6 m) and 21-25 s (0.3 m). Surfline independently shows an 18-20 s
swell at 0.5-0.6 m from 210-212 deg. **Two independent sources confirm a swell Open-Meteo's
partitions do not carry, exactly where the guard said to look.** Stage 3b's acceptance item
"missed-swell backtest" now has its first real data point, and it passed.

### Actions

**No knob moved** - one point, one day, and ECMWF is a model too. But this is now the most
valuable open thread, and it is cheap to settle:

1. **Sweep OM swh vs ECMWF swh across all 32 Sri Lanka spots** (and the Philippines, also
   monsoon-fed and buoy-less). Both are already fetched per cycle; this needs no new source.
   If the deficit is regional and persistent it is a genuine per-region input correction - the
   first defensible one, since unlike the Hs work in the entry above it would not be built on
   instrument-class cancellation.
2. Re-check whether the deficit is in the **windsea partition specifically** rather than the
   total, which is what the guard hints.
3. Only then consider whether anything should change. Note this cuts the opposite way from the
   Israeli picture, which is another reason a single global Hs constant would be wrong.

## 2026-07-30 (cont.) - CORRECTION: it is not a model deficit, it is Open-Meteo's partitions not closing

The entry above concluded "Open-Meteo is ~0.8 m low on the monsoon sea". **That was wrong**, and
three follow-up tests took it apart. What is left is a different problem, and a more actionable one.

### Test 1 - regional sweep with a control group

OM partition-RMS vs ECMWF swh, 755 matched (spot, hour) pairs:

| group | region | n | OM | ECMWF | EC-OM | ratio |
|-------|--------|---|-----|-------|-------|-------|
| TEST | sri-lanka | 128 | 1.59 | 2.19 | **+0.60** | 1.38 |
| TEST | philippines | 64 | 0.57 | 0.70 | +0.13 | 1.22 |
| CONTROL | israel | 126 | 0.69 | 0.65 | -0.04 | 0.95 |
| CONTROL | portugal | 126 | 0.62 | 0.61 | -0.01 | 0.99 |
| CONTROL | costa-rica | 125 | 1.38 | 1.41 | +0.03 | 1.02 |
| CONTROL | nicaragua | 75 | 1.48 | 1.44 | -0.04 | 0.97 |
| CONTROL | japan | 96 | 0.63 | 0.68 | +0.04 | 1.06 |
| | **= CONTROL** | 563 | 0.94 | 0.94 | **+0.00** | 1.00 |

The control lands on exactly 1.00, so the method is sound and the Sri Lanka gap is not a
constant model-vs-model offset. This is where it was tempting to stop and apply a regional
correction. **That would have been the third artifact-driven "fix" this project nearly shipped.**

### Test 2 - deep water: the gap vanishes entirely

Sampling open ocean >200 km from land, where neither model has a resolution or sheltering problem:

| point | OM | ECMWF | diff |
|-------|-----|-------|------|
| Indian Ocean south of Sri Lanka | 2.17 | 2.16 | -0.01 |
| IO southwest of Sri Lanka | 2.02 | 2.04 | +0.02 |
| IO south of India | 1.77 | 1.77 | -0.00 |
| **TEST group** | **1.99** | **1.99** | **+0.00** |
| CONTROL group | 1.75 | 1.75 | -0.00 |

**There is no Indian-Ocean model difference.** Whatever the gap is, it is made near the coast.

### Test 3 - the transect: two different mechanisms, neither a model being wrong

Open-Meteo's own Hs walking straight out from the spot:

| km offshore | Hikkaduwa OM / ECMWF | Arugam Bay OM / ECMWF |
|-------------|----------------------|------------------------|
| 0 | **2.32** / 2.18 | **1.32** / 2.16 |
| 20 | 2.41 / 2.18 | 2.13 / 2.16 |
| 50 | 2.40 / 2.24 | 2.49 / 2.45 |
| 120 | 2.36 / 2.13 | 2.61 / 2.42 |

- **Arugam Bay: an ECMWF artifact.** OM resolves the island sheltering its east coast from the
  SW monsoon (1.32 m at the coast climbing to 2.61 m at 120 km); ECMWF at 0.25 deg (~28 km)
  cannot, and reads a flat ~2.2 m. OM is right; the "+1.05 m deficit" was our coarse reference.
- **Hikkaduwa: OM's total is fine.** 2.32 m against ECMWF's 2.18 - they agree. So OM is NOT low.

### What is actually wrong: the partitions do not sum to the model's own total

At Hikkaduwa's offshore point, Open-Meteo's four partition fields against its own `wave_height`:

| hour | TOTAL | windsea | swell 1 | swell 2 | swell 3 | RMS parts | unaccounted |
|------|-------|---------|---------|---------|---------|-----------|-------------|
| 00Z | 2.22 | 1.00/4s | 0.92/11s | 0.58/14s | 0.00 | 1.48 | **1.66** |
| 06Z | 2.24 | 1.02/4s | 1.04/10s | 0.72/17s | 0.00 | 1.62 | **1.54** |
| 18Z | 2.34 | 0.48/3s | 0.98/9s | 0.90/15s | 0.00 | 1.41 | **1.86** |

Tertiary swell is empty, so we are not dropping a field - **Open-Meteo simply does not place all
of its energy into the four partitions it publishes.** Rosa reads only partitions, so at
Hikkaduwa the transform is fed a ~1.6 m sea when the model itself says 2.2-2.3 m.

Closure ratio RMS(partitions)/total, 3 spots per region, pure within-OM (no second source):

| region | closure | mean unaccounted Hs |
|--------|---------|---------------------|
| sri-lanka | **0.86** | **0.85 m** (crust 0.72, hikkaduwa ~0.72) |
| california | 0.91 | 0.39 m |
| portugal | 0.93 | 0.19 m |
| philippines | 0.94 | 0.13 m |
| hawaii | 0.95 | 0.43 m |
| japan | 0.97 | 0.15 m |
| nicaragua / costa-rica | 0.99 | 0.08-0.19 m |
| **israel** | **0.99** | **0.05 m** |

Closure is near-perfect in simple seas and degrades in big multi-modal ones - four slots cannot
hold a monsoon sea carrying windsea plus three or more swell trains. **Israel at 0.99 is why
this never showed up in any calibration we have ever done**: every graded frame is Med.

### What survives from the previous entry

- Surfline's **9 s reading is still ruled out** - that argument used ECMWF's Tm02 of 5.6 s, and
  since OM's total (2.24) and ECMWF's (2.28) agree, both describe the same sea. A sea that size
  at 9 s predicts Tm02 10.0 s.
- The **missed-swell guard corroboration still stands** - ECMWF and Surfline independently show
  17-21 s energy that OM's partitions do not carry. That is the same failure as the closure gap,
  seen from the long-period end.
- Best reading of Hikkaduwa: a real sea of ~2.3 m, of which ~1.84 m is short-period (~4.5-5 s)
  monsoon windsea. OM's windsea partition carries only ~1.0 m of it. **We have the character
  right and roughly half the energy.**

### Actions

**Still no knob moved, and no regional Hs correction - that idea is dead** (tests 1-3 killed it).
The real item is different and narrower:

1. **`wave_height` is fetched every cycle and thrown away** - `extract.py` uses it solely as a
   horizon null-sentinel. Carrying it onto `HourForecast` costs nothing and gives us a per-hour
   **closure ratio**: a pure within-source data-quality signal, the energy analogue of the
   Stage-3b missed-swell guard.
2. Only then decide what to DO about a short sea. Options (none obviously right, all need
   thought): surface low closure as a confidence penalty; synthesise a residual partition
   (but with what period and direction?); leave the forecast alone and just monitor. **Do not
   scale partitions to close the gap** - that would invent direction and period the model
   never gave, and Rosa's whole premise is not doing that.
3. Sri Lanka's 32 spots are the exposed region, and it has no buoy. Worth re-checking closure
   across a full monsoon cycle before treating 0.86 as its steady state.

**Method note, third time this month:** a measured "bias" that turns out to be a comparison
artifact - APD vs Tm-1,0 (period), blended `mwd` vs per-partition directions, and now a 0.25 deg
grid vs a sheltered coast. The control group and the deep-water test are what caught this one.
Build both into any future cross-source claim.

## 2026-07-30 (cont.) - closure ratio wired up, and measured across the fleet

`extract.py` now carries Open-Meteo's own `wave_height` onto `HourForecast.total_hs_m` (it had
been read solely as the horizon null-sentinel and dropped), and the payload gains a per-hour
`closure` = RMS(partitions) / total. **Diagnostic only - nothing scores on it.**

Note on reading the number: it is a ratio of HEIGHTS. Energy goes as H², so the energy actually
visible to the transform is `closure²`. My earlier framing of Hikkaduwa's 0.73 as "a third of the
sea" was loose - it is ~27% of the height and **~47% of the energy**.

Full fleet, 25,136 published hours (closure present on 98% - the GFS-Wave tail days beyond the
marine horizon carry no comparable total):

| region | mean | p10 | min | energy the transform sees |
|--------|------|-----|-----|---------------------------|
| sri-lanka | 0.90 | 0.76 | 0.59 | 81% |
| california | 0.91 | 0.72 | 0.50 | 82% |
| costa-rica | 0.94 | 0.82 | 0.54 | 89% |
| portugal | 0.94 | 0.83 | 0.59 | 89% |
| hawaii | 0.95 | 0.91 | 0.84 | 90% |
| nicaragua | 0.95 | 0.84 | 0.51 | 90% |
| philippines | 0.96 | 0.88 | 0.33 | 93% |
| japan | 0.97 | 0.90 | 0.52 | 94% |
| **israel** | **1.00** | **0.98** | **0.85** | **99%** |

### This moderates the alarm, and sharpens where it belongs

Over a full forecast Sri Lanka averages **0.90**, not the 0.72 measured at Hikkaduwa on one
morning - that hour sat in the bad tail, not the middle. The 3-spot sample in the previous entry
(0.86 for Sri Lanka) over-stated it too; 32 spots x 128 hours is the honest figure.

What the full sample adds that the small one could not:

- **The tail matters more than the mean.** Every region except Israel and Hawaii has hours below
  0.60, and the Philippines reaches 0.33 - a single hour where two thirds of the height and ~89%
  of the energy is in no partition. A regional mean hides these completely; they are exactly the
  hours a forecast would be most wrong.
- **California at 0.91 is the surprise.** It is buoy-covered and was in the CONTROL group that
  read +0.00 against ECMWF, so its partitions are short without the total being wrong - the same
  signature as Sri Lanka, in a region we thought was well characterised. Only 2 spots, so weak,
  but it means this is not a monsoon-only story.
- **Israel really is the outlier at 1.00** (min 0.85). Every graded calibration frame this project
  has is Israeli, so no amount of past calibration could have surfaced this. Worth remembering the
  next time an Israeli result is treated as evidence about the fleet.

### Still not acting on it

No knob, no scaling, no confidence penalty yet. A low ratio says energy is missing but not its
direction or period, and Rosa's premise is not inventing those. The number is now recorded every
cycle, so the questions it needs are answerable in a week rather than by a one-morning snapshot:
does a spot's closure track the sea state or the spot? is the missing energy short-period (where
`period_rideability` would have floored it anyway, making this nearly harmless) or long? do the
sub-0.6 hours cluster in conditions a user would care about?

## 2026-08-02 - the depth march never reached the surf zone, and the wave got smaller on the way in

Triggered by the user watching Santa Teresa's cam: surfers in frame put the face **over 1 m**
against a published **0.5-0.7 m**. Unlike the 07-30 Surfline round this is a direct eye frame in
a **long-period Pacific** region, the regime CLAUDE.md has flagged as untested since the log's
"Scope & honesty" header was written. It found a structural fault, not a constant that needed
nudging.

### What was wrong

`breaker_height_over_profile` marches a partition shoreward and returns `gamma*d` at the depth
where it first breaks. If it never breaks inside the profile it returned **the most-shoaled
height it had reached** - the height at the shallowest GEBCO sample. The docstring called that
a sub-grid gap "a per-spot residual coefficient absorbs". `height_coeff` is 1.0 at all 199
spots, so nothing absorbed it.

That branch is not an edge case. Committed profile floors, all 199 spots:

```
<2 m  9      2-5 m  42      5-10 m  76      10-20 m  54      >=20 m  18
```

Median floor 7 m, so a wave needs ~5.5 m of height to break inside the profile. Share of
published hours that actually reach depth-limited breaking:

```
California 0.0%  Hawaii 0.0%  Israel 0.0%  Nicaragua 0.0%  Portugal 0.7%
Japan 1.8%  Costa Rica 2.7%  Philippines 2.7%  Sri Lanka 3.0%
```

**97-100% of the fleet was being served a mid-shelf height labelled as a breaker height.** And
the shallowest sample is the worst possible place to stop: it sits inside the shoaling dip and
has already taken the refraction loss, but none of the shallow-water growth. At Santa Teresa the
dominant partition went **x0.74 from offshore to "break"** (Ks 0.93, Kr 0.80 at 60 deg incidence,
last wet sample 13 m). Fleet median of published `h_mid` over RMS of in-window offshore
partitions: **0.69**. Waves were arriving smaller than they left.

### The fix, and what was deliberately not done

Closed the march with **Komar & Gaughan (1972)**, `Hb = 0.39 g^0.2 (T H0'^2)^0.4`, refraction
iterated to the breaking depth, H0 de-shoaled from the profile's reference depth first
(`deep_water_equivalent`) so a spot whose profile starts shallow does not get an inflated H0.
It needs only H0, T and the approach angle - no bathymetry we do not have.

**Rejected: appending a plausible shallow tail to the profiles.** It looks like more physics but
the answer becomes exactly `gamma x whatever final depth was invented`. That is a knob wearing a
lab coat.

### The exponent had to move with it, and this is the important part

`RIDEABILITY_EXP = 1.4` was fitted **on top of the truncated march**, so part of what it was
"measuring" was the truncation. Refitting on the same 5 frames with the march closed, using the
harness's own criterion (predicted mid inside observed +- slack):

```
BEFORE - march stops at the GEBCO floor        AFTER - march closed
candidate  pass  maxerr                        candidate  pass  maxerr
peak^1      4/5    0.20                        peak^2.2    4/5    0.15
peak^1.4    3/5    0.15  <- shipping           peak^2      4/5    0.17
energy^1    3/5    0.16                        mean^1      4/5    0.19
peak^1.2    3/5    0.17                        energy^1.4  4/5    0.20
```

Adopted **`peak^2.2`** (key unchanged, exponent 1.4 -> 2.2). The tie-break inside the 4/5 tier
was not the frames - they cannot separate 1.8 from 2.2 - it was the fleet:

```
median height multiplier vs the deployed forecast
region          exp 1.4  exp 1.8  exp 2.0  exp 2.2
California         1.70     1.68     1.67     1.66
Costa Rica         1.66     1.64     1.62     1.61
Nicaragua          1.72     1.70     1.70     1.69
Sri Lanka          1.46     1.44     1.44     1.44
Japan              1.39     1.36     1.34     1.34
Philippines        1.60     1.51     1.49     1.47
Hawaii             1.44     1.30     1.25     1.20
Portugal           1.48     1.34     1.27     1.21
Israel             1.39     1.19     1.11     1.06
```

Because rideability caps at 1.0 above ~10 s, **the exponent is in practice an Israel/Portugal
knob** and the closure is a long-period-region correction. They separate cleanly. 2.2 is the
value that leaves the **calibrated** region essentially where its graded frames put it
(Israel x1.06) while the closure corrects the regions that never had an eye frame. Choosing 1.8
would have raised Israel 19% on no eye evidence at all.

### A claim I made and had to withdraw

I first reported that **"exponent 2.5 with the march closed makes all five frames pass, the
first time any candidate has"**. It does not. That came from a scratchpad pass test asking
whether the *displayed range* overlapped the observed band; the project's harness asks whether
the predicted *midpoint* sits inside observed +- slack, which is stricter and is the criterion
every previous entry in this log used. Under the real criterion **no candidate passes all five,
before or after** - the 2026-07-19 flat frame is over by +0.15 to +0.24 everywhere. Fourth
comparison artifact in three weeks, and the first one that was purely my own bookkeeping:
**score candidates with the shipped harness, never a scratchpad reimplementation of it.**

The flat frame's residual looks structural rather than tunable: it is a 0.60 m 5.05 s Med
windsea observed ankle-high, and a breaker index assumes something that breaks as a wave.

### Two supporting faults found on the way, both fixed

**1. Peak period was missing from 7 of 9 regions.** Coverage of `peak_period` on published
partitions: Israel 18.9%, Portugal 15.7%, **everywhere else 0.0%**. Cause: `best_match` resolves
to `meteofrance_wave` (its Hs matched to the centisecond at all 5 probe points), which publishes
no peak period at all. Stage 2E's peak-keyed rideability was therefore falling back to the mean
everywhere outside Europe - the fix shipped 07-30 was reaching two regions.

Probed every marine model. `gwam` (DWD global WAM) publishes `swell_wave_peak_period` at all 5
probe points out to ~7.3 days; `ewam` does too but is Europe-only; `ncep_gfswave016` and
`meteofrance_wave` publish none. Added `gwam` to `MARINE_MODELS` as a peak-period-only source -
one extra model on the same request, so no extra cost against the rate limiter. Santa Teresa now
reads Tp **11.2 s** where its mean is 8.7 s.

This is a cross-model join and the only one in the pipeline. It is safe because Tp feeds
`period_rideability` and the display, never the dispersion march or `period_score`. It is also
what Open-Meteo already does inside `best_match` over Europe: at Hilton and Supertubos its Hs is
meteofrance's while its Tp is gwam's, identical to the centisecond. Tests pin that gwam supplies
**only** the Tp and never becomes the horizon tail. `secondary_/tertiary_swell_wave_peak_period`
do not exist as API variables, so those partitions still have no Tp - an API limit, not a choice.

**2. Santa Teresa's swell window was the regional default and was wrong.** `[190, 310]` put its
lower edge exactly on the dominant 189-190 deg swell, costing 28% of that partition's energy,
while its top 20 deg pointed at dry land. New `horizon.py` fans rays over 360 deg from the spot
and asks which reach open ocean, using the same GEBCO source and `destination` geometry as the
depth profiles. Derived: **[160, 290]**, adopted.

The criterion needed care and nearly produced a fifth artifact. A plain `elevation >= 0` test
carved a false notch at 220-235 deg straight through the open Pacific - a submerged bar at
1.5-3 km reading 0 to +2 m with 60-90 m of water beyond it. Two thresholds instead of one: land
must stand above GEBCO's noise (`HORIZON_LAND_M = 3.0`) and the ray must reach deep water
(`-50 m`), in that order. The derived window is stable for any land threshold in 2-5 m and only
collapses below 2 m, which is the bar being read as a coast again. `rosa-pipeline horizon`
reports and never applies - same rule the cam sweep learned the hard way.

### Status

The other 198 spots still carry regional-default windows. `horizon --all` would take ~25 min
against the OpenTopoData rate limit and every result wants an eye on it before adoption, so it
was not run. Santa Teresa is the one spot with an observation behind it.

`height_coeff` remains 1.0 at all 199 spots.

## 2026-08-02 (cont.) - fleet horizon sweep: a negative result, nothing adopted

Ran `rosa-pipeline horizon --all` (199 spots, ~1,200 rate-limited GEBCO requests). **185 of 199
disagree with their YAML window. None were adopted**, because the disagreement turned out not to
be evidence the YAML is wrong.

```
derived window width        <30    30-60   60-90   90-135   >=135
                              4       6      29      75       73
```

**39 of 187 derived windows are narrower than 90 deg, which no open beach is**, and 12 spots
returned no window at all. Reading the captured rays back:

- **miramar (Nicaragua), derived 10 deg.** Bearings 225-275 all sit on the same shelf. The only
  thing separating "open" from "blocked" is whether the 0.5 km sample rounds to **+3 or +4 m**
  against `HORIZON_LAND_M = 3.0`. On a shallow-shelving coast the nearshore GEBCO cell straddles
  the waterline, so the threshold behaves like a coin flip and chops the arc at random.
  `manzanillo` (25 deg) is the same story.
- **calicoan-abcd (Philippines), derived 10 deg.** Different mechanism: bearings 145+ never reach
  `HORIZON_DEEP_M = -50 m` within 40 km (deepest -43, -32, -28), so a wide-open ocean sector reads
  blocked. This is also what the 12 no-window spots are, and **they are not all geometry faults**
  whatever my error message says - `pavones`, `panga-drops`, `miura`, `kodomonokuni` sit inside
  gulfs and bays where land really is 20 km across the water and swell really does wrap in
  through the mouth.
- **arugam-bay, derived [25, 175] against a hand-set [120, 200].** The scan is right that the
  Indian Ocean is open from the NNE. The point that shelters the break from exactly that swell
  is smaller than a GEBCO cell. The method measures **ocean visibility at ~450 m**; it cannot
  measure local sheltering.

So Santa Teresa's success does not generalise - it is the easy case, a long simple open beach on
a steep coast, and it cleared a bar the sweep results cannot: **stable across the entire
plausible threshold range (2-5 m) AND a user eye observation backing the forecast it produces.**

`horizon` output is a **flag for review, not an answer**, and that is now written into the module
docstring so the next person does not adopt 185 windows on the strength of "the tool said so".
Making it adoptable would mean tolerating isolated blocked bearings as noise rather than walls,
and making the deep-water test relative to the local shelf instead of a fixed -50 m. Not
attempted - it needs its own experiment and its own eyes.

Separately, `prune_index` was fixed: it drove off `index.json` only, so a payload whose index
entry had already vanished was invisible to it and shipped in every prebuilt deploy forever.
Four such orphans had been riding along since 2026-07-23 (`ahangama-kabalana`, `bugrashov`,
`herzliya-marina`, `metzitzim`). It now sweeps the payload directory against the spot DB as well.

## 2026-08-02 (cont.) - horizon made adoptable, 183 windows adopted

The negative result above was two mechanical faults, not a dead end. Both are fixed and the
sweep re-run offline against the captured elevations (reproducible, no new requests).

**Fault 1 - the spot's own shoreline cell was deciding the window.** `HORIZON_DISTANCES_KM`
starts at 0.5 km, which is inside one GEBCO cell of the spot itself, and on a shallow-shelving
coast that cell straddles the waterline by construction. At `miramar` bearings 225-275 sit on
one identical shelf and the only thing separating "open" from "blocked" was whether that sample
rounded to **+3 or +4 m**. `HORIZON_MIN_BLOCKER_KM = 1.0` now ignores land the source cannot
resolve. This single change took no-window 12 -> 4 and sub-90-deg windows 39 -> 18.

**Fault 2 - a -50 m "open water" bar is unreachable on a broad shelf.** `calicoan-abcd` never
gets past -43 m in 40 km, so a wide-open sector read blocked. `HORIZON_DEEP_M` is now **-20 m**:
past the surf zone, still discriminating, and it removes every remaining sub-60-deg window.
Beyond -20 the curve flattens.

```
                    none   <30   30-60   <90   median width
before (-50, 0.0)     12     4       6    39      125
after  (-20, 1.0)      3     0       0    10      136
```

**A rewrite in between was wrong and got caught.** Trying to replace the deep test with "still
in water at the far end", I dropped the ORDERED land-vs-water comparison. That immediately
regressed santa-teresa from [160, 290] to [210, 290] - a single **+5 m bar cell at 3 km** on
bearing 205 became a wall, chopping off the southern sector where its dominant swell arrives.
The ordering test is what lets a ray shrug off a bar it has already sailed past; it is
load-bearing and must not be dropped. Santa Teresa is invariant under every threshold pair
tried, which is what a well-conditioned spot looks like.

### Adoption

**Adopt where the current value is provably wrong, or where the change is immaterial:**

- **13 spots whose YAML window did not contain their own shore normal.** An independent check,
  needing no part of this tool: 14 of 199 windows excluded the direction the beach faces
  (`salema` off by 44 deg, `whiskey-point` 40, `coconut-beach` 30, `molhe-leste` 26). Same class
  of fault as the 2026-07-29 shore_normal audit. The derived window contains the normal by
  construction, so it is unambiguously better on that axis.
- **170 spots where the height moves less than 10%.**

**Held - 16 spots:** 3 large movers whose size the tool's blind spot could explain
(`calicoan-abcd` x0.68, `zavial` x0.69, `kodomonokuni` x0.89), 10 flagged NARROW (<90 deg, which
no open beach is - the CLI now prints that warning), and 3 whose shore normal is blocked
(`pavones`, `panga-drops`, `miura` - genuinely inside gulfs, not geometry faults).
`playa-cocles` still excludes its own normal and is NARROW-flagged; it needs eyes.

**Fleet height impact of the windows alone: x1.01 median** (p10 0.94, p90 1.06). Windows rotate
by tens of degrees and the forecast barely moves, because the soft exposure taper and the fact
that swell usually arrives near the shore normal absorb it. The windows were worth fixing for
correctness, not for size.

**The remaining limit is unchanged and is not fixable from GEBCO:** the scan measures ocean
visibility at ~450 m, so a derived window is an **upper bound on exposure**. It cannot see a
headland sheltering the break at 50-200 m (`arugam-bay` opens at 25 deg because the Indian Ocean
genuinely is open from the NNE) nor swell wrapping in around a point (`pottuvil-point`).

### Two things this shook loose

Adopting moved `beit-yanai`, `hilton` and `poleg` - the three calibration-frame spots - so the
2E exponent refit had to be redone against the new geometry. **`peak^2.2` still wins, 4/5 frames,
maxerr 0.15** (per-frame +0.15 / 0.00 / 0.00 / -0.04 / -0.04). The conclusion survives.

And a live `run --all` took two Open-Meteo **429s on the ensemble request**. That was mine:
adding `gwam` took the marine request from 2 models to 3, so its quota weight went ~4.9 -> 7.3
per point and `MARINE_BATCH_SIZE = 90` no longer fit the 600/min bucket. Reduced to **65** with
the arithmetic written out. It degrades honestly (publishes without the confidence ensemble
rather than failing), which is exactly why it would have rotted silently on the VM cron.
Re-derive that batch size whenever `MARINE_MODELS` or `MARINE_HOURLY` changes. Clean re-run
after: 199 spots, 0 warnings.

## 2026-08-03 - Santa Teresa over-called: the partitions were being combined twice over

User side-by-side from his phone, Santa Teresa, 2026-08-02 (Rosa screenshot vs Surfline
screenshot, "Observed heights" on, both metric, both 3-hourly, same local day):

| local | Rosa (shipped) | Surfline | Rosa (after this fix) |
|-------|----------------|----------|-----------------------|
| 12am | 1.0-1.5 | 0.6-1.1 | 0.8-1.2 |
| 3am  | 1.2-1.7 | 0.6-1.1 | 0.8-1.3 |
| 6am  | 1.1-1.6 | 0.9-1.2 | 0.8-1.2 |
| 9am  | 1.0-1.5 | 0.6-1.1 | 0.8-1.2 |
| noon | 1.2-1.8 | 0.6-1.1 | 1.0-1.5 |
| 3pm  | 1.1-1.6 | 0.6-1.1 | 0.8-1.2 |
| 6pm  | 1.1-1.6 | 0.6-1.1 | 0.8-1.2 |
| 9pm  | 1.1-1.7 | 0.6-1.1 | 0.8-1.2 |

His words: "extreme in the other direction" - i.e. session 12's closure, which was built to
answer his own ">1 m" eye frame at this spot, had over-shot past it. Note the eye frame and
Surfline do not actually disagree by much: ">1 m" sits at the TOP of Surfline's 0.6-1.1 band.
Rosa's *midpoints* were 1.25-1.50, above both.

**Standing caveat, same as every Surfline entry: another model, not truth. No Surfline data
enters the spot DB or any fit (CLAUDE.md legal red lines).** What makes this one gradeable is
that the user's own eyes and Surfline agree on roughly where the top of the range should be.

### The fault: `sqrt(sum Hb_i^2)` over per-partition breaker heights

`breaker_height_from_profile` marched each partition to its own breaker height and then RMS'd
those heights. That is wrong in two independent ways at once, and both inflate:

1. **The breaker index is sublinear in height.** Komar & Gaughan is `Hb ~ (T H0^2)^0.4`, i.e.
   `Hb ~ H0^0.8`, so the smaller a partition is the *larger* its amplification. At Santa Teresa
   midnight the 0.86 m 8.9 s partition transformed x1.16 (60 deg incidence) while the 0.56 m
   9.2 s one transformed **x1.68** - a partition two-thirds the size arrived at 96% of the
   height. Running the index once per partition and then adding therefore always beats running
   it once on the combined sea.
2. **Two trains 55 deg apart do not merge into one breaking wave.** They refract to different
   angles and break on different parts of the beach; the wave a surfer rides belongs to one of
   them. RMS assumes they stack.

Decomposition of the midnight hour under the shipped code:

```
H=0.86 Tm=8.9 Tp=11.2 dir=190  w=0.99 inc=60  H0=0.86  Hb=0.98  ride=1.00 -> 0.97
H=0.56 Tm=9.2 Tp=None dir=245  w=1.00 inc= 5  H0=0.56  Hb=0.94  ride=0.83 -> 0.78
RMS -> 1.26        (dominant partition alone -> 0.97)
```

### The fix: combine by wave FIELD, not by RMS

`field_coherence(delta, spread_a, spread_b)` = `cos^2` taper, 1.0 at zero separation, 0 once
the separation reaches the sum of the two partitions' own directional spreads
(`spectral.parametric_spread_deg`, 20-35 deg each). Partitions still coherent add their energy;
the sum is taken in `Hb^2.5` (`FIELD_ENERGY_EXP`), which is the exact inverse of K&G's 0.4
exponent - so summing there and taking the 0.4 power *is* "add the offshore energy flux, then
apply the breaker index once". Partitions past that arc taper out toward the dominant one alone.

Deliberate properties:
- **A single in-window partition is bit-identical** to the old transform (verified over 2,811
  such fleet hours, max delta 4e-16). The Israel eye frames are all single-swell, so the whole
  Stage-2E calibration is untouched: `rosa-pipeline experiment` still grades `peak^2.2` at 4/5,
  max |err| 0.15 m, exactly as on 2026-08-02.
- **The arc is derived, not fitted.** It is the sum of the two fans' spreads - "one field while
  the fans still overlap" - so no new magic constant was introduced.
- **The taper is smooth on purpose.** A hard cluster threshold scored identically at Santa
  Teresa but moved the published height **0.183 m on a 3 deg direction wander**; this taper
  moves it 0.016 m. Open-Meteo reshuffles partition directions by a few degrees every hour
  (2026-07-29), so a threshold here would have shipped visible hour-to-hour jitter. There is a
  regression test pinning < 0.02 m per degree.

### What else was tested, and why each was rejected

Graded on two frame sets at once: the 8 Surfline hours above, and the 5 Israel eye frames in
`data/calibration/frames.yaml`. A candidate had to fix the first without moving the second.

| candidate | Santa Teresa | Israel eye frames | verdict |
|-----------|--------------|-------------------|---------|
| shipped (RMS) | 0/8 in band, bias +0.24 m | 4/5 | the fault |
| **field-coherent combine** | **7/8, bias +0.01** | **4/5 unchanged** | **adopted** |
| combine in energy only (p=2.5, no coherence) | 0/8, +0.15 | 4/5 | right direction, only 6% - the index-once fix alone is not enough |
| dominant partition only (p=inf) | 7/8, +0.01 | 4/5 | same score at Santa Teresa but discards genuinely aligned energy: two equal 1.0 m 12 s swells from the SAME bearing read as one. Fleet Nicaragua x0.79, Hawaii x0.80 |
| hard direction clustering | 7/8, +0.01 | 4/5 | same score, but jitters 0.183 m on a 3 deg wander (above) |
| flatten the index's steepness exponent (`b` 0.20 -> 0.05, `a` re-anchored at Israel) | 7/8 | **2/5** | needs `b ~= 0`, i.e. no steepness dependence at all. Every published breaker index has 0.2-0.25. Rejected on physics AND on the frames |
| `KOMAR_GAUGHAN_COEFF` 0.39 -> 0.30-0.33 | 3-6/8 | **1-2/5** | Israel pins the index; the coefficient is not free |
| `RIDEABILITY_EXP` 1.8 / 2.6 / 3.0 | 0/8 (no effect) | 2-4/5 | rideability saturates at its 1.0 cap above ~10 s, so it cannot reach this at all |
| `period_rideability` cap 1.0 -> 0.8 | 5/8 | 4/5 | *does* separate the two regions - but only because no eye frame ever tests the cap (all five sit at 0.27-0.68). Lowering it is not a rideability statement, it is a flat x0.8 on every long-period region, i.e. asserting the index is 20% hot when three independent indices say it is not. Rejected |
| feed the index Tp instead of Tm | 0/8, worse | 3/5 | wrong direction on both sets |
| directional-spreading loss at the break | 0/8 | 2/5 | too small, and costs Israel |
| blunt global `scale` 0.7-0.9 | 5-8/8 | 1-2/5 | fits Santa Teresa by breaking the calibrated region. The null hypothesis, and it loses |
| revert santa-teresa's swell window to `[190,310]` | 0/8, +0.18 | - | the 2026-08-02 horizon adoption is worth only x0.95 here. **Not the cause** - the window stays |

The two levers that could separate Santa Teresa from Israel were the combination rule and the
rideability cap. They were discriminated on principle, not on score: the combination rule was
fixing an outright mathematical error (the index applied N times), while the cap would have been
overriding a well-supported physical relation in the one regime no frame constrains.

### Fleet impact (same-input A/B, 24,674 hours of today's partitions)

| region | median | p10 | p90 |
|--------|--------|-----|-----|
| Israel | **1.00** | 0.91 | 1.00 |
| Philippines | 0.97 | 0.77 | 1.00 |
| Japan | 0.95 | 0.75 | 1.00 |
| Portugal | 0.92 | 0.79 | 0.98 |
| Sri Lanka | 0.92 | 0.80 | 0.99 |
| Costa Rica | 0.90 | 0.75 | 1.00 |
| California | 0.89 | 0.75 | 0.97 |
| Hawaii | 0.88 | 0.74 | 0.98 |
| Nicaragua | 0.86 | 0.77 | 0.97 |
| **FLEET** | **0.93** | 0.78 | 1.00 |

Surgical by construction: 11% of hours are bit-identical (single exposed partition), Israel's
median is exactly 1.00, and the movers are the multi-swell Pacific regions. Santa Teresa itself
moves x0.76 today because it happens to have two big well-separated swells - the fleet number
understates what it does to the case that was actually wrong. Published/offshore over the same
hours: 0.83 -> 0.76 fleet.

### Found, not fixed - `physics.py`'s march/index handoff has a step

Writing the smoothness test surfaced it: when the march *does* reach `gamma*d` inside the
profile it returns `gamma*d`, otherwise it falls through to Komar & Gaughan, and the two branches
disagree. On a test profile whose shallowest sample is 1.5 m the published height steps
**1.167 -> 1.303 m between 13 and 14 degrees of incidence**. Real GEBCO profiles bottom out at
7-13 m, which is why 97-100% of published hours take the index branch and this is invisible in
production - but it is a genuine discontinuity and it will bite whenever a profile is unusually
shallow. Not touched here (a separate defect, and this session already moves the fleet). The
regression test uses a deep profile so it grades the combine, not the handoff.

### Residual and honesty

Noon is the one hour still above Surfline's band (1.22 vs their 0.6-1.1). Its dominant partition
is 0.72 m at 10.8 s arriving at 10 deg incidence, and that single partition alone transforms to
1.2 m - so no combination rule can reach it; it is index-level and small (+0.12 m). Not chased.

**One spot, one day still.** This entry rests on the same single-spot exposure the closure did.
It is stronger than session 12's in that Surfline and the user's eye bracket the same answer and
the fix is a correctness argument rather than a fitted constant, but Santa Teresa is still the
only long-period spot anyone has ever graded. **Grade more frames in a long-period region.**

## 2026-08-03 (session 14) - the march/index handoff, and wind enters the height

### The handoff step is closed, and it was bigger than "found, not fixed" said

Session 13 logged the step as a curiosity - 1.167 -> 1.303 m between 13 and 14 degrees of
incidence, invisible because 97-100% of hours take the index branch. Reproduced and measured, it
is two defects wearing one coat:

1. **The branch is non-monotone.** Preferring the march wherever it reached `gamma*d` means a
   WORSE approach angle can return a BIGGER wave, because the two branches disagree by ~0.13 m at
   the crossover.
2. **The sampling interval was setting the height.** The march can only break AT a sampled depth.
   On a profile stepping 4 m -> 1 m it skips the real break point and clamps:

   | case | old (march wins) | K&G | `H(d) = gamma*d` solved continuously |
   |---|---|---|---|
   | 2.0 m 14 s over `[50,20,8,4,1]` | **0.780** | 3.313 | 2.984 |
   | 3.0 m 14 s over `[50,20,8,4,2]` | **3.120** | 4.583 | 4.153 |

   Up to 3.8x low, against the same linear theory the march itself uses. **51 of the 199 committed
   profiles reach 1-2 m** (elephant-rock, hikkaduwa-south, midigama, pottuvil-point, pavones,
   playa-cocles, aoshima, shishikui and 43 more), so the clamp fires on exactly their biggest days.
   It does not show in the current 24,808 published hours - no hour is anywhere near it - which is
   why it stayed invisible: it is a big-day defect at a minority of spots.

**Fix: the deeper break wins, `max(gamma*d_march, Hb_KG)`.** A K&G height implying a breaking
depth deeper than where the march found one means linear shoaling under-called the growth just
before breaking - which it does, everywhere - so the wave broke at the deeper of the two. The
result is continuous across the handoff and monotone in incidence (regression test pins both).
K&G sits above linear theory in nearly every real sea state, so in practice the max resolves to
the index; the depth limit still binds for a steep short-period storm sea over a shelf, which is
pinned by its own test so the branch cannot rot into dead code.

#### Fleet impact (same-input A/B, 25,136 hours of one captured fetch)

Captured once with `run --all --capture`, then replayed through both code versions offline, so
the only difference is the code (the local box failed the capture twice on the documented TLS
handshake timeout; the run was done on the Oracle VM in a scratch clone, publishing nowhere).

| | |
|---|---|
| h_mid new/old, median | **1.0000** (p10 1.0000, p90 1.0000) |
| bit-identical hours | 23,149 / 24,994 (**92.6%**) |
| hours moving >2% | 1,984 (**7.94%**) |
| null heights, old / new | 0 / 0 |
| rating changes | 1,258 hours (5.0%) - 263 up, 995 down |

Median is exactly 1.0000 in **every** region: the change is invisible except where a profile
reaches the surf zone, and there it is large and always upward. Worst cases are the long-period
Japan swell: `okuragahama` published **0.6-0.8 m for a 1.56 m 18 s groundswell arriving 1 deg
off its shore normal** - the profile has a 1 m sample and the march clamped to gamma*1.
`kodomonokuni` 2.2 -> 6.3 m on a 5.26 m 19.8 s typhoon swell, where the continuous depth-limited
solve gives ~6.7 m and K&G ~7.5 m - the new number is bracketed by both, the old one by neither.
Ratings mostly fall because `size_score` tapers above the ideal band, which is the correct
response to a wave that is now honestly oversize.

**No eye frame exists anywhere near this regime.** This is a correctness fix - the old branch
contradicted its own linear theory - not a calibrated one. The affected spots (Japan, Sri Lanka,
Philippines, pavones, playa-cocles) have never been graded.

Two tests asserted the old behaviour and were rewritten, not deleted - both now carry why the
old assertion was wrong. **Stage-0 scorecard unmoved**: `peak^2.2` still grades 4/5, max |err|
0.15 m, every frame identical. Expected - the Israel frames sit on deep profiles that take the
index branch either way.

### Height absorbs wind: the product call is settled, the coefficient is not

**Decision (user, 2026-08-03): yes.** A 2 m sea shredded by a 40 kph onshore gale must not
publish the same height as the same sea glassed off.

Part of the gap was already in the data and is NOT what a wind term fixes: onshore hours carry
**14.4%** of their in-window energy as windsea against **0.8%** offshore (24,808 published
hours), so counting chop as surf explains roughly 7% of height. The rest is a missing term.

**The first attempt was a guess and was removed the same day.** `wind_face_factor` reused the
rating's wind geometry - a 25% loss ramping from 15 to 35 kph, offshore treated as a no-op. It
was wrong in form (raw kph), wrong in sign (offshore is not neutral), and its magnitude came
from nowhere.

#### What measurement says, and where it stops

**1. The buoys say the offshore input is clean.** NDBC's standard-met file carries WDIR/WSPD on
the same line as WVHT and `observe.py` had been parsing past them since Stage 0; they are now
captured. Pairing the forecast archive (13 stations) against the stations' own observations with
the shipped `_nearest_obs`, 2,001 hours at lead <= 6 h:

| wind (m/s) | n | bias (m) | rel bias | rmse (m) | obs Hs |
|---|---|---|---|---|---|
| 0.0-2.5 | 227 | +0.059 | +6.4% | 0.166 | 0.93 |
| 2.5-5.0 | 487 | +0.045 | +4.5% | 0.175 | 1.00 |
| 5.0-7.5 | 634 | +0.046 | +3.7% | 0.168 | 1.23 |
| 7.5-10.0 | 369 | +0.066 | +4.1% | 0.201 | 1.62 |
| 10.0-12.5 | 276 | +0.020 | +1.1% | 0.209 | 1.89 |

Flat to *shrinking* with wind (model/obs 1.050 calm vs 1.010 blowing). **Open-Meteo's offshore
Hs is not wind-biased**, so none of this belongs upstream and the effect is entirely nearshore -
which also means **no buoy can ever fit it**. Caveats: the five CDIP stations contributed zero
pairs (Waverider buoys have no anemometer), so these are 7 discus buoys; wind tops out near
12.5 m/s; the archive only starts 2026-07-22.

**2. The literature gives the form, sign and scaling.** Douglass (1990), *Influence of wind on
breaking waves*, JWPCOE 116(6):651-663: onshore wind moves the break point offshore and
**decreases** the breaker height-to-depth ratio gamma_b; offshore wind does the reverse.
Feddersen & Veron (2005, JPO 35:1223) summarise it - break-point location up to 40%, gamma_b up
to 100% over the tested range, U/c range applicable to a natural nearshore environment - and
state the net: "with offshore wind not only do waves break closer to shore, but they have larger
breaking-wave heights." Douglass tested U/sqrt(g*h_0) = +-2.3 on a 1:8 slope. Note that the
modern gamma parameterizations (e.g. Zhang et al. 2021, on offshore steepness and kh) carry no
wind term at all, so there is no field-calibrated wind-gamma formula off the shelf.

So the shipped form is `physics.wind_breaker_factor(U_n, h_b)`: keyed on `U_n/sqrt(g*h_b)` with
`U_n` the shore-normal component **positive offshore** (`transform.shore_normal_wind_ms`),
signed, clamped to +-50%, applied to the combined breaker height after the field combine. At a
1.5 m breaking depth a 40 kph onshore wind is -2.9, comparable to Douglass's tested range.

**3. Nothing we own can set the coefficient, so it is 0.0.** Wind is now recorded on all five
frames (archive hindcast, same provenance as the 07-19/07-24 partitions):

| frame | wind | theta | class |
|---|---|---|---|
| 07-19 beit-yanai flat | 9.4 kph from 232 | 130 | cross-shore |
| 07-24 beit-yanai windswell | 23.0 kph from 238 | 136 | onshore |
| 07-25 hilton (hour unknown) | 11.5-15.2 kph, 223-279 | 108-164 | cross -> onshore |
| 07-26 hilton | 13.6 kph from 300 | 175 | onshore |
| 07-27 poleg | 1.9 kph from 56 | 46 | cross-shore |

**No frame is blown out.** The set spans 1.9-23.0 kph, where any sane wind term is ~1.0, so the
Stage-0 scorecard cannot constrain the coefficient - a sweep would return "every candidate
identical", which looks like validation and is not. The one frame with real onshore wind (07-24)
is also the only one whose observed band is not direct eyes. The surfer feedback store holds one
row. `WIND_BREAKER_COEFF = 0.0` therefore ships inert: the form is plumbed and tested, and the
published forecast does not move by a millimetre.

**To switch it on: grade 2-3 frames in a genuine onshore blow (>30 kph), then fit.** That is the
only measurement that can set it, and it is a morning at the beach on a bad day, not a sweep.

#### Bonus: open item 3 is settled, and not in the direction hoped

The 07-19 flat frame - +0.15 m over under every candidate, the one nothing could fix - blew
**9.4 kph cross-shore**. It is not a blown-out frame, so the wind term cannot reach it at any
coefficient. That over-call stays **structural** (a breaker index assumes something that breaks
as a wave; that frame is a 0.60 m 5.05 s windsea observed ankle-high). One fewer hypothesis.

## 2026-08-14 (session 27) - Stage 3a's promotion gate, measured: a two-grid blend reaches parity

**Why this ran.** The question asked was how worldwide spot coverage scales. The binding
constraint is the FETCH plane: Open-Meteo costs ~8.8 quota units per spot per cycle
(`fetch.py`'s own arithmetic, 65 points per minute bucket), so spot count is capped by
someone else's quota. Global model GRIB is O(1) in spot count instead. Stage 3a already
built the raw GFS-Wave source, the GRIB point reader and the dual-source archive; what it
never had was the acceptance evidence its own plan requires ("raw-source lead-time skill
>= OM's at the proxy buoys"). This is that measurement.

**Method.** 15 NDBC buoys, the committed dual-source archive, scored with the SHIPPED
`verify.lead_time_scorecard` (method rule: never a scratchpad reimplementation). Four arms:
`om`, `gfswave`, `ecmwf`, and a `blend` pairing the two grids on the same valid hour and
nearest cycle (<=12 h apart), equal weights, blended row carrying the LATER run so lead is
never overstated. No Open-Meteo calls; one NDBC obs fetch per buoy.

**Significant wave height, n-weighted MAE (m), pooled:**

| lead | OM | GFS-Wave | ECMWF | blend |
|---|---|---|---|---|
| 0-1d | **0.194** | 0.248 | 0.207 | 0.211 |
| 1-3d | **0.203** | 0.240 | 0.230 | 0.210 |
| 3-4d | 0.248 | 0.270 | 0.284 | **0.247** |
| 4-5d | 0.259 | 0.278 | 0.283 | **0.253** |
| 5-7d | 0.277 | 0.301 | 0.316 | **0.274** |
| 7-9d | **0.319** | 0.341 | 0.383 | 0.338 |

**Wave direction, n-weighted MAE (deg):** blend wins 5 of 6 buckets - 29.4 vs OM's 33.2 at
0-1d, 29.6 vs 32.6 at 1-3d, narrowing to a 0.75 deg loss at 7-9d.

**Findings.**
1. **GFS-Wave ALONE fails the gate** - worse than OM on Hs at every single lead. That is why
   the gate never opened, and it is the right verdict. Do not promote a single raw model.
2. **The blend reaches parity on Hs and wins on direction**, with EQUAL WEIGHTS and no
   tuning. Worst Hs case is 1.6 cm behind OM at 0-1d; it is ahead across 3-7d. Blending two
   free global grids is what recovers what best_match was buying.
3. **The period comparison from this run is VOID** - the `om` arm scores the energy period
   against APD while the raw arms score peak period against DPD. That is exactly the
   like-for-like rule at the top of this file, and the run violated it. The apparent 26%
   blend win on `tp` means nothing; re-run it against a single obs column before quoting it.

**Not yet established, needed before promotion:** tuned (not equal) weights, with their own
entry here; a per-region breakdown, since the acceptance bar is per-region and this pooled
the fleet; a fresher archive (these rows start 2026-07-23, and the raw arms carry ~6x fewer
rows than OM, so the arms are not the same sample); and a valid period comparison.

## 2026-08-14 (session 27, part 2) - fetch-plane plan executed: A1-A3, C1 build, D1

**A1 - NEGATIVE result: a like-for-like OM period race is impossible, permanently.**
The plan assumed archiving OM's `wave_peak_period` would let an OM-peak-vs-DPD race
accumulate. Built it, then checked the field live before shipping: **`wave_peak_period`
is null from EVERY OM model at the fleet** (best_match, ncep_gfswave016, gwam,
meteofrance_wave all return only nulls; the sole populated peak column anywhere is
`swell_wave_peak_period_gwam`, swell-only, which pairs with DPD only when swell dominates
- the APD-vs-Tm-1,0 class of mismatch, do not use it). The code change was REVERTED
rather than shipped: an always-null archived column costs quota weight on every archive
request and reads like a measurement. Standing conclusion: OM's period story is
energy-period-only; **the raw arms' race is the period evidence, full stop** - restated
valid (all Tp vs DPD): blend best at every lead past 3d (1.45-1.61 s MAE), GFS-Wave best
at 0-1d (1.74 s). Do not re-propose archiving an OM peak period without first proving the
column carries values.

**A2 - tuned blend weights do NOT beat 50/50 yet.** Grid-searched w (GFS share) per lead
on even-day runs, evaluated on odd-day runs, shipped harness both halves, 12 buoys:
fitted w = {0-1d: 0.2, 1-3d: 0.45, 3-4d: 0.5, 4-5d: 0.45, 5-7d: 0.5, 7-9d: 0.75}; holdout
gains are 0.010 m at 0-1d, 0.005 m at 7-9d, <=0.001 m elsewhere - inside noise on a
5-week archive. **Verdict: keep 50/50** until the archive clears A4's >=8 weeks, then
re-fit. (The w=0.2 nowcast hint - ECMWF-heavy near, GFS-heavy far - is physically
plausible and worth re-testing then.)

**A3 - per-region: the pooled parity hides real structure.** Hs MAE, all archived rows,
blend at 50/50 vs OM:
- **us-west (6 buoys): blend AHEAD at 5 of 6 leads** (by 0.003-0.035 m) - the first
  region to clear the promotion bar on Hs.
- **us-east (3): parity** (within +-0.012 m through 5-7d, behind 0.039 at 7-9d).
- **hawaii (3): OM clearly ahead at every lead** (0.006-0.054 m). Expected physics: the
  0.25-deg global grids cannot resolve island shadowing at nearshore Waveriders; Hawaii
  stays OM under the per-region rollout rule.
- **portugal (3 CMEMS buoys, measured ON THE VM 2026-08-14, full 15-buoy archive):
  blend AHEAD of OM at EVERY lead, by 0.031-0.076 m** (0.098 vs 0.131 at 0-1d; 0.136 vs
  0.212 at 7-9d - a 36% improvement). The strongest region in the fleet and the second
  past the promotion bar. The VM archive is ~3 weeks fuller than this box's snapshot;
  on it, us-west softens to parity-to-ahead (behind <=0.012 at 0-3d, ahead 3-7d+),
  us-east reads slightly behind everywhere (0.002-0.023), hawaii stays behind everywhere.
  VM-run A2 agrees with the local verdict: tuned weights buy <=0.005 m out-of-sample
  (fitted w drifts ECMWF-heavy near, 0.3-0.35) - keep 50/50 until A4. VM period race:
  blend best through 4-5d (1.39-1.43 s), ECMWF best at 5-9d.

**C1 - EOT20 tide built, verified, committed, NOT yet consumed.** 2.1 GB EOT20 grids
downloaded (gitignored `data/tide-src/`); `tide.py` extracts per-spot constants at the
derived offshore point (bilinear, nearest-wet fallback, refuses dry land) and synthesises
via pyTMD FES arguments; `rosa-pipeline tide --all --verify data/out` extracted **199/199
constants** (committed, the bathy pattern, ~1 KB each) and scored them against the OM
tide series in today's payloads: **median corr +0.969, median demeaned rmse 0.087 m**.
The mean offsets (-0.81..+0.41 m, sign flips by basin) are a SEMANTIC difference, not an
error: OM's `sea_level_height_msl` includes non-tidal sea level (seasonal steric, surge),
EOT20 is the astronomical tide alone. One flagged extraction: **isonoura** (corr 0.849,
rmse 0.198 m at 1.61 m range) - its offshore point masks out and the nearest wet cell
sits up the Kii Channel where tidal phase genuinely differs. The seven Sri Lanka
east-coast "low-corr" spots are microtidal (0.26 m range, demeaned rmse <=0.03 m) - noise
ratio, not error. **The switch is a separate change**: `tide_m` feeds `score.py` depths,
so consuming this moves published ratings - same-input fleet A/B + entry here, per
pb_0049. Sequenced: fill the null day-10-16 tail first, then replace.

**D1 - whole-globe GRIB fits the VM.** Measured: global `gfswave.0p25` file = 11.9 MB
per step (19 messages - wind, combined, windsea, 3 partitions: the full schema), 2 s
download, and parsing EVERY field of a full-globe step peaks at **168 MB RSS / 3.0 s** -
comfortable on the 1 GB VM one step at a time. Per cycle at 3-hourly x 16 d (129 steps):
~1.5 GB download, ~5 min sequential. ECMWF global via the existing byte-range path:
~10 MB x 41 steps ~= 410 MB. Per-basin grib-filter subsets remain ~100x cheaper in bytes
(~15-20 MB/cycle across 9 basins, at ~1,160 requests) - B1 should default to per-basin
and keep whole-globe as the scale mode; both hold the O(1)-in-spot-count property.

**A3 no-buoy promotion policy (decided 2026-08-14, operator call):** a region with no
buoy promotes on **pooled fleet evidence plus its own 👍👎 feedback stream** - clear
pooled skill first, then a trial period in which the region's feedback shows no
regression. The Hawaii exception generalises: any region measurably worse under the
blend stays on OM regardless of the pooled verdict. Only regions with their own buoy
can be promoted on skill alone.

## 2026-08-14 (session 27, part 3) - plan B built: the blended wave source exists

`blend.py` + `run --wave-source blend`, the A/B arm - NOT promoted, OM stays the default.
Composition per hour: partitions (windsea + 3 swells) from GFS-Wave full-schema boxes -
the only free source with partitions; totals (Hs/direction/Tp) blended 50/50 with ECMWF,
whose fetch is the SAME one the spectral member already makes (once per run, not per
leg); total mean period from ECMWF `mwp` alone (GFS gridded publishes none, honest None
past 240 h); weather + SST/tide still ride OM transitionally (plan C), with the marine
request cut to 2 fields (~0.2 weight/pt vs ~8.8); `ensemble=None` - blend-arm confidence
degrades to the horizon proxy until C4. The composed marine dict is unsuffixed, which
`_merge_models` passes through - extract/transform/score untouched.

**The smoke caught a real correctness bug before it shipped:** a 3-hourly UTC series
contains a local-midnight hour only where the UTC offset is a multiple of 3 h, so
publish's whole-local-day filter dropped EVERY day at Pipeline (UTC-10) - and would have
at all of Sri Lanka (UTC+5:30). Fixed by interpolating the GRIB steps to hourly before
composing (linear, circular for bearings, keys missing at either endpoint stay missing;
the same thing Open-Meteo does to 3-hourly models), pinned by two tests.

**Live smoke, 3 spots / 3 regions, full payload each:** beit-yanai 125-128 h rated,
tamarindo 120 h (blend carries 4.0 swell trains/hour vs OM's 3.0), pipeline 120 h/15 d
after the fix. Mean |rating delta| vs the OM arm: 7-9 points, max 33 - the two arms are
genuinely different forecasts, which is exactly what D3's promotion A/B adjudicates
against buoys and feedback, not something to reconcile by hand. Repo suite 421 green,
8 blend tests, 64 KB of committed fixtures.

## 2026-08-14 (session 27, part 4) - plan C2 + C4 on the blend arm

**C2 - SST from NOAA OISST.** `oisst.py`: one 0.25-deg global daily netCDF (~1.5 MB,
public domain, `*_preliminary` until the final lands ~2 weeks later; fetcher tries
final-then-preliminary back to 4 days). Blend arm only: the daily value fills the SST
column (intra-day drift ~0.1 C, below model error), the OM light value stays as the
per-hour fallback and the guard path - an NCEI outage cannot sink a run. Sanity-checked
live at 5 spots across 5 basins (Med 29.2, Portugal 20.4, Hawaii 27.2, CR 30.2,
Sri Lanka 28.8 C). SST is display + tail carry, never rating physics - not pb_0049
territory.

**C4 - the blend arm's confidence ensemble is its own two members.** No OM ensemble
request: the RAW pre-blend GFS totals ride as a one-member ensemble body (never the
blended total - it is not independent) and extract appends the ECMWF spectral member
exactly as on the OM arm. Agreement + dir_span are live again on the blend arm with
n_models=2, and `dir_n=2` marks the member-count era, per the 2026-08-11 rule. The OM
arm's 4-5-member fan is unchanged. Promotion note for D3: the two arms' confidence
numbers come from DIFFERENT member sets, so the promotion A/B compares them as separate
eras, never pooled.

## 2026-08-14 (session 27, part 5) - plan C3 evidence: wind enters the buoy archive

The weather-migration decision (C3) had no data: the archive recorded waves only, while
the buoys carry anemometers nobody was reading. Now every archive cycle records 10 m
wind from BOTH sources: OM via one extra weather-host request (2 vars, m/s so it pairs
with NDBC WSPD without conversion - the like-for-like rule), joined onto the wave points
by exact timestamp; GFS-Wave from the SAME wave gribs the archive already downloads
(`ws`/`wdir` messages ride along free). `WavePoint.ws/.wdir`, `ws`/`wdir` row keys, and
a wind pairing on the OM and GFS-Wave variable tuples - NOT the ECMWF tuple, whose wave
stream has no 10 m wind and whose card must not show an always-empty row. Both fields
were VERIFIED live before shipping (the A1 lesson): OM 384/384 non-null in m/s at
Monterey, GFS ws=3.71 m/s from a committed grib, and a live `archive --buoy 46042` wrote
384 OM rows all carrying wind. Wind columns are None on all history; `verify --archive`
starts reporting the wind rows as they mature. Guarded so wind can only ever cost its
own columns, never a wave row. Decision rule stays: OM weather remains until the
scorecard says otherwise - re-run the C3 comparison once a few weeks accumulate.

## 2026-08-14 (session 27, part 6) - C1-switch built flag-gated; the flip waits on its A/B

`run --tide-source eot20` (default om, shipped behavior untouched): extract synthesises
tide_m from the committed EOT20 constants for every hour - including the day-10-16 tail
the OM field leaves null - via one predict() per point group. Offline same-input A/B on
the committed Beit Yanai fixture: **127 paired hours, 0 rating moves, 0 bucket changes**
(mean tide delta 0.22 m - micro-tidal Israel cannot move the breaker march), and **47
null tail hours newly carry a tide value**. That is NOT the promotion evidence: the
regions that can move are the 2.5-3 m-range coasts (Portugal, Costa Rica, Japan), and
the fleet-wide same-input A/B needs a fresh `run --all --capture` after the quota reset
(00:00Z). The flip - default om -> eot20, and dropping sea_level from the blend arm's
light request - lands in ONE change with that A/B and its entry here, per pb_0049.

## 2026-08-15 - C1-switch FLIPPED: tide is EOT20 by default (the pb_0049 A/B)

**Same-input fleet A/B, 199 spots**: one live captured cycle (2026-08-15 ~05:30Z),
replayed offline through both arms with identical inputs and `--skill /dev/null`.
Result: **mean |rating delta| 0.001, maximum 1 point anywhere in the fleet, 17 spots
moved at all (each by exactly 1 at their worst hour), 3 bucket-change hours out of
~25,000** - the breaker march barely notices a <=0.8 m water-level offset at surf
depths. Gain: **10,283 hours - the entire day-10-16 tail, fleet-wide - newly carry a
tide value** (the OM field is null past day ~9), so the tide curve and tide windows now
cover the whole horizon. `run --tide-source` default om -> eot20; `om` stays as the
fallback arm. The blend arm's light marine request keeps `sea_level_height_msl`: at 2
variables the request weight is already at its floor of 1, so dropping the field saves
nothing and keeps a live fallback for a spot whose constants file ever goes missing.
The VM installs pyTMD itself (publish.sh runs `uv sync` every cycle).

Also shipped with the same evidence run: `OpenMeteoSource` now retries TRANSPORT
errors (3 tries, backoff) - four consecutive fleet captures had died on single TLS
handshake timeouts mid-run while single requests succeeded in 0.3 s, and the fix's
first live run needed and survived exactly one such retry. HTTP-level handling (the
ensemble-429 degrade) is unchanged.

## 2026-08-15 - beit-yanai's pin was ~700 m INLAND; MOVED, sample point pinned, score-neutral

Found in the Israel sat-verification batch: the `beit-yanai` pin sits in the village,
about 700 m east of the water. **This is not new and not an oversight** - the 2026-07-22
coordinate-correction pass (`02c5d61`) snapped 49 inland spots to the waterline and
*deliberately reverted this one*, tagged "calibration + fixture anchor - not snapped".
The move is held again for the same reason, now written down properly:

1. **The committed fixture key IS this pin's derived offshore point.** Pin 34.8635 minus
   the region's 0.06 deg westward push = `pipeline/tests/fixtures/32.3817_34.8035.json`.
   Moving the pin to the waterline (34.8560) derives 34.7960, and the fixture no longer
   matches - `test_pipeline_end_to_end` and every offline replay lose their input. The
   fix would be regenerating the fixture, which silently rebases the one captured
   response the whole offline suite is pinned to.
2. **Israel's scoring constants were fitted at this coordinate.** `q(T)`, the wind-gate
   denominator and the per-spot `height_coeff` were tuned against Beit Yanai readings
   (CALIBRATION rows from 2026-07-20 on). Moving the sample point makes the fitted
   constants non-comparable to their own evidence.

**What is actually true about the forecast:** the offshore SAMPLE point is 0.06 deg west
of the pin, i.e. genuinely offshore in open water, so the forecast Beit Yanai serves is
sampled from the sea - it is the MAP DOT and the derived geometry that are wrong, not the
wave data. That is why this has been survivable.

**RESOLVED the same day, exactly that way.** Pin moved 34.8635 -> **34.8612**, the
waterline read off a z16 tile and confirmed at z16 before adopting. To keep the sample
point fixed, the spot gained `offshore_bearing: 270.0` + `offshore_km: 5.42`, solved
against `bathymetry.destination` so the derived point is **(32.3817, 34.8035) exactly** -
byte-identical to the committed fixture key, so `test_pipeline_end_to_end` and every
offline replay keep their input untouched.

**The bathy profile still moved, because it is cast from the PIN, not the sample point** -
nearshore depth 15 m -> 23 m. So the move was A/B'd like any scoring change, same captured
fixture, old profile vs new: **127 paired hours, 0 rating moves, 0 bucket changes, 0.000 m
height delta.** The reason it is exactly neutral is worth recording: GEBCO's ~450 m cells
bottom this profile out at 15/23 m, both far deeper than where a Med windswell actually
breaks, so the shoaling march never consumes the changed samples - the difference sits
below the resolution the physics can use. (Which is also why CLAUDE.md forbids appending
invented shallow samples: the nearshore band simply is not measured here.)

Net: the map dot and the derived geometry are now honest, the forecast and every published
number are unchanged, and Israel's fitted constants keep their baseline. `swell_window`
[210,5] held against a derived [200,5] - no objective fault, the adoption rule's HOLD.

## 2026-08-26 - plan C3 DECIDED: weather stays on Open-Meteo, on the measured wind

Part 5 (2026-08-14) put both sources' 10 m wind into the archive and set the decision
rule: "OM weather remains until the scorecard says otherwise - re-run the C3 comparison
once a few weeks accumulate." Re-run today on the VM, `verify --archive --all-buoys
--source {om,gfswave}`, pooled MAE weighted by each buoy's n. **The scorecard does not
say otherwise. C3 closes in favour of keeping OM, and the interim posture becomes the
decision.**

Wind speed, pooled MAE (m/s), the 7 NDBC stations that carry both waves and an anemometer
(41008 41013 44013 46022 46026 46042 46059):

| lead | n | OM | GFS-Wave | GFS-OM |
|---|---|---|---|---|
| 0-1d | 1926 | **1.056** | 1.187 | +0.131 |
| 1-3d | 1758 | **1.417** | 1.433 | +0.016 |
| 3-4d | 1422 | **1.834** | 1.851 | +0.017 |
| 4-5d | 1254 | 1.983 | **1.961** | -0.021 |
| 5-7d | 1086 | 2.190 | **2.154** | -0.035 |
| 7-9d | 750 | 2.365 | **2.323** | -0.042 |
| 9d+ | 246 | 2.690 | **2.384** | -0.305 |

Wind direction is noise either way (OM ahead at 5 of 7 leads, every gap 0.4-3.7 deg,
against a 21-62 deg MAE). By region, all leads pooled: us-west a dead tie (1.855 vs
1.855 m/s), us-east OM ahead by 0.038.

**Why this is a decision and not a wash.** The crossover sits at day 4. OM wins every
lead before it and GFS wins every lead after it, and the wind gate is a rating-critical
input at SHORT lead - that is where a surfer acts on the forecast, and past day 4 the
horizon ceiling has already priced the rating down. A migration would trade 0.131 m/s at
0-1d for 0.3 m/s at 9d+, i.e. give up accuracy exactly where it is consumed. Keep OM.

**Equal samples, unlike A4's wave arms.** Both arms scored n=1926 at 0-1d - identical,
because both are joined onto the same archived wave rows. This is the same weather on
both sides, so the A4 maturity caveat does NOT apply to the comparison itself.

**What is genuinely thin, recorded rather than papered over.** 12 days of wind pairs
(the columns start 2026-08-14, None on all history) and 7 stations, ALL mid-latitude US.
Hawaii's 51201/51202/51205 and the three CMEMS Portugal buoys pair no wind - 51201 is in
the NDBC registry but returns no anemometer column, and the CMEMS wave stream carries
none. So there is no tropical or European wind evidence, and none for any region Rosa
actually has spots in. Re-run at the 2026-09-17 A4 gate, when 8 weeks are in and the
comparison is being run anyway; the verdict flips only if the short-lead sign flips.

**Quota consequence: none, and that is the point.** C3 was never the ceiling. The binding
constraint is the MARINE host at 7.69 units/point; weather is a separate host at ~1.2 and
was already measured (part 2) at a ~3,000-spot ceiling. Keeping OM weather costs nothing
against the 265-spot fleet's real cap. The 6x cut is still the blend promotion
(7.69 -> 1.21), which waits on A4.

Ledger the same day, for the record: `data/verify/quota.json` read 2,037.9 after the
02:20Z cycle = 265 points x 7.69, so four cycles are 8,152 against a 9,400 budget and a
10,000 vendor cap. **Fleet headroom on the current plane is ~305 spots, i.e. ~40 more.**

## 2026-08-26 - plan A3's no-buoy policy DECIDED: promote WORLDWIDE, verify after

A3 left one question open since 2026-08-14: when a source clears the bar, does it get
promoted in regions that have no buoy to check it against? It was explicitly recorded as
"a policy, not a measurement". **Decided by the product owner 2026-08-26: promote
worldwide. Buoy verification and tests follow once the fleet can cover all the spots.**

**The shape of the problem.** The buoy registry covers 45 of 265 spots - portugal 42,
california 2, hawaii 1. The other 220 (mexico 43, israel 42, sri-lanka 32, japan 24,
el-salvador 23, philippines 16, nicaragua 15) have no station at all. That is not a gap
that registration closes: public wave buoys cluster in US and European waters, and large
stretches of the coasts Rosa serves have none at any price.

**Why the alternative was rejected.** A per-region gate ("no buoy, no promotion") reads
as the cautious option and is in fact the self-defeating one. It would promote Portugal's
42 spots, save 42 x (7.69 - 1.21) = ~272 units a cycle, buy roughly 35 more spots, and
leave the ceiling exactly where it is. Every new spot would land in a region with no buoy
and therefore stay on the expensive per-spot call forever. A gate that can never open for
the regions being added is a decision never to scale.

**The reasoning that carries the promotion.** A buoy validates the MODEL, not the spot.
GFS-Wave, ECMWF and Open-Meteo are global grids running the same physics at every
latitude; a buoy is simply a place where the model's homework can be checked. Spot-level
coverage was never the right unit and was never achievable.

**The risk, stated plainly and accepted.** The evidence base is four buoyed regions, and
one of them - hawaii, the only tropical sample - is one where OM is clearly ahead
(measured 2026-08-14). 220 of the 265 spots are tropical or subtropical. So the worldwide
flip extrapolates from a sample that under-represents the regime most of the fleet sits
in. **This was raised, and the decision stands: go worldwide, add buoy verification
afterwards.** D3's per-region OM fallback stays in the code, so a region that later
measures badly can be reverted without a redeploy.

**What this does NOT waive.** The blend still has to clear the bar against OM on the
evidence that does exist before anything flips - pb_0049's same-input A/B and an entry
here, per CLAUDE.md's tuning rule. A3 decides WHERE a cleared source is applied, not
WHETHER it cleared. That A/B is the remaining gate.

## 2026-08-26 - plan D3 FLIPPED: the blend is the default wave source, worldwide (the pb_0049 A/B)

**Fleet A/B, 265 spots, same cycle window, run on the VM.** OM arm = the 08:20Z cron
cycle's own `data/out` (fetched 08:20-08:50Z). Blend arm = `run --all --wave-source
blend --out ~/ab/blend` started 08:57Z the moment that cycle finished, so both arms saw
the same model cycles (GFS 00Z, ECMWF 00Z, OM's best_match of the same morning). Not a
fixture replay: a source swap has no shared input to replay, so "same input" here means
same weather, same hour. Diffed per spot per shared timestamp (`abdiff.py`, scratch).

**Result: the change is large and it is the SOURCE, not a bug.** 32,223 paired hours:

| | n | mean Δ | mean \|Δ\| | p90 \|Δ\| | bucket moves | h_mid mean Δ |
|---|---|---|---|---|---|---|
| FLEET | 32,223 | +3.72 | 6.64 | 17 | 7,966 (24.7%: 3,625 up / 4,341 down) | +0.115 m |
| philippines | 1,952 | +6.91 | 12.66 | 30 | 48.3% | +0.179 m |
| hawaii | 123 | +5.14 | 7.56 | 14 | 47.2% | +0.133 m |
| japan | 3,000 | +1.74 | 7.67 | 20 | 34.1% | +0.256 m |
| portugal | 5,334 | +5.84 | 7.59 | 20 | 32.8% | +0.124 m |
| israel | 5,334 | +4.50 | 5.62 | 17 | 24.0% | +0.040 m |
| sri-lanka | 3,520 | +0.62 | 5.02 | 12 | 23.9% | +0.076 m |
| mexico | 5,160 | +3.06 | 5.94 | 15 | 18.5% | +0.104 m |
| costa-rica | 3,000 | +3.85 | 6.01 | 12 | 18.1% | +0.142 m |
| el-salvador | 2,760 | +3.41 | 6.67 | 16 | 16.8% | +0.162 m |
| nicaragua | 1,800 | +3.52 | 4.74 | 11 | 2.8% | +0.019 m |
| california | 240 | -0.06 | 6.78 | 20 | 24.6% | -0.046 m |

Rating delta histogram: 60% of hours within ±10, 29% in ±10..20, 5% beyond ±30, max 89.
The blend rates HIGHER on average and publishes a LARGER breaker (+0.115 m mean). That is
the opposite sign to the known blend handicap (below), so the handicap is not what moved
the fleet - the partition fields themselves differ. Worst spot pairs, read by hand:
boca-barranca (costa-rica, h ratio 3.0): at the same hour OM's primary swell is 0.26 m @
9.1 s mean / 18.0 s peak from 206 deg, GFS's is 0.77 m @ 17.8 s mean from 231 deg - a
different partitioning of the same groundswell, not an artefact. bagasbas (philippines,
ratio 0.5): OM 1.2 m falling to 0, GFS 0.6 m flat at 0.2 - a typhoon-season windsea the
two models place differently. **Neither can be adjudicated: there is no buoy within reach
of either coast.** That is the A3 decision, applied.

**What this A/B is and is not.** It is the pb_0049 artifact - it measures HOW MUCH the
published numbers move, which is what the tuning rule requires before a fleet-wide change
ships. It is NOT an accuracy verdict. The accuracy evidence is the archive scorecard
(2026-08-14: blend ahead in portugal and us-west, parity us-east, behind in hawaii), and
220 of 265 spots have no evidence either way. The product decision to promote worldwide
on that basis is recorded under A3 above, with its risk stated. This entry does not
re-argue it.

**The known handicap, now live.** `blend arm: 318,918 partition slot(s) have no peak
period` - GFS-Wave gridded carries per-partition MEAN periods only, so every published
partition has `peak_period: null` and `period_rideability` keys on the mean (the 1.6-2x
under-call regime of 2026-07-30). It is one-directional (down) and the fleet moved UP,
so it is a floor under the numbers, not the driver. Open item; no honest repair exists in
the source (blend.py's docstring says why inventing one is out).

**A real regression, recorded not fixed: the current day's first hours are missing.**
OM reaches `past_days=1` back to local midnight; the blend series starts at the GFS
cycle's f000 (00Z here = 03:00 Lisbon, 09:00 Tokyo, 06:30 Colombo). 157 of 265 spots lose
today's first 1-6 three-hourly rows (833 rows fleet-wide, 33,056 -> 32,223), worst
furthest east. `days[0]` still publishes (16 days in both arms) but its daylight max can
miss a dawn session on the far-east coasts. Fix is a back-reach: sample the PREVIOUS
GFS cycle's f000-f006 for the hours before this cycle's f000. Open item.

**Ops, measured on the run.** 8 auto-clustered boxes x 129 steps = 1,032 grib-filter
requests to NOMADS, sequential, zero 4xx/5xx, no throttling. Wall 1h42m (5% CPU -
network-bound), peak RSS 338 MB on the 954 MB VM. Fits inside the 6 h cron gap;
publish.sh's flock covers an overrun. Marine-host ledger: 4,075.8 -> 4,396.4 = 320.6
units, exactly `marine_light_units(265)`. A cron day on this arm is ~1,280 units against
the 10,000 allowance; spot count no longer sets the ceiling. `tail_from` is null on this
arm by design (one model, no tail seam).

**Shipped with this entry:** `run --wave-source` default om -> blend; `om` stays as the
fallback arm and the offline-replay arm (the committed OM fixtures replay through it, the
tests say so explicitly). Payload `attribution` now credits NOAA GFS-Wave + ECMWF for
waves and Open-Meteo for weather. `quota.py`'s prose, CLAUDE.md, roadmap §2, OPEN-ITEMS
14/19 and the deploy README all say the blend is primary.

## 2026-08-26 - peak-period plan A SHIPPED: DWD GWAM restores Tp on the blend arm (the pb_0049 A/B)

Same design as the morning's promotion A/B: arm A = the 14:20Z cron cycle's own `data/out`
(blend, no Tp - the first cycle on the promoted code); arm B = `run --all` from the
`gwam-tp` branch in a worktree on the VM, started 15:20Z the minute that cycle finished,
`--skill` pointed at the VM's live skill.json so confidence ceilings matched. 265/265 both
arms, 32,856 paired hours.

**What it restored, exactly as planned:** `swells[0].peak_period` non-null on **46% of
primary-swell hours and 47% of wind-sea hours** (0% before) - the 174 h GWAM horizon over a
384 h series is 45%, so coverage is the source's window and nothing else. The blend arm's
gap warning went 318,918 -> 261,859 slots; what remains is secondaries (never had a peak on
any arm) and the tail past 7.25 days.

**What it moved - small, and NOT the direction the docstring predicted:**

| | n | mean Δ | mean \|Δ\| | bucket moves | h_mid mean Δ |
|---|---|---|---|---|---|
| FLEET | 32,856 | +0.01 | 1.09 | 1,693 (5.2%: 602 up / 1,091 down) | -0.024 m |
| portugal | 5,376 | -1.23 | 2.51 | 11.8% | -0.074 m |
| philippines | 2,048 | +1.21 | 2.29 | 10.6% | -0.123 m |
| japan | 2,880 | +2.04 | 2.20 | 9.1% | -0.053 m |
| israel | 5,376 | -0.43 | 1.54 | 8.4% | -0.008 m |
| mexico | 5,160 | +0.15 | 0.31 | 1.4% | +0.009 m |
| costa-rica / el-salvador / nicaragua / sri-lanka | | ~0 | <0.25 | <1% | ~0 |

89% of hours within ±10; max |Δ| 52 (portugal). The 2026-08-16 measurement said the Tp gap
was a one-directional UNDER-call (stripping OM's Tp took h_break_mid to x0.44). Restoring a
Tp here nudged heights slightly DOWN on average, and the groundswell coasts barely moved.
Two readings, both recorded rather than resolved: (a) GFS's per-partition mean period
(`mpts`) sits much closer to the peak than Open-Meteo's `swell_wave_period` did, so the
mean-period fallback was under-calling far less on this arm than the OM-arm measurement
implied; (b) GWAM's "total swell" peak is a different partitioning from GFS's primary
swell, and where GWAM sees a short-period swell dominating, the join hands the primary a
SHORTER period than its own mean - the Portugal/Israel sign. Neither is a reason not to
ship: the join is the same cross-model rule the OM arm ran for a month, the numbers are
now the same shape the transform was calibrated on, and the effect is inside the noise
of the morning's flip. It IS a reason to keep OPEN-ITEMS 21's bulletin route alive if
secondary-swell Tp ever matters.

**Ops:** 35m26s wall for the whole fleet run - the parallel GFS fetch (e007605) cut the
morning's 1h42m by 3x even with 118 extra DWD files - 370 MB peak RSS, zero DWD errors.
Marine-host ledger +320.6 as before (GWAM costs no Open-Meteo units).

**Shipped:** `gwam.py`, `blend.compose_raw(tp=...)`, `GwamSource` wired as the default arm's
peak source, attribution names DWD (CC BY 4.0) in the payload, About and Settings; 3 real
DWD files as fixtures; 8 tests. `--wave-source om` unchanged.

## 2026-08-27 - pb_0049: GFS-Wave's duplicated wind sea, dropped (the A/B that gates the merge)

At some GFS-Wave cells one wave system is written into BOTH `shww/mpww/wvdir` and a
`shts/mpts/swdir` slot, so the partition set carries more energy than the `swh` it
partitions and the transform breaks the same wave twice. Found from Poleg publishing
1.4-2.1 m for 2026-08-30 09:00 against a 1.6 m swell that Surfline and Rosa's own OM arm
agreed on, `closure` 1.43 where healthy is 1.00. Source-side measurement (2026-08-27 00Z,
350 cells across Israel / California / Sri Lanka / Portugal / Japan / Peru x f024/f078/f120):
**6 cells (1.7%) carry the duplicate**, and in every one the pair is the same system twice -
median |Δdir| 1.7 deg, |ΔT|/T 0.002, height ratio 0.99. The 328 that close sit median 63.7
deg and 53% of period apart, and **not one falls inside the 20 deg / 15% window**. Clean
separation, so this is de-duplication, not the partition scaling ALGORITHM.md forbids: no
height is altered, no energy invented, a bimodal sea is untouched.

**Design.** Arm A = the 08:20Z cron cycle's own `data/out` (blend at `main`, WITH the
duplicate), snapshotted the moment that cycle finished. Arm B = `run --all` from the
`windsea-dedup` worktree, started 09:26:30Z, `--skill` pointed at the VM's live skill.json
so confidence ceilings matched. 469/469 both arms, **57,536 paired hours**. The arms are an
hour apart in wall clock, which is only a same-input A/B if both drew the same GFS cycle -
they did, and the diff itself is the proof: **93.1% of hours are bit-identical in rating and
97.2% in `h_mid`**. A different source cycle would have moved nearly every hour.

| | n | mean Δ | mean \|Δ\| | max \|Δ\| | hours moved | bucket moves | h_mid mean Δ |
|---|---|---|---|---|---|---|---|
| FLEET | 57,536 | +0.04 | 0.36 | 73 | 3,977 (6.9%) | 1,095 (1.9%) | -0.007 m |
| israel | 5,376 | -0.47 | 1.24 | 29 | 1,527 (28.4%) | 360 (6.7%) | -0.008 m |
| portugal | 5,376 | -0.20 | 0.96 | 28 | 1,376 (25.6%) | 308 (5.7%) | -0.011 m |
| japan | 3,072 | +0.11 | 0.77 | 73 | 229 (7.5%) | 112 (3.6%) | -0.061 m |
| california | 17,880 | +0.25 | 0.28 | 31 | 531 (3.0%) | 247 (1.4%) | -0.003 m |
| philippines | 2,048 | -0.08 | 0.18 | 18 | 69 (3.4%) | 19 (0.9%) | -0.007 m |
| mexico / sri-lanka / oregon / washington / costa-rica / el-salvador / nicaragua / hawaii | | ~0 | <0.11 | | <3.5% | <0.6% | ~0 |

**closure >1.25: 7.82% -> 4.53% of hours; median 1.000 -> 0.990; max 7.31 -> 7.31.** It
halves, it does not collapse - the handoff expected collapse and that expectation was wrong.
The residual is spread over 323 spots (boca-barranca 80 h, pillar-point 67, salema 57), i.e.
a different, still-open cause, and the unchanged max says the very worst hour was never a
duplicate at all. **Do not chase the residual off the back of this entry** - `closure` is
diagnostic only and nothing scores on it.

**Direction of the move.** `h_mid` changed on 1,603 hours: **1,546 down, 57 up**; the 57 up
average +0.123 m, max +0.400 m, and 50 of them land on a single far-horizon hour
(2026-09-05T15:00+09:00) on the Japan coast. This is not energy appearing from nowhere:
dropping a short-period wind sea raises the effective period of what is left, and shoaling
gain is period-dependent, so a smaller offshore sea can break slightly bigger. Their
`closure` improves in the same move (okuragahama 1.29 -> 1.02, praia-do-meco 1.29 -> 1.23),
which is the expected sign.

**Rating goes down where waves are small and up where they are big** - israel -0.47 and
portugal -0.20 against california +0.25 - because the removed duplicate was inflating
heights, and inflation reads as a better rating on a small day and a worse one on a big day.
Fleet mean +0.04 is inside the noise; the honest number is that 6.9% of hours changed rating
at all and 1.9% changed bucket.

**Ops:** 42m33s wall for the 469-spot treatment run, 457 MB peak RSS, exit 0. No extra
Open-Meteo units - the de-dup is pure post-processing of files already fetched.

**Shipped:** `blend.drop_duplicate_windsea()` with `DEDUPE_DIR_DEG` / `DEDUPE_PERIOD_FRAC`,
applied in `compose_raw`'s per-hour loop; 5 tests. `--wave-source om` is untouched.
**Re-derive the two constants if GFS-Wave's partitioning changes** - they are the measured
gap between the duplicate cluster and the nearest genuine bimodal sea, not round numbers.

## 2026-08-28 - Random-sea surf height: friction + Battjes-Janssen + the 0.79 close (session 25)

**Trigger.** User side-by-side, Poleg, Sun 2026-08-30: Rosa published 1.5-2.3 m against
Surfline's 0.6-1.1 m on near-identical inputs (offshore Hs 1.55 vs 1.6 m, 8 s, 280-284 deg,
identical 142 kJ at midnight). Two independent causes found; both fixed.

### Fix 1 - `extract._partition` discards a peak period below the mean (`ef5a658`, on main)

The GWAM Tp join stamped another sea's peak on GFS partitions: 35/74 poleg partitions carried
Tp < Tm (worst: Tp 2.2 s on a 1.31 m / 7.8 s sea), crushing rideability and swinging the
published day 3x (0.55-1.9 m mids) while the sea itself barely moved. Tp < Tm is spectrally
impossible - such a peak is now dropped to None (mean fallback). Effect confined to
blend-arm hours whose GWAM cell disagrees with GFS partitioning; Sunday's 15:00-21:00 mids
went 0.55-0.89 -> 1.20-1.45 under old physics.

### Fix 2 - the transform ran monochromatic-hot; random-sea march (this entry)

**The claim, measured before any code:** a Battjes-Janssen reference march (SWAN-class
random-wave breaking + JONSWAP friction) over poleg's committed profile gives 1.4 m where
the shipped march + K&G close gave 1.9-2.0. Two independent routes agree at ~1.4:
BJ numerics, and Caldwell & Aucan 2007's finding that K&G(Hs) tracks the TOP-TENTH breaker
(H1/10) with H1/3 = 0.79 x H1/10 (their eq. 4, Rayleigh) - 2.01 x 0.79 x friction ~ 1.4.
The same paper flags physics estimators as overestimating short-period (<11 s) surf.

**Shipped** (`physics.surf_height_over_profile`, replaces the monochromatic
`breaker_height_over_profile` in the production path):
- JONSWAP bottom friction (Cb 0.038, Hasselmann et al. 1973) - needs along-ray DISTANCE, so
  the whole path switched from bare depth lists to `(dist_m, depth_m)` samples
  (`DepthProfile.wet_samples_deep_to_shallow`). Poleg's 12+ km shelf takes ~20% off an 8-9 s
  sea; a steep groundswell coast loses ~nothing - the correction is regime-dependent in
  exactly the direction the July side-by-sides kept hinting at.
- Battjes-Janssen (1978) breaking dissipation in ~25 m substeps between measured samples,
  replacing the hard gamma*d cap. Interpolating between MEASURED samples; the march still
  never continues past the shallowest one - no invented bathymetry.
- The K&G close is fed the friction-attenuated offshore height and multiplied by
  H13_OVER_H110 = 0.79: publish the significant breaker, not the top-tenth wave.

**Poleg Sunday, end to end (blend arm, both fixes):** flat 0.84-1.29 m mids across the day
against Surfline's flat 0.6-1.1 band; was 0.55-1.9 swinging 3x. Small Med windswell
(0.6 m / 5 s) moves 0.78 -> 0.60; a 2.5 m / 14 s groundswell case 2.9 -> 2.3.

**The July eye frames no longer gate physics (product call, 2026-08-28).** Under the new
march the five frames conflict internally - 07-19 beit-yanai demands the transform DOWN at
~7 s where 07-26 hilton demands it 1.6x UP - and their inputs are OM hindcast
reconstructions, not the blend production serves. Doctrine set by the user: **the math must
carry the forecast on its own; eye reports are never required or waited for, but when one
arrives it is ground truth and the calibration layer re-fits on it.** The frames stay
committed as history + future recalibration material; the 07-26 pin in
`test_experiment.py` now asserts the new (0.3, 0.4) range with the full story in its
docstring. `height_coeff` remains 1.0 at all 624 spots; rideability untouched.

**Owed:** the same-input fleet A/B on the VM (469+ paired spots, old vs new physics arm) to
size the worldwide move - expected: short-period shelf regions (Israel, wide-shelf beach
breaks) down 25-40%, groundswell coasts down ~21% flat (the 0.79). And the OM-vs-blend A/B
from 08-26 is still owed, now on top of both fixes.

## 2026-08-29 - Wind: hot at sea, damped at the coast; the coastal-station arm (session 46)

**Trigger.** User, over several sessions: "we have been way too light on wind." Side-by-side
Zvulun, Sun 2026-08-30: Rosa 19/15/4/9/13/17/16 kph at 00/03/.../18 vs Surfline
31/23/17/15/17/20/21 kph, on the same swell (1.9/1.75/1.6/1.5/1.3 m vs 1.8/1.7/1.6/1.5/1.3 m,
WNW, ~8-9 s both). The swell input is not in dispute; the wind is.

**Measured, not guessed - three facts.**

1. **Against the buoys the model is HOT, not light.** `verify --archive --all-buoys --source om`
   on the VM archive (15 anemometers, 358 pairs at 0-1 d): wind-speed bias is positive at
   nearly every station and every lead - +0.3 to +1.6 m/s at 0-1 d, growing to +1 to +4 m/s
   past day 4. So the offshore wind field is not under-forecast.
2. **The published wind is a mixed land-sea cell.** Live check, Zvulun: the 5.5 km offshore
   point returns the IDENTICAL series to the beach pin - same ~13 km `best_match` (ICON)
   cell. Same hours, knots:

   | | 00 | 03 | 06 | 09 | 12 | 15 | 18 |
   |---|---|---|---|---|---|---|---|
   | our cell | 9.0 | 4.5 | 2.4 | 7.8 | 9.8 | 8.6 | 4.9 |
   | 40 km out | 10.8 | 8.9 | 6.3 | 6.7 | 12.8 | 13.4 | 10.6 |
   | GFS, same cell | 11.7 | 8.3 | 8.7 | 9.5 | 11.9 | 10.7 | 7.2 |
   | Surfline | 16.7 | 12.4 | 9.2 | 8.1 | 9.2 | 10.8 | 11.3 |

   The 2.4 kn 06:00 lull - the hour that makes the green "best session" - is the most
   damped one, and no other source agrees with it.
3. **The harness had no coastal truth.** Every anemometer in `data/buoys` is offshore, so
   the bias a surfer sees has never been measured. Nothing can be tuned off it until it is.

**What Surfline does (public record, no API touched).** Wind is bought, not built: GFS
globally, NAM in North America and Hawaii; no proprietary atmospheric model - LOTUS and
the "Nearshore Model" are wave products. Their coastal fix is ~500 stations at spots,
about half their own, feeding a "Predicted" correction whose method is unpublished.
The one published algorithmic fix in the industry is Windguru's CS+ (sample the model
half a grid cell seaward of the model's coastline; shipped OFF by default, "may be
detrimental in others").

**Built.** The free-data version of their stations: `data/stations/metar.yaml` (90
aviationweather.gov airfields within 25 km of a spot, generated; 280 of 624 spots have
one), the IMS Envista adapter for Israel's beach-level 10-minute stations (token
pending - `ims.yaml` stays empty rather than carry ids from memory; the API doc's rule
that stamps are always UTC+2 whatever suffix they carry is applied in the parser), the
archive arm (the model's 10 m wind at every station each cycle, one weather-host request,
`data/verify/stations/<id>.jsonl`, never able to fail the buoy archive) and
`verify --stations --archive` (per-station + pooled lead cards, wind columns only).
Live smoke: 90 stations archived (384 hourly rows each), 89 of 90 scored (one 504,
degraded per station), nothing matured yet - the archive was ten minutes old.

**Method rule, restated.** Nothing was tuned. No wind gain, no gate change,
`height_coeff` 1.0 everywhere. The correction is chosen AFTER ~2 weeks of station pairs,
from the measured bias by wind sector and hour of day, as an A/B against the same
stations (OPEN-ITEMS 25). An airport is 5-20 km from the beach: this measures the
regional and diurnal bias, not the last 5 km.

## 2026-08-30 - Zvulun graded by eye; the published wind moved from ICON to GFS (session 47)

**Trigger.** Same spot, next morning. Surfline vs Rosa at 07:16, Sun 2026-08-30, then the
user AT THE BEACH: "wind and wave as surfline predicted". First volunteered eyes on the
wind question - truth per the doctrine at the top of this file.

**The frame (06:00-07:00 local, Zvulun).**

| | swell in | face | wind |
|---|---|---|---|
| Rosa (20:33Z cycle, ICON) | 1.75 m 8.3 s, Tp 9.2, 299 | 1.1-1.6 m "head-high", GOOD 52 | 3.4 kn NW |
| Surfline | 1.7 m 8 s, 297 | 0.9-1.2 m | 16 kph = 8.6 kn NW |
| Eyes | | 0.9-1.2 m | ~9 kn NW |
| METAR LLBG (15 km inland) | | | VRB 2-3 kn |
| METAR LLHA (Haifa, coastal, 06:50) | | | 5 kn |

**Wind - three facts.**

1. **Surfline's wind IS raw GFS.** Open-Meteo `gfs_seamless` at the pin gave 15.0 / 11.5 /
   8.3 kn at 00 / 03 / 06; Surfline showed 29 / 23 / 16 kph = 15.7 / 12.4 / 8.6 kn. Every
   hour of the day matched to the rounding. The "Surfline vs Rosa" wind gap was ICON vs GFS.
2. **The beach sided with GFS; the airport did not.** Ben Gurion read 2-3 kn at 06:20
   while the beach had ~9 - so an inland METAR cannot referee the beach-hour wind. It can
   referee the regional bias, and its first matured pairs (last night's westerly, 21-04Z)
   say the model was LIGHT by 2.6 m/s at LLBG (n = 8) and 2.0 m/s at Haifa (n = 4) - the
   direction OPEN-ITEMS 25 predicted for the coastal cell.
3. **Offshore, GFS is hotter still** (2026-08-29: the model is already +0.3..+1.6 m/s at
   the buoys). Beach outranks sea for a surf app; noted, not hidden.

**Done.** `fetch.WEATHER_MODEL = "gfs_seamless"` - the run's weather leg (both arms:
`OpenMeteoSource._fetch_batch` and the blend's aux weather batch) and the archive's wind
batch all name it; a single model keeps the hourly keys plain. Same host, same weight,
plan C3 untouched. **The A/B is kept:** the station arm also fetches
`WEATHER_AB_MODEL = "icon_seamless"` and archives it at `<station>.icon`, and
`verify --stations --archive --wind-model {gfs,icon}` scores either against the same
METAR/IMS observations. The 2 ICON cycles archived before the switch were renamed to
`.icon` on the VM so the history is not mixed. Smoke, Zvulun OM arm: 28 / 21 / 15 / 14 /
18 / 22 / 23 / 16 kph at 00..21 vs Surfline 29 / 23 / 16 / 15 / 18 / 24 / 24 / 16;
06:00 dropped GOOD 52 -> FAIR 45 and the false "best session" with it.

**Height - the transform, not the swell.** Same swell in (1.75 vs 1.7 m, 8.3 vs 8 s), faces
1.1-1.6 vs 0.9-1.2, eyes with Surfline: our breaker gives mid 0.77 x Hs where the beach
showed ~0.62 x Hs on this 8-9 s WNW swell at a Herzliya beach break. **One frame does not
tune a transform** - `height_coeff` stays 1.0, the breaker constants stay. This frame is
the first graded one for wind; the transform gets re-examined when there are enough
graded frames to sweep, as an A/B with the shipped harness.

**Second frame, same morning - Hilton (TLV), ~09:00 local, eyes: wind 10-15 kn, faces
1.0-1.2 m.** Published (ICON, 20:33Z run): 2.8 kn onshore, faces 0.9-1.4, FAIR 49. Same
hour, same pin: GFS 6.7 kn (gust 7.4) W, ICON 4.7 kn. METAR 06:00Z: Ben Gurion 300/10 kn,
Haifa 290/8 kn. So on this hour the beach and the airport agree (10 kn) and BOTH models are
light - GFS by ~5 kn, ICON by ~8. The switch halves the miss; it does not close it. That
remainder is what OPEN-ITEMS 25 step (3) - the per-sector, per-hour bias table from the
station pairs - is for, now measured on top of GFS. Faces: 1.0-1.2 seen inside our
0.9-1.4 - this 8.4 s 305 swell at Hilton the transform had right.

**Method rule, restated.** The model switch is a source change on eyes + one night of
station pairs + an exact match of a competitor's published numbers to a public model; it
is NOT a tuned knob and it is reversible in one constant. The measured A/B (`--wind-model
icon` vs `gfs` after ~2 weeks) is what confirms or reverts it. Buoy-archive `ws` rows
before 2026-08-30 04:35Z are ICON; after, GFS - a wind card that straddles the date mixes
them.

## 2026-09-07 - Bottom friction: the coefficient is effective, not textbook (Dream review)

**What was found.** The 2026-09-07 Dream review checked the friction line against the law it
cites. SWAN's JONSWAP energy form is `S_bot = -Cb * sigma^2 / (g^2 sinh^2 kd) * E`; the march
(`physics.surf_height_over_profile`) computes `Cb / g * (sigma/sinh kd)^2 * E` - one factor
of g short, so with `BOTTOM_FRICTION_CB = 0.038` the dissipation is 9.81x what Hasselmann's
0.038 gives. Dimensionally the term is kg m s^-5 summed with Battjes-Janssen in W m^-2. The
suite could not see it because `test_physics._scalar_march` transcribes the same line.
The reviewer's offline probe over all 1407 profiles (straight-in, single partition): under
the textbook coefficient heights rise at ~2/3 of spots (median x1.09-1.30 by sea, p90 up to
x2.7), and 25-31 spots that publish <0.05 m today would publish >=0.3 m. Poleg 1.55 m @ 8 s:
1.416 m now, 1.568 m under textbook Cb, 1.587 m with no friction - the shelf takes 11% off
today, not the "~20%" the 2026-08-28 entry wrote.

**Decision - keep the heights, fix the label.** The 2026-08-28 entry's "two routes agree at
~1.4" and every eye grade since were produced by this line, and the operator's standing
read is that the fleet is close and, where wrong, still a little HIGH. Removing 90% of the
friction loss is therefore the wrong direction on the evidence we have; the textbook value
is not truth, the graded frames are. So nothing in the output moves: the constant stays
0.038, the line stays `/ GRAVITY`, and the code, ALGORITHM.md and this entry now say what
that means - an EFFECTIVE Cb of 0.038 * g ~ 0.37 m^2 s^-3, ten times SWAN's swell default,
a tuned knob and not a literature constant. Same-input A/B: byte-identical, by construction.

**Standing rule.** Do not "correct" the g to g^2 as a code fix. A future change to friction
is a re-tune of the effective coefficient under pb_0049 (Stage-0 same-input A/B scored with
the shipped harness, buoys where they exist, graded frames where they do not), and it must
start from the fact that today's 0.37 is what the eyes agreed with. Dream diff
`2026-09-07/rosa/jonswap-friction-over-g-squared.diff` is REJECTED in the ledger for this
reason; its test proves the label, not the surf.

## 2026-09-08 - Tide: a dried bathy sample is the shoreline, not a hole (Dream review)

**What was found.** `score.score_hour` (and its copy in `experiment.predict_frame`) shifted
the depth profile by the EOT20 tide and DELETED every sample whose depth went to zero or
below. On a monotone ray the dried sample is the beach; deleting it handed the march a
profile ending one whole GEBCO segment further out (median 0.5-1 km, 4-8 m deeper), so the
K&G close ran from a barely-attenuated offshore height. Five centimetres higher the same
sample was back at 0.05 m, the march ran the wave into centimetres of water where the
friction term annihilates it, and the close got ~0. The hour table stepped from a real wave
to FLAT and back as the tide crossed the sample's depth. Reachable since the 2026-09-03
seedings: 130 of 1408 spots have an EOT20 amplitude sum larger than their shallowest wet
sample. Reviewer's fleet sweep (1.5 m / 10 s down the normal, 0.05 m tide steps, all 1407
profiles): 72 spots stepped >= 0.2 m at a sample drop-out, 40 of them >= 0.5 m, worst
1.289 m -> 0.001 m at mona-vale-beach; saunton 0.51 -> 0.00 m between -2.00 and -1.95 m.

**Fix.** `physics.tide_shifted_samples`: the dried sample becomes the shoreline, placed
where the shifted depth crosses zero by linear interpolation between it and the last wet
sample (the same between-measured-points interpolation the march already does - nothing
invented, no new constant), everything shoreward is dropped. `score_hour` and
`predict_frame` share it, so the calibration harness is the production path again.

**Same-input A/B (reviewer's, offline, all 1407 profiles x 3 swells).** At tide 0 the march
is BIT-IDENTICAL. Drop-out steps 72 -> 0; >= 0.5 m steps 40 -> 4; 0.8 m / 7 s: 54 -> 4.
The footprint is ~115 macro-tidal spots for ~0.6 % of fleet hours (~3,400 of 540,288 in
one 16-day table; median 3.2 % of a touched spot's own hours, up to 41 % at lynmouth), and
at those hours the height moves DOWN: median new-minus-old -0.23 m, < 0.05 m at 149 of 575
sampled spot-levels vs 38 before. That is the fix no longer marching AROUND a dry sample:
the old non-zero numbers at those hours were not physics either. Goulien's low-tide range
goes 0.17-0.69 m -> 0.00 m; perranporth and strathy barely move (-0.04 m).

**Decision - applied 2026-09-08.** Continuity in the tide is the same contract
`breaker_height_over_profile` states in incidence, and the discontinuity was a defect, not
a tune. Accepted with eyes open that macro-tidal beaches (Goulien/Saunton/Rhossili class)
now read consistently flat at low water where the shallow-shelf friction eats the wave; the
reviewer's paired remedy (a shallow-shelf friction re-tune) was never filed, and any such
change is an effective-Cb re-tune under pb_0049 (see 2026-09-07), not part of this fix.
Repo pin: `test_score.TestTideShiftedSamples` (unit rules + a 0.05 m sweep on a synthetic
shelf, worst step < 0.2 m). 148 further spots still step 0.2-1.0 m across 5 cm of tide with
the sample set UNCHANGED - the `qb > 0.1` gate vs the K&G close - recorded as OPEN-ITEMS 31.

## 2026-09-09 - The two GEBCO grids, measured: the local one is right, and it is not safe to ship yet

Ran the source swap OPEN-ITEMS 17/23 has been holding since 2026-08-15. `bathy --source local`
(new; `bathymetry.LocalGebcoSource`, h5py straight onto `data/bathy/GEBCO_2024.nc`, no netCDF4
stack) cut a candidate profile for all 1408 spots into a scratch dir in **3.2 s** - the 25 min
an API sweep takes is entirely OpenTopoData's 1 req/s pacing. Nothing committed was touched;
`run --bathy-dir` was added so an arm can be scored without disturbing the fleet.

**The candidate reproduces item 23's spot measurements exactly** - pasta-point 280 m -> 13 m,
sultans 255 -> 5, madihera 264 -> 1 at the 0.25 km ray point.

### Four independent measures, all favouring the local grid

| measure | committed (gebco2020 API) | candidate (GEBCO 2024 local) |
|---|---|---|
| profiles differing at all | - | 1408 / 1408 |
| 0.25 km sample, median | 0.5 m | 2.0 m |
| \|delta\| > 50 m / > 100 m | - | 76 / 36 spots |
| land samples, fleet total | 1268 | **928** |
| non-monotone samples | 833 | **765** |
| deepest sample IS the reference | 1206 | **1229** |
| spots with < 3 wet samples | 4 | **1** |
| eye frames, shipping knob `peak^2.2` | 1 of 5 pass | **2 of 5** |
| eye frames, least-bad max error | 0.17 m | **0.13 m** |

Every geometry counter moves the right way, the shipped experiment harness prefers the
candidate at **every one of the five frames** (hilton -0.18 -> -0.16, poleg -0.24 -> -0.23,
beit-yanai-flat +0.08 -> pass), and CMEMS SDB already agreed with this grid and not the API
(item 23). Eyeballing the raw rays settles it beyond the counters - `jelly-baby` reads
`[-73, -65, -31, 92, 127, -44, -4, 344, 944]` on the API (73 m of hillside 250 m offshore,
then water, then land again at 5 and 8 km) against `[1, 1, 1, 1, 1, 3, 37, 178, 490]` locally,
which is simply what an atoll rim looks like.

### Why it is NOT applied

Same-input fleet A/B (`ab_height.py`: identical synthetic seas down each spot's own window
centre through both cuts, so weather is held fixed by construction and all 1408 spots are
covered rather than the handful a live capture reaches):

| sea | median h_mid A -> B | mean delta | \|delta\| p90 | moved > 0.5 m | bucket changes |
|---|---|---|---|---|---|
| 1.0 m 8 s | 0.54 -> 0.53 m | -0.014 m | 0.256 m | 32 | 357 (25.4%) |
| 1.5 m 12 s | 1.31 -> 1.30 m | -0.027 m | 0.640 m | 185 | 245 (17.4%) |
| 2.5 m 16 s | 2.17 -> 2.17 m | -0.013 m | 0.971 m | 336 | 201 (14.3%) |

The fleet median barely moves - but the tails are enormous and they land on named waves. At
1.5 m / 12 s, **50 spots go flat (< 0.15 m) that were not, and 48 that were flat come back**.
The newly-flat list includes **uluwatu 1.60 -> 0.01, g-land-speedies 1.67 -> 0.13, hikkaduwa
1.40 -> 0.01, weligama-west 1.55 -> 0.01, koggala, kabalana, jelly-baby, villingili**. Publishing
0.01 m at Uluwatu is a worse failure than the wrong 1.60 m it replaces.

**The mechanism is not the grid - it is that the grid and the friction coefficient are coupled.**
The local cut resolves reef flats the API never showed: 3-5 km of 1 m water in front of the
break. `BOTTOM_FRICTION_CB = 0.038` applied over `g` is an *effective* Cb of ~0.37 m2s-3, ~10x
SWAN's swell value, tuned by eye on 2026-09-07 **against profiles that contained no such flats**.
Marched across 3 km of 1 m water that coefficient annihilates the wave. The old profiles never
stressed it; the new ones do, at exactly the reef spots the swap was meant to fix.

**So the swap is blocked on a friction re-fit, not on more bathymetry evidence.** The grid
question is closed - the local grid is the better seabed on four independent measures. What is
open is `BOTTOM_FRICTION_CB` (and possibly a cap on friction path length over a flat) re-graded
against the new profiles. Do them together or neither: applying the grid alone publishes zeros
at world-class waves, and re-fitting friction against the old rays fits it to a seabed that
isn't there.

Tooling committed and inert: `LocalGebcoSource`, `bathy --source {opentopo,local} --grid`,
`run --bathy-dir`, and the profile `source` string now records which grid a cut came from
(`DepthProfile.grid_label`) so the two can never be mixed silently inside one fleet.

## 2026-09-09 - Coastal wind: the bias is real, and none of the corrections is defensible

OPEN-ITEMS 25 step 2 is done - the station archive has matured. 89 of 90 METAR stations,
**17,920 paired hours at 0-1 d** (it was 649 on 2026-08-30). Step 3 asked which correction
to fit from the measured bias. Answer: **none of them, on this data.**

Harness extended rather than reimplemented (`verify --stations --archive --bias-profile`):
`station_bias_profile` and `_station_pairs` reuse the lead card's exact pairing - same
tolerance, same nearest-obs match, same collapse of the several archived runs covering one
valid hour - and only regroup it. Hour is SOLAR (lon/15), not civil, so stations sharing a
timezone across 30 degrees of longitude are not smeared.

### The bias is real and it is a sea breeze

Pooled wind-speed bias at 0-1 d is **-0.01 m/s** - no bias at all, at fleet level. Broken
out by solar hour it is nothing of the kind:

| solar hour | 00-04 | 06-07 | 12-14 | 15-17 | 21-23 |
|---|---|---|---|---|---|
| bias (model - obs) | **+0.23 to +0.29** | ~0.00 | -0.18 to -0.25 | **-0.28 to -0.34** | +0.14 to +0.25 |

0.63 m/s peak to peak, crossing zero at dawn and dusk: the model runs hot overnight and
light through the afternoon, which is the thermal sea breeze it cannot resolve. The pooled
average is zero because the two halves of the day cancel.

### Every candidate correction, fitted on the earlier hours and scored on the later

Split by TIME, never at random - a random split leaks, because the same weather system sits
in both halves. Train 12,030 h, test 5,913 h, 85 stations (`tools/wind-bias/fit_variants.py`):

| candidate | held-out MAE | vs uncorrected |
|---|---|---|
| uncorrected | 1.306 m/s | - |
| pooled diurnal (one 24-slot table) | 1.299 m/s | **-0.5%** |
| per-station constant | 1.149 m/s | **-12.0%** |
| per-station diurnal | 1.149 m/s | -12.0% |

**The diurnal term does not pay.** 0.63 m/s of systematic error inside 1.31 m/s of scatter
moves MAE by half a percent. It is a true signal and a worthless correction.

**Per-station diurnal is not actually a third candidate at 11 days** - at ~11 samples per
station-hour slot every slot falls back to the station constant (MIN_HOURS_PER_SLOT = 40),
so it scores identically. Re-run it at a month before believing either number.

### Why the 12% must not be shipped

The per-station constant works because it fits each airfield's **siting**, not the model:
median +/-0.05 m/s, p10 -0.96, p90 +0.87, mean magnitude 0.65 m/s, and the sign is a coin
flip - 38 of 85 stations read hot, 47 read light. There is no fleet direction to it.

Applying that to a spot means carrying an airfield's shelter 5-20 km to a beach. At the 38
sheltered stations the correction **removes** wind from the published forecast - the same
direction as the lightness this item exists to explain (Zvulun 2026-08-30: Rosa 19/15/4/9/13
kph against Surfline 31/23/17/15/17). The best-scoring candidate would make the known
complaint worse at nearly half the fleet, and nothing in this archive can tell us whether
it would, because every station in it is the airport, not the beach.

**So no correction ships, and the blocker moves back to step 1: `IMS_API_TOKEN`.** The
question "is the beach windier than the model's coastal cell" cannot be answered by
instruments sitting 5-20 km inland, however many hours of them accumulate. Do not re-run
this analysis hoping for a different answer; run it again when there is a beach-level
station, or at a month for the per-station diurnal term alone.

Committed and inert: `--bias-profile` on the station pass, `station_bias_profile`,
`fit_diurnal_correction`, `merge_bias_profiles` and `tools/wind-bias/`. Nothing in the
published pipeline changed.

## 2026-09-09 - Friction re-fit against the local grid: the coefficient is not the lever

Follow-on to the entry above. The seabed swap is blocked because the local cut resolves
reef flats that the eye-tuned friction annihilates; the obvious move was to re-fit
`BOTTOM_FRICTION_CB` against the new profiles. It does not work, and the sweep says why.

`breaker_height_from_profile` now takes a `friction_cb` sweep hook, same shape as the
existing `rideability` one (None ships the constant). `tools/bathy-ab/friction_sweep.py`
sweeps it over both cuts and scores each candidate on the five graded frames, the flat-spot
count, ten named reef waves, and fleet movement against today's published baseline:

| cb | arm | frames passed | flat spots | of the 10 watched | median h | vs today |
|---|---|---|---|---|---|---|
| 0.038 | committed | 1 | 63 | 0 | 1.31 m | - (shipping) |
| **0.038** | **local** | **2** | 65 | **10** | 1.30 m | -0.027 m |
| 0.019 | local | 1 | 20 | 6 | 1.55 m | +0.213 m |
| 0.0095 | local | 1 | 4 | 1 | 1.70 m | +0.363 m |
| 0.0038 | local | 1 | 1 | 1 | 1.79 m | +0.458 m |
| 0.0019 | local | 1 | 0 | 0 | 1.81 m | +0.490 m |

**The best frame fit in the whole sweep is the local grid at the SHIPPED coefficient** - two
frames instead of one, and a fleet median that does not move (-0.027 m). Every reduction
that clears the reef spots costs +0.21 to +0.49 m across all 1408 spots and gives a frame
back. There is no value that buys the reefs without inflating the fleet by more than the
error being fixed.

### Why - measured, not reasoned

All **50** spots the swap makes flat are recovered by switching friction off entirely;
**0** are still flat (`1.5 m / 12 s` down each spot's own window centre). It is friction,
not geometry - the profiles themselves are fine.

Tracing uluwatu on the local cut: samples run 11 m at 2 km, then 1 m at 1 km and at 250 m.
The march reaches the shallow leg carrying ~1.4 m (that is what no-friction returns), and
1750 m of JONSWAP dissipation at 1-11 m depth takes it to 0.013 m. The wave is destroyed
**before it ever breaks**: at 11 m a 1.4 m wave has `qb` ~ 0, so `surf_in_profile` - which
records the largest height at any substep where `qb > 0.1` - never sees it, and the K&G
close is fed the same friction-attenuated offshore height, so both terms of the `max` are
near zero together.

So the pathology is not the coefficient's magnitude but **where the friction is applied**:
across a kilometre-scale shallow shelf that a 460 m GEBCO cell smears in front of a reef
which in reality breaks a few hundred metres out. The same coefficient is right on the
frames it was tuned on, and right for the fleet median, and wrong only on this geometry.

### What to grade next - a structural change, not a knob

The candidate is to stop or taper friction once the wave is depth-limited: past the point
where breaking sets the height, JONSWAP friction is second order, and continuing to
integrate it over a smeared reef flat is what drives the answer to zero. That is a change
to the physics, not a tuning, so it wants its own pre-registered question, both A/Bs
(frames + the 1408-spot same-input sweep) and its own CALIBRATION entry. **Do not lower
`BOTTOM_FRICTION_CB` to buy the reefs** - the sweep above is the record of what that costs.

Until then the seabed swap stays unapplied, and OPEN-ITEMS 17/23 stay open on this, not on
bathymetry evidence.
