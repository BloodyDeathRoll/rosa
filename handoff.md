# Session Handoff - 2026-11-19

## Goal
Seed leftover spot candidates from earlier gap passes into the Rosa spot DB (playbook: `docs/spot-db-scraping-playbook.md`), two batches, each committed straight to main.

## Current State
- DB is 5062 spots (was 4988). Two commits on main: `a975031b` (+65, 4988 -> 5053) and `1f2c8d2b` (+9, 5053 -> 5062).
- 718/718 tests pass locally. Rosa GitHub checks passed after the repo went public.
- NOT verified live: new spot pages on the CDN after a VM publish cycle (memory rule: verify from CDN after a VM cycle).
- Worktree is clean.

## Active Files
- `data/spots/*.yaml` - new rows in peru, mexico, south-africa-east/west, mozambique, morocco, cantabria, galicia, cadiz, krui, simeulue, nias, taiwan, venezuela, kerala; new `bengkulu.yaml` (indonesia basin).
- `data/spots/derived/` - bathy + tide cut for every new spot.
- `CLAUDE.md`, `docs/SPOT-DB.md`, `pipeline/tests/test_geo_seam.py` - counts updated.
- `pipeline/src/rosa_pipeline/swellmap.py` - region list for bengkulu.
- `tools/spot-seed/emit_spots.py`, `seed.py`, `towns.py` - emit helpers for these batches.
- `docs/spot-db-scraping-playbook.md`, `docs/SESSIONS.md` - batch logs.
- Agent work dirs (untracked scratch): `tools/spot-seed/work/cand-*/`, `cand2-*/` with `final.json`, `dropped.json` (dropped rows keep located pins).

## Changes Made This Session
1. Batch 1: 6 agents (KZN, Cape/Namibia/Mozambique, Morocco, Spain north+Huelva, China, Americas). Kept 65 after coordinator tile review. Dropped `la-curva` (pin in flat water).
2. `achakar` auto-assigned to cadiz by nearest pin; moved to morocco. Huelva spots put in `cadiz` (Atlantic).
3. Mexico timezones: Monuments + 14 earlier Baja/Nayarit rows fixed from the Mexico_City fallback to `America/Mazatlan`/correct zone.
4. `isla-de-santa-marina` ray crossed land; set `shore_normal: 335`.
5. Batch 2: 4 agents (Sumatra+NTT, China/HK/Taiwan, Korea+India, Galapagos/Colombia/Venezuela). Kept 9. Dropped `air-manis` (sheltered, no surf on tile) and `siete-olas` (no source calls it a surf break). Added 2 off-list Kerala Tourism beaches (Black Beach Varkala, Beypore). New region `bengkulu`. `the-slab` ray hit land; set `shore_normal: 275`.
6. GitHub Actions failures diagnosed: Free plan private-repo minutes exhausted (~2,000/30 days; Oct 1,887 min, 1-18 Nov 924). User made rosa public; its checks now run free. Other private repos stay blocked until reset.

## Failed Attempts
- China leads (both batches): no non-competitor second source for any name. Do not retry without a new source type.
- Korea/India list leads: all competitor-only or no source. Gwangalli is a calm bay.
- Galapagos: Tongo Reef has sources but no map feature; candidate pin -0.9055,-89.6293 at 0.55 in `cand2-latam/dropped.json`.
- Still one source short after 2 tries: Cave Rock, Port Edward, Donkin Bay, Lajao, Larache, Plage Blanche, Wreck (Swakopmund).
- GitHub actions timing API returns 0 billable for every run; measure minutes from job start/end instead. Billing endpoint needs `gh auth refresh -s user`.
- Sequential per-job API scan timed out at 15 min; parallelize.

## Next Step
1. After the next VM cycle, fetch a few new spot JSONs from the CDN (e.g. `bengkulu` spot, `the-slab`, `isla-de-santa-marina`) and confirm they publish with waves.
2. Check DB spot `green-point` (south-africa-east): KZN agent says its pin sits on Umzumbe beach; real Green Point is in Clansthal, 47 km NE. Not changed.
3. Remaining never-retried leads: Philippines/Japan/Okinawa 10, Azores/Madeira 7, North Europe 8, Algeria west 2; barely searched countries St Vincent, Cayman, Croatia, Albania, Montenegro, Libya, Syria.
4. Optional: Yeongildae (Pohang) 0.4 and Golden Beach Varkala 0.6 in `cand2-korea-india/dropped.json` need a second source.
