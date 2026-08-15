# Session Handoff - 2026-08-15

## Goal
Work the 2026-08-15 Dream overnight review of `pipeline/` (via `/dream-review`): apply its one
finding and two of its three proposals, then bring every doc and derived artifact the change
touched back into sync. Operator directive mid-session: **ALWAYS UPDATE STALE DOCS** - fix them
on sight, never report-and-wait.

## Current State
- **`main` = `c932bae`. Tree is NOT clean: 211 uncommitted files, nothing pushed.**
  443 tests green (was 434; 9 added, none edited), ruff check + format clean.
- **The whole change set is a fleet-wide same-input NO-OP, proven not asserted.** 199-spot
  payload SHA-256 with `generated_at` blanked is
  `9745eaff58a2ee38a299dedfd3a02aa878583043849998c778a12108cdaf036d` on a clean
  `git worktree --detach HEAD` and on the patched tree. So CLAUDE.md's knob-tuning gate
  (pb_0049) does not apply to any of it.
- **Applied:** the refraction-singularity fix (`physics.py`), two bathy QC counters
  (`bathymetry.py` + `cli.py`), the implausible-breaker warning (`cli.py`).
- **NOT applied, deliberately:** the review's third proposal, `d_ref = max(...)`. It moves
  published numbers, so it is gated on a Stage-0 A/B that needs the VM-only archive.
  Logged as DEFERRED (not rejected) in OPEN-ITEMS item 15 and in Dream's ledger.
- **All 199 bathy profiles re-cut live and re-installed.** Diffed against the committed set
  BEFORE installing: all 199 identical on every shared key, 551 insertions / 0 deletions.
  GEBCO returned the same depths, so no profile's physics moved.
- **Nothing is deployed.** The last cron cycle still runs the pre-change code.

## Active Files
- `pipeline/src/rosa_pipeline/physics.py` - the applied diff: skip any marched sample deeper
  than the reference (12 lines, one `continue` plus its rationale).
- `pipeline/src/rosa_pipeline/bathymetry.py` - NEW `DepthProfile.non_monotone_samples` and
  `.deepest_is_reference`; both persisted in `to_dict()`.
- `pipeline/src/rosa_pipeline/cli.py` - `IMPLAUSIBLE_BREAK_RATIO` 3.0 +
  `IMPLAUSIBLE_BREAK_FLOOR_M` 0.5 + `_implausible_break_hours()`; per-hour warn line and a
  run-summary count; the two new counters on the `bathy` warning line.
- `pipeline/tests/test_bathymetry.py` (+5 tests), `pipeline/tests/test_cli.py` (+5 tests,
  incl. `TestImplausibleBreakGuard`).
- `data/spots/derived/bathy/*.json` (199) - two new QC keys; 153 of them ALSO gained
  `missing_samples`, a key added 2026-08-07 that had never reached the committed DB.
- `data/spots/derived/bathy/bathy_elevations.json` - refreshed capture (18 KB Jul-22 -> 43 KB).
  The old one was stale since today's pin moves and broke offline `bathy --fixtures`.
- `docs/ALGORITHM.md` (2 bullets), `docs/SPOT-DB.md` (3 bullets + a stale count),
  `docs/spot-db-scraping-playbook.md` (1 bullet), `docs/SESSIONS.md` (SESSION 28),
  `docs/OPEN-ITEMS.md` (items 15, 16).

## Changes Made This Session
1. **Applied the MEDIUM finding.** `physics.breaker_height_over_profile` refracts with
   `Kr = sqrt(cos a_ref / cos alpha)`, unbounded as `alpha -> 90`, and skipped a sample only at
   `sin_a >= 1` - i.e. just PAST the blow-up. Reaching it needs a sample deeper than the
   reference, which `wet_depths_deep_to_shallow()` permits because it orders by DISTANCE, not
   depth. Measured before the fix: 24.96 m in 32 m of water from a 3.0 m swell
   (cantinho-bah-a), 192.7 m from a 4.0 m swell (zvulun), published as breaker heights.
2. **Proposal 1 by hand** - `non_monotone_samples` + `deepest_is_reference`, printed on the
   same `bathy` line as land samples and GEBCO holes, persisted to the profile JSON. The
   geometry the march's whole premise rests on was previously invisible in the DB.
3. **Proposal 2 by hand** - a precompute-time magnitude check that WARNS, never clamps. No
   payload key, no constant that scores, so it cannot move a rating. Rosa serves static JSON
   with no request-time backend, so precompute is the only place a bad number can be caught.
