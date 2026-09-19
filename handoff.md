# Session Handoff - 2026-09-18 (morning, Dream review session)

## Goal
Work the Dream overnight reviewer's open backlog for rosa (`/dream-review`): three findings and
one proposal from the 2026-09-17 and 2026-09-18 reports, each with a same-input A/B where it
moves a published number. Then a side question: is anything in use on the Frankfurt Oracle account.

## Current State
- **All four items are applied, committed and pushed to main** (`1ba9c7c`, `a256474`, `7ae1d62`,
  `fa9e359`, docs `a08bd74`). Repo suite 675 passed, ruff clean. Each fix has one new repo test
  that is red without it.
- **NOT yet live / NOT smoke-checked.** The VM pulls on its next cycle (17:20 local / 14:20Z,
  2026-09-18). Nothing was verified from the CDN after the push.
- Dream ledger (`~/Projects/Dream/.../reports/.state/rosa.applied`) closed at "0 open through
  2026-09-18"; one untagged learning appended to Dream `playbook.md`. Dream was not committed
  (rule: never commit Dream from a project session).
- Frankfurt Oracle tenancy ("shibumi", `~/.oci/config` `[DEFAULT]`): checked read-only - no
  instances, no boot/block volumes, no public IPs; VCNs `rosa-vcn` (2026-07-22, the ARM hunt,
  empty) and `oneshot-cms-vcn` (2026-09-18, not Rosa's). No grabber running locally or on
  `rosa-arm`. `rosa-backup` and the old micro refused my SSH key, so not checked there. **I offered
  to delete `rosa-vcn`; the operator did not answer - nothing was deleted.**
- Working tree: `handoff.md` and `progress.md` modified, uncommitted (`progress.md` was modified
  by an earlier session, not this one).
- A/B scratch is in this session's scratchpad (disposable). The 2026-09-16 capture + replay rig
  it reused is at `/tmp/claude-1000/-home-shahar-Projects-rosa/61b9a090-.../scratchpad/ab/`
  (`cap/`, `replay.py`, `diff.py`) - in `/tmp`, so it dies on reboot.

## Active Files
- `pipeline/src/rosa_pipeline/nearshore.py` - `archive_rows(series, cycle, run_time=None)`; with
  `run_time` the row's `run` is the invocation time and the model cycle rides as `cycle`.
- `pipeline/src/rosa_pipeline/cli.py` - `_cmd_swan_archive` passes `run_time=now`; `_cmd_run`
  passes `aims=aims` to both GWAM sources.
- `pipeline/src/rosa_pipeline/verify.py` - new `_score_hours` (per hour: mean of its runs'
  ERRORS); `lead_time_scorecard` and `station_bias_profile` use it; `_collapse_hour` kept for
  `_station_pairs` only.
- `pipeline/src/rosa_pipeline/blend.py` - `_interp_hourly`: a swell slot filled at both steps
  that fails the DEDUPE same-system test leaves `shared`, so it is held from the nearer step.
- `pipeline/src/rosa_pipeline/gwam.py` - `parse_points(data, points, aims=None)` picks via
  `geo.nearest_wet`; `GwamSource` / `GwamFixtureSource` take `aims`.
- Tests: `test_swan_buoys.py`, `test_verify.py`, `test_blend.py`, `test_gwam.py` (one each).
- `docs/CALIBRATION.md` - four 2026-09-18 entries. `docs/OPEN-ITEMS.md` 11 - pre-fix `.swan`
  rows warning. `docs/SESSIONS.md` - one entry.
- Memory `stage4-swan-ab-due-2026-10-05.md` - same warning appended.

## Changes Made This Session
1. **Backlog read.** 34 report nights; everything through 09-16 closed in the ledger and
   cross-checked diff by diff (`git apply --check` / `-R`). Open: 09-17 MEDIUM, 09-18 HIGH +
   MEDIUM, 09-18 proposal. All three findings were scored under 80 by the reviewer's second
   pass, each time because real-data size was unmeasured - the A/Bs below measured it.
2. **SWAN stamp** (applied via `review-apply.sh`). Recording-only arm, no A/B. `.swan` rows
   recorded 2026-09-14 until the VM pulls this fix carry the GFS cycle as `run` (4-10 h early, no
   `cycle` key) - drop them from the 5 Oct read.
3. **Scorecard run-mean** (A/B, then applied). VM archive copied read-only (215 MB, then
   deleted); ONE `verify --all-buoys --archive` pass per source with `cli.lead_time_scorecard`
   wrapped so base and candidate score the same `(rows, obs)`. Base reproduced the live
   `skill.json`. om RMSE +1% at 0-1d, +10-13% past day 5; ceilings 0.821/0.737/0.684 ->
   0.815/0.709/0.654; no label edge (0.70/0.45) crossed; blend < ecmwf < gfswave in every bucket
   on both arms. Cards printed before 2026-09-18 are run-mean cards - never compare across.
4. **Promoted swell** (A/B, then applied as filed). Two worktrees on `3a98707` (V2 commit, 1947
   spots = the capture's DB), replayed the 09-16 capture; control vs 09-16's V2 arm = 0 rows.
   Shape is 21.8% of both-filled slot pairs (62% slot moves, 25% death+birth, 13% one evolving
   system that now steps instead of ramps). Made-up filled-hour swells 6.5% -> 0 (by
   construction). 22.5% of rows move at 1833 spots; no-swell rows 0 -> 0, closure<0.5 1077 -> 1044.
   Traced top movers (carcavelos, pors-carn, eaglehawk-neck) at blend level: base's inventions.
5. **GWAM seaward cell** (A/B, then applied by hand). 99 of 2254 spots confirmed on decoded
   values; swell Tp moves >= 1 s at only 10-14 of them per step. Replay: 88 spots, 0.47% of rows,
   39 bucket rows; Tp becomes None on 162 rows, appears on 282 (`nearest_wet` radius vs the old
   square window). **The A/B shows footprint, not a gain - no Tp truth exists.** Applied on the
   2026-09-11 one-rule argument; flagged to the operator as the one fix that could be dropped.
6. Operator said "Go" (apply all four, A/B first) and later "Commit" on 2026-09-18 - history
   only; commit on Rosa means commit + push to main.

## Failed Attempts
- The Dream applier's own test runner fails every shipped proof with `ModuleNotFoundError:
  rosa_pipeline`. Run proofs as `PYTHONPATH=pipeline/src pipeline/.venv/bin/python <test> $PWD`.
- My first "made-up swell" counter used `wind_wave_*` keys; `GfsSea.fields` uses `windsea_h/p/d`.
- The "made-up -> 0" number for the blend fix is tautological (held values are native by
  construction); the honest evidence is the prevalence split, the pb_0332 counters and the
  traced movers. Do not quote the 0 as proof on its own.
- A published-JSON native-vs-filled test does not work: table rows are 3-hourly LOCAL, so in many
  time zones every published row is a filled hour. Measure at `blend._interp_hourly` level.
- `replay.py` sets `GwamFixtureSource.__init__.__defaults__ = (gwam_cycle,)`; after the GWAM
  change the tuple must be `(gwam_cycle, None)` or the replay breaks.
- HEAD (2254 spots) cannot replay the 09-16 capture (1947 points); arms must be built on
  `3a98707` or a new capture taken.

## Next Step
1. **Smoke check after the 17:20 local (14:20Z) cycle, from the CDN, never a local `run --all`:**
   `ssh ubuntu@82.70.253.255 'cd ~/rosa && git log --oneline -1 && cat data/verify/skill.json'`
   - expect HEAD `a08bd74` or later and `1-3d` scatter_index ~0.183 (was 0.1755); then
   `curl -s https://rosa-data-opal.vercel.app/data/spots/carcavelos.json` - fresh `fetched_at`,
   payload sane; check a `.swan.jsonl` tail on the VM has a `cycle` key.
2. Ask the operator again whether to delete the empty Frankfurt `rosa-vcn` (and whether
   `deploy/oracle/grab-arm-frankfurt.sh` should go). Not approved yet.
3. Not built, noted in CALIBRATION.md: pair a promoted slot in `_pair_flipped_slots` so it ramps
   instead of stepping (needs collision handling); would un-step the 13% evolving-system class.
4. Inherited from 2026-09-17 sessions, **not re-verified here** (check before acting): tester
   sign-in "Rosa couldn't be reached" cause unknown (`cd deploy/user-api && npx wrangler tail`);
   PWA + Play duplicate sheet never tested on a real phone; About back button goes to Profile
   (ask first); the 10 re-aims live on the CDN?; cycle-time read from `~/rosa/publish.log` for
   the CALIBRATION.md 2026-09-17 entry; stale "13 of the 19" in `tools/a4-gate/far-end-rays.md`
   and OPEN-ITEMS 15; `bessa` publishes 72 hours vs 104; 9 remaining bad rays + 128 shelf rays
   (OPEN-ITEMS 23; do not re-propose `d_ref = max(depths)`); review the 49 South America normals.
5. Commit `handoff.md` + `progress.md` (ask the operator).
6. Dated: C3b wind A/B 26 Sep; IMS beach wind 28 Sep; SWAN A/B 5 Oct (drop pre-fix `.swan` rows).
