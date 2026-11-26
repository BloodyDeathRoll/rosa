# Session Handoff — 2026-11-26

## Goal
Find new spot-seeding candidates and seed them (operator: "new seeding candidates", then "all", "any other candidates?", "yes").

## Current State
- DB 5062 -> 5226 spots, three commits pushed to main: `20ca3ad0` (batch 3, +61), `a870e386` (batch 4, +39), `e0ed2bbc` (Japan 63 + `ikurahama` restored, +64).
- Every new spot: rendered and judged at z16 (agent + coordinator contact sheet), committed bathy profile + EOT20 tide constants, GFS-Wave wet node within 0.6 deg (checked against live 06Z / 12Z 2026-11-26 files). `uv run pytest -q` 718 passed after each commit; ruff clean.
- 13 new regions: aruba, benin, togo, cameroon, gabon, kosrae, nauru, kiribati, line-islands (Kiritimati, UTC+14), grenada, cayman-islands, san-andres, libya. New basin `line-islands`; the rest joined existing basins (see `pipeline/src/rosa_pipeline/swellmap.py`).
- Two existing pins moved (sat-read): `le-petit-minou` 5 km E onto the Petit Minou cove; `ikumi` 1.8 km SW onto Ikumi surf beach.
- NOT verified live: no `/spot/<id>` page or CDN payload for any new spot has been checked. The data and web prerender go out with the VM cycle after the push (publish.sh 3b redeploys web when the spot list changes).
- Carried from 2026-11-25, still unverified by me: OISST lookback fix (`ad305cbd`) - live `current.sst` / `current.wetsuit` on the CDN.
- EEA bathing match NOT re-run (no EEA workbook on this workstation): new Brittany / Tuscany / Portugal spots have no EEA grade. NSW match was re-run (+66 NSW spots in `data/water/bathing.yaml`).

## Active Files
- `data/spots/*.yaml` - 13 new region files; appended blocks ("candidates batch 3/4") in japan, mexico, victoria, california, etc.
- `data/spots/derived/{bathy,tide}/*.json` - one profile + one tide file per new spot.
- `data/water/bathing.yaml` - NSW re-match.
- `pipeline/src/rosa_pipeline/swellmap.py` - BASINS entries for the new regions.
- `pipeline/tests/test_geo_seam.py` - spot count 5226 (the documented count pin).
- `tools/spot-seed/{seed.py,emit_spots.py,towns.py}` - REGIONS / CFG / REGION_PBF for new regions.
- `CLAUDE.md`, `docs/SPOT-DB.md` - spot count + per-region list (5226).
- `docs/spot-db-scraping-playbook.md` §5 - batch 3 and batch 4 logs, updated gap queue.
- `docs/SESSIONS.md` - two 2026-11-26 entries.
- `tools/spot-seed/work/BRIEF-2026-11-26.md` (gitignored) - subagent brief; agent outputs in `tools/spot-seed/work/c3-*/`, `c4-*/` (worktree-local, gitignored).

## Changes Made This Session
1. Fleet-wide OSM sweep of `sport=surfing` features in all 175 local extracts (528 features, 89 > 3 km from DB) + box counts of zero-spot coasts and thin famous coasts -> candidate list.
2. Batch 3: 7 subagents (web flow, discovery + render + judge only). Coordinator cut at conf >= 0.65, re-read tiles. Dropped Malem (Kosrae) and Playa Azul (GEBCO land to 2 km) again, as on 2026-11-12. Cambodia, Gabon (first pass), St Vincent below cut.
3. Batch 4: second OSM sweep (names containing surf / サーフ / 冲浪, 636 features) + box count of ~60 famous coasts. Found West Victoria had 0 spots west of Apollo Bay; Shizuoka 3, Mie/Wakayama 1, Tottori/Shimane 0. 6 subagents. Crescent Bay (Juan de Fuca) dropped: no GFS-Wave wet node.
4. I treated Tenkura (Japan Weather Association leisure site) as a competitor and held back 63 Japan pins + removed `ikurahama`. Operator overruled ("A weather site IS NOT a competitor") -> all 63 (including the 0.55-0.6 ones, operator said "all") + `ikurahama` restored. `hime` got a hand `shore_normal: 104` (first ray crossed land at 5 km). Memory saved: `weather-sites-not-competitors.md`.
5. GEBCO land to 0.5-1 km then deep water was accepted as the documented shoreline-cell case (listed per spot in the playbook).

## Failed Attempts
- `rosa-pipeline bathy/tide --spot` run from inside `pipeline/` finds no spots ("unknown spot ...; known: "). Run from the repo root with `uv run --project pipeline`.
- `uv` not on PATH: export `PATH=$HOME/.local/bin:$PATH` or the pre-push hook fails with a misleading "pipeline lint failed".
- Worktree lacks `data/osm`, `data/bathy`, `data/tide-src`, `tools/spot-seed/work`: symlinked the first three to `~/Projects/rosa/data/*` (gitignored).
- My first doc-count regex double-added `bengkulu` in `docs/SPOT-DB.md` and grep-counted japan as 168 (actual 170). Verify list sums against `yaml.safe_load` counts, not grep.
- Treating a weather site as a competitor was wrong (see Changes 4).
- Google Places geocoding returned REQUEST_DENIED / HTTP 400 for agents again; pins rest on Nominatim / Photon / local extracts + tiles.

## Next Step
1. After the next VM cycle (check `TZ=Asia/Jerusalem date`; cycles 04:20 / 10:20 / 16:20 / 22:20 local), verify one new spot on the CDN and its page: `curl -s https://rosa-data-opal.vercel.app/data/spots/logans-beach.json | head -c 400` and `curl -sI https://rosa.surf/spot/logans-beach` (expect 200). Also check `current.sst` non-null (OISST fix from 2026-11-25).
2. Re-run the EEA bathing match when the workbook is available: `uv run --project pipeline rosa-pipeline bathing --match eea --xlsx <workbook>`.
3. Remaining gaps (not seeded): Aichi's Atsumi peninsula (Akabane, Irago) - 0 spots; Mauritania, Palau, Yap, Marshalls, Tuvalu, Cambodia, Sulawesi, West Timor had nothing sourceable.
4. Flagged existing pins, not moved (re-ask operator / sat-read first): `libanona` (sits on OSM Plage Ankoba; Plage Libanona 1.3 km E), `charlies-point` (Baler; OSM marker 280 m away at the creek mouth).
