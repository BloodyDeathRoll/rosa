# Rosa Spot-DB Scraping Playbook

**Purpose.** Build Rosa's own exact, worldwide surf-spot database, region by region,
over a long period. This is the moat. It does **not** need to be fast - it needs to be
**exact, and exact about *locations* above names.** A wrong name is a cosmetic fix; a
wrong pin silently poisons every forecast for that spot. Work in chunks; verify everything.

> **Iron rule (from `docs/spot-mapping-approach.md`): from-memory coordinates are fake.**
> Every coordinate that enters the DB must be either coastline-geometry-derived, geocoded
> **and** sat-verified, or user-verified. Never type a lat/lon from knowledge. This session
> proved it twice - a from-memory "Uchiumi" landed on an inland river town; "Monaliza" on
> open water. The geocoder+render caught both.

## Authority ladder (coordinate trust, highest first)
`user-verified` > `sat-verified` (ESRI crosshair, human/vision judged) > `geocoded+rendered`
(multi-provider agreement, then sat-verified) > `osm-name-confirmed` > `coastline-generated`
> `approximation`. Never let a lower tier overwrite a higher one. Tag every spot with its tier.

---

## 0. One-time foundations (download once, never again)
The whole pipeline runs **offline** - no request-time API caps, no Overpass roulette. Both
big datasets are gitignored (`data/bathy/`, `data/osm/`).

- **Local GEBCO grid** - `data/bathy/GEBCO_2024.nc` (~7.5 GB, 15 arc-sec global). Sampled by
  `tools/spot-seed/local_bathy.py`. Replaces the OpenTopoData API (1000 calls/day cap).
  Redownload: the CEDA direct link the GEBCO/BODC portal redirects to (`GEBCO_2024_CF.nc`).
- **Local OSM Geofabrik extracts** - `data/osm/<region>.osm.pbf` per country
  (`download.geofabrik.de/<continent>/<country>-latest.osm.pbf`). Read by
  `tools/spot-seed/osm_local.py` (pyosmium). Replaces Overpass (which 504s under load).
- **Tool venv** - `tools/spot-seed/.venv` (`uv venv` + `uv pip install netCDF4 numpy osmium pyyaml`).
  Run every tool with `tools/spot-seed/.venv/bin/python`.
- Headless render needs `google-chrome` + `node` (already present); tiles via
  `tools/spot-verify/shoot.mjs`.

## Tooling map (`tools/spot-seed/`)
| file | role |
|---|---|
| `seed.py` | **primary pipeline** CLI: coastline → generate → bathy-prune → OSM-validate → tier + review |
| `coast_generate.py` | coastline→candidate geometry (segment, shore-normal, openness) - pure helpers reused by seed |
| `bathy_gate.py` | seabed pruning + `destination()` / `gebco_elevations()` (API path) |
| `local_bathy.py` | local GEBCO sampler (`--bathy local`, default when grid present) |
| `osm_local.py` | local Geofabrik extractor (`--osm local`, default when pbf present); applies `is_business` |
| `osm_seed.py` | `BIZ_NAME_RE` + `is_business()` (tag AND name business filter, multilingual) |
| `render.py` | **sat-verify**: renders ESRI crosshair tiles for candidates → read+judge |
| `multi_geocode.py` | secondary: Google Places + Nominatim + Photon, agreement-spread cross-check. `--file <queue.json>` takes `[[id, query, region], ...]`, `--out <path>` writes the result |
| `emit_spots.py` | turn a region's reviewed `result.json` into DB YAML (offshore_point/swell derived) |
| `work/<region>/` | cached stages: coastline / candidates / bathy / beacons / result.json (resumable) |

---

## 1. PRIMARY FLOW - coastline generation (comprehensive, physics-first)
Generates the candidate-break *universe* from the coast itself, then confirms names via OSM.
Comprehensive by construction; OSM only **confirms/names**, never rejects (its absence ≠ absence).

