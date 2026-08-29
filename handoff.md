# Session Handoff — 2026-08-29

## Goal
Opened on "santa teresa camera not available again"; that led into a stale CDN, a crash on
main, and a cycle-duration problem. All three closed. No work is mid-flight.

## Current State
- **`main` at `74065f8`, pushed. 545 tests pass, ruff clean, tree clean.**
- **CDN healthy: 624 spots, median age 7.6 h, zero spots over 24 h.** All six regions that
  had never published are there (Maldives 23, Peru 49, Morocco 42, Panama 23, Angola 9,
  El Salvador 32).
- **No cycle running.** The 02:20Z cycle ran 02:20:01Z -> 09:20:06Z (7 h) and 08:20Z skipped
  on the lock. Next cron is 14:20Z (17:20 IDT).
- **The VM is at `352779a`, two docs commits behind main** - it pulls on the next cycle.
- **Open, not broken: a cycle takes ~7 h against a 6 h cron, so every other one is skipped
  and the fleet publishes twice a day instead of four times.** OPEN-ITEMS 24.
- **Every timing in OPEN-ITEMS 24 is PROVISIONAL.** Taken 2026-08-29 against a pipeline that
  had just changed its breaker physics, wave source, failure handling and spot count
  (469 -> 624). **User decision: do not use them as a baseline; wait a couple of days of
  settled cycles and re-measure.** The same-day A/Bs (one variable, same box) are sound; the
  absolute durations are not.

## Active Files
- `pipeline/src/rosa_pipeline/physics.py` - `hb <= 0.0` guard in
  `breaker_height_komar_gaughan`; new `wave_state()` returning (k, C, Cg) from one solve,
  `celerities()` is now its k-free view.
- `pipeline/src/rosa_pipeline/cli.py` - `EXIT_PARTIAL = 4`, `PARTIAL_FAILURE_MAX_SHARE = 0.05`.
- `deploy/oracle/publish.sh` - `git checkout -- data/spots` before the pull; step 1b cam
  repair; exit-4 branch that alerts and deploys.
- `deploy/oracle/cam-watch.sh` - header rewritten; stays weekly and read-only.
- `deploy/backup/freshness-watch.py` - per-spot rot sweep off `index.json`. **Deployed to
  rosa-backup (`~/rosa-watch/`), md5 verified equal to the repo copy.**
- `data/spots/{israel,japan,portugal}.yaml`, `data/cams/seen.json` - cam ids.
- `pipeline/tests/{test_physics,test_cli,test_freshness_watch}.py` - the new pins.
- `CLAUDE.md`, `docs/{SPOT-DB,OPEN-ITEMS,SESSIONS}.md`, `deploy/oracle/README.md`.

## Changes Made This Session
1. **santa-teresa cam: nothing broken.** `@malpaisurfcam1` is daylight-only and YouTube mints
   a new video id on every restart, so any pinned id dies within a day.
2. **Cam repair moved onto the cycle** (`5e878c3`). `verify --resolve --apply` runs in
   publish.sh step 1b. The read-only-deploy-key objection that kept `cam-watch.sh` from
   applying is answered by `git checkout -- data/spots` BEFORE the pull: the patch lives one
   cycle, the pull stays a clean fast-forward. Dark window a week -> ~6 h. Makes the cam tool
   an explicit exception to CLAUDE.md's "report, never apply", written into the prohibition.
3. **Cam audit: 6 of 21 dead.** Four auto-repaired by title match (`f4c6d37`);
   costa-caparica's Praia do Infante retired (`8a3bf0f`, user-approved).
4. **Fixed a crash on main** (`d021154`). `test_quota.py::test_fixture_replay_is_exempt` had
   been red since `cdd6e1a`. The random-sea march feeds K&G the friction-attenuated H0, so a
   0.25 s partition drives `atten` to ~1e-210, `h0**2` underflows to 0.0, and the refraction
   iteration asked for the celerity at depth 0.
5. **A partial fleet failure now publishes** (`c3a72e9`). Exit 4 when failures are <=5% of the
   fleet; publish.sh deploys and alerts. **This was the actual cause of the stale CDN**: three
   spots raised the K&G ValueError, `run --all` returned 1, the ERR trap killed the cycle, and
   621 healthy spots plus 155 newly seeded ones sat off the CDN for a day.
