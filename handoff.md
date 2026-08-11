# Session Handoff — 2026-08-10 (session 22)

## Goal
Pull and land the 2026-08-10 Dream overnight review for rosa: 2 findings (both
with red→green diffs) and 3 proposals (one with a diff), applied in full at the
user's direction, then commit and push.

## Current State
- **All done, committed, and pushed.** `main` = `7f098d0`. Working tree clean
  except this file.
- **404 tests green** (`PYTHONPATH=pipeline/src pipeline/.venv/bin/python -m
  pytest -q pipeline/tests`), the report's 4 shipped tests green, `ruff check`
  clean. The Dream diffs shipped no new repo tests — the proof tests live in the
  Dream report dir only, so the suite count is unchanged from the 404 baseline.
- **Smoke-tested live, not just on fixtures.** A full local `run --all`
  completed: 199/199 spots published, zero null ratings, 25,472 hour entries,
  `dir_span` present on 14,853 of them and correctly absent below 2 member
  bearings. This was the CLAUDE.md smoke rule for an extract/publish change.
- **NOT yet deployed.** Deliberate: pipeline-only change, so `publish.sh` on the
  Oracle VM picks it up at the next cron `git pull`. At write time the next
  cycle is **08:20 UTC**, which will publish the first payloads carrying
  `dir_span`. The local `run --all` output was NOT deployed from this box — a
  second fleet fetch would spend the same Open-Meteo daily quota that caused the
  2026-08-03 outage.
- **Untested live: everything in this commit.** The notify guard only fires on a
  real push-vendor failure, and the bathy/horizon guards only on a real
  OpenTopoData error; neither has been exercised in production.
- Dream loop closed: 3 diff lines auto-logged to `.state/rosa.applied`, 2 hand
  lines appended, 1 untagged playbook bullet added.

## Active Files
- `pipeline/src/rosa_pipeline/notify.py` — per-subscription guard in
  `send_notifications`; subsumed clause removed from `plan_feedback_push`.
- `pipeline/src/rosa_pipeline/cli.py` — per-spot guards in `_cmd_bathy` and
  `_cmd_horizon`.
- `pipeline/src/rosa_pipeline/extract.py`, `models.py`, `publish.py` —
  `dir_span_deg` threaded from `Agreement` through `HourForecast` to the payload.
- `pipeline/src/rosa_pipeline/verify.py` — obs-window skip in
  `lead_time_scorecard`.
- `docs/SESSIONS.md` — session 22 entry appended.
- `docs/OPEN-ITEMS.md` — item 12 corrected.
- `handoff.md` — this file (previously described session 21, uncommitted).

## Changes Made This Session
1. **Classified the report** (`~/Projects/Dream/assignments/codebase-reviewer/
   reports/2026-08-10/rosa/`): all 3 diffs pending, nothing ruled out by the
   ledger or the playbook's Load-bearing section.
2. **`notify-per-sub-guard.diff`** [MEDIUM]. `send_notifications` caught only
   `WebPushException`, leaving three real raise sites bare: a connection-level
   error out of `webpush` (pywebpush wraps HTTP responses, so
   `requests.ConnectionError` propagates raw), an httpx error from the
   `prune_subscription` call *inside* the except handler, and a malformed
   subscription from the admin API (`"spots": null` → `TypeError` in
   `plan_notifications`). Any of them killed the run twice over: later
   subscriptions got nothing, **and `save_state` never ran**, so every in-memory
   `mark_sent` was lost and the next cron re-pushed the same swell to devices
   already served — breaching the one-swell-one-notification requirement. This
   was the one fleet loop living outside `cli.py`.
3. **`bathy-horizon-sweep-guard.diff`** [LOW]. Both sweeps pace at ~1 s/spot
   against the OpenTopoData rate limit and `_get_with_backoff` retries only 429s,
   so an HTTP error at spot 150 of 199 discarded every later profile. Targeted
   `--spot` runs still raise; bathy keeps its rate-limit sleep on the failure
   path and exits 1 with a failure summary.
4. **`persist-dir-span-diagnostic.diff`**. `Agreement.dir_span_deg` was computed
   hourly and dropped — `extract_hours` copied only `score` and `n_models`, so
   the span reached no payload, archive, or file. Session 19 and OPEN-ITEMS item
   12 both claimed it "ships"; it did not. **The calibration distribution the
   reverted direction penalty was told to come back with could never accumulate**
   — the sanctioned route back was locked from the inside. Now published as
   `dir_span` (whole degrees, omitted below 2 member bearings), the `closure`
   idiom: diagnostic, scored by nothing, so the pb_0049 tuning gate is not
   tripped.
5. **Proposal by hand**: `lead_time_scorecard` computes the obs window once and
   `continue`s on rows outside `min/max(obs) ± tol` before the per-variable
   bisect. Obs reach back ~45 days (NDBC realtime2) while the archive is
   append-only and already 246k rows / 25 MB, so the pass stops scaling with
   archive age. Output bit-identical — out-of-window rows pair with nothing.
   Empty obs is guarded (skipping every row is the same zero-pair result).
6. **Proposal by hand**: deleted the first `any(...)` in `plan_feedback_push`'s
   quiet-gate — every `fb:<spot>:<date>` it could find already matches the
   broader `fb:`-prefix clause. Added a comment stating the any-spot semantics
   are deliberate, since the dead clause made the gate read stricter than it is.
7. **Docs**: session 22 appended to `docs/SESSIONS.md`; OPEN-ITEMS item 12
   corrected to say the fan was in-memory only until today.

## Failed Attempts
- **The Dream applier reported both shipped tests as FAILING and warned "the
  tree is NOT green".** It was wrong: `ModuleNotFoundError: No module named
  'rosa_pipeline'` — the applier's runner does not set `PYTHONPATH=pipeline/src`,
  which `targets.yaml` documents as load-bearing for this repo. Re-run directly
  with that env and all 4 pass. **Read the report's test header before believing
  the applier's verdict**; do not start reverting on that warning.
- Nothing else failed. Both findings and all three proposals applied cleanly on
  the first attempt, no conflicts, no test edits needed.

## Next Step
1. **Verify the 08:20 UTC cycle on the VM** (`ssh` per `deploy/oracle/README.md`,
   IP 82.70.218.149): confirm no `FAILED at:` in `publish.log`, then confirm the
   CDN payload carries the new key —
   `curl -s <data-base>/spots/beit-yanai.json | jq '[.hours[] | select(.dir_span)] | length'`
   should be non-zero. If it is zero fleet-wide, the VM published from stale code
   — check the `git pull` step ran.
2. **Do not act on `dir_span` yet.** It is diagnostic only. A direction-scoring
   proposal still needs the full pb_0048/pb_0049 package: a Stage-0 same-input
   A/B on the shipped harness, a `docs/CALIBRATION.md` entry deriving the
   tolerance from the *measured* spans, reasoning about total-sea vs
   per-partition direction, and doc updates in the same change. The data has to
   accumulate over real cycles first.
3. **`docs/SESSIONS.md` skips 19 → 22.** Sessions 20 and 21 were logged only in
   `handoff.md` and their commit messages (`2b2ac66`, `8327cf4`). Back-fill from
   git if the narrative gap matters; noted in the session 22 entry.
4. Open items unchanged otherwise — see `docs/OPEN-ITEMS.md`. Item 9 (a failed
   `archive` kills the whole cycle) is still the largest unresolved pipeline
   robustness question and is adjacent to the guard work landed today.
