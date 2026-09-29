# Session Handoff — 2026-09-29

## Goal
Grow the spot DB: seed Sicily (new region), fill the Philippines and the north of Japan
(incl. a new Hokkaido region), commit + deploy; then sweep the Dream/swarm review backlog.

## Current State
- All seeding work is committed and pushed to main and LIVE on the data CDN
  (`https://rosa-data-opal.vercel.app/data/spots/<id>.json` - note the `/data/` prefix):
  - `5374573` Sicily 42 spots (mondello, fontane-bianche verified 200).
  - `64f0d98` Philippines 16 -> 32, Honshu north of Tokyo +56, new `hokkaido` region 18
    (jacking-horse, oarai, shizunai verified 200 at 16:35Z).
- Other sessions seeded in parallel today (south-west Africa, northern Europe); main is now
  at 2741+ spots. My commit was rebased onto theirs; counts reconciled, 686 tests passed.
- Dream/swarm rosa backlog: 0 open except holds - swan-spread-power-kuik (until the
  2026-10-05 Stage-4 A/B read), verify calm-direction proposal (needs a VM before/after),
  push-api rate limits (blocked: Vercel Hobby). Swarm ROSA-001..004 all fixed.
- `rosa-pipeline horizon` was NOT run on any of today's new spots.

## Active Files
- `data/spots/sicily.yaml` (new), `data/spots/hokkaido.yaml` (new), `data/spots/japan.yaml`,
  `data/spots/philippines.yaml` - the new spots.
- `data/spots/derived/{bathy,tide}/*.json` - one profile + tide file per new spot.
- `tools/spot-seed/seed.py` (sicily, hokkaido boxes), `towns.py` (REGION_PBF), `town_overrides.json`.
- `pipeline/src/rosa_pipeline/swellmap.py` - new `sicily` basin; Hokkaido joined `japan`.
- `pipeline/tests/test_geo_seam.py` - spot-count assertion.
- `CLAUDE.md`, `docs/SPOT-DB.md` (counts + narrative), `docs/spot-db-scraping-playbook.md` §5, `docs/SESSIONS.md`.
- Outside the repo: Dream `reports/.state/rosa.applied` + `playbook.md` (one REJECTED line, one untagged learning).

## Changes Made This Session
1. Sicily: `europe/italy/isole` extract downloaded (size matched Content-Length), symlinked as
   `data/osm/sicily.osm.pbf`. 0 OSM surf nodes -> web flow (wannasurf, surfproject.it,
   mondo.surf): 54 names -> 42 kept, 10 dropped, every pin rendered at z16 and judged.
2. 16 Sicily normals were 60-120 deg off (harbour moles/points); re-aimed to the middle of the
   largest land-free arc with `tools/spot-seed/work/sicily/arc.py` (0.5-5 km ray, 2-deg sweep).
3. Manual publish cycle run on the VM for Sicily (took ~3 h; it made the 08:20Z cron skip on the lock).
4. Two parallel forks: Philippines (+16, 12 dropped) and north Japan (+56 Honshu, +18 Hokkaido,
   9 dropped, 51 pins moved - Google returns town/harbour/car park for Japanese names).
5. Rebased onto parallel sessions' seeding; merged town_overrides as a JSON union (no clashes).
6. /dream-review: whole backlog swept (30 Dream nights, 2 swarm audits). Swarm 09-11 proposal to
   rename `web/.env.production` REJECTED on the operator's call (Vite loads it by name,
   csp.mjs + prerender.mjs read it, values are public) - logged in rosa.applied + playbook.

## Failed Attempts
- `ca_xref.py` snaps an OSM name within 1.5 km of ANY provider: a wrong provider drags the pin
  (Siracusa's Arenella -> Palermo's, 250 km; Marina di Ragusa -> Marina di Acate). Caught on
  render. Not fixed in the tool - distrust `osm:` snaps on rows with spread > 5 km.
- Google gave Terrasini's Cala Rossa for Termini Imerese's Cala Rosa (57 km); Photon was right.
- My first VM poll loop exited early (bad pgrep filter); CDN path is `/data/spots/`, not `/spots/`.
- `towns.py` on the 2.4 GB Japan extract exceeds 10 min foreground - run in background.
- `ca_final.py` title-cases apostrophes (`Stimpy'S`, id `stimpy-s`) - fixed by hand.
- Unplaceable, dropped: Kamikaze (Cefalu), Santa Lucia, Portopalo, Aci Trezza, Lindy's (Baler),
  Tangbo, Guiuan outer reefs, Takasegawa, Esan, Shiranuka.

## Next Step
1. Optional, ask first: re-place the existing `cloud-9` pin (Siargao) - it sits ~250 m off its
   reef in open water. Render it with `tools/spot-seed/render.py --file` and judge.
2. Run `rosa-pipeline horizon --spot <id>` over today's new spots (sicily, hokkaido, new
   japan/philippines ids) - playbook §3b step 4 says to; it was skipped.
3. Consider fixing `ca_xref.py` to ignore the OSM snap when the row's provider spread > 5 km.
4. 2026-10-05: Stage-4 SWAN A/B read, then re-offer swan-spread-power-kuik (Dream 09-26).
