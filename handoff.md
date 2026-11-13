# Session Handoff - 2026-11-13

## Goal
Keep seeding coasts with no or few spots: zero-spot areas from box counts, thin coasts, and densifying famous regions that were thin. DB went 4750 -> 4988 over 4 gap batches, plus 2 pin moves.

## Current State
- All committed and pushed to main from worktree branch `suggested-new-seeding-areas-de40f56e`. Last commit `481c4636`. Only `handoff.md` uncommitted.
- DB = 4988 spots (checked with `rosa_pipeline.spots.load_spots(Path('../data/spots'))`). `pipeline` pytest: 718 passed at 4988.
- `data/spots/derived/bathy/` has 4989 files: the extra one is `bathy_elevations.json`, a cache, not a spot.
- **Not verified on the CDN.** None of the 238 new spots or the new regions (kamchatka, newfoundland, gulf-of-st-lawrence, seychelles, tanzania, bangladesh, poland, lithuania, latvia, christmas-island, primorye, laayoune, orkney-shetland, marquesas, sakhalin, estonia, kaliningrad, falklands) was checked after a VM cycle.
- **Black Sea has no wave data** (OPEN-ITEMS 45): GFS-Wave has no wet nodes there. Existing `harmani` and `aglayankaya` get no forecast. Kilyos is published but probably samples a Sea of Marmara node (not verified). Nothing changed for those spots.
- Web search is capped at 200 per session, shared by all subagents. Batch 4 ran out early, so most of its names came from official pages fetched directly.

## Active Files
- `data/spots/*.yaml`: new region files (list above) and many extended ones.
- `data/spots/derived/bathy/*.json`, `data/spots/derived/tide/*.json`: one each per new spot; rifles and pottuvil-point recut.
- `pipeline/src/rosa_pipeline/swellmap.py`: `BASINS` for the new regions.
- `tools/spot-seed/{seed,emit_spots,towns}.py`: REGIONS bbox, CFG anchor, REGION_PBF for new regions.
- `pipeline/tests/test_geo_seam.py`: spot count 4988 (CLAUDE.md sanctions this edit).
- `CLAUDE.md`, `docs/SPOT-DB.md`: total and per-region counts.
- `docs/spot-db-scraping-playbook.md` §5: per-batch log, including the flagged-pin list.
- `docs/SESSIONS.md`, `docs/OPEN-ITEMS.md` (item 45 Black Sea).
- `tools/spot-seed/work/{gap-*,gap2-*,gap3-*,gap4-*}/` (gitignored): each agent's final.json, dropped.json, build.py, tiles/.
- New OSM extracts in `data/osm/`: seychelles, newfoundland-and-labrador, quebec, comores, mayotte, russia far-east, estonia, kaliningrad.
- Memory: `no-agent-concurrency-cap.md` (user removed the 4-agent cap on 2026-11-12).

## Changes Made This Session
1. **3810f656, 4750 -> 4805:** Gippsland 14, Molokai/Lanai 5, Kochi 4, Kamchatka 1, Chiapas 4, Chile 2, Atlantic Canada 7, East Africa 4, Bangladesh 1, Seychelles 4, Baltic 9. Percé and Shipwreck Beach rays re-aimed off land.
2. **8e695da3, -> 4838:** Wild Coast 6, Western Sahara 2 (region laayoune), Christmas Island 1, Konkan 2, Jalisco/Michoacán 4, Banyak 1, La Union 1, PNG 4, Primorye 3, Sakhalin 3, Orkney/Shetland 6, Marquesas 1. Six rays re-aimed.
3. **bea6e507, -> 4862:** Kaliningrad 4, Gotland 2, North Uist 2, Sicily 3, Plettenberg 2, plus single spots (Bornholm, Lista, Schiermonnikoog, Hiiumaa, Sinclair's Bay, Shenzhen, Hong Kong, Noosa North Shore, Teewah, Kodiak, Assateague).
4. **fa21131c, -> 4988:** Peru 25 (names from Peru's official surf-break registry), Portugal 21, Canaries 16, Mexico 15 (9 Ensenada pins use Baja California state tourism coordinates), Bali 10, Sri Lanka 9, Costa Rica 9, Panama 7, Morocco 4, Durban 3, Falklands 2, others 1 each. 2 Mai (Romania) dropped because the Black Sea has no wave data. Seven rays re-aimed.
5. **481c4636:** moved `rifles` 14 km onto Karangmajat's east reef (Kandui Resort + 3 operators; long right on the tile) and `pottuvil-point` 0.7 km south onto the boulder point. Both checked on z15 tiles; bathy and tide recut.

Decisions:
- Keep bar stays at confidence 0.65. On 2026-11-12 the user said "do all" to a list that included the 0.6 leftovers. I read that as approval for those leftovers only: Maruata, Surf Bay, Bertha's Beach and Palanga went in. Plaja Modern (inside a breakwater pool) and Santa Lucia (its source points elsewhere) were dropped on the tile. That approval does not carry forward.
- Before adding a batch, every spot is checked against the GFS-Wave wet grid using the pipeline's own 0.6° nearest-node rule.

## Failed Attempts
- **Black Sea:** no wave source, so Romania and Georgia stay out (OPEN-ITEMS 45).
- **Emptied by the 0.65 bar (sources were competitor-only or windsurf-only):** Cucao and Pumillahue, Lance Cove and Middle Cove, Bukhta Zhirovaya, Atacama, Tierra del Fuego, Comoros, Mayotte, Rodrigues, Palau, Chathams, Enggano, south Flores, Panaitan, east Samar, Aurora, east Mindanao, Turkey's Aegean coast, west Algeria, north Mozambique, Uruguay, the Antofagasta reefs, Zanzibar, Bazaruto, Cantabria/Galicia/Huelva, and sub-peaks (Fraserburgh, Swakopmund, Kommetjie).
- **Borongan pins** (`sabang-borongan`, `bato-borongan` in gaps-b): dropped on purpose earlier. They are river mouths in a sheltered bay, and `borongan` is already in the DB.
- **Search-cap casualties worth a rerun:** China's Liu'ao bays and Taiji Bay; 19 located Morocco beaches each needing one more source (Sidi Mghait first); Cantabria/Galicia/Huelva; Pipa reefs; Ponta Backdoor (Tofo, pin ready at 0.6); 365s (Kommetjie); Playa Linda in Ixtapa (0.6).

## Next Step
1. After the next VM cycle (Asia/Jerusalem 04:20/10:20/16:20/22:20), check the CDN: sample `rosa.surf/spot/<id>` answers 200 with wave rows for, e.g., `kilcunda`, `melnrage`, `coffee-bay-point`, `zelenogradsk`, `burgerworld`, `surf-bay`, `rifles`.
2. Fix the Black Sea spots (OPEN-ITEMS 45): decide what to do with `harmani` / `aglayankaya`, and verify which node Kilyos samples.
3. Flagged existing pins the tiles didn't settle (listed in playbook §5): `coxos`, `crazy`, `libanona`, `bay-of-plenty` / `north-beach`, `sanur-reef` / `hyatt-reef`, `bank-vaults`, `panic-point`, `santa-maria-del-mar`; two Peniche spots share the name "Praia da Baía".
4. Rerun the search-cap casualties above in a fresh session with a full search budget.
5. Still open from earlier: the NZ council surf-break layer licence (footer credit if CC-BY), Hourtin, Porpoise Bay, and widening the tight seed.py boxes.
