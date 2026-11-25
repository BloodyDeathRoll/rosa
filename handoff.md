# Session Handoff - 2026-11-25

## Goal
Water temperature and the suggested suit were blank in the app. Find out why and fix it.

## Current State
- Cause found and fixed in code: NOAA's newest OISST daily file was 2026-11-18 (7 days old at 12:24 local on 2026-11-25). `OisstSource._latest_bytes` only walked back `MAX_LAG_DAYS = 4`, found nothing, and every spot got `sst: null`. `wetsuit` is computed from SST (`pipeline/src/rosa_pipeline/score.py:169`), so it went blank too.
- Fix committed and pushed to main as `ad305cbd`: `MAX_LAG_DAYS = 14`.
- Verified locally: a live `OisstSource().fetch` on 3 points returned `[23.92, 23.12, 21.07]`; `uv run pytest -q -x` 718 passed.
- NOT verified live yet. At 12:24 local the CDN still served the 04:31 local cycle (`fetched_at` 2026-11-25T02:31:21Z). The 10:20 local cycle had not published 2 hours after it started; its cause was not checked. The fix first runs in the 16:20 local cycle (14:20 UTC).
- Live check sampled 40 random spots from `https://rosa-data-opal.vercel.app/data/index.json`: 40/40 had `current.sst` and `current.wetsuit` null.

## Active Files
- `pipeline/src/rosa_pipeline/oisst.py` - `MAX_LAG_DAYS` 4 -> 14, comment says why.
- `docs/CALIBRATION.md` line 1787 - notes the 14-day lookback since 2026-11-25.
- `docs/SESSIONS.md` - 2026-11-25 entry.

## Changes Made This Session
1. Diagnosed from the live data, then the NOAA directory listing (`.../v2.1/access/avhrr/202611/`, newest `oisst-avhrr-v02r01.20261118_preliminary.nc`).
2. Raised the lookback to 14 days. NOAA's final file replaces the preliminary one about 2 weeks later, so 14 days covers a stall of up to 2 weeks. Each missing day costs two 404 requests, which is cheap. A stall longer than 14 days would blank SST again.

## Failed Attempts
- `index.json` and spot files live under `/data/` on the data host (`/data/index.json`, `/data/spots/{id}.json`), not at the root; the root URLs return 404.
- `index.json`'s `spots` is a dict keyed by id, not a list.
- `uv` is not on this shell's PATH: use `~/.local/bin/uv`, and push with `PATH=$HOME/.local/bin:$PATH git push origin HEAD:main` or the pre-push lint hook fails with `uv: command not found`.
- I gave the operator a cycle time that had already passed (I said 10:20 local when it was 12:24). Check `TZ=Asia/Jerusalem date` before naming the next cycle.

## Next Step
1. After 16:20 local (allow time for the cycle to finish), check the CDN: `curl -s https://rosa-data-opal.vercel.app/data/spots/wurtulla.json` and sample more spots; expect a fresh `fetched_at` and non-null `current.sst` / `current.wetsuit`.
2. If `fetched_at` is still 2026-11-25T02:31:21Z, the cycles themselves are stuck: inspect the VM (`rosa-arm`, `deploy/oracle/README.md`) cron log for `publish.sh`.
3. Open question for the operator, not decided: whether a stale-SST alert is wanted (NOAA stalls are silent today; the pipeline just publishes null).
