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