6. **Closed the hole that opened** (`9183082`). The watchdog read exactly ONE payload
   (`beit-yanai.json`) - verified on the box - so a spot left behind by a partial cycle would
   have rotted invisibly. It now sweeps `index.json`'s per-spot `generated_at`, pages past
   24 h (not 8 h: a spot that missed one cycle reads 6-12 h and must not page).
7. **Forced the publish out by hand.** Killed the 6 h 47 m cycle, staged `data/out` (already
   624 spots at 6.8 h median from the run that completed then failed on the exit code) and
   ran `vercel deploy --prebuilt --prod`. CDN 469 -> 624, age 31 h -> 7 h.
8. **`352779a`:** the march solved the dispersion relation twice per substep - `wavenumber()`
   then `celerities()` for the same (T, d) - which is the exact waste `celerities`' docstring
   says it exists to remove. **VM 10.91 -> 6.22 s/spot, -43%, payload bit-identical.**
9. **`1d623c2` + `74065f8`:** removed an invented "laptop" (machine type was never
   established) and marked the timings provisional per the user's decision.

## Failed Attempts
- **The channel-embed cam fix - built end to end, then reverted.**
  `/embed/live_stream?channel=UC...` was wired through SpotCam/payload/iframe before
  `docs/OPEN-ITEMS.md` 8 turned out to have recorded it dead on 2026-08-03. Re-verified
  against a channel live at that moment: `previewPlayabilityStatus: ERROR / "Video player
  configuration error" / Error 153`. **Read OPEN-ITEMS before building; it was one grep away.**
- **Benchmarked the physics with samples sorted by DEPTH.** Production reverses by DISTANCE
  (`wet_samples_deep_to_shallow`). The depth sort made distances non-monotone, inflating
  `seg_len`, and reported 10 ms/call where the truth is 2.7 ms.
- **Read a cProfile number as wall time** (6.31 s/spot). Fair best-of-3 on the pc is 2.21 s.
- **Generalised a pc measurement to the VM** without measuring the VM, whose core is ~5x
  slower. Every headline number was re-taken on the box afterwards.
- **A caller-level regression test for the K&G underflow** - not reachable through
  `surf_height_over_profile`: `surf_in_profile` latches the height on the first breaking
  substep before `atten` collapses, so the K&G close never decides the answer.
- **`pkill -f "deploy/oracle/publish.sh"` LOOKS successful but leaves the `uv` and python
  children running.** Needed `kill -9` by PID. Check with `pgrep -af "rosa-pipeline run"`.
- **`grep -E "^===" publish.log` misses cycle markers.** The log glues `=== run start ===`
  onto the end of a spot line. Use `grep -o "=== 2026-..-..T[0-9:]*Z \(run start\|done\|skipped\)"`.
- **`awk "/14:20:01Z run start/,0"` matched earlier days** - the pattern needs the full date.

## Next Step
1. **Do nothing to the cycle for a couple of days** (user decision). Then take the cycle
   duration and per-spot cost from a few consecutive settled cycles and REPLACE the
   provisional figures in OPEN-ITEMS 24. Only then decide whether to tune further.
2. **Attribute the other ~5 h** before touching the physics again. The archive step alone ran
   46 min on 2026-08-28; swellmap, the skill measurement and the global-file fetch are
   unmeasured. The next FREE per-spot win is a memo on exact `(period_s, d_mid)` - 771 march
   calls per spot cover only 170 distinct periods. **`_SUBSTEP_M` (25 m) moves published
   heights - it needs the A/B; the double solve did not.**
3. **Confirm publish.sh step 1b actually runs.** It has never executed cleanly: the 14:20Z
   cycle pulled a modified publish.sh while bash was executing it. After the next cycle,
   `grep -E "OK   |DEAD " ~/rosa/publish.log` on the VM should show the cam verify output.
4. **Verify exit 4 in the wild** - it has never fired. `moclips` and
   `seabrook-pacific-beach` were the two stale spots and are now fixed, so nothing is failing.
5. Still owed from before: the physics fleet A/B (`~/ab/physics-report.md` was never
   produced - the recovery script died with the cycle), OM-vs-blend A/B, bathymetry A/B
   (OPEN-ITEMS 23), `closure >1.25` residuals (OPEN-ITEMS 22), more regions.
