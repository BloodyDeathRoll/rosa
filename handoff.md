# Session Handoff - 2026-09-17

## Goal
Finish seeding South America (Chile, Ecuador, Uruguay, Argentina, the Brazil gaps) without
breaking the Open-Meteo weather quota, then shorten the publish cycle. Two older tracks are
carried from the previous handoff, NOT re-verified here: the Dream 09-16 blend fix smoke, and the
Google Play closed test.

## Current State
- **Spot DB: 2254 spots** (was 1947), pushed as `2586700`. The 20:20Z cycle on 16 Sep published
  all 2254 (verified on the CDN and in `publish.log`): 3 minutely 429s, retried; no daily refusal.
  Punta de Lobos carries swells and scores up to 92.
- **Weather quota estimate is OVER the nominal line**: ~11,800 units/day vs 10,000 (arithmetic,
  the weather host is not metered by `quota.py`; the cap has never been enforced). OPEN-ITEMS 34.
- **ICON station leg dropped** (`8975c44`): the station A/B confirmed GFS. `<station>.icon.jsonl`
  stays on the VM; `--wind-model icon` still scores it.
- **Cycle speed-up pushed as `1967545`, NOT yet measured on the VM.** The 08:20Z cycle on 17 Sep
  pulls the new pipeline code (forked scoring) but still runs the OLD `publish.sh` order, because
  bash keeps executing the script it started with; the new order first applies at 14:20Z.
  Locally: 672 tests pass, ruff clean, same-input A/B byte-identical.
- The 02:20Z cycle on 17 Sep was still running at 07:15 local (started on time). Not checked after.
- A one-time cloud routine `trig_01HwESHBzh1UG6bDQug4sPYc` was set for 03:30Z 17 Sep (CDN-only
  check of the 2254 spots). Its result was not read in this session.
- Uncommitted: `docs/SESSIONS.md` (this session's entry + two other sessions' entries),
  `handoff.md`, `progress.md` (untracked).
- Carried, unverified: blend fix `3a98707` smoke from the CDN was never formally done (this session
  only saw non-empty `swells` on ~90 sampled spots). Play closed test `1 (1)` was in review on
  16 Sep; `assetlinks.json` untested on a device.

## Active Files
- `data/spots/{chile-north,chile-central,chile-south,ecuador,uruguay,mar-del-plata,patagonia-argentina,paraiba,alagoas,sergipe}.yaml` - the 10 new regions; 307 bathy + 307 tide files under `data/spots/derived/`.
- `tools/spot-seed/seed.py` (10 REGIONS boxes), `tools/spot-seed/emit_spots.py` (CFG), `pipeline/src/rosa_pipeline/swellmap.py` (4 new basins + 3 states into `brazil-northeast`).
- `tools/spot-seed/work/<region>/judge.json` - per-region judge logs (gitignored work dirs).
- `pipeline/src/rosa_pipeline/cli.py` - ICON leg removed; `archive --stations {with,skip,only}`; `_score_point`, `_score_workers`, `run --workers`.
- `pipeline/src/rosa_pipeline/fetch.py`, `gfsatmos.py` - `WEATHER_AB_MODEL` removed, comments.
- `deploy/oracle/publish.sh` - `run_evidence()` + EXIT trap; step 1 is `archive --stations skip`; `RUN_RC=0; ... || RUN_RC=$?`.
- `pipeline/tests/test_cli.py` (2 new tests, station test rewritten), `test_fetch.py`, `test_geo_seam.py` (count 2254).
- Docs: `CLAUDE.md` (counts, ICON line), `docs/SPOT-DB.md`, `docs/spot-db-scraping-playbook.md` section 5, `docs/CALIBRATION.md` (2026-09-16 station A/B, 2026-09-17 cycle time), `docs/OPEN-ITEMS.md` 25/34, `docs/rosa-stage4-plan.md`, `docs/rosa-fetch-plane-plan.md`, `deploy/oracle/README.md`.

## Changes Made This Session
1. Read the station wind A/B on the VM (`verify --stations --archive --wind-model {gfs,icon}`,
   207 stations): GFS speed bias -0.04 m/s vs ICON -0.80 at 0-1 d, GFS better MAE at every lead.
   Dropped the ICON fetch (~916 units/day at 229 stations). Operator asked for this step.
