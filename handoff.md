# Session Handoff - 2026-08-26

## Goal
Resume from the 2026-08-23 handoff, whose sole open item was "run the `run --all`
fleet smoke on the next quota day". Ended up proving that smoke never needed a
local run at all, verifying the six Dream proposals live instead, and rewriting the
rule that had produced the false blocker.

## Current State
- **HEAD `cc5331b`, unchanged this session. No code was touched.** Only `handoff.md`
  is modified; nothing committed, nothing deployed.
- **The six-proposal change (swellmap accumulators, 0/360 seam fix, `tail_from`
  provenance) is VERIFIED LIVE and healthy.** The smoke the last handoff was waiting
  for had in fact been passing on the VM 4x/day since 08-23.
- Verified from the CDN at 07:40Z against the 02:47Z cycle, zero Open-Meteo quota:
  - 265/265 spots fetched OK, no errors
  - `tail_from` present and non-null on **all 265** (e.g. acadia `2026-09-04T03:00+03:00`)
  - zero null `h`, zero null `rating` across every published hour
  - `hours` is 120 or 128; `fetched_at` spread 02:46:00Z..02:50:07Z (5 distinct)
- VM `rosa-instance` on `cc5331b`, cycle done clean 2026-08-26T02:56:32Z.
  swellmap published 9 basins + world, 57 frames each.
- **"crosses the 0/360 seam" and "outside the global slice" have NEVER appeared** in
  `publish.log` (grep count 0 over all 145 cycles).
- Every traceback/warning in `publish.log` predates **2026-08-19**: historic 429s,
  one `ConnectTimeout`, one Faro-coast-buoy `ReadTimeout` (08-18), and one
  `TypeError: NoneType - float` from **2026-07-28** (the already-fixed wind-null bug).
  **Nothing has failed since the change landed.**
- Dream backlog still 0 findings / 0 proposals.

## Active Files
- `handoff.md` - rewritten. Its "Next Step" no longer asks for a local smoke.
- `~/.claude/projects/-home-shahar-Projects-rosa/memory/pipeline-change-smoke-rule.md`
  - rewritten (see below). `MEMORY.md` index line updated to match.
- Scratch (not in repo):
  `/tmp/claude-1000/-home-shahar-Projects-rosa/<session>/scratchpad/sweep.py`
  + `ids.txt` + `sweep.json` - the 265-spot CDN sweep, reusable.

## Changes Made This Session
1. **Read the handoff, then checked it rather than relaying it** (global rule 5).
   Confirmed HEAD `cc5331b` and that local `data/out` had no `tail_from`.
2. **Proposed the local smoke - user pushed back: it eats the data.** Correct. The
   Oracle VM already runs `run --all` 4x/day. A local run duplicates it for ~2,038
   quota units and risks 429-ing the shared workstation IP into the next real cycle.
3. **Verified from the published CDN instead.** Wrote a 16-thread sweep over all 265
   payloads at `https://rosa-data-opal.vercel.app/data/spots/{id}.json`.
4. **Date-stamped every `publish.log` warning against its cycle** with an awk pass,
   rather than reporting a raw grep count. This turned "29 warnings" into "29
   warnings, newest 2026-08-18, none since the change" - the opposite conclusion.
5. **Rewrote the smoke-rule memory.** It used to mandate a local `run --all` before
   push; it now says: push, wait for a cycle, verify free from the CDN. The old rule
   is what manufactured this session's blocker and burned a run last session.
6. Stripped em-dashes from `handoff.md` (standing preference).

## Failed Attempts
- **First CDN URL was wrong** - `/spots/{id}.json` 404s. The real path is
  `/data/spots/{id}.json` (and `/data/index.json`). Confirmed in `web/src/api.ts:10`.
- **I first reported `tail_from` as MISSING and called it a real bug.** Wrong: I
  looked for it per-hour. **`tail_from` is a single TOP-LEVEL payload key**
  (`publish.py:449`), which was the deliberate design choice recorded in the last
  handoff. Check `d['tail_from']`, never `d['hours'][0]['tail_from']`.
- **`source .../activate` does nothing for me** - every Bash call is a fresh shell,
  so env never persists. Use `pipeline/.venv/bin/python` by absolute path.
- Carried, still true: **never run `run --all` locally to "smoke" a change**, and
  never `--ignore-quota`.
- Carried, still true: `npm run deploy` in `web/`; bare `npx vercel deploy --prod` fails.
- Carried, still true: the antimeridian guard in `slice_basin_field` tests the
  PUBLISHED geometry, not the source frame. Do not "simplify" it back.
- Carried, still true: `load_spots` returns a dict - use `.values()`.
- Carried, still true: Dream ledger is at
  `assignments/codebase-reviewer/reports/.state/rosa.applied`.
- Carried, watch for it: a stray 0-byte `/home/shahar/package.json` breaks
  `npm run deploy`. Reappeared Aug 21. Not seen this session.

## Next Step
Nothing is blocked and nothing is in flight. Pick from the value-ordered list:

1. **Register more buoy networks** before the 2026-09-17 promotion decisions.
   `data/buoys/ndbc.yaml` has 8 stations; NDBC has 908 wave stations. Also CMEMS,
   NOWPHAS, INCOIS. This is the gate on promoting a raw source to primary.
2. **Fetch-plane migration** - `docs/rosa-fetch-plane-plan.md` B1/C3 (OPEN-ITEMS 14).
3. **`d_ref = max(depths_deep_to_shallow)`** (OPEN-ITEMS 15) and **two GEBCO sources
   A/B** (OPEN-ITEMS 17), both at the 2026-09-17 archive-maturity gate.
4. Optional, cheap: render `tail_from` in the UI. Published on all 265, nothing
   renders it today, by choice.

To re-verify the fleet any time, for free:
```
curl -s https://rosa-data-opal.vercel.app/data/index.json
curl -s https://rosa-data-opal.vercel.app/data/spots/<id>.json | python3 -m json.tool
ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 \
  'cd ~/rosa && git log --oneline -1 && tail -40 publish.log'
```
Date-stamp any `publish.log` warning before treating it as new.
