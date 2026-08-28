# Session Handoff — 2026-08-28 (14:40 IDT)

## Goal
Opened on "santa teresa camera not available again". Closed the cam-rot problem
structurally, and fixed a crash the previous session's physics commit had left on main.
The previous session's work (Tp join bug + random-sea breaker physics) is still mid-flight:
committed and pushed, **not yet on the CDN**, with a fleet A/B still running.

## Current State
- **`main` at `5e878c3`, pushed.** 537 tests pass, ruff clean.
- **The CDN is STALE and has been since 2026-08-27 14:43 IDT.** The 20:20Z, 02:20Z and
  08:20Z cycles all died on the Open-Meteo minutely-cap 429; `bd3e7b8` fixed the retry.
- **A recovery cycle IS RUNNING on the VM** (`~/ab-physics2.sh`, PID 507537, started
  12:25 IDT). It reran `publish.sh` with the 429 fix and is now deep in `run --all`
  (478/624 spots at 14:34 IDT, retry visibly working). When it publishes it snapshots that
  as the physics TREATMENT arm, then runs the CONTROL arm (`ef5a658`, Tp fix without
  physics) in a worktree and diffs into `~/ab/physics-report.md`. **The control arm runs at
  `ef5a658`, which lacks the 429 retry - it may die on the minutely cap.**
- **`index.json` on the CDN lists 469 spots; the local DB is 624.** Measured today, not yet
  explained - the last good publish predates the recent seeding. The running cycle is the
  first that should publish the full set. **Verify the count after it lands.**

## Changes Made This Session
1. **Diagnosed santa-teresa: nothing is broken.** `@malpaisurfcam1` is a DAYLIGHT-ONLY cam -
   it streams ~14:00-04:00 IDT and YouTube mints a NEW video id on every restart, so the id
   pinned in `costa-rica.yaml` had been dead since 2026-08-04 and any pinned id dies within
   a day.
2. **Built the render-time escape, then reverted it.** `/embed/live_stream?channel=UC...`
   would let the player resolve the current live stream and never go stale; it was wired end
   to end (`SpotCam.channel` -> payload -> iframe) before `docs/OPEN-ITEMS.md` 8 turned out
   to have recorded it as deprecated on 2026-08-03. **Re-verified against a channel that was
   live at that moment: `previewPlayabilityStatus: ERROR / "Video player configuration
   error" / Error 153`.** All reverted; the doc carries the 2026-08-28 re-test. The lesson is
   the cheap one - OPEN-ITEMS was one grep away and would have saved the build.
3. **`verify --resolve --apply` now runs in every publish cycle** (`publish.sh` step 1b,
   non-fatal, ~1 API unit clean / +100 per dead cam). `cam-watch.sh` would not `--apply`
   because the VM holds a READ-ONLY deploy key and a dirty `data/spots` breaks the next
   `git pull --ff-only`, silently freezing the box on local code. Answered by a
   `git checkout -- data/spots` BEFORE the pull: the patch lives one cycle, the pull is
   always a clean fast-forward. Dark window: a week -> ~6 h.
4. **Fleet cam audit: 6 of 21 assigned cams were dead.** Four auto-repaired by title match
   and committed (hagolshim, hebara, kamogawa-malibu, aoshima). Two need a human - see
   Next Step 2.
