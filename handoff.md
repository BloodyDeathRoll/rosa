# Session Handoff - 2026-09-14

## Goal
(1) Put the new IMS (Israel Meteorological Service) API token to work: beach-level wind truth for
OPEN-ITEMS 25. (2) Work Dream's 2026-09-14 review: run the pb_0049 same-input A/B on its one
finding (blend filled hours blend swell slots), and ship the fix the A/B supports.

## Current State
- **IMS live in code and on the VM.** `bbb71b2` + `f45f1f2` pushed. `data/stations/ims.yaml` has 21
  stations (5 on the beach: 178 Tel Aviv Coast, 46 Hadera Port, 124 Ashdod Port, 208 Ashqelon
  Port, 106 Rosh Haniqra). `IMS_API_TOKEN` is in the VM's `~/rosa/.env` (chmod 600) and in local
  `.env.local` (the user renamed it from `IMS_TOKEN`). All 21 fetched live through the adapter.
  NOT verified: that a VM cycle has since archived model wind at the IMS ids and that step 4c scored them.
- **Guarded swell tracker shipped:** `516d9e7` pushed to main (blend.py, test_blend.py, 3 docs).
  650 tests passed, ruff clean on the changed files. NOT yet run on the VM: the first cycle that
  pulls it is 14:20Z (17:20 local) 2026-09-14.
- **The other session's Stage-4 SWAN work is all committed** (`2ff6a8b`..`2ad1571`, 2026-09-14):
  the SoCal pilot records `.swan` buoy rows every cycle from 14:20Z today, publishing stays on
  the march; see `docs/rosa-stage4-plan.md` and OPEN-ITEMS 11. Nothing of theirs is uncommitted.
- Dream ledger (`~/Projects/Dream/.../reports/.state/rosa.applied`) is closed through 2026-09-14.
  A playbook learning was appended (untagged) under "Codebase reviewer - learnings".