4. **Re-cut all 199 profiles + the elevations capture**, because nothing does this
   automatically (`run --all` reads profiles; the cron never calls `bathy`).
5. **Doc sweep** after the operator directive - five files, including two staleness bugs this
   session did NOT cause: SPOT-DB.md still said "80/199 pins settled as of 2026-08-04" (it is
   199/199), and handoff.md claimed a clean tree and 434 tests.
6. **Dream loop closed** (append-only, nothing committed there): 4 lines to
   `reports/.state/rosa.applied`, 3 untagged bullets to `playbook.md`.

## Failed Attempts
- **Proposal 2's own wording is wrong and implementing it literally ships a bug.** It says
  "largest in-window partition height". Implemented with the hard `transform.in_window()`
  bearing test, the guard fired on **42 perfectly sound fleet hours** (worst: ba-a, 0.54 m
  breaker from a 0.02 m "sea"). The march weights every partition by
  `sqrt(spread_exposure(p, window))` - a SOFT window - so a train whose fan merely clips the
  window still feeds the breaker. With `spread_exposure(p, window) > 0` the report's numbers
  reproduced exactly (fleet max ratio 2.012 at onjuku, 0 hours over 3x across 76,416 scored
  hours). `test_cli.py::TestImplausibleBreakGuard` now pins the distinction.
- **`review-apply.sh`'s test runner reported `ModuleNotFoundError: rosa_pipeline`** - purely
  its own PYTHONPATH, not the code. The shipped test needs
  `ROSA_REPO=/home/shahar/Projects/rosa PYTHONPATH=pipeline/src pipeline/.venv/bin/python -m pytest`
  and passes 4/4 that way. Do not read that FAIL as a red tree.
- **The report's counts did not reproduce: 88/15 vs the DB's 87/17.** Not a definition
  disagreement - the review ran at 01:31 and the sat-verify pin moves landed 15:26-15:57 the
  same day. Re-measure any DB-derived count before quoting it anywhere.
- **`bathy --fixtures data/spots/derived/bathy` failed** with
  `KeyError: no captured elevation for 39.3689,-9.3422` on every moved pin - the committed
  capture was from Jul 22. Refreshed now. Also note `--fixtures` takes the DIRECTORY, not the
  json path.
- **ruff rejected `zip(wet, wet[1:], strict=False)`** (RUF007); use `itertools.pairwise`.

## Next Step
**Nothing is blocked. The immediate next thing is to commit and deploy** - 211 files, verified
green and digest-identical, currently only on disk. Suggested split: `fix(physics):` the
refraction skip, `feat(bathy):` the QC counters + the 199 re-cut profiles, `feat(publish):` the
implausible-break warning, `docs:` the sweep. Per standing preference, commit implies push +
deploy.

Then, in value order:
1. **Register more buoy networks** - unchanged from last session and still the highest-value
   item. Must land BEFORE the 2026-09-17 promotion decisions or most regions get promoted on
   pooled evidence alone. NDBC publishes 908 wave stations; `data/buoys/ndbc.yaml` has 8.
2. **Route the new implausible-break warning somewhere a human sees it** (OPEN-ITEMS 16).
   Today it is a stderr line the cron swallows into the publish log. The `rosa-backup`
   freshness watchdog and the admin push snapshot are the existing precedents.
3. **Run the A/B for `d_ref = max(depths_deep_to_shallow)`** (OPEN-ITEMS 15) at the 2026-09-17
   archive-maturity gate, when the shipped harness is being run anyway. It needs a
   CALIBRATION.md entry in the same change. Sized already: 13/199 spots, 55/76,416 ratings,
   max |delta h_break_mid| 0.014 m.
4. **Commit the blend/weight-fit script into `tools/`** - still only in a prior session's
   scratchpad; September will otherwise re-derive it from CALIBRATION.md prose.
5. Finish the fetch plane: phases B1 (whole-globe/per-basin fetch) and C3 (the weather call).

**Useful rig discovered this session, worth reusing:** the whole scoring path runs offline in
~5 s for the entire fleet - `FixtureSource(pipeline/tests/fixtures).fetch(32.3817, 34.8035)`
gives 384 real hours and all 199 spots score against them. SHA-256 of the 199 payloads with
`generated_at` blanked, computed on a `git worktree add --detach HEAD` baseline and on the
patched tree, turns "this should move nothing" into a fact in two commands. The script is at
`<scratchpad>/digest.py`; it is worth moving into `tools/`.