5. **Fixed a crash on main** (`test_quota.py::test_fixture_replay_is_exempt`, red since
   `cdd6e1a` - so the previous handoff's "535 tests pass" was already wrong). The random-sea
   march feeds Komar & Gaughan the FRICTION-ATTENUATED H0, and beit-yanai's 0.25 s wind-wave
   partition (OM publishes `wind_wave_period` down to 0.0) drives `atten` to ~1e-210.
   **`h0` squared underflows to exactly 0.0**, `hb` with it, and the refraction iteration
   asked for the celerity at depth `hb/gamma` = 0.0 - one hour's `ValueError` aborting the
   whole spot's publish. Guarded: a sea that thin has no breaker, return 0.0. The guard only
   fires where the old code raised, so nothing published moves and no A/B is owed.

## Active Files
- `deploy/oracle/publish.sh` — `git checkout -- data/spots` + step 1b (cam repair).
- `deploy/oracle/cam-watch.sh` — header rewritten; stays weekly and read-only, now for the
  NEEDS-A-HUMAN cases and the cams nobody has committed.
- `pipeline/src/rosa_pipeline/physics.py` — the `hb <= 0.0` guard in
  `breaker_height_komar_gaughan`; `pipeline/tests/test_physics.py` pins it.
- `data/spots/{israel,japan}.yaml` — four refreshed cam ids.
- `CLAUDE.md` (cam tool is now an explicit exception to "report, never apply"),
  `docs/SPOT-DB.md`, `docs/OPEN-ITEMS.md` 8, `docs/SESSIONS.md` 43.
- VM `~/ab-physics2.sh`, `~/ab-physics2.log` — the running recovery + A/B.

## Failed Attempts
- **The channel embed** (item 2 above) — Error 153, third time it has been proposed. Do not
  build it a fourth time; read OPEN-ITEMS 8 first.
- **A caller-level regression test for the underflow** — not reachable through
  `surf_height_over_profile`: `surf_in_profile` latches the height on the first breaking
  substep before `atten` collapses, so the K&G close never decides the answer. The unit test
  on `breaker_height_komar_gaughan` plus test_quota's fixture replay are the coverage.
- Carried over from the physics session: "blend vs OM explains poleg" (measured false);
  "re-fit rideability on the July frames" (impossible - 07-19 and 07-26 demand opposite
  moves); 100 m dissipation substeps (zeroed the surf); `sqrt(1 - loss/flux)` attenuation
  (goes to exactly 0); a scratch probe fed the profile shallow-first (check sample order);
  `nohup` over ssh without `disown` hangs the connection but the job DOES launch - verify
  with `pgrep` in a second ssh rather than re-launching.

## Next Step
1. **Watch the recovery cycle land**, then verify on the CDN:
   `curl -s https://rosa-data-opal.vercel.app/data/spots/poleg.json` — poleg Sunday mids
   should read ~0.8-1.3 m flat (was 0.55-1.9 swinging 3x from the Tp bug); and
   `index.json` should list **624** spots, not 469.
2. **Two cam decisions are yours:**
   - `santa-teresa` — nothing to fix. The 17:20 and 23:20 IDT cycles fall inside its
     daylight window and will repair it; it is dark every night regardless.
   - `costa-caparica` third angle `TxI7MEJIGWc` ("Praia do Infante") — **retired**, last
     frame 2026-08-23 23:00. The channel's only unmatched live stream is Marina de Portimão,
     a sheltered harbour ~200 km south with no surf and no Rosa spot within 33 km. Same call
     as 2026-08-04: remove the angle. The other two angles are live and healthy.
3. **Fetch the A/B report** when it appears:
   `ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 'cat ~/ab/physics-report.md'`
   Expected: Israel/short-period-shelf regions h_mid down 25-40%, groundswell coasts ~-21%
   flat. Append the table to the 2026-08-28 CALIBRATION.md entry. If a region moves in a way
   the physics can't explain, investigate before anything else ships.
4. **Confirm step 1b actually ran** in the 17:20 IDT cycle: `grep -A3 "cam" ~/rosa/publish.log`
   on the VM should show the verify output, and `git status` there should be clean at the
   start of the following cycle.
5. Sunday is the live test for the physics: Surfline says 0.6-1.1 m at poleg. A volunteered
   eye report is ground truth and the calibration layer re-fits on it (doctrine, 2026-08-28).
6. Still owed: OM-vs-blend A/B (from the 08-26 promotion), bathymetry A/B (OPEN-ITEMS 23),
   `closure >1.25` residual characterisation (OPEN-ITEMS 22), more regions (BC, Indonesia,
   Australia, Chile, France/Spain, South Africa).
