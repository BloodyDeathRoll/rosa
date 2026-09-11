# Session Handoff — 2026-09-11 (afternoon)

## Goal
Close the Dream 2026-09-05 sampler finding (OPEN-ITEMS 27) for good with a measured A/B and a
written mode of operating, then recover the 08:20Z publish cycle that died on the Open-Meteo
marine host.

## Current State
Both changes are committed and pushed to `main` (`6d12010`, `d995a85`). 614 pipeline tests
pass, ruff clean. Only this `handoff.md` is uncommitted.

- **Sampler fix (`6d12010`) - live but NOT yet smoke-checked.** The three GRIB wave samplers
  (`ecmwf`, `gfswave`, `blend`) share `geo.nearest_wet`: ground-distance metric (lon scaled by
  cos lat) plus the spot's shoreline plane (`geo.Seaward` = pin + `shore_normal`; a wet node
  more than `SEAWARD_TOL_DEG` = 0.05 deg / ~5.5 km behind the pin loses to the nearest node
  that is not). `run` passes a `Seaward` per point; the buoy archive passes none.
  - Measured on real fields, all 1947 spots (`tools/ab-nodes/`): 0 spots refused a node before
    or after; 73 (GFS) / 79 (ECMWF) spots change node, median +0.13 / +0.17 m at those spots.
    Full table in `docs/CALIBRATION.md` 2026-09-11 (second entry of that date).
  - Known limits, recorded in OPEN-ITEMS 27: `ocean-grove` still reads Port Phillip Bay across
    the Heads (half-plane is not line-of-sight; fix is its `offshore_km`). `anchor` (normal 160
    beside devil-s-rock's 255) and `le-morne` (normal 0) look like wrong normals.
- **Marine-light leg non-fatal (`d995a85`).** `blend.fetch_aux_many` warns and hands a batch
  `{}` when the marine request fails all three attempts; the leg only backs up EOT20 tide and
  OISST SST. Weather stays essential. The OM arm's `fetch_marine_waves_many` was NOT changed.
- **Network fault, still present at 12:55 IDT (OPEN-ITEMS 32):** from all three Oracle VMs,
  TCP connects to `marine-api.open-meteo.com`'s IPv4 152.53.84.37 fail in ~5 ms with
  `EHOSTUNREACH` on ~40 % of tries. Works from the workstation. `api.open-meteo.com`, NOMADS,
  ECMWF, Vercel are fine. Seen (and survived by retries) on Sep 3 and Sep 9 too.
- **A manual publish cycle is RUNNING on rosa-arm**, started 12:57 IDT (09:57:49Z) on
  `d995a85`, launched with `nohup setsid deploy/oracle/publish.sh`. At 1947 spots a cycle takes
  ~2 h 15 m, so it should finish ~15:15 IDT. Its outcome was not known when this was written.
  The CDN still serves the 05:26 IDT (02:26Z) publish. The rosa-backup freshness watchdog
  (`~/rosa-watch/freshness-watch.py`, hourly at :17, last "ok" 12:17) pages once the publish
  is > 8 h old, i.e. at 14:17 IDT unless the manual cycle beats it.
- The crash alert push ("FAILED at: rosa-pipeline run --all", 12:49 IDT) is what the user saw
  as "healthcheck is down". Not verified whether a Healthchecks.io ping is also wired.
- Dream: `.state/rosa.applied` ledgered the 09-05 diff as applied by hand; an untagged learning
  was added to Dream `playbook.md` above the Load-bearing subsection. The two 2026-09-11 LOW
  findings (`notify.py` feedback-pull / damaged-stamp) and the 09-10 / 09-11 proposals are
  still open, not applied - the user never picked them.

## Active Files
- `pipeline/src/rosa_pipeline/geo.py`: `lon_scale`, `Seaward`, `nearest_wet`, `SEAWARD_TOL_DEG`.
- `pipeline/src/rosa_pipeline/ecmwf.py`, `gfswave.py`, `blend.py`: samplers call
  `geo.nearest_wet`; `aims` kwarg on the parse functions and on `EcmwfSource`,
  `EcmwfFixtureSource`, `GfsFullSource`, `GfsFullFixtureSource`. `blend.fetch_aux_many`
  degrades the marine-light batch.
- `pipeline/src/rosa_pipeline/cli.py`: `_cmd_run` builds `aims = {point: Seaward(...)}` from
  the first spot at each point and passes it to the four sources.
- `pipeline/tests/test_nearest_wet.py` (new, 12 tests), `pipeline/tests/test_blend.py` (+1).
- `tools/ab-nodes/ab_nodes.py` + `README.md` (new): `fetch | sample [--no-aim] | diff`.
- `docs/CALIBRATION.md`: new method rule (run the A/B the same day) + the 2026-09-11 node entry.
- `docs/OPEN-ITEMS.md`: 27 CLOSED (with follow-ups), 32 added. `docs/SESSIONS.md`: two
  entries. `docs/SPOT-DB.md`: `shore_normal` now also draws the sampler's shoreline plane.
- `.claude/settings.local.json`: `defaultMode` switched from `bypassPermissions` to `auto`
  (user asked; applies from the next session).
- Memory: `run-the-ab-same-day.md` + MEMORY.md line.

## Changes Made This Session
1. Project default permission mode set to `auto`.
2. `/dream-review`: classified all 9 nights of rosa reports; only the two 09-11 LOW diffs and
   the held 09-05 diff were open. The user asked what to do about 09-05 and, after a first
   "want me to do it?" answer, demanded research and a mode of operating instead.
3. Ran the pb_0049 A/B locally in ~20 min: one global swh field per model (<1 MB, no OM
   quota), the shipped parsers under two `PYTHONPATH`s (base `df1d72e` in a worktree). The
   reviewer's cos-only diff moved 42 / 34 spots and put point-lonsdale + ocean-grove INSIDE
   Port Phillip Bay - distance was the wrong primitive. Recommended cos fix + seaward rule;
   user said "do it".
4. First seaward rule (strict half-plane at the sample point) moved 454 / 576 spots; drawing
   the plane at the PIN cut it to 199 / 268; only 41 / 55 of those flips were clearly-behind
   nodes (bays), the rest the ordinary coast cell traded for the next cell out (median +0.13 /
   +0.20 m). Shipped the 5.5 km tolerance variant (73 / 79 spots) and recorded the strict
   numbers so a future buoy-backed decision can flip one constant.
5. Wrote the mode of operating in three places (CALIBRATION method rules, Dream playbook,
   memory): a gated finding whose A/B is runnable from the workstation gets it the same day.
6. Outage review on request: traced the 08:20Z failure to `EHOSTUNREACH` on the marine host
   from Oracle; made the leg non-fatal; re-ran the cycle by hand.

## Failed Attempts
- The Dream diff no longer applied (`blend.py` import hunk) - re-ported by hand.
- `ssh rosa-arm` alias does not resolve; use `ssh -i ~/.config/rosa/ssh-key-2026-07-23.key
  ubuntu@82.70.253.255`.
- `pipeline/tests/` has no `__init__.py`: a relative import from `test_ecmwf` failed at
  collection; the test defines its own fixture path instead.
- The publish log is `~/rosa/publish.log` (not under `deploy/oracle/`). It is append-only;
  bracket by dated `run start` / `done` lines.
- Two seaward-rule variants were measured and rejected before the shipped one (see 4).
- `ocistatus.oracle.com` did not resolve from the workstation; Oracle status unchecked.

## Next Step
1. **Check the manual cycle**: `grep -n "run start\|done ===\|FAILED\|marine-light batch"
   ~/rosa/publish.log | tail` on rosa-arm. If it published, smoke-check from the CDN
   (`curl -s https://rosa-data-opal.vercel.app/data/spots/portsea.json | head -c 600` should
   show a fresh `fetched_at`; portsea / georgica-beach / black-rock-carenero are the biggest
   movers, ocean-grove is the known regression). If it failed again, read the traceback first;
   the 14:20Z cron will retry regardless.
2. If the marine host is still ~40 % unreachable on 2026-09-12: Oracle ticket for
   il-jerusalem-1 egress to 152.53.0.0/16, or enable IPv6 on the VCN (OPEN-ITEMS 32).
3. Spot-DB follow-ups from OPEN-ITEMS 27: `ocean-grove` `offshore_km` (push the sample point
   south of the Heads, then re-derive its tide constants), re-check `anchor` and `le-morne`
   normals.
4. Dream backlog still open: 09-11 LOW diffs `feedback-pull-survives-a-non-object-row` and
   `notify-stamp-check-survives-a-damaged-stamp` (both `notify.py`, order irrelevant),
   09-10 proposals (`feedback --at` out-of-range refusal, `member_directions_at` gating,
   `events._elevated` deque), 09-11 proposals (peak-vs-mean direction note, NDBC `MWD`
   definition check).

**Carried from the 2026-09-11 morning handoff (unverified this session):**
- Smoke-check the depth-grid swap (`dabaa6f`) and the 539 new spots from the CDN
  (`pantin.json`, `fort-point`, `tourinhos`); measure the cycle duration at 1947 spots.
- Test the Samsung "Open in Chrome" install flow on a real Samsung phone.
- Gap queues in `docs/spot-db-scraping-playbook.md` §5 (Spain Med/Huelva, Brazil AL/SE/PB,
  Fuerteventura, Oran west).
- Figma workflow diagram not updated for the depth-grid swap.
- Confirm `3feb20e` (map default focus) on a device with location denied.
- The user was to add a Gmail filter `from: formsubmit.co` -> never spam.
