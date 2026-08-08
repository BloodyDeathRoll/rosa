# Session Handoff — 2026-08-08 (session 20)

## Goal
Close out session 19's two open items (verify the fleet skill measurement's first
production runs on the Oracle VM; write the session 19 docs), then pull and land the
2026-08-08 Dream overnight review.

## Current State
- **All done, committed, and pushed.** Working tree clean.
- **VM verified clean (2026-08-08, ~15:00 UTC):** every publish cycle since the 08-07
  code landed completed — no `FAILED at:` in `publish.log` since the pre-existing
  08-03 quota incident. The fleet skill pass writes `data/verify/skill.json` each
  cycle from 15 buoys (12 NDBC + 3 Portugal), zero per-buoy failures.
- **Measured ceilings are LIVE, not pending.** Payloads publish
  `ceiling_source: "measured (verify skill.json <ts>, buoys: ...)"` — the archive was
  seeded with the retired GH-Actions rows, so SKILL_N_FLOOR cleared immediately
  (0-1d bucket n=5040). "static defaults" appearing NOW would be a regression
  (check the `warn:` path in `publish.load_skill_ceilings`).
- **Dream 2026-08-08 review fully applied** (2 findings + 1 proposal, all accepted):
  the torn-file class is closed at source (atomic writes) and at every reader.
  405 tests green (402 existing + 3 shipped Dream tests), ruff check clean.
  `ruff format --check` still flags only the pre-existing `pipeline/tests/test_observe.py`.
- Dream loop closed: `.state/rosa.applied` has the 3 diff lines (auto-logged by the
  applier), playbook got one untagged verdict bullet (torn-file seam closed; the
  "notify parses twice" proposal declined by reviewer and operator alike).
- **Untested live: the patched write path** — next VM cycle (20:20 UTC pull) is the
  de-facto smoke, per the accepted no-local-`run --all` stance (Open-Meteo quota).

## Active Files
- `pipeline/src/rosa_pipeline/notify.py` — `_iter_payloads` generator: a torn spot
  payload skips with a warning instead of killing the whole notify cron run.
- `pipeline/src/rosa_pipeline/swellmap.py` — guarded `swellmap/index.json` read
  (torn index → rebuild from this run's basins, no more permanent crash loop);
  basin/world/index writes via `write_json_atomic`.
- `pipeline/src/rosa_pipeline/publish.py` — `write_json_atomic` helper (tmp+replace,
  the `skill.json` idiom) used at all six `data/out` JSON write sites.
- `docs/SESSIONS.md` — SESSION 19 entry appended.
- `docs/OPEN-ITEMS.md` — new item 12 (closure/direction scoring gated on the
  calibration package); pin backlog renumbered 12→13.

## Changes Made This Session
1. VM verification (SSH per oracle-vm memory): tailed `publish.log`, grepped
   `FAILED at:` since the code landed (none), confirmed `skill.json` body (15 buoy_ids,
   all buckets but 9d+), curled beit-yanai payload — `ceiling_source` already measured.
2. Session 19 docs written and pushed as `8135957`.
3. `/dream-review`: applied the 3 diffs via Dream's applier in the documented order
   (notify-torn-payload-skip, swellmap-index-torn-write-self-heal, atomic-json-writes —
   fed "2 3 1" because the applier numbers alphabetically). One flagged deviation:
   reworded a `swellmap.py` comment that still claimed "the write below is not atomic"
   after diff 3 made it atomic.
4. Declined (with the reviewer's own recommendation) the "notify parses payloads
   twice" efficiency proposal — below measurement noise.
5. Committed: pipeline fix + docs/handoff, pushed to main.

## Failed Attempts
- The applier's shipped-test runner reported FAIL on both Dream tests —
  `ModuleNotFoundError: rosa_pipeline`. Not a real failure: it doesn't set
  `PYTHONPATH=pipeline/src`. Run them directly:
  `PYTHONPATH=pipeline/src pipeline/.venv/bin/python -m pytest -q <report>/tests/`.
- Notes against false alarms: the two `FAILED at:` lines in `publish.log` are the
  known 2026-08-03 quota incident (OPEN-ITEMS item 9), and `publish.log` is
  append-only across days — bracket reads between *dated* banners.

## Next Step
1. **Optionally spot-check the 20:20 UTC cycle** (~21:30 UTC finish) — first live run
   of the atomic write path: `ssh -i web/.oracle/ssh-key-2026-07-23.key
   ubuntu@82.70.218.149 'tail -20 ~/rosa/publish.log'`; expect a normal `done` banner,
   no `.tmp` files left in `data/out`.
2. **Costa Rica batch of 14 pin verifications**:
   `python3 tools/spot-verify/queue.py --batch 14 --region costa-rica`, then
   `tools/spot-seed/render.py` + judge per `tools/spot-verify/JUDGING.md` (item 13).
3. **ISRAMAR email** (info@ocean.org.il, Dr. Isaac Gertman) — request the Hadera buoy
   feed AND the route (robots.txt blocks the download endpoints). CAMERI held until
   ISRAMAR answers (item 10).
4. **Portugal lead-time re-run ~2026-08-11**:
   `uv run --project pipeline rosa-pipeline verify --buoy Leixoes-coast-buoy --archive`
   — safe, cannot touch skill.json without `--write-skill`.
5. Privacy page before launch (re-offer).

## Constraints carried forward
- Closure/direction scoring requires the full calibration package (OPEN-ITEMS item 12);
  recorded-not-scored is the correct current state.
- ISRAMAR: manual calibration only — never in the scheduled fleet pass.
- No local `run --all` smoke without weighing the Open-Meteo daily quota; the
  production cycle is the de-facto smoke. `python` is not on the VM, only `python3`.
- `horizon`/cam tools report, never apply. Never import competitor spot data.
- Dream: only append-only writes (`.state/rosa.applied`, untagged playbook bullets);
  never commit in the Dream repo from a project session.