```
tools/spot-seed/.venv/bin/python tools/spot-seed/seed.py <region> --osm local --bathy local
```
Stages (all cached under `work/<region>/`):
1. **coastline** - `natural=coastline` ways from the local pbf (whole country; scoped to the
   region's surf bbox after generate).
2. **generate** - resample every ~400 m; shore-normal from OSM way direction (water on the
   right) → `offshore_direction` (= inland-pointing normal, the wind-FROM azimuth). **O(n)
   spatial-grid clustering** (an O(n²) all-pairs check chokes on Japan's 106k / Philippines'
   23k coastline ways).
3. **bathy prune** - march a seaward transect on the local GEBCO grid; drop land-on-ray
   (enclosed/inland), mudflat, no-shelf. GEBCO 15" is noisy in the first ~500 m → judge on the
   **1-3 km shelf band**, not near-shore slope. **Recall gate: must keep ~all known spots**
   (validated 40/40 on Israel).
4. **OSM validate** - surf beacons (`sport=surfing` + named `natural=beach`), business-filtered.
   Tier **A** (a surf beacon within ~450 m → confirmed + named), **A-** (named beach), **B**
   (physics-valid, unnamed → sat-verify/community later).
5. **review** - name-aware dedup: `have` (name-match or <400 m), `pin correction` (same name
   **and** <5 km), `new distinct`. Emits `result.json`.

Then **sat-verify** every *new* candidate before adding:
```
tools/spot-seed/.venv/bin/python tools/spot-seed/render.py <region>      # tiles → work/<region>/tiles/
```
Read each PNG; keep only crosshairs on surfable coast (beach/reef/point at the water's edge).
Add with `emit_spots.py` (osm-seeded block, ODbL attribution, `TODO verify`).

## 2. SECONDARY FLOW - web-search discovery (catches famous-but-unmapped)
OSM is sparse where surfers didn't map (Latin America, much of the Philippines). Surf guides
name the real spots. This flow fills that gap.

**Phase 1 - country.** Web-search each country several ways and extract *areas* + spot names:
- `best surf spots and surfing regions in <country> for beginner intermediate advanced`
- `complete surf guide <country>` · `surfing in <country>` · `top surf beaches <country>`

**Cross-reference** the found names against the DB (fuzzy token match, accent-fold, drop
surf/geo stopwords). Matches = validated coverage; misses = gap queue. (This session: Costa
Rica 9/9, Israel 6/6, Sri Lanka 6/6 confirmed complete; gaps found in PT/JP/PH/NI.)

**Phase 2 - area.** For each gap area, search again:
- `best place to surf in <area>, <country>` · `surfing <sub-region>` · `<area> surf spots list`
Extract the specific break names.

**Locate - multi-geocoder + render (the exactness core).**
```
GOOGLE_MAPS_API_KEY=<from .env.local> tools/spot-seed/.venv/bin/python tools/spot-seed/multi_geocode.py
```
- Query **Google Places** (best POI), **Nominatim**, **Photon** (both free/keyless).
- **Agreement spread** is the confidence signal: <1 km = trust; ~2 km = must sat-verify to
  pick; >5 km = one provider is wrong (this session: Uchiumi spread 27 km - Google returned
  Aoshima). Google often returns the *town or resort POI, not the peak* → render to refine.
- **Render + sat-verify EVERY result** (`render.py --file`); correct the pin off the tile or
  drop. Only sat-passed spots get added.

Add via a `websearch-seeded` block (provenance + `TODO verify`).

---

## 3. Quality gates (never skip - this is where "exact" lives)
- **Render before every add.** No coordinate enters the DB unseen on satellite. Non-negotiable.
- **Multi-source or geometry for coords.** Single-source or from-memory = not allowed.
- **Business filter** (`is_business`, tag AND name, multilingual): drops surf schools/shops/
  hostels/kitesurf/dive/`clube`/`lounge`/`centro`/`escola`/… Surf schools mark a break but are
  never a spot *name*. (They can be a weak proximity beacon, but not a name.)
- **Dedup discipline.** Name-token + distance. Hold **sub-spots** (Ahangama Bay ≠ our Kabalana;
  Praia do Baleal beach ≠ Lagide reef) and **spelling variants** (kizakihama ≠ our kisakihama)
  - surfacing them as "new" or "correction" is usually wrong.
- **"Corrections" are guilty until proven.** A flagged pin move is real only if the OSM feature
  is the **same spot** (exact name) AND <5 km AND not a sub-spot/second node on a long beach.
  This session: 0 of ~10 flagged corrections were genuine (Shichirigahama had two OSM nodes and
  our pin sat between them; Weligama→Marriott and Baleal→beach were different spots). **Never
  move a good pin on a weak match.**
- **offshore params, derived not guessed.** `offshore_direction` from coastline geometry (the
  shore normal). The deep-water sample is `offshore_km` (~5 km) along the spot's own seaward
  normal, so it follows the pin - **`offshore_point` is rejected by the loader**, because an
  absolute coordinate went stale the moment a pin moved. Without `offshore_km` a spot falls
  back to a 0.06° **W** push, correct only for a west-facing coast. `swell_window` ≈ seaward
  ± ~65°, or the region anchor's default. All `TODO verify` until calibrated.
- **Provenance tag** on every seeded spot; OSM-derived carries `© OpenStreetMap contributors,
  ODbL`. A DB built by correcting/extending OSM is a Derivative Database → publish ODbL.
  Tags follow the authority ladder and a lower tier NEVER overwrites a higher one:
  `user-verified` > `sat-verified` > OSM > google-geocoded > approximation.
- **Derived data is part of the add, not a follow-up.** Every new spot needs a committed
  bathy profile AND committed EOT20 tide constants (§3b step 4); both are test-enforced,
  one file per spot, no gaps and no orphans.
- **Every new spot needs a `town`** - the nearest OSM `place=city|town|village|hamlet` within
  12 km, which is what makes it findable by the name people actually search ("Puerto
  Escondido" holds three breaks, none of them named that). Test-enforced
  (`test_every_spot_carries_a_town`). It is a search key and a subtitle, never part of `name`.

## 3b. Adding a region that is not in `seed.py` yet

Four things, in this order:

1. **Bbox** - add `"<region>": (S, W, N, E)` to `REGIONS` in `tools/spot-seed/seed.py`,
   scoped to the SURF coast, not the country. A whole-country box explodes the candidate
   count (§6) and drags in coastline nobody surfs.
2. **OSM extract** - `data/osm/<region>.osm.pbf` from
   `download.geofabrik.de/<continent>/<country>-latest.osm.pbf`. Gitignored, one-time.
   Without it `--osm local` silently falls back to Overpass.
3. **Region defaults** - a new `data/spots/<region>.yaml` needs its anchor block: timezone,
   a default `swell_window`, `height_coeff: 1.0`, `ideal` wind/size, and the seaward
   convention for that coast (the YAML loader's default pushes the sample point 0.06 deg
   **W**, which is right only for a west-facing coast - every other coast sets `offshore_km`,
   optionally with `offshore_bearing`, per spot).
   Create the file **before** running `seed.py`: it reads the region's existing spots, and a
   brand-new region simply has none (`spots: []` parses fine and every Tier-A hit comes back
   NEW). Add the region to `emit_spots.py`'s `CFG` too, and to `swellmap.BASINS` - a region
   in no basin has no map layer, and `test_every_spot_region_has_a_basin` fails.
4. **Derived data per new spot** - after `emit_spots.py`:
   `rosa-pipeline bathy --spot <id>` AND `rosa-pipeline tide --spot <id>`. Both are
   enforced by tests (`test_committed_bathy_profiles_match_their_spots`,
   `test_committed_constants_match_the_spot_db`) - a region seeded without the tide step
   fails the suite. Then re-check the three angles with `rosa-pipeline horizon --spot <id>`.

## 4. Chunked, long-running workflow
- Do **one region (or one gap area) at a time**; the `work/<region>/` cache makes every stage
  resumable and re-runnable cheaply (`--fresh <stage>` forces a refetch).
- After each chunk: `uv run --project pipeline python -c "…load_spots…"` to confirm it parses,
  then `cd pipeline && uv run pytest -q`. Commit per region (`data(spots): …`).
- Keep the primary and secondary flows **both** running on a region - they find different
  spots (primary = comprehensive coastline incl. unnamed Tier-B; secondary = famous named).

## 5. Session log & queue (as of 2026-08-27, DB = 601 spots, ALL sat-verified)

**Peru 0 -> 49, Panama 0 -> 23, El Salvador 23 -> 32 (2026-08-27) - the Pacific Latin-America
block.** New `REGIONS` boxes (Peru = the whole Pacific coast, Tumbes to Tacna, it has no other
shore; Panama = both coasts, so every Caribbean spot must override the Pacific-facing default),
`peru.yaml` / `panama.yaml` anchors, a `peru` swellmap basin, Panama joined the existing
`central-america` frame, Geofabrik `peru` 256 MB + `panama` 36 MB. El Salvador was NOT a fresh
seed: it already had 23 spots, so it ran as a gap-finding pass over 12 atlas names.
- **Primary:** Peru -> **9 OSM surf beacons** (Punta Roquitas, La Pampilla, Playa Redondo,
  La Herradura, El Silencio, Caballeros, Playa Blanca, El Huaico, Huancarute); Panama -> **1**
  ("Surf Dojo", a surf camp `is_business` missed); El Salvador -> **0** new.
- **Secondary:** 58 + 36 + 12 names rendered at z16 and judged one tile at a time. Peru 35 keep
  / 7 move / 16 drop; Panama 21 / 2 / 13; El Salvador 7 / 2 / 3. Every moved pin was
  re-rendered and read again before it entered.
- **What this pass taught:** (1) The coordinate-collapse lesson from Morocco repeated harder:
  Google put **Dumpers, Playa Larga and Paunch on one pin**, Venao and Madrono on another,
  Las Tunas and Torola on a third, and Colan and Cabo Verde both on Paita's port. Collapsed
  pairs are now a routine drop, not an investigation.
  (2) **Two Tier-A beacons lost to a web name on purpose** - `huancarute` (55 m from
  Huanchaco) and `huaico` (56 m from Santa Maria del Mar). When an OSM beacon and a web name
  are the same break, keep the name a surfer would search. `ca_final.py` now reads the skip
  list from `work/<region>/skip.json` instead of the hardcoded California dict.
  (3) **A rename must move the id too** - `ca_final.py` re-slugs from the rename now, so
  "Santa Catalina" no longer ships as `punta-roca-santa-catalina`.
  (4) **A hand town override now outranks OSM**, not just fills a null: OSM's nearest place
  node was a hamlet named after the break (`Playa San Marcelino`, `Las Escobas del Venado`),
  a typo (`Puerto Fiiel`) or a neighbouring beach 11 times in 81 spots.
  (5) Five Peruvian shore normals (`waikiki`, `makaha`, `barranquito`, `puerto-fiel`,
  `puerto-huarmey`) came back with a dry deep end. Instead of eyeballing the tile, this pass
  **swept bearings against the local GEBCO grid** and took the mid-bearing of the widest
  unobstructed arc - faster and reproducible. Lima's Costa Verde is the failure mode: a
  seawall coast where the nearest coastline candidate faces the wrong way.
  (6) The pipeline entry point is **`rosa-pipeline`**, not `rosa`; `uv run --project pipeline
  rosa bathy` fails with "Failed to spawn" and the loop silently writes nothing.

**Morocco 0 -> 42 and Angola 0 -> 9 (2026-08-27) - the first African regions.** New `REGIONS`
boxes (Morocco = the Atlantic coast only, Cap Spartel to Dakhla; the Mediterranean side is
barely surfed and would drag in 400 km of flat coastline. Angola = the whole coast incl. the
Cabinda exclave), `morocco.yaml` / `angola.yaml` anchors, own basins, Geofabrik `morocco`
243 MB + `angola` 85 MB.
- **Primary:** Morocco 607 coastline ways -> 4,616 candidates -> 3,911 bathy-passed -> **9 OSM
  surf beacons** (Anchor Point, Imsouane Bay, Cathedral, Tafedna, Skhirat, Oued Cherrat,
  Dahomey, Plage des Nations, 3eme piscine) + 169 named beaches. Angola -> 2,933 bathy-passed
  -> **1 beacon** (Praia dos Surfistas = Cabo Ledo). Both are web-search country.
- **Secondary:** 51 + 19 atlas names -> `ca_queue.py` -> `multi_geocode.py` -> `ca_xref.py`
  (9 + 1 OSM-confirmed) -> z16 render of all 43 + 17 -> judge. Morocco 16 keep / 16 move /
  11 drop; Angola 5 keep / 3 move / 9 drop. Every moved pin was re-rendered and read again.
  A requery round fixed **Temara** (first pin was the Rabat kasbah), **Tifnit** (an inland
  village of the same name), **Baia Azul** and **Barra do Kwanza**; Dakhla, Tan-Tan Plage,
  Praia das Namoradas and Praia Amelia geocoded wrong twice and were dropped.
- **What this pass taught:** (1) **Nominatim returns nothing for surf-vocabulary queries** -
  it is in `PROV` but contributed 1 result in 61; Google+Photon is the real pair, and
  "single provider - render decides" is the normal case outside Europe/US, not an alarm.
  (2) Google collapses several names onto one place: Safi Garden / Ras Lafaa / Souiria Kdima
  all returned Safi's Sidi Bouzid beach, Cabo Ledo / Miradouro one pin, Shipwreck /
  Praia das Palmeirinhas another. **Dedup by coordinate before rendering, not only by name.**
  (3) Angola's guides name 15 spots and only 9 survive imagery - Luanda's Chicala, the
  Mussulo lagoon shore and the Lobito restinga are all inside sheltered bays with no break.
  (4) Five Moroccan shore normals (`cro-cro`, `devil-s-rock`, `oualidia`, `oudayas`, `tifnit`)
  came back blocked by land and were re-aimed by hand off the tile - the same
  point/harbour/river-mouth failure California saw.
  (5) `tools/spot-seed/.venv` had a dead base interpreter (a rotated snap path); rebuild with
  `uv venv --python 3.12` + the four deps rather than debugging the symlink.
  (6) **Run `bathy` from the repo root**, or `--out` defaults cwd-relative and 50 profiles
  land in `pipeline/data/spots/derived/bathy` where no test looks.

**Oregon 0 -> 37 and Washington 0 -> 22, the same evening, same recipe** (new `REGIONS`
boxes, `oregon.yaml` / `washington.yaml` anchors, one shared `pacific-northwest` swellmap basin,
Geofabrik `oregon` 253 MB + `washington` 362 MB). The primary flow found **0 and 1** OSM surf
features respectively (Twin River, on the Strait) - the Pacific Northwest is web-search country
outright. Secondary: 50 + 32 atlas names -> geocode -> `ca_xref.py` (8 + 1 OSM-confirmed) ->
z16 render of all 83 -> judge (Oregon 18 keep / 14 move / 12 drop / 6 requery; Washington
14 / 7 / 9 / 3), moves re-rendered, 3 nudged a third time, 5 a fourth. Requeries fixed 6 of 9
(Nelscott, Peter Iredale, Cape Kiwanda, Umpqua South Jetty, The Cove at Westport, Cape
Lookout); Gold Beach, Grayland and Salt Creek geocoded wrong twice and were dropped. 4 more
shore normals re-aimed by hand after `test_committed_profiles_reach_open_water` (Bandon, Seal
Rock, Shi Shi, Waikiki Beach). New: `emit_region.py` (the generalised emitter; `ca_*.py` now
take a region argument), and **the Washington bbox was widened to -123.4 mid-pass** because
Crescent Bay / Salt Creek on the Strait of Juan de Fuca fell outside the first box - a bbox is
a surf-coast judgement and the geocodes are the check on it. **Spot ids are global**: the
first Oregon build died on `rockaway-beach` (Pacifica has one) - `load_spots` raises, and the
fix is a `-or` / `-wa` suffix on the newcomer. Next on this coast: British Columbia (Tofino)
is a different country and pbf; Alaska is not surfed enough to seed.

## 5b. California (as of 2026-08-26 afternoon, DB = 412 spots, ALL sat-verified)

**California, 2 -> 149 in one pass (2026-08-26) - the first region seeded after the fetch-plane
flip removed the per-spot quota ceiling.** Both flows, in the order the playbook prescribes:
- **Primary** (`seed.py california --osm local --bathy local`, new `REGIONS` bbox = the whole
  Pacific coast incl. the Channel Islands; Geofabrik `california-latest` 1.3 GB): 3,606 coastline
  ways -> 5,970 candidates -> 4,275 bathy-passed -> **only 17 OSM surf features in the whole
  state**, 11 Tier-A (Santa Cruz east side, Ventura, San Clemente), 394 named beaches. California
  is web-search country like Latin America, despite being the most-surfed coast on Earth.
- **Secondary**: surf-atlas county pages -> 182 names -> `ca_queue.py` (fuzzy cross-ref) ->
  `multi_geocode.py` 177 queries -> `ca_xref.py` (OSM beach/beacon within 1.5 km of any
  provider confirms 48; 4 geocodes landed outside the state - New Jersey, Massachusetts, Bali,
  Baja) -> **z16 render of all 173** -> judge. First pass: 80 keep, 47 move, 22 requery, 21 drop,
  3 wide (z13). Every moved pin was re-rendered; 15 needed a THIRD render; one (Venice Pier) a
  fourth. 22 refined queries fixed 10 (Rincon Point, Seaside Reef, Blackies, Cottons, Oceanside
  Harbor, Ventura Harbor, Surf Beach, Arena Cove, Whaler Island, Sandspit) and left 12 at the
  same wrong place - those were dropped, not nudged. Net **138 web + 9 OSM = 147 added**, 33
  dropped (generic town names, duplicates within 400 m, geocodes that would not land on the
  coast after two tries: Hospitals, Horseshoe, Kelly Avenue, Gaviota, Andrew Molera,
  Patricks Point, Magnolia St, Princeton Jetty). Judge log: `work/california/judge.json`;
  helpers `ca_queue.py`, `ca_xref.py`, `ca_final.py` beside `seed.py`.
- **What this pass taught:** (1) Google geocodes street-named breaks ("28th St", "Newland St",
  "Magnolia St") to the STREET inland, every time - render decides, and a second query with the
  beach name rarely helps. (2) OSM's 9 surf beacons were on the break 9/9; the 48 OSM-confirmed
  geocodes were 46/48. (3) A pin in the surf zone 50-100 m off the sand is fine - the sample
  point is 5 km seaward and the ray marches from the pin - so "move" only when the pin is on
  land or the wrong feature. (4) `offshore_direction` came from the nearest coastline candidate
  (`ca_final.py`, all within 730 m); harbours and points can hand a spot the inner shore's normal
  - `test_committed_profiles_reach_open_water` and `horizon` are the check. (5) `towns.py` misses
  a town for ~4% (6/147) - `town_overrides.json` grew by six. (6) The tile shooter needs node >= 22
  (`WebSocket` global); use nvm's v24, system node 18 dies with `ReferenceError`.
- Not seeded yet on the US west coast: **Oregon and Washington** (Geofabrik `oregon`,
  `washington`; new REGIONS boxes + `oregon.yaml` / `washington.yaml` anchors + basins).

## 5a. Earlier log (as of 2026-08-16, DB = 265 spots, ALL sat-verified)
**Seeded (generation + web-search):** Sri Lanka 16→32, Portugal 16→42, Japan 17→24,
Philippines 12→16, Nicaragua +1, **Mexico 0→43 and El Salvador 0→23 (2026-08-15/16)**.
**Curated already-complete:** Costa Rica, Israel.

**Mexico + El Salvador, what the two flows actually delivered.** The primary flow found almost
nothing: El Salvador's whole coast has **1** OSM surf beacon (El Zonte) and Mexico's Pacific has
**4** (Rosarito, Zippers, The Rock, San Agustinillo) against 18,386 bathy-passed candidates. Latin
America is web-search country, exactly as §2 says. But OSM was still the best *second source* -
scanning the `.osm.pbf` for `natural=beach|cape` and `place=village|hamlet` names near each
geocode confirmed 34 of 42 Mexican and 15 of 21 Salvadoran candidates within 1 km, and corrected
two that Google had put in the wrong place (Atami's geocode was 800 m inland at the resort's
street address; Punta Mango's was 450 m from the OSM cape). **Run that scan before rendering** -
it costs one pbf pass and turns single-source geocodes into two-source ones.

**Round two (2026-08-16), after the user spotted a gap the first pass could not have shown.**
The complaint was that Puerto Escondido was missing; it was not - it was in the DB three times
over as `zicatela`, `la-punta` and `carrizalillo`, and **search matched only the break name**,
so the town that half the world knows the wave by returned nothing. That is a DB-shape bug, not
a coverage bug, and the fix was a `town` field on every spot in every region (§3 and SPOT-DB.md).
The same pass re-searched both countries for genuinely absent majors and added eight:
`killers` (Isla Todos Santos - placed at the island's NW point, which the first pass could not
settle), `punta-baja`, `baja-malibu`, `caleta-de-campos`, `punta-chivo`, `km-61` (a real break
500 m from K59, dropped in round one only because Google had geocoded it onto El Zonte),
`el-majahual` and `playa-san-diego`. Two more were rejected again: `cuatro-casas` (Google
returns a point 100 km from where the guides put it, on two different queries) and
`punta-perfecta` (imagery shows no break). **`zicatela` is now displayed "Puerto Escondido"** -
the one case where the town IS the wave's common name.

**Dropped rather than shipped** (the render is what decided each): `atami`'s Google pin (inland,
replaced by the OSM one, kept), `km-61` (Google returned El Zonte - a duplicate, no second
source), `the-rock` (a real break but 250 m from `zippers`, same bathy, a sub-spot),
`todos-santos-island` / Killers (the island is unmistakable but the break is offshore of its NW
tip and two passes could not place it), `punta-baja` (Google returned the town of El Rosario,
10 km inland), `matanchen` (pin verified, but no ray out of the bay reaches open water - see
OPEN-ITEMS 18).

**Two pins were still wrong after the first render and only the second caught them:** `la-ticla`
sat 300 m inland in the village and `la-punta` 150 m up the beach. Both came from a coordinate
*nudged by eye* off a z16 tile rather than re-rendered. **A nudged coordinate is a new
coordinate: render it again.** The final pass rendered all 58 at z15 and read every one.
**Verification: COMPLETE 2026-08-15** - 199/199 pins checked against imagery (was 80/199 on
2026-08-04); `queue.py --status` reads 0 outstanding. Israel and Portugal are 100%;
`ollies-point` and `witchs-rock`, which two satellite passes could not settle, were closed by
operator-supplied coordinates and are tagged `user-verified`.

**What that sweep proved about SOURCING - use it when seeding the next region:**
- **`approx` pins were wrong almost every time** - offshore by 0.3 to 6 km, or inland in the
  village. Pottuvil Point was pinned in a lagoon; Playa Bejuco 6 km out to sea. Treat an
  `approx` seed as a placeholder that has not yet been located, never as a coordinate.
- **OSM surf markers were right almost every time.** Israel's and the Sri Lanka south
  coast's OSM-sourced pins came back near-100% keep. Prefer the primary (coastline+OSM)
  flow; it is not just more comprehensive, it is more accurate.
- **A single-source geocode must never be adopted.** Four were rejected this sweep; one was
  45 km off (Coxos), one landed inland (Okanda). Two providers agreeing under ~1 km, THEN a
  z16 render, is the bar. A single provider is at best a candidate to confirm off imagery.
- **Moving a pin to the waterline improves the physics**, because GEBCO can then sample the
  real nearshore: shallowest wet depth went 21→2 m at Playa Maderas, 15→4 m at Tangalle.
  The `land_samples` warning that follows is usually just GEBCO's ~450 m beach cell, which
  the march drops - judge on shallowest WET depth (JUDGING.md), not the warning.
- **Two of `bathy`'s four warnings are geometry, not errors** (added 2026-08-15):
  `N sample(s) deeper than the one before` and `deepest wet sample is not the 18 km reference`
  describe the seabed, not a mistake you made - 87/199 committed rays trip the first and
  17/199 the second, on shelves, banks and canyons. Do NOT chase them by re-aiming a
  shore normal; the march skips such samples itself. They are worth reading only as a
  hint that the ray crosses complicated ground. `land_samples` and `missing_samples` are
  the two that actually mean "check something".
- **A moved pin invalidates its angles.** Two spots this sweep aimed their depth ray and
  their sample point at different seas after moving (tangalle 51 deg apart, miura marched 5
  samples up a headland); `test_seaward_directions_agree_with_each_other` caught both. Always
  re-run `horizon` and re-check `shore_normal`/`offshore_bearing` after a move.

**Next gap queue:** the six drops above (Killers, Punta Baja, La Saladita's neighbours, Matanchén
once bathymetry allows); Mexico detail - the East Cape between Shipwrecks and Nine Palms, the
Punta Mita sub-breaks, Oaxaca's Salina Cruz points beyond Conejo/Chipehua; Japan Hokkaido /
Okinawa / Wakayama detail; Philippines more (Daku, Zambales Liwliwa neighbours); Portugal
Ericeira micro-spots & the **Azores**; Nicaragua north (Puerto Sandino cluster). Regions with
zero spots today: everywhere else - Indonesia, Australia, Chile, Ecuador, France/Spain,
South Africa.
**The real frontier = Tier-B.** Tens of thousands of physics-valid, *unnamed* coastline
stretches (Japan 22k, Philippines 37k). OSM/guides never named them; this is the sat-verify +
community-contribution layer, and it's where "all the spots" ultimately lives.

## 6. Common failure modes (seen this session - don't repeat)
- from-memory coords → inland/offshore (Uchiumi, Monaliza). Always geocode+render.
- business leakage when the extractor skips the tag+name filter (Portugal "G3 Store", "Koala
  Surf School" surfaced as spots until `is_business` was applied in `osm_local.py`).
- name-match over-merge without accent/`Praia`/`Playa` stopwords → garbage 68 km "corrections".
- O(n²) clustering hangs on 100k-way coastlines → use the spatial grid.
- whole-country coastline explodes candidate counts → scope to the surf bbox.
- external API caps/flakiness (Open-Meteo, OpenTopoData, Overpass) → the local grids above.
