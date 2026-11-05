# Session Handoff — 2026-11-05

## Goal
1. Give the Charts map the same buttons as the Map: share, search and north, plus zoom +/- on desktop.
2. Close the famous-break gaps in the spot DB, before seeding unnamed coastline.

## Current State
- Everything is committed and pushed to main. Last commit: `c045795`. The working tree is clean.
- **Charts buttons:** commit `9162e6a`. Deployed to rosa.surf (Vercel project "rosa"). Not checked by eye on the live site.
- **Spot DB is 4000 spots** (it was 3593). `pipeline` pytest: 718 passed.
- The new spots go live in the next VM cycle (cron 02:20/08:20/14:20/20:20 UTC). **Not yet verified on the CDN** that the new spots publish. The new regions and basins (`southern-italy`, `tyrrhenian`, `malaysia` and others) have never run through `run --all`.
- The famous-break gap queue is closed. The playbook §5 now says so.
- Google geocoding still returns `REQUEST_DENIED` (billing is off on the key). Nominatim and Photon were used instead.

## Active Files
- `web/src/pages/MapPage.tsx`: `MapSearch` was pulled out as a shared search overlay.
- `web/src/pages/ChartsPage.tsx`: uses the Map's fabs and `MapSearch`. Picking a spot zooms to level 6.
- `data/spots/*.yaml`: new regions puerto-rico, nova-scotia, vancouver-island, liguria, tuscany, lazio, sardinia, dakhla, tobago, british-virgin-islands, malaysia, thailand, nsw-mid-north-coast, nsw-south-coast, nsw-central-coast, campania, basilicata, calabria and puglia. Many existing regions also grew.
- `data/spots/derived/bathy/*.json` and the tide files: one per new spot.
- `pipeline/src/rosa_pipeline/swellmap.py`: `BASINS` entries for the new regions. New basins: `tyrrhenian`, `southern-italy`, `malaysia`.
- `tools/spot-seed/{emit_spots,seed,towns}.py`: tables for the new regions (anchor, bbox, region name).
- `pipeline/tests/test_geo_seam.py:154`: the spot count, now 4000. CLAUDE.md sanctions this edit.
- `CLAUDE.md` and `docs/SPOT-DB.md`: spot counts and the per-region list.
- `docs/spot-db-scraping-playbook.md` §5: the session log, and the gap queue marked closed.
- `docs/SESSIONS.md`: entries for 2026-11-04 cont. 1-3.

## Changes Made This Session
1. **`9162e6a` Charts fabs.** On mobile: share, search, north. On desktop: +/- zoom, and share moves to the top bar, as on the Map. Search is the same `MapSearch` component as the Map's.
2. **Famous-break gap analysis.** A hand-written list of about 470 breaks was name-matched against the DB, then the misses were geocoded and measured. That gave two lists: single missing breaks in existing regions, and whole areas with no spots.
3. **`7fe9ed0` (3593 -> 3613).**
   - 9 singles added.
   - 11 operator pins added.
   - `lowers` moved onto the operator's Trestles pin and renamed Lower Trestles.
   - `hash-point` renamed Mysteries (Hash Point).
   - Sacate moved inshore at the operator's request.
   - Las Islitas closed OPEN-ITEMS 18.
4. **`eb54145` (-> 3706).** Big Island 25, Puerto Rico 35, Vancouver Island 13, Nova Scotia 20.
5. **`b56a3a5` (-> 3931).** Italy and Sardinia 49, Australia 136, East London 11, Dakhla 3, Tobago 4, BVI 5, Malaysia 7, Thailand 10.
6. **`c045795` (-> 4000).**
   - NSW Central Coast 25 and southern Italy 41.
   - Operator pins: Blackfellows, Little Kirra, Pigeon Point.
   - Dakhla's country set to "Morocco" (operator decision, 2026-11-05).
   - terrigal-haven re-aimed 20 -> 70 and dudley-beach to 118.
- **Method for every batch:**
  - Background subagents placed and judged the pins in the scratchpad only.
  - The coordinator re-checked every pin on a z16 contact sheet.
  - The coordinator then emitted the YAML, cut bathy and tide per spot, and re-aimed any normal whose ray crossed land.
- Competitor sites were used for break names only, never for coordinates.
- Operator pins are tagged `user-verified` in the YAML comment.

## Failed Attempts
- **`git push` failed** at first: the pre-push hook needs `uv`, and `uv` is not on PATH by default. Fix: `export PATH=$HOME/.local/bin:$PATH`.
- **Google geocoder:** `REQUEST_DENIED`. Do not retry until billing is turned on.
- **Nominatim** returned 429 when several agents ran at once. Photon worked as the fallback.
- **Dropped for having no locatable source**, so not added. Each needs an operator pin:
  - Puerto Rico: Indicators, Dogman's, Little Malibu, Antonio's, Middles, Margara, Aviones, Inches, Table Rock, Bridges.
  - Big Island: Kehena, Miloli'i, Ho'okena, Napo'opo'o, Old Airport, Kings Landing, South Point.
  - Vancouver Island: Lennard Island, Botanical Beach.
  - Nova Scotia: Minutes, Lawrencetown Reef, Backyards, Caldwells Cove.
  - Dakhla: Arish, Pukas.
  - Southern Italy: Tombino (Bari), Pizzo, Capo Miseno.
- **`aim_normal`'s land count is no proof on steep coves.** GEBCO reads the first 0.25-1 km as land on every bearing there. Only `offshore_depth_m <= 0` disqualifies a spot.

## Next Step
1. After the next VM cycle, check from the CDN that the new spots publish. Check one id per new region, e.g. `nsw-central-coast`'s `terrigal-beach`, `capo-suvero` and `domes` (Puerto Rico): fetch `data/spots/<id>.json` from the rosa-data CDN and check `fetched_at`. Also check that the `southern-italy` and `malaysia` swellmap frames exist. Do not run `run --all` locally (memory rule).
2. Next seeding phase: the unnamed-coastline frontier (playbook §5). It needs satellite checks or user-submitted spots. Ask the operator before starting.
3. Optional: give the operator the dropped-names list above, to get pins for them.
