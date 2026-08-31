# Session Handoff — 2026-08-31 (session 47)

## Goal
Settle "Surfline is right" on Zvulun's wind and faces with measurements, then fix the
two things the measuring exposed: the published wind model and the 6-7 h publish cycle.

## Current State
- **`main` at `a41aa3d`, pushed. 582 tests pass, ruff clean.** Five commits this session
  (`1bd68a6` GFS wind, `d73ba2f` physics perf, `f5d977a`+`1235b5c` docs, `a41aa3d` Dream).
- **Published wind is GFS (`fetch.WEATHER_MODEL="gfs_seamless"`) since 2026-08-30**, on
  all three legs (OM arm, blend aux batch, archive wind batch). Proven: Surfline's wind
  IS raw GFS (matched their kph hour-by-hour via Open-Meteo `gfs_seamless`), and the
  user's eyes at Zvulun 06-07 (9 kn NW, faces 0.9-1.2 m) sided with GFS over ICON's
  3.4 kn. ICON stays archived at every station under `<id>.icon`;
  `verify --stations --archive --wind-model {gfs,icon}` scores either. VM's 2 pre-switch
  ICON cycles renamed to `.icon`. First pooled GFS card (n=895, 0-1d): bias +0.31 m/s.
- **Faces**: same swell in, our breaker gave 0.77×Hs where eyes saw ~0.62×Hs (Zvulun);
  Hilton same morning was inside our band. Logged as graded frames (CALIBRATION.md
  2026-08-30), `height_coeff` untouched — one frame does not tune a transform.
- **The publish cron now runs on `rosa-arm`** (A1.Flex 4 OCPU/24 GB, 82.70.253.255,
  same key; it existed since 26 Jul, idle). Cycle measured **1 h 29 m** (archive 14 m +
  NOMADS fetch 48 m + 624 spots in 18 m @1.75 s/spot + deploy/verify 9 m) vs 6-7 h on
  the micro (sar: 6% user/45% steal = ~1/16 core). Cron kept 4×/day at 6 h; overnight
  cycles ran clean (1h11m, 1h10m), backup rsync + watchdog verified. `rosa-instance` is
  an idle spare (crontab emptied, backup in `~/crontab.before-arm-move.bak`).
- **physics 3.1x** (`d73ba2f`): breaker-march state-independent terms precomputed with
  numpy; A/B all 623 profiles × 48 cases worst 2.4e-15; scalar march kept in the test.
- **Dream 2026-08-31 review fully worked** (`a41aa3d`): 2 findings applied via applier,
  2 proposals by hand (Retry-After/ledger 429 classification; seam-safe `basin_boxes`),
  1 rejected (quantize vectorization — ~1-3 s of a 1.5 h cycle). Ledger + playbook
  bullet written in Dream.
- **IMS token: still not received** (requested by mail 2026-08-29). `ims.yaml` empty.
- `a41aa3d` not yet on the box — the 08:20Z (11:20 local) cycle pulls it.

## Active Files
- `pipeline/src/rosa_pipeline/fetch.py` — WEATHER_MODEL/WEATHER_AB_MODEL,
  `fetch_wind_many(model=)`, `_retry_wait_s` (Retry-After capped 300 s; unclassifiable
  429 retried iff quota ledger has room).
- `pipeline/src/rosa_pipeline/blend.py` — aux weather leg sends `models=WEATHER_MODEL`.
- `pipeline/src/rosa_pipeline/cli.py` — station arm archives both models
  (`STATION_AB_KEY_SUFFIX=".icon"`), `verify --wind-model`.
- `pipeline/src/rosa_pipeline/physics.py` — `_march_terms` (numpy precompute);
  `surf_height_over_profile` keeps only the dissipation recurrence as a loop.
- `pipeline/src/rosa_pipeline/swellmap.py` — seam-safe `basin_boxes` (signed offsets,
  warn, no clamp), unsliceable keyed on first GOOD step (Dream diff).
- `pipeline/tests/` — test_physics (scalar-march reference), test_fetch (429 cases,
  models param), test_swellmap (no-op + Fiji seam), test_cli (dual-model station arm,
  offline fleet-archive test).
- Docs: CALIBRATION.md 2026-08-30, OPEN-ITEMS 24 (RESOLVED) + 25, SESSIONS 47,
  CLAUDE.md, deploy/oracle/README.md (three-machine table, bootstrap §7).

## Changes Made This Session
1. Measured the wind dispute: Surfline = raw GFS; METARs + eyes → switched to GFS,
   kept ICON as station A/B. No knob touched; the switch is reversible in one constant
   and the A/B after ~2 weeks confirms or reverts it (OPEN-ITEMS 25).
2. Diagnosed the cycle: burstable micro at ~1/16 core (sar steal), not code alone.
   Found rosa-arm already existed (watcher launched it 26 Jul; its log ends BEFORE the
   launch — `oci compute instance list` is the truth). Migrated: deploy key, NodeSource
   Node 20 arm64, Vercel CLI, uv sync, 563 tests on aarch64, rsync data/verify+out+.env+
   rosa-push, micro's crontab emptied FIRST, same 3 cron lines on arm.
3. Vectorized the breaker march (identical to 2.4e-15, 3.1x).
4. Worked the first Dream report for rosa (details above).

## Failed Attempts
- **`pgrep -f publish.sh` over ssh matches the ssh command line itself** — showed a
  phantom running cycle twice; filter out `bash -c` (noted in oracle-vm memory).
- **`crontab -l | ... | crontab -` under `set -e` installed an EMPTY crontab** on arm
  (no prior crontab → `crontab -l` exits 1, subshell died, empty stdin piped through).
  Re-ran without set -e.
- **py-spy needs the real python pid** (a wrapper/false pid gives "Failed to find
  python version"); on the VMs use `sudo ~/.local/bin/uvx py-spy dump` (sudo drops PATH).
- **rosa-instance's `id_ed25519` is NOT authorized on rosa-arm** — hop with the project
  key from the workstation instead.
- **The A/B-test yaml for fake spots must carry `ideal:`** (and swell_window etc.) —
  `load_spots` KeyErrors otherwise; copy the shape from Dream's rig or israel.yaml.
- The arm cycle's ~1 h fetch phase is NOMADS' grib-filter pace (4 idle-ish conns,
  ~12 KB/s stretches) — not the box, not a bug; don't kill a "stuck" cycle for it.

## Next Step
1. **Verify `a41aa3d` from the CDN after the 08:20Z cycle** (pipeline-change smoke
   rule): `curl -s https://rosa-data-opal.vercel.app/data/spots/zvulun.json | jq .fetched_at`.
2. **IMS token when it arrives**: add `IMS_API_TOKEN=...` to `~/rosa/.env` on **rosa-arm**
   (82.70.253.255 now, not the micro), then locally
   `IMS_API_TOKEN=... uv run --project pipeline rosa-pipeline stations --discover ims > data/stations/ims.yaml`,
   review, commit; smoke `verify --station <id> --archive`.
3. **In ~2 weeks**: the GFS-vs-ICON station A/B
   (`verify --stations --archive --wind-model gfs|icon` on rosa-arm) confirms or
   reverts the wind switch; then pick the residual per-sector/hour correction
   (OPEN-ITEMS 25 — Hilton showed GFS itself still ~5 kn light at the beach some hours).
4. Optional, only if cycle time matters again: NOMADS fetch (~1 h) is the remaining
   chunk — fewer/fatter subset requests or a mirror (OPEN-ITEMS 24 tail note).