## Active Files
- `pipeline/src/rosa_pipeline/observe.py` - `IMSSource.fetch`: `to` = tomorrow on IMS's UTC+2 calendar; 204 -> `[]`.
- `pipeline/tests/test_observe.py` - 2 tests (exclusive `to`, 204).
- `data/stations/ims.yaml` - the 21 IMS stations (from `stations --discover ims`).
- `deploy/oracle/README.md` - IMS paragraph updated.
- `pipeline/src/rosa_pipeline/blend.py` - `_track_swells` (guarded) + `_interp_hourly` uses it.
- `pipeline/tests/test_blend.py` - `test_filled_hours_follow_the_swell_not_the_slot`, `test_a_swell_born_or_dying_is_never_paired_with_another`.
- `docs/CALIBRATION.md` - method rule exception line (top) + entry "2026-09-14 - Filled hours blend swell SLOTS".
- `docs/OPEN-ITEMS.md` - 25 updated (IMS step 1 done), 38 added and RESOLVED.
- `docs/SESSIONS.md` - 2026-09-14 entries (one landed inside the other session's `dd11bc4`).

## Changes Made This Session
1. IMS: verified token (191 stations), confirmed from the IMS PDF that stamps are winter time
   (UTC+2) all year - the adapter already did that. Ran discovery, filled `ims.yaml`. Measured two
   API quirks live and fixed them: `to` is exclusive (from=to=today = empty 204), and a no-data
   station answers 204 with an empty body. Token added to the VM env.
2. Dream review: backlog through 09-13 was already closed. 09-14 = one MEDIUM (60/100), no proposals.
3. A/B, zero Open-Meteo quota: captured GFS-Wave 00z f000-f120 (24 boxes), ECMWF, GWAM, OISST for
   all 1947 points; synthetic calm weather; real `run --all` replayed under two PYTHONPATHs with
   fixture cycles and the clock pinned. A-vs-A = 0 moved.
   - Slots swap in 15.8% of 3 h transitions (1821/1947 points).
   - Diff as filed: 5,427 transitions better, 1,366 worse (pairs slots across a swell's birth or
     death; jameos-del-agua 72 -> 26 because the invented swell made `drop_duplicate_windsea`
     delete a 2.08 m wind sea). REJECTED.
   - Guarded (each moved pair must pass blend's DEDUPE 20 deg / 15% "same system" test): 3,962
     re-paired, 2,267 better, 0 worse, made-up partitions 8,121 -> 582; 1.8% of published rows move
     at 791 spots. doran-beach's false 8 FLAT hour between two 52 GOOD hours becomes 52.
4. The user approved (2026-09-14, history only) applying the guarded variant, then committing and
   pushing only the 5 files. Done as `516d9e7`.

## Failed Attempts
- `stations --discover ims` run from `pipeline/` found 0 stations: `--spots-dir` defaults to the
  relative `data/spots`. Run from the repo root.
- Inspecting one spot with `GfsFullFixtureSource([one point])` returned nothing: box keys come
  from `cluster_boxes` over the WHOLE fleet. Cluster all points, then parse that box's files.
- The first guarded worktree was made from `HEAD` after another session had committed three
  re-aimed CA rays; its spot points no longer matched the capture and the replay died on a missing
  `weather_33.843_-118.452.json`. Pin worktrees to the capture's commit and run each replay with
  cwd = its own worktree (`load_spots` reads `data/spots` from cwd).
- `cmd1 && cd X && export P=... && {a} & {b} & wait` - jobs b/c ran in the parent shell without the
  cd/export and imported main's code. Put each job in its own `(cd X && PYTHONPATH=... cmd)`.
- The unguarded tracker (whole-set permutation minimising total cost) is a dead end - see 3 above.
- A/B scripts (`capture.py`, `replay.py`, `compare.py`, `fabricated.py`, `better_worse.py`) lived
  in the session scratchpad and are gone. The recipe is in CALIBRATION.md 2026-09-14.

## Next Step
1. After the 2026-09-14 14:20Z (17:20 local) cycle: on the VM (`ssh ubuntu@82.70.253.255`,
   hostname `rosa-arm`, verified this session) check the cycle finished:
   `grep -E "^=== .*(done|skipped)|^!!!" ~/rosa/publish.log | tail -3`; confirm `git log -1` there
   is `516d9e7` or later; check IMS rows are archiving:
   `ls ~/rosa/data/verify/stations/ | grep -E '^(178|46|124|208|106)\.'`; then the CDN
   `fetched_at` (`https://rosa-data-opal.vercel.app/data/spots/doran-beach.json`).
2. On/after 2026-09-28: score the 5 IMS beach stations (`verify --station 178 --archive` etc.)
   against the model's coastal cell - OPEN-ITEMS 25 (memory `ims-beach-wind-read-due-2026-09-28`).
3. Small doc fix, verified but not done: `blend.blend_archive_rows` docstring says compose_raw
   "fills ECMWF's 3-6 h steps by interpolation"; it is a nearest-step join (`extract._nearest_spectral`).
4. Carried from the 2026-09-13 web handoff, NOT re-verified this session:
   - Ask the operator whether to add `--archive=tgz` to `web/package.json` `deploy` (Vercel free
     upload quota; asked 2026-09-13, unanswered). Workaround:
     `cd web && npm run build && npm run prepare-output && npx vercel deploy --prebuilt --prod --archive=tgz`.
   - On a real phone, check Home shows the share icon left of search (a 14:34 screenshot showed none).
   - After a cycle on the METAR-208 commit `62341ce`: station-arm duration, weather-host 429s;
     if it blows up, `git revert 62341ce`. Figma station card (node `103:4`) to 208 / 886 of 1947.
   - GA "(not set)" in `web/src/ga.ts` `initGa()`; OPEN-ITEMS 36 and 37 - operator calls.
