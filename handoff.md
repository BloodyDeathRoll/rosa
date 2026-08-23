# Session Handoff — 2026-08-23

## Goal
Second Dream pass of the day. The first (session 34, commit `51f2b9d`) worked
only the 2026-08-23 report; this session swept ALL 17 report nights and applied
every still-open finding from the 2026-08-06 → 2026-08-22 backlog.

## Current State
- **12 finding diffs applied, UNCOMMITTED in the working tree.** Nothing was
  committed, pushed or deployed this session.
- Repo suite **459 passed**. `ruff check` + `ruff format --check` clean.
- Every shipped Dream proof test for the applied diffs passes against the live
  repo (see the env note under Failed Attempts).
- **No `run --all` smoke has been run against these changes.** `fetch.py`,
  `physics.py` and `verify.py` all changed, so the project's smoke rule applies
  before any commit/push.
- Dream findings backlog is now **0 open**. Proposals backlog is **6 open**.
- `handoff.md` still carries the unresolved VM check from sessions 31-34.

## Active Files
- `pipeline/src/rosa_pipeline/fetch.py` — three 08-21 diffs: ensemble 5xx no
  longer sinks the batch; archive fleet marine request now passes
  `retry_429=True`; the phantom "retry 3/2" log line moved inside the guard.
- `pipeline/src/rosa_pipeline/feedback.py` — `from_row` rejects non-dict
  `predicted`/`observed` (08-22).
- `pipeline/src/rosa_pipeline/blend.py` + `quota.py` + `cli.py` — the blend
  arm's OM aux legs get transient retry (08-22) and are now metered/refused
  against the day ledger (08-17). **Note: this is OPEN-ITEMS 19's "next step",
  now done via Dream's diff rather than by hand.**
- `pipeline/src/rosa_pipeline/notify.py` — an already-peaked best event no
  longer vetoes the swell push for the whole group (08-17); the dead
  `web/src/events.ts` docstring reference removed (08-06).
- `pipeline/src/rosa_pipeline/physics.py` — Komar-Gaughan celerity clamped at
  `c_ref`, killing an unbounded `Kr` when the implied breaking depth is deeper
  than the reference (08-18). Unreachable at today's profiles (shallowest
  reference 18 m) — changes nothing the fleet publishes.
- `pipeline/src/rosa_pipeline/verify.py` — skill scorecard skips n=0 rows so the
  nowcast card stops printing permanent "+0.00" wind rows (08-18).
- `pipeline/src/rosa_pipeline/cli.py` — `swellmap --basin X` now says it skipped
  the world layer (08-13).
- `handoff.md` — this file. `docs/SESSIONS.md` and `docs/OPEN-ITEMS.md` were
  NOT updated this session.

## Changes Made This Session
1. Swept all 17 `reports/<date>/rosa/` dirs (2026-08-05 → 2026-08-23) and
   classified all 55 diffs against the tree. Found the `.state/rosa.applied`
   ledger existed but the git log was the real record: everything through
   08-16 and all of 08-23 was applied; **08-17, 08-18, 08-21 and 08-22 had
   never been worked at all.**
2. Applied 12 diffs via `review-apply.sh`, one run per date (08-06, 08-13,
   08-17, 08-18, 08-21, 08-22).
3. **Skipped `feedback-poison-fixture.diff` (08-06)** and logged it REJECTED.
   It is a test-only edit whose companion `feedback-poison.diff` was never
   applied — `pull_feedback` still does not validate `at`, so the fixture
   change has no fix behind it. Editing a passing test with no fix underneath
   violates the project's rule 3.
4. Skipped `blend-aux-retrying-get.diff` (08-18) as superseded by
   `blend-aux-legs-no-retry.diff` (08-22), same finding re-filed.
5. Ledger appended (12 applied lines + 1 REJECTED). No commit in Dream.
6. **2026-08-18 has no `findings.md` or `proposals.md`** — that night's runner
   died after writing diffs and tests but before the report. The two diffs were
   read directly and applied on their own merits.

## Failed Attempts
- `review-apply.sh` again printed **"WARNING: a shipped confirm-green test
  FAILED"** on every date. Same false alarm as sessions 32-34: the applier's
  PYTHONPATH, not a red tree. Run the tests directly instead.
- `test_blend_quota.py` (08-17) genuinely failed standalone with
  `unknown spot 'beit-yanai'; known:` — it hardcodes a stale worktree path.
  Fix is the env override the test header documents:
  `CBR_WORKTREE=$PWD PYTHONPATH=pipeline/src pipeline/.venv/bin/python -m pytest -q <file>`
  → 2 passed. **Always set `CBR_WORKTREE` when running shipped Dream tests.**
- `test_retry_log_overcount.py` failed inside the applier but passes standalone
  — ordering/env only.
- `<date>/rosa/tests/run.py` is a harness, not a test; pytest errors on
  collection. Ignore it.
- Carried, still true: the ledger lives at
  `assignments/codebase-reviewer/reports/.state/rosa.applied`, NOT
  `assignments/codebase-reviewer/.state/rosa.applied`.
- Carried, still true: `npx vercel deploy --prod` (bare) fails — always
  `npm run deploy` in `web/`.

## Next Step
**Smoke, then commit.** These are fetch/physics changes, so the project rule
requires a full local run first:
```
PYTHONPATH=pipeline/src pipeline/.venv/bin/python -m rosa_pipeline.cli run --all 2>&1 | tee /tmp/runall.log
```
Expect 265/265 published, no new warnings. Note this spends ~2,038 local
quota units (per-IP, does not touch the VM's cron budget). Then commit the 9
files as one "apply the 2026-08-06 → 2026-08-22 Dream backlog" change, append
session 35 to `docs/SESSIONS.md`, and **close OPEN-ITEMS 19** — the blend-arm
ledger charge it describes is now implemented.

Then, in value order:
1. **The VM check, now carried over five sessions:**
   ```
   ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 \
     'cd ~/rosa && git log --oneline -1 && tail -20 publish.log && cat data/verify/quota.json'
   ```
   Expect HEAD at `51f2b9d` (or later) and a ledger pre-charged ~2,038/run.
2. **6 open Dream proposals, all REASONED, none a live bug.** Cheap and safe:
   dedupe `blend._nearest_sp` against `extract._nearest_spectral` (08-22); stop
   notify parsing every payload twice per cycle (08-22); slice basin frames out
   of the world layer's downloads (08-17). Real operational value: fall back one
   GFS cycle when NOMADS publishes late (08-17). Product decision: per-hour
   model provenance (08-21) — allowed ONLY as per-hour, never a constant label.
   Insurance: longitude-seam handling in the four nearest-cell samplers (08-21),
   not triggered by any committed spot.
3. **Register more buoy networks** before the 2026-09-17 promotion decisions —
   NDBC has 908 wave stations, `data/buoys/ndbc.yaml` has 8; also CMEMS,
   NOWPHAS, INCOIS.
4. **Fetch-plane migration** — `docs/rosa-fetch-plane-plan.md` B1/C3
   (OPEN-ITEMS 14).
5. **`d_ref = max(depths_deep_to_shallow)`** (OPEN-ITEMS 15) and **the two
   GEBCO sources A/B** (OPEN-ITEMS 17), both at the 2026-09-17 gate.
