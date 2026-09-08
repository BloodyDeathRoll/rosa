# Session Handoff - 2026-09-08

## Goal
Work the Dream overnight review for rosa (all report dates, 2026-08-05 to 2026-09-08): apply
the one open finding and the one open proposal the user accepted, verify, close the loop in
Dream's ledger. Nothing else was in scope.

## Current State
Both items applied and verified. **UNCOMMITTED, working tree only** - the user has not asked
for a commit. HEAD is still `91c4a6b`.

- Tide fix (Dream 2026-09-08 HIGH): `physics.tide_shifted_samples` - a bathy sample that
  dries at this tide becomes the interpolated shoreline instead of being deleted. Used by
  `score.score_hour` and `experiment.predict_frame`. Bit-identical at tide 0; heights move
  DOWN at ~115 macro-tidal spots for ~0.6 % of hours. Shipped Dream test PASS against the
  live repo.
- Model run timestamp (Dream 2026-09-02 proposal 1): blend-arm payloads carry
  `model_run: {"gfswave": iso, "ecmwf": iso|null}` beside `fetched_at`, per point. Omitted
  (not null) on the OM arm and on fixtures. Nothing reads it yet.
- Verification: pytest 601 passed (592 + 9 new), `ruff check` + `ruff format --check` clean,
  `tsc --noEmit` clean.
- NOT YET ON THE CDN: the VM picks this up only after a commit + push + its next cron pull.
  `model_run` unverified on a real payload until then.
- Everything from the 2026-09-07 handoff (accounts, Worker, rosa.surf, moved screen) is
  live and unchanged. OPEN-ITEMS 30 (iOS installed-PWA sign-in) still unverified.

## Active Files
- `pipeline/src/rosa_pipeline/physics.py`: new `tide_shifted_samples`.
- `pipeline/src/rosa_pipeline/score.py`, `experiment.py`: call it (shared production path).
- `pipeline/src/rosa_pipeline/blend.py`: `GfsSea.run`, `parse_gfs_full(run=)`,
  `fetch_series` stamps the cycle it settled on, `_model_run`, `compose_raw` sets it.
- `pipeline/src/rosa_pipeline/models.py`: `SpectralSea.run`.
- `pipeline/src/rosa_pipeline/ecmwf.py`: `parse_grib_points(run=)`, live `_absorb` passes
  the cycle; fixture source does NOT stamp.
- `pipeline/src/rosa_pipeline/fetch.py`: `RawForecast.model_run`.
- `pipeline/src/rosa_pipeline/publish.py`: `build_payload(model_run=)`, emitted when present.
- `pipeline/src/rosa_pipeline/cli.py`: passes `raw.model_run`.
- `web/src/types.ts`: documents `model_run?`.
- Tests: `test_score.py` (`TestTideShiftedSamples`, 5), `test_blend.py` (2),
  `test_ecmwf.py` (1), `test_publish.py` (1).
- Docs: `docs/CALIBRATION.md` 2026-09-08 entry, `docs/ALGORITHM.md` tides paragraph,
  `docs/OPEN-ITEMS.md` 31 (qb-gate discontinuity), `docs/SESSIONS.md` 2026-09-08 entry.
- Dream (append-only, not committed): `reports/.state/rosa.applied` 4 lines,
  `playbook.md` one untagged learning.

## Changes Made This Session
1. Loaded all 28 Dream report nights for rosa. Everything through 2026-09-07 was closed in
   the ledger; `git apply --check` "conflict" on ledger-applied diffs is drift from later
   edits, not open work. Open set was: 2026-09-08 HIGH (diff), 2026-09-08 MEDIUM (measured
   gap, no diff, no proposals.md was written that night), 2026-09-02 proposal 1 (never
   applied or rejected; SESSIONS 50 had noted it as not done).
2. User chose "apply both" over the recommended HOLD. Rationale accepted into
   CALIBRATION.md: the tide discontinuity is a defect not a tune, and the reviewer shipped
   the same-input fleet A/B pb_0049 asks for.
3. Applied the tide diff via `DREAM_ROOT=~/Projects/Dream ~/Projects/Dream/bin/review-apply.sh
   rosa 2026-09-08` (fed "1"). Ran the shipped test with the repo venv.
4. Built `model_run` by hand, per point (the proposal's gotcha: GFS drop-back is per box,
   so a fleet-wide constant would repeat the mistake that retired the `model` key).
   Newest stamp wins so back-reach steps from earlier cycles never label the forecast.
5. Recorded the MEDIUM as OPEN-ITEMS 31, wrote the docs, appended the ledger + playbook.

## Failed Attempts
- The applier's own test runner reports FAIL (`ModuleNotFoundError: rosa_pipeline`) - it
  has no venv, same as every night. Run shipped tests as
  `PYTHONPATH=pipeline/src pipeline/.venv/bin/python <test> $PWD`.
- The first classification pass ran `git apply --check` from the Dream cwd, so every
  result was wrong. Classify from the rosa root.
- A blanket string replace on `parse_grib_points(...)` in `ecmwf.py` also hit the fixture
  source, where `cycle` is undefined. Reverted that one call site by hand.
- `SHELF = [...]` as a class attribute in the test tripped ruff RUF012; a tuple + `list()`
  at the call sites fixed it.

## Next Step
1. Commit + push when the user asks (memory: "commit" implies push + deploy). Suggested:
   `fix(pipeline): Dream 2026-09-08 - a dried bathy sample is the shoreline; blend arm publishes model_run per point`.
2. After the next VM cron cycle (02:20/08:20/14:20/20:20 UTC): fetch one blend-arm payload
   from the CDN and confirm `model_run` is present with a plausible cycle and that a
   macro-tidal spot (saunton, goulien, mona-vale-beach) no longer flips to 0.00 m at low
   water between adjacent hours.
3. OPEN-ITEMS 31 (qb > 0.1 gate vs K&G close) waits for a physics design decision + A/B.
4. OPEN-ITEMS 30 (installed iOS PWA sign-in) still needs a human test.
