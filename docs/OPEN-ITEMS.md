# Rosa — open items

The live to-do / unresolved list. Update this when the open list actually changes; per-session
narrative goes in `docs/SESSIONS.md`, live machine state in `handoff.md`.

1. **The K&G closure still rests on ONE long-period eye frame** (santa-teresa 2026-08-02) plus five Med frames. It over-shot on 2026-08-03 and the field-combine fix pulled it back (×0.93 fleet, ×0.76 at santa-teresa); the closure itself was never re-graded. Grade more frames in a long-period region and re-check santa-teresa across several days.
   - 1b. **Noon at santa-teresa is still above Surfline's band** (1.22 vs 0.6–1.1) and no combination rule can reach it — its single dominant partition transforms to 1.2 m alone. Index-level, +0.12 m, not chased.
   - 1c. **`physics.py`'s march/index handoff has a real discontinuity** — the depth-limited branch and the K&G branch disagree, so a shallow profile steps 1.167 → 1.303 m between 13° and 14° of incidence. Invisible today (real GEBCO profiles bottom out at 7–13 m so 97–100% of hours take the index branch), but it will bite on an unusually shallow profile.
2. `playa-cocles` derived window is NARROW-flagged and needs eyes. Held windows: calicoan-abcd, zavial, kodomonokuni (large movers); pavones, panga-drops, miura (shore normal genuinely blocked — inside gulfs).
3. The 07-19 flat frame is over by +0.15 m under every candidate. Now looks **structural**, not tunable — a breaker index assumes something that breaks as a wave; that frame is a 0.60 m 5.05 s windsea observed ankle-high.
4. Not analysed, would move the rating fleet-wide: should `period_score` and the shoaling march follow rideability onto Tp?
5. Not actionable yet: OM/ECMWF's shared ~+16° clockwise direction bias is measured on total-sea `mwd`, but `spread_exposure()` eats per-partition directions. Needs a per-partition measurement first.
6. Product call nobody has made: **should a blown-out sea read smaller?** Surfline's height appears to absorb wind; ours puts wind in the rating only.
7. Local knowledge needed: ingrina's window ends at 220° while neighbouring zavial reaches 260°; matapalo-osa/okanda/peanut-farm sit 65–73° between wind direction and coastline; `tide_best` unfilled; a chigasaki cam replacement (nearest official is 平塚海岸 `62_twW5uXd4`, ~6 km west); `hagolshim` has always pointed at a stream ~5 km south.
8. Then Stage 4 on `rosa-arm`; worldwide spot-DB scale-up (ODbL seed) after calibration.
9. Housekeeping: 4 orphan payloads in `data/out/spots/` from spots removed 2026-07-23; 79 ruff findings in `tools/` + `deploy/` (untested scripts — needs a deliberate pass).
