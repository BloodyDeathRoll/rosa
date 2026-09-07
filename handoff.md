# Session Handoff - 2026-09-07

## Goal
Work the Dream overnight review of 2026-09-07 (8 findings, 5 proposals) into the rosa
pipeline, close the loop back into Dream's ledger, and commit nothing until the user says so.

## Current State
All review work is applied and verified in the WORKING TREE. NOTHING IS COMMITTED. 15 files
modified on top of HEAD `8e94156`.

- Repo suite: 592 passed (590 + 2 new). `ruff check` and `ruff format --check` fully clean
  (the old swellmap.py:64 E501 was reformatted this session).
- All 8 shipped Dream probe tests PASS against the live repo when run as
  `PYTHONPATH=pipeline/src pipeline/.venv/bin/python <test> $PWD`. Dream's own applier
  SKIPs them every night (no `test_*` functions); that is expected.
- Dream ledger `~/Projects/Dream/assignments/codebase-reviewer/reports/.state/rosa.applied`
  is up to date through this session. Backlog across all 24 report dates is zero open.
- The VM has not run this code. Nothing here changes published numbers except the
  Greenwich swellmap slice (3 basins) and the new refusals/exit codes listed below.
- Vercel and the Oracle VM were not touched.

## Active Files
- `pipeline/src/rosa_pipeline/swellmap.py` - `slice_basin_field(periodic=True)` on the cron
  path: Greenwich-crossing basins are cut from the global file as two joined column ranges.
- `pipeline/src/rosa_pipeline/fetch.py` - `retrying_get` raises the real last transport
  error (no stale 5xx); `_fetch_batch` runs `_check_batch_order` on marine + weather
  (raise) and ensemble (degrade to None with a warn).
- `pipeline/src/rosa_pipeline/notify.py` - shape-broken payload costs one spot, not the run;
  `send_notifications(failures=...)`; `spot_regions` warns when index.json is unreadable.
- `pipeline/src/rosa_pipeline/cli.py` - `notify` exits 1 when every push failed and nothing
  sent; `feedback --at` REFUSES a value with no UTC offset (exit 2) and an unparseable one.
- `pipeline/src/rosa_pipeline/publish.py` - `load_skill_ceilings` zero-weight tier is
  static, not ZeroDivisionError; `dir_n` comment corrected.
- `pipeline/src/rosa_pipeline/feedback.py` - `from_row` raises TypeError on a non-dict row
  (caught by `records_from_rows`).
- `pipeline/src/rosa_pipeline/horizon.py` - deep test shares the 1 km resolution guard.
- `pipeline/src/rosa_pipeline/confidence.py` - `n_dirs` comment corrected (ECMWF bearing IS
  in the fan since 2026-08-11).
- `pipeline/src/rosa_pipeline/physics.py` - COMMENTS ONLY: friction coefficient relabelled
  as effective ~0.37, applied over g on purpose. Constant and march line untouched.
- `pipeline/tests/test_feedback.py` - 2 new tests for the `--at` refusal.
- `docs/CALIBRATION.md` - new 2026-09-07 entry: friction is a tuned effective coefficient,
  standing rule "no g² fix, only a re-tune under pb_0049".
- `docs/ALGORITHM.md` - friction sentence relabelled; new `agreement_score` pooling note.
- `docs/OPEN-ITEMS.md` - 28 (friction) added and CLOSED; 29 (k-biased agreement score) added.
- `docs/SESSIONS.md` - session entry written.
- `~/Projects/Dream/playbook.md` - one untagged learning: never re-propose the friction g² fix.

## Changes Made This Session
1. Classified every `.diff` across all 24 Dream report dates for rosa against the working
   tree. Everything through 2026-09-05 was already applied, superseded, or ledgered
   (verified by checking the diffs' added lines exist in the source, not by trusting the
   ledger). Only 2026-09-07 was open.
2. Applied 8 of 9 diffs via `review-apply.sh rosa 2026-09-07`, fed `"5 4 7 6 1 2 8 9"` so
   the report's apply order held (notify one-bad-payload BEFORE notify exit-code;
   retrying-get BEFORE publish-batch-bodies). `--all` would have gone alphabetically.
3. Hand-applied proposals 2 (docstrings), 5 (`spot_regions` warn), 4's doc half
   (ALGORITHM.md note; the k-aware spread itself is pb_0049-gated, OPEN-ITEMS 29).
4. Proposal 3, naive `feedback --at`: user chose REFUSE ("always type the timezone").
5. Friction finding (HIGH, `/ GRAVITY` where SWAN has `/ GRAVITY**2`): first HELD, then
   the user ruled it out. Their read: fleet heights are close and if anything slightly
   HIGH, so removing 90% of the friction loss is the wrong direction. Resolved as a LABEL
   fix: zero output change, code + docs now say the coefficient is effective ~0.37 and
   tuned by eye. Diff REJECTED in the ledger, playbook learning added.
6. Reformatted the pre-existing swellmap.py:64 long line on request.

## Failed Attempts
- The first `/dream-review` invocation failed its shell permission check (the skill's
  inline `ls` preamble); a re-run passed. Not a code problem.
- Wrote "(session 50)" into the CALIBRATION.md heading by guess; removed it after checking
  SESSIONS.md has no such numbering for this date. Do not invent session numbers.
- `notify.spot_regions` warn first used `file=sys.stderr`; notify.py has no `sys` import
  and its sibling warns use bare `print`. Fixed to match.

## Next Step
1. Ask the user whether to commit. Suggested split, all from the working tree:
   - `fix(pipeline): Dream 2026-09-07 - Greenwich basins sliced, notify/feedback/skill
     robustness, batch-body guard on the publish path, feedback --at needs an offset`
   - `docs(calibration): friction coefficient is effective ~0.37, not SWAN's 0.038`
   Then push. Deploy is the VM's next cron pull (02:20/08:20/14:20/20:20 UTC).
2. After the first VM cycle with this code, verify from the CDN that
   `swellmap/index.json` now carries fresh frames for `biscay-celtic`, `north-sea` and
   `west-africa` (they were refused every cycle before). Never `run --all` locally.
3. Watch the first live cycle's log for a `_check_batch_order` refusal on a WEATHER body
   (the one new false-positive risk the proposal named: `MAX_GRID_SNAP_DEG` 0.3° cap).
4. Open: OPEN-ITEMS 27 (lon-in-ground-distance sampler diff, HELD, needs A/B) and 29
   (k-aware agreement spread, needs a CALIBRATION.md entry first).