2. Measured a weather-request sharing idea on 233 spots (~230 OM units): 161 distinct series
   (~31%); operator then accepted the recommendation to skip building it (C3b read is 26 Sep).
   Design + numbers are in OPEN-ITEMS 34.
3. Seeded 10 regions with 10 parallel subagents per the playbook. Renamed `chubut` ->
   `patagonia-argentina` (9 of 16 spots are Rio Negro). Tightened paraiba's N edge to -6.47
   (it re-offered RN's `pontal`), widened mar-del-plata's to -36.60. Re-cut 15 Chile North tide
   files that predated their re-aim. Committed + pushed (Rosa commits straight to main).
4. Measured the cycle from VM file mtimes (4 h 32): station GRIB leg ~70 min, SWAN ~51, fetch
   ~74, scoring ~53 on one of 4 cores. Operator approved fixes 1 and 2 (17 Sep), then the alert fix.
5. `publish.sh`: evidence legs after the deploy and from an EXIT trap (archives cannot be
   back-filled); verified with a stub harness over exits 0/3/4/1. False "Cycle FAILED" on exits
   3 and 4 fixed (bash ERR trap fires even under `set +e`).
6. `run --all`: forked workers return events, the parent replays in point order and does all
   writes. A/B on a captured 135-spot run with a frozen clock: 136/136 files byte-identical, logs
   line-identical, wall 134.9 s -> 83.7 s (scoring ~69 -> ~18 s).

## Failed Attempts
- **Bucketing spots by a 0.25 deg (or 0.1 deg) cell to share weather requests**: changes the
  published wind (134 of 233 rows at 0.25). Open-Meteo's `gfs_seamless` grid is ~11 km, 3 km in the
  US. Even spots with the same RETURNED lat/lon differed (17 pairs gusts/pressure, 2 pairs wind).
- My first quota claim ("ICON saves 870", "sharing saves 60%") was wrong until measured: 916 and ~31%.
- `run --fixtures` replay of a fresh capture publishes nothing: the fixture sources stamp a fixed
  2026-08-14 / 2026-07-22 cycle, so wave hours never overlap the weather hours. Use a harness that
  passes `cycle=` and freezes `datetime.now` (scratchpad `par/replay.py`, deleted with the session).
- Subagent briefs said `cd pipeline && uv run rosa-pipeline bathy`: that resolves `data/spots`
  against the wrong cwd. Run from the repo root with `uv run --project pipeline`.
- `emit_spots.py` is the wrong emitter for a 0-Tier-A region (no `town`, reads only
  `result.json["new"]`); forks used `ca_final.py` -> `towns.json` -> `emit_region.py`.
- A local CDN watcher (`watch_cycle.sh`, background) was killed overnight; nothing lost.

## Next Step
1. After the 14:20Z cycle on 17 Sep (17:20 local): `ssh ubuntu@82.70.253.255` and read
   `~/rosa/publish.log` - confirm the order (archive --stations skip -> run --all -> deploy ->
   station archive -> SWAN), that no "scoring pool failed" warn appears, and time run-start ->
   index.json mtime (target ~2 h 15; was ~4 h 16). Record the measured numbers in
   `docs/CALIBRATION.md` 2026-09-17. Watch the 6 h slot: evidence legs now END the cycle, an
   overrun makes the lock skip the next one.
2. Read the cloud check: `RemoteTrigger list_runs` on `trig_01HwESHBzh1UG6bDQug4sPYc`.
3. Review the 49 re-aimed shore normals from the seeding (start with `punta-de-lobos`:
   `offshore_direction: 151`, window [266, 36] on a west-facing point); `aim_normal.py` reports only.
4. Commit or leave `docs/SESSIONS.md`, `handoff.md`, `progress.md` - ask the operator.
5. Dated: 8-week checkpoint was due 17 Sep (progress.md); C3b wind A/B 26 Sep; IMS beach wind
   28 Sep; SWAN A/B 5 Oct. Play: tester link, device install, delete-account URL (old handoff).
