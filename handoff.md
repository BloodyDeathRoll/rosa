# Session Handoff — 2026-10-09

## Goal
Long session (2026-10-07 to 10-09): get Rosa off the public Open-Meteo quota without cutting the
16-day horizon or paying, clear the board, seed a big batch of new coasts, SEO, and fix the
"Atsunai favourite missing" report by grouping favourite chips by country.

## Current State
- **Self-hosted Open-Meteo on rosa-arm (82.70.253.255) is live** for weather AND marine
  (`ROSA_WEATHER_URL`, `ROSA_MARINE_URL` in `~/rosa/.env`), image `open-meteo-local:290493f`
  built from open-meteo main (HRRR direction fix #2157). Falls back to the public API on any
  failure; `publish.sh` 4f alerts on fallback, 4g alerts when an official 1.7.0+ release ships.
  Compose file: `deploy/oracle/open-meteo/docker-compose.yml`. Disk 153 GB; rosa-instance terminated.
- **Spot DB 3056**, tests pass. New this session: South Florida, Iceland 11, Normandy 32,
  England South 48, Massachusetts/NH/Maine, US south-east (Florida NE/Panhandle/Gulf, SC, GA,
  Outer Banks +6), Colombia 33, Venezuela 39, Galapagos 5, plus ~75 operator-supplied pins.
  New Caledonia's 23 lagoon candidates: 0 kept. Lampedusa + Pantelleria: no named break, 0.
- **Country chips (`f4db4fe`) - deployed to rosa.surf, NOT yet verified live.** Every
  `data/spots/*.yaml` has `country:`; pipeline publishes `country` in the payload and index;
  the web groups chips by country (regions as sub-headings) and remembers the chip per account.
  At 11:55 Israel on 10-09 the live index (`https://rosa-data-opal.vercel.app/data/index.json`)
  still had no `country` (atsunai generated 02:26Z, before the pull). Until a cycle publishes it,
  the web falls back to region chips.
- **Atsunai cause (verified):** the server D1 row for jp.einh@gmail.com contains `atsunai`; it was
  hidden under a separate "Hokkaido" chip plus a device-wide remembered chip. The per-account
  chip is the fix; not confirmed on the operator's phone.
- **Portuguese names fixed** (ids unchanged): Cantinho da Baía, Praia da Baía, Molhe Leste,
  Praia das Piscinas (nearest OSM locality, no surf source confirms it).
- **SEO (OPEN-ITEMS 35):** push links on `/spot/{id}?ev=`, per-spot 1200x630 share cards built in
  the web build (resvg + Inter, cached in `web/.og-cache`). Search Console waits on the operator's
  HTML verification tag.
- **publish.sh 3b** redeploys the web when the spot list signature changes (sig in
  `~/.rosa-web-spots.sha`). A publish.sh change takes effect one cycle after the pull.
- Rosa mailbox (info@rosa.surf) photo is set and verified.
- HEAD = origin/main = `eff4457`, working tree clean before this file.

## Active Files
- `data/spots/*.yaml` - `country:` on all 127 region files; new regions; portugal names.
- `pipeline/src/rosa_pipeline/{models,spots,publish}.py` - `Spot.country`, payload + index `country`.
- `pipeline/tests/test_spots.py` - `test_every_region_file_declares_its_country`.
- `web/src/components/GroupChips.tsx` - `chipOf()`, per-account `rosa.spotsGroup:<sub>` key.
- `web/src/pages/{SpotsPage,TodayPage}.tsx`, `web/src/styles.css`, `web/src/types.ts` - country chips.
- `web/src/test/group-chips.test.ts` - chip tests.
- `docs/SPOT-GAPS.md` - NEW: names waiting for operator pins + 3 pins to re-check.
- `docs/spot-db-scraping-playbook.md`, `docs/SPOT-DB.md`, `docs/UI.md`, `CLAUDE.md` - counts, notes.
- `deploy/oracle/publish.sh`, `deploy/oracle/open-meteo/`, `deploy/oracle/README.md` - self-host.

## Changes Made This Session
1. Self-hosted Open-Meteo (weather then marine) instead of a smaller horizon or a paid plan -
   operator refused both ("absolutely NOT dropping to 13 days", "Not going for paid either").
   Built our own image because the release lagged the HRRR direction fix.
2. Board: 35 redeploy + SEO, 32 marine in-house, 37b buoy mean-direction pairing, 37a confidence
   ceilings from the blend card, 33a rate-limited relay for push-api writes.
3. Seeding sweep via parallel fork agents on worktree branches, merged one at a time on main.
4. Operator-supplied pins: each rendered and checked; Tiavea Bay moved, Ramsgate -> The Wall.
5. Country chips + per-account chip memory (Atsunai), because regions like Hokkaido were their
   own chip and the chip choice leaked between accounts on one device.
6. `docs/SPOT-GAPS.md` at the operator's request, to work through the missing names later.

## Failed Attempts
- 02:20Z cycle did not run 3b: bash keeps the already-opened publish.sh, so a change lands one
  cycle late. Web was redeployed by hand.
- Web deploy failed `Cannot find package '@resvg/resvg-js'` - fix: `npm ci` in `web/` first.
- First `country:` insertion script assumed a `defaults:` key (costa-rica has none) - insert
  before the first top-level key instead.
- Skull Island coastline normal ran along the reef spit (GEBCO blind) - set by hand.
- Graph lookup of info@rosa.surf by address 404s - use the object id / mail filter.
- A fork agent's image tool returned no picture while it marked pins checked
  (`[media removed: request limit]`); re-checked, coordinator spot-checked 6 pins.
- 4 Gulf of St Malo (Normandy) spots held: EOT20 amplitude sum 6.0-7.6 m exceeds the 6 m cap in
  `test_committed_constants_are_sane`. Their data was in session scratch (gone) - would need a re-cut.

## Next Step
1. Verify country chips live: `curl -s https://rosa-data-opal.vercel.app/data/index.json` and
   check `spots.atsunai.country == "Japan"` (after the 08:20Z or 14:20Z cycle = 11:20/17:20 Israel).
   Then confirm rosa.surf Your spots shows Atsunai under Japan.
2. Waiting on the operator (re-ask, nothing is pre-approved):
   - Search Console HTML tag for the URL-prefix property https://rosa.surf/, then sitemap submit.
   - The 4 held Normandy spots: raise the tide cap to ~8 m or leave them out.
   - Pins for the names in `docs/SPOT-GAPS.md`; re-check Bolt Head, Trayhan's, Maine Beach.
   - iPhone sign-in test (OPEN-ITEMS 30).
3. Later: switch to the official Open-Meteo image when 1.7.0+ ships (4g alert); SWAN re-read due
   2026-10-27.
