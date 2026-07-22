# Calibration Log

Method: CLAUDE.md §Calibration. Log every dogfood session below; adjust height_coeff / score weights only from accumulated evidence.

## Scope & honesty (read first)
**This calibration is Israel/Med-only, not global — do not claim otherwise.** The numeric
knobs (`PERIOD_EXP`/`q(T)`, wind-gate denominator, per-spot `height_coeff`) are fit against a
handful of Israeli beaches (user's eyes + cam) and one buoy (ISRAMAR Hadera). That regime is
short-period windswell + micro-tides. It is **untested** for macro-tidal, long-period
groundswell spots (Costa Rica, Sri Lanka).

Split what generalizes from what doesn't:
- **Structural fixes generalize** — period-aware breaker height, the wind gate (offshore wind
  can't invent surf), daylight-only day-max. These are physics, true everywhere.
- **The constants do not** — they are tuned to the Med and are guesses everywhere else.

### Validation strategy (the real fix)
Ground truth for the whole world cannot come from human eyes — the user watches only a few
beaches. **Primary global validation is buoy-only:** compare Rosa's predicted `Hs`/`Tp` (model
input) and `h_break` against measured **NDBC / CDIP** buoys worldwide. No eyes needed; catches
whether the height/period math is sane **per region**. It validates *size*, not *rideability* —
that's an accepted limit.

### Admin/manual per-beach calibration (allowed, but NOT the basis)
For specific beaches we actively watch, an optional admin/manual `height_coeff` (or similar
per-spot override) may refine that **individual** spot. Strict rule: **the global formula knobs
(`PERIOD_EXP`, wind gate, defaults) are NEVER driven by these eye-based per-beach observations.**
Manual tuning is a local override on top of a buoy-validated global formula — never the
foundation of it. (Consistent with CLAUDE.md's rejection of ad-hoc user corrections as the moat.)

| Date | Time | Spot | Rosa pred (h, rating) | Observed (eyes) | Buoy (source, Hs, T) | Notes |
|------|------|------|------------------------|-----------------|----------------------|-------|
| 2026-07-19 | ~10:00 | beit-yanai | 0.5–0.8 m waist-high, GOOD 56 (day max FIRING 73) | ankle-high at best, ~0.1–0.2 m (user, cam) — Surfline forecast said 0–0.3 POOR | ISRAMAR Hadera #80 @ 07:00 UTC: Hs 0.56 m, Tp 6.5 s (OM input 0.66 m = +18% hot, minor) | **Calibration fix #1**: pred was pre-fix. Root causes: h_break ignored period; additive wind pts made night land breeze FIRING. Fixed: `q(T)=clamp(T/10,0.4,1.2)` height transform, wind gate `min(1,(size+period)/30)`, daylight-only day max. Post-fix same day: knee-high 0.3–0.4 m, FAIR 35 (day max 37) — still one bucket above Surfline's POOR; if pattern repeats, tighten wind-gate denominator (30→~60) or q floor before touching height_coeff. Cam recheck (user): ankle at best → linear q still ~2× hot. Buoy confirmed input is real (0.56 m measured) → transform was the culprit; **q steepened to quadratic `clamp((T/10)², 0.15, 1.2)`**. Final same-day output: shin-high 0.1–0.2 m, POOR 18 (day max 19) — matches cam + Surfline. Watch next: OM +18% Hs bias vs Hadera buoy (recheck on future entries before correcting); verify quadratic q doesn't under-call genuine 8–9 s Med swell days. |
| 2026-07-20 | ~12:00 | beit-yanai (+ all IL) | Fri 2026-07-24: was 0.1–0.2 m POOR 17 | Surfline LOTUS: Fri 0.3–0.6 m "poor to fair, almost surfable"; user directed heights up | — | **Calibration row 2**: quadratic q under-called Med windswell ~2–3× vs Surfline. With a ~5 s dominant period, *height* (not period) separates a flat day from a rideable one — the steep penalty erased that. Reverting fully to linear q over-called Fri to FAIR and re-opened the night-land-breeze inflation (clean knee-high night → GOOD). Settled on **q(T)=clamp((T/10)^1.4, 0.3, 1.2)** + **wind-gate denominator 30→60** (the fix-#1 pre-registered next lever). Result: Fri 0.3–0.5 m POOR 25 (poor-to-fair, not FAIR), today 0.1–0.2 m POOR, Sat 0.5–0.8 m GOOD; a clean knee-high night stays POOR (can't fire). Tension logged: this favors Surfline agreement over the single buoy-anchored 7-19 cam frame; `PERIOD_EXP` in transform.py is the dial (2.0 old → 1.0 linear). Also: breaker range widened to a real ≥0.1 m spread ("0.1–0.1" isn't a range). |
