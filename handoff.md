# Session Handoff - 2026-07-30 (session 11)

## Goal
Run Stage 2E for real (the archive matured). Both halves ran. The buoy half said the input
needs no correction at all; the Israel half moved one knob. A Surfline side-by-side afterwards
then turned up a separate, larger finding about Open-Meteo's partitions.

## Current State
- **All committed and pushed**, main at `867ca1d`. **318 pipeline tests green**, `ruff check`
  and `ruff format` clean. Fleet `run --all` clean (199 spots, 0 warnings).
- **Stage 2E is DONE.** `period_rideability` now keys on the PEAK period; `RIDEABILITY_EXP`
  stays 1.4. No other constant moved - not gamma, not `height_coeff`, no input de-bias.
- Web deployed and verified live (`index-tWop6GtP.js` on rosa-rust.vercel.app, with the
  rewritten `#/about/reading` disclosure confirmed present in the shipped bundle).
- **VM was still on `cb5cda9` as of 08:09Z**; the 08:20Z cycle is the first to pull 2E AND the
  closure ratio together. **Unconfirmed at handoff time - check it first.**
- Local `data/out` is a fresh full fleet run from this morning (post-2E, with `closure`).
- Local `data/verify/archive/` is rsynced from the VM (25 MB, 12 stations, ~1 week).

## Active Files
- `pipeline/src/rosa_pipeline/transform.py` - `rideability_period()` (new, peak-keyed),
  `partition_closure()` (new), `breaker_height_from_profile` default factor changed.
- `pipeline/src/rosa_pipeline/experiment.py` - `BASELINE` now `key="peak"`; report footer
  reports both ranking criteria and no longer promises a de-bias.
- `pipeline/src/rosa_pipeline/models.py` - `HourForecast.total_hs_m`.
- `pipeline/src/rosa_pipeline/extract.py` - carries `wave_height` through (was dropped).
- `pipeline/src/rosa_pipeline/publish.py` - per-hour `closure` key.
- `data/calibration/frames.yaml` - Poleg 07-27 added (5 frames now).
- `web/src/pages/AboutPage.tsx` - period disclosure corrected.
- `pipeline/tests/{test_transform,test_experiment,test_publish}.py`
- `docs/CALIBRATION.md` (five entries today), `CLAUDE.md` (SESSION 11 + NEXT rewritten).

## Changes Made This Session
1. **2E buoy half - no input correction is defensible.** 12 stations x 3 sources, OM n=45,252:
   period bias **+0.21 s** (the "hot period" is dead), Hs fleet **-0.005 m but that is pure
   cancellation** (CDIP -0.299 vs NDBC +0.088; Hawaii 51201 +0.232 against 51202/51205
   -0.498/-0.466). Direction +15.6 deg. **No source swap** - GFS-Wave is 0.12 m low and loses
   Hs mae at every lead; it is the better direction source but that is measured on total-sea
   `mwd`, not per-partition, so still not actionable.
2. **2E Israel half - KNOB MOVED.** Added the Poleg frame the log earmarked. Every mean-keyed
   candidate under-calls 3 of 5 frames by -0.22..-0.43 m; every peak-keyed one fixes them; **no
   exponent reconciles all five, checked to exp 3.0** - the split is by SPOT, not period regime.
   Fleet effect is surgical: rideability saturates at its 1.0 cap above ~10 s, so every >=8 s
   region is bit-identical. 3.39% of hours change bucket, **POOR->FAIR 734 vs 2 downgrades**.
3. **Surfline side-by-side, 5 spots.** Clean-conditions agreement in Israel (our 0.3-0.5 inside
   their 0.3-0.6 at all three spots). Direction agrees within a few degrees with inconsistent
   sign - more support for the +15.6 deg being a blending artifact.
4. **Partition closure found and wired up.** OM's four partition fields do not always hold all
   of its own energy. Fleet: israel 1.00, japan 0.97, philippines 0.96, nicaragua/hawaii 0.95,
   portugal/costa-rica 0.94, california 0.91, sri-lanka 0.90; every region but Israel and Hawaii
   has hours below 0.60. Diagnostic only - nothing scores on it.
5. `#/about/reading` corrected (it said height is computed from the mean period).

## Failed Attempts
- **Three of my own conclusions were wrong today and had to be walked back in the log.** Each
  was caught by adding a control, not by more reasoning. If closure ever justifies a change,
  give it the same treatment before shipping.
  - "We read bigger than Surfline on the small hours" - drawn from Zvulun alone. Their own
    Zvulun reads 0-0.3 where their Hilton reads 0.3-0.6 on identical input.
  - "Open-Meteo is ~0.8 m low in Sri Lanka" - **wrong, and I nearly proposed a regional Hs
    correction on it.** Deep water showed OM and ECMWF agreeing to 0.01 m; a transect showed
    Arugam Bay's gap was ECMWF's 0.25 deg grid failing to resolve the island sheltering its own
    east coast. OM's total was never low.
  - "A third of the sea is missing" - closure is a ratio of HEIGHTS; energy is `closure^2`.
- **Third comparison artifact this month** (after APD-vs-Tm-1,0 and blended `mwd`): a coarse
  grid against a sheltered coast. **A control group and a deep-water check are what caught it -
  build both into any future cross-source claim.**
- **ECMWF's period bands start at 10 s**, so they cannot referee a 4 s vs 9 s question directly;
  `swh` plus the Tm02/Tm-1,0 moments do.
- **`Spot` has no `offshore_bearing`** - it is consumed when deriving `offshore_point`; compute
  the bearing from the pin if you need it.
- **Bash cwd persists between calls** - bit me again after a `cd pipeline`. Use absolute paths.
- **`run --all` died once on an Open-Meteo TLS handshake timeout mid-batch** and needed a plain
  retry. Transient, not a code fault - do not go looking for a bug.

## Next Step
1. **Confirm the 08:20Z cycle** - first production run of the 2E forecast change AND closure:
   `ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 'grep -E "^=== |FAILED at:" ~/rosa/publish.log | tail -4'`
2. **User action, highest value: eyeball a flat Israeli morning.** The residual 2E error is
   per-spot and `height_coeff` is still 1.0 at all 199 spots. Surfline could not settle it -
   only eyes can. Prefer **as-logged** frames; provenance confounded the existing five.
3. **In a week, once closure has data:** does it track the sea state or the spot? Is the missing
   energy short-period (where `period_rideability` floors it anyway, making this nearly
   harmless) or long? **Do NOT scale partitions to close the gap** - that invents direction and
   period the model never gave. A confidence penalty is the honest option.
4. **Product decision nobody has made:** Surfline's surf height drops a band in an onshore
   afternoon; ours does not, because wind lives in the rating. Should a blown-out 0.6 m read
   smaller?
5. Backlog: the notify fix has still never fired a real push in production (simulation only);
   chigasaki cam replacement (nearest official is Kanagawa's 平塚海岸 `62_twW5uXd4`, ~6 km west);
   `hagolshim` points at a Rishon LeZion stream ~5 km south; `tide_best` values; 79 ruff
   findings in `tools/`+`deploy/`.
