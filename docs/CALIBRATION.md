# Calibration Log

Method: CLAUDE.md §Calibration. Log every dogfood session below; adjust height_coeff / score weights only from accumulated evidence.

| Date | Time | Spot | Rosa pred (h, rating) | Observed (eyes) | Buoy (source, Hs, T) | Notes |
|------|------|------|------------------------|-----------------|----------------------|-------|
| 2026-07-19 | ~10:00 | beit-yanai | 0.5–0.8 m waist-high, GOOD 56 (day max FIRING 73) | 0–0.3 m, poor (Surfline cam + their forecast 0–0.3 POOR) | — (model input: 0.66 m @ 5.2 s W windswell) | **Calibration fix #1**: pred was pre-fix. Root causes: h_break ignored period; additive wind pts made night land breeze FIRING. Fixed: `q(T)=clamp(T/10,0.4,1.2)` height transform, wind gate `min(1,(size+period)/30)`, daylight-only day max. Post-fix same day: knee-high 0.3–0.4 m, FAIR 35 (day max 37) — still one bucket above Surfline's POOR; if pattern repeats, tighten wind-gate denominator (30→~60) or q floor before touching height_coeff. |
