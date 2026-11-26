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
  **CHECK THE FILE SIZE AFTER EVERY DOWNLOAD.** A wrong path does not fail: Geofabrik
  serves a ~9 KB HTML 404 page, `curl -sL -o` saves it happily, and `seed.py` reads it as
  an extract with zero coastline ways - a silent empty region. Britain is the live trap:
  it is `europe/united-kingdom/{england,wales,scotland}`, NOT `europe/great-britain/...`
  (2026-09-03). Any real country extract is tens of MB or more.
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
| `aim_normal.py` | **post-emit gate**: sweeps seaward bearing every 2 deg on the GEBCO grid and scores the 0.25-18 km ray. **Reports only, never edits a YAML.** Run it after every emit - see 3c |
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
3. **Region defaults** - a new `data/spots/<region>.yaml` needs a top-level `country:` (the
   favourites chips group by it - Hokkaido under Japan; test-enforced) and its anchor block: timezone,
   a default `swell_window`, `height_coeff: 1.0`, `ideal` wind/size, and the seaward
   convention for that coast (the YAML loader's default pushes the sample point 0.06 deg
   **W**, which is right only for a west-facing coast - every other coast sets `offshore_km`,
   optionally with `offshore_bearing`, per spot).
   Create the file **before** running `seed.py`: it reads the region's existing spots, and a
   brand-new region simply has none (`spots: []` parses fine and every Tier-A hit comes back
   NEW). Add the region to `emit_spots.py`'s `CFG` too, to `towns.py`'s `REGION_PBF` (else
   it finds no town), and to `swellmap.BASINS` - a region
   in no basin has no map layer, and `test_every_spot_region_has_a_basin` fails.
4. **Derived data per new spot** - after `emit_spots.py`:
   `rosa-pipeline bathy --spot <id>` AND `rosa-pipeline tide --spot <id>`. Both are
   enforced by tests (`test_committed_bathy_profiles_match_their_spots`,
   `test_committed_constants_match_the_spot_db`) - a region seeded without the tide step
   fails the suite. Then re-check the three angles with `rosa-pipeline horizon --spot <id>`.

## 3c. Check the shore normal after every emit (added 2026-09-03)

`seed.py` takes `offshore_direction` from the nearest OSM coastline segment. On a headland, at a
bay mouth, or across a sand spit that normal can point **along** the shore or **into land**, and
`bathy` will then happily cut its profile over dry ground. Nothing fails; you get a committed
profile whose depths are negative, which is a land elevation wearing a depth's name.

Run after `emit_region.py` and the bathy cut:

```
tools/spot-seed/.venv/bin/python tools/spot-seed/aim_normal.py --yaml data/spots/<region>.yaml
python3 -c "..."   # or read land_samples / offshore_depth_m straight off the profiles
```

**The only disqualifying signals are `offshore_depth_m <= 0` and land samples past 0.25 km.** One
land sample at 0.25 km is just the shoreline cell: GEBCO's ~450 m cell straddles the beach and
reports the land side. 104 of 1299 committed profiles have 3+ land samples and every one of them
still reaches real water, so a land count on its own proves nothing.

Two rules learned the hard way on East Africa:

1. **Do not take the sweep's global argmax.** Along-shore rays are usually land-free and often
   score best, so the argmax will quietly aim a spot down the coast. Read the full bearing table,
   find the arc that is open water, and pick the middle of it.
2. **A broken normal is often a broken pin.** Praia da Barra's ray crossed the Barra spit because
   the pin was on the sheltered north-facing bay beach, not the ocean side. Re-aiming would have
   produced a plausible profile for the wrong water. Render before you re-aim.

Since 2026-09-11 `aim_normal.py` and `rosa-pipeline bathy` both read GEBCO_2024 from disk (before
that `bathy` read gebco2020 via OpenTopoData and the two disagreed by a cell at the shoreline).
The sweep samples bearings and the profile samples the ray the physics marches, so still **judge
the fix on the committed profile, not on the sweep**.

- **New spots' pages.** `rosa.surf/spot/<id>` is a prerendered web page, not data. Since
  2026-10-08 the VM redeploys the web app in the cycle that first publishes a changed spot list
  (`publish.sh` 3b), so nothing to do by hand - but a seed is done only when one new `/spot/<id>`
  answers 200 after that cycle (South Florida sat at 404 for a day before 3b; OPEN-ITEMS 35e).

## 4. Chunked, long-running workflow
- Do **one region (or one gap area) at a time**; the `work/<region>/` cache makes every stage
  resumable and re-runnable cheaply (`--fresh <stage>` forces a refetch).
- After each chunk: `uv run --project pipeline python -c "…load_spots…"` to confirm it parses,
  then `cd pipeline && uv run pytest -q`. Commit per region (`data(spots): …`).
- Keep the primary and secondary flows **both** running on a region - they find different
  spots (primary = comprehensive coastline incl. unnamed Tier-B; secondary = famous named).

## 5. Session log & queue (as of 2026-11-26, DB = 5226 spots, ALL sat-verified)

**Famous-break gap pass, 3593 -> 3602 (2026-11-04).** A hand-written list of ~470 well-known breaks
was matched against every DB name (accent-folded tokens), every miss geocoded with Nominatim and
measured to the nearest committed spot (Google still `REQUEST_DENIED`). ~75 misses were the same
break under another name (Hossegor = La Nord/La Sud, Byron Bay = The Pass/Clarkes, Noosa = First
Point, Lower Trestles = `lowers`). Singles in existing regions were placed off a pyosmium name search
of the local extract plus a z14 read and confirmed at z16: **Santa Rosalillita, Stoners Point,
Chacala (mexico), Johanna (victoria), Dungeons (south-africa-west - the breaking ring is on the
tile), Telescopes (mentawai, NW Sipora, the long left up the reef), Mandiri (krui), Habushiura
(japan, Niijima), Salani (samoa, the right on the E side of the pass).** Santa Rosalillita carries a
hand `shore_normal` 180 (its wind normal crosses the bay; 150-210 all reach open water).
- **Then 11 operator-supplied pins, 3602 -> 3613** (user-verified, each rendered at z16): Cottons
  (San Clemente), Gaviota Pier, and Hollister Ranch's Agua Caliente, Alegria, Sacate (lat sent as
  4.464542, read as 34.464542; then moved 0.65 km N from the kelp onto the surf line at the operator's request), Drakes and San Augustine;
  Las Islitas (Matanchen Bay - the pin on the SW point reaches open water at 204 deg, closing
  OPEN-ITEMS 18) and Punta Blanca (Seven Sisters, id `seven-sisters` - `punta-blanca` is the
  Canaries spot); Honky's (S tip of Thanburudhoo, 175 m from `sultans`, kept on the operator's call);
  Safi. Moved: `lowers` 0.5 km SE onto the operator's Trestles pin (renamed Lower Trestles),
  `hash-point` 0.4 km W (renamed Mysteries (Hash Point)).
- Surf-guide coordinates (mondo.surf, surf-forecast) appeared in search results; they are
  competitor spot data and were NOT used - pins come from OSM names and the tile.

**Big Island 25, Puerto Rico 35, Vancouver Island 13, Nova Scotia 20, 3613 -> 3706 (2026-11-04).**
Three parallel subagents (discovery + render + judge only, no repo edits) wrote final JSONs; the
coordinator re-rendered all 93 pins on contact sheets, emitted the YAML, cut bathy + tide and
re-aimed two Puerto Rico normals (Gas Chambers 226, El Cocal 158) inside the eye-read error.
- **Extracts:** `north-america/us/puerto-rico` (the first download hung - check the size against
  the server), `north-america/canada/{british-columbia,nova-scotia}`.
- **Dropped:** PR - Indicators, Dogman's, Little Malibu, Antonio's, Middles, Margara, Aviones,
  Inches, Table Rock, Bridges (no OSM or geocoder hit), The Room and Kokomo (OSM surf nodes on car
  parks), five flat-water names, Sardinera (OSM name in the wrong town). Big Island - Kehena,
  Miloli'i, Ho'okena, Napo'opo'o, Old Airport, Kings Landing, South Point / Green Sand. BC -
  Lennard Island, Botanical Beach, Sombrio Point (one Sombrio kept). NS - Minutes, Lawrencetown
  Reef, Backyards, Caldwells Cove (unlocatable), Silver Sands (folded into Moose), Sandy Cove,
  the Fundy-side names.
- GEBCO reads 2-3 shoreline land samples on every bearing at nine PR spots and Keokea / Hakalau
  (steep volcanic coves); all end in deep water - the documented non-disqualifying case.

**Italy + Sardinia 49, Australia 136, East London 11, Dakhla 3, Tobago 4, Tortola 5, Malaysia 7,
Thailand 10 - 3706 -> 3931 (2026-11-04).** Same three-subagent flow; the coordinator re-rendered
every pin on contact sheets and re-aimed 17 normals off `aim_normal.py` (only where the sweep's
bearing agreed with the tile, or where a pin on a headland's sheltered side - Crescent Head,
Crowdy Head, Bawley Point - had its normal pointed into the bay instead of open sea).
- **Extracts:** `europe/italy/{nord-ovest,centro,sud}` (Sardinia is in `isole`, already local),
  `asia/{malaysia-singapore-brunei,thailand}`; Geofabrik's `morocco` covers Dakhla and
  `central-america` covers Tobago and the BVI. Local stems are symlinks per region.
- **Dropped:** Italy - Capo Marina, Il Trabucco, Artiglieria, Silver Rock, Pipeline (Sardinia),
  Maresciallo (only located by competitor text); none of Campania / Puglia / Calabria judged
  famous enough. Australia - Point Bell, Fowlers Bay, Tractor Beach, Sceale Bay, Anxious Bay,
  Sleaford Bay, Waterloo Bay, Stokes Bay, Couta Rocks, Temma, V-Wall, Racecourse Head, Stockton,
  Wallagoot Gap, Haycock Point, Bannisters Point; Blackfellows and Little Kirra not locatable.
  Dakhla - Arish, Pukas (no hit), Westpoint (= Foum Labouir). Tobago - Pigeon Point. Malaysia -
  Cherating Beach (= the point), Kemasik.
- **Towns set for findability:** East London (OSM now names the city KuGompo), Penong (Cactus,
  Castles, Caves - nearest OSM place is "Kevin"), Elliston / Port Lincoln / Kangaroo Island where
  nothing lies within 12 km.

**NSW Central Coast 25, southern Italy 41, three operator pins, 3931 -> 4000 (2026-11-04, third pass).**
Two subagents, web flow, every pin re-checked by the coordinator on a contact sheet.
- **nsw-central-coast** (new region on `australia-east`): Pearl Beach to Dixon Park. `terrigal-haven`
  re-aimed 20 -> 70 deg (the N ray crossed Wamberal's beach, offshore depth -3 m); `dudley-beach`
  118 deg. Ten beaches keep 1-3 GEBCO land cells at the shoreline with deep water beyond (the
  documented non-disqualifying case).
- **campania** (joins `tyrrhenian`), **basilicata, calabria, puglia** (new `southern-italy` basin):
  the Phlegraean coast, Ischia, Cilento, Calabria's two coasts, the Gulf of Taranto, Salento and the
  Gargano. Dropped: Tombino (Bari - guides give only a 4 km stretch), Pizzo and Capo Miseno (cliff, no
  break locatable), Salerno Santa Teresa (harbour wall), Le Castella / Capo Rizzuto / Ciro (kite and
  windsurf sources only). No surf source names a break at Polignano, Torre Canne, Leuca, Gallipoli or
  Tropea / Capo Vaticano.
- **Operator pins:** Blackfellows (Elliston), Little Kirra (Gold Coast, 0.4 km W of `kirra`), Pigeon
  Point (Tobago). Dakhla's country set to "Morocco" by operator decision.

**Zero-spot areas: Asia 37, France Atlantic 52, Caribbean 48, Mediterranean 63 - 4000 -> 4200 (2026-11-12).**
The 2026-11-04 "closed" queue was closed against a 470-name list; a box count over the DB still found
whole coasts with no spot. Seven subagents (web flow: discovery + render + judge, no repo edits), every
pin re-read by the coordinator on contact sheets. 41 new region files: greece 17, charente-maritime 16, gironde 16, vendee 16, provence 14, guadeloupe 12, vietnam 12, corsica 8, martinique 8, trinidad 8, emilia-romagna 6, languedoc 5, pakistan 5, bahamas 4, jamaica 4, loire-atlantique 4, sabah 4, saint-martin 4, lebanon 3, maharashtra 3, papua 3, saint-barthelemy 3, bermuda 2, malta 2, marche 2, oman 2, turkey-black-sea 2, turkey-med 2, andaman 1, antigua 1, brunei 1, bulgaria 1, curacao 1, egypt 1, iran 1, maluku 1, myanmar 1, savu 1, timor-leste 1, united-arab-emirates 1, us-virgin-islands 1.
- **Coordinator cut, 129 of 329 agent pins dropped.** Kept only confidence >= 0.65 (Mediterranean) or a
  located take-off, and never a break whose ONLY evidence is a competitor listing's name
  (surf-forecast, wannasurf, surf-report). That removed Bangladesh, Tunisia, Abruzzo, Molise, Veneto
  and Romania whole, and Cap Saint-Louis and Dili Rock. The agents had already dropped Kumari
  Point, Tim's Reef and Kelibia as unlocatable without competitor coordinates.
- **Nothing locatable:** West Timor, Sulawesi, Sarawak, Labuan, Kalimantan, Cambodia, Muscat, Grenada,
  Aruba / Bonaire. **Barely searched:** St Lucia, Dominica, St Vincent, Cuba, Haiti, Cayman, Croatia,
  Albania, Montenegro, Libya, Syria, Georgia.
- **`shore_normal` set by hand on 7 sheltered spots** (the bathy ray crossed land over a bay; the beach's
  own `offshore_direction` is kept for wind): nam-o 40, le-phare-la-tranche 255, saint-nicolas-verdon 280,
  soubregeon 320, le-lizay 315, pointe-rouge 280, agios-nikolaos-arkasa 280. Each was picked from the
  middle of the open arc in a 10-deg GEBCO sweep, not the argmax. **Re-cut `tide --spot` after any
  re-aim** - the sample point moves and `test_committed_tide_constants_match_their_spots` fails.
- **Extracts:** `asia/{gcc-states,pakistan,iran,myanmar,bangladesh,vietnam,east-timor}`,
  `europe/france/{pays-de-la-loire,poitou-charentes,languedoc-roussillon,provence-alpes-cote-d-azur,corse}`,
  `europe/italy/nord-est`, `europe/{malta,greece,turkey,bulgaria,romania}`, `asia/lebanon`,
  `africa/{egypt,tunisia}`. `central-america` covers the Lesser Antilles, Jamaica, Trinidad, the Bahamas
  and Curacao. The Andamans are in `india-southern-zone`. **Bermuda has no Geofabrik extract.**
- **Towns are the agents' labels** (the name people search), not `towns.py` output. Google stayed
  `REQUEST_DENIED`; Nominatim returned nothing for whole batches, so many pins rest on Photon or the
  local extract plus the tile.
- New basins: `gulf-of-oman`, `adriatic`, `greece`, `black-sea`, `bermuda`. Lebanon, Alanya and
  Alexandria joined `cyprus`; Provence and Corsica `tyrrhenian`; Languedoc `western-med`; Malta `sicily`.

**Thin-coast pass: Queensland 11, Norway 4, West Africa 12 - 4200 -> 4227 (2026-11-12, cont.).**
Three subagents (same web flow). Queensland north of the Sunshine Coast and west Norway: 22 returned,
15 kept as queensland-central (Double Island Point, Bargara, Agnes Water, the Capricorn Coast),
moreton-bay (Point Lookout, Moreton North Point, Woorim), norway-north (Bleik) and 3 appended to
norway-south (Sele, Stavasanden, Farstadsanden). West Africa: 40 returned, 12 kept (sierra-leone,
ivory-coast, nigeria, sao-tome, congo, 3 appended to ghana). The keep rule was confidence >= 0.65,
so a name from one blog or a competitor listing does not enter; that left Gambia, Togo, Benin,
Cameroon, Gabon, Mauritania and Guinea empty. Hand shore_normal on Kemp Beach (ray hit Great
Keppel), Double Island Point (10 deg: 45 deg put the beach's offshore wind 90 deg off the ray and
failed test_offshore_wind_comes_from_the_land) and Cape Three Points (headland). **New Zealand's
subagent died on a usage limit** after 345 renders with no final list
(tools/spot-seed/work/new-zealand/, chunk*.json) - NZ is still at 17 and is the next pass.

**New Zealand 295, north Brazil + Pacific 18, Caribbean islands 9, Nicaragua + Philippines 9 - 4227 -> 4558 (2026-11-12, cont. 2).**
Five subagents. New Zealand was finished from the dead agent's work: names and points come from the
regional councils' coastal-plan surf break layers (Northland, Auckland, Waikato, Taranaki Schedule 8A,
GWRC Schedule K, Bay of Plenty surf break study) and the NZCPS 2010 Schedule 1 - public government
data, not competitor data; licence not yet checked (NZ government GIS is usually CC-BY, which would
need a credit line). 299 at >= 0.65; the coordinator re-read a random 24 on contact sheets, not all.
About a fifth sit a few hundred metres offshore at the council's mapped reef or point. Ten new regions
(northland, auckland, coromandel, waikato, bay-of-plenty, gisborne, hawkes-bay, taranaki, wellington,
south-island) all in the new-zealand basin. 23 rays crossed land: 4 pins dropped (Whananaki Bar,
Rangaunu Harbour Bar, both Kapiti Island points - no open arc or inside a harbour), 19 re-aimed to the
middle of the widest wet arc (scratchpad arc.py logic: rays wet past the shoreline cell). Pacifico
(Siargao) moved 8 km north onto the OSM surf node at Pacifico village. Farol Velho (Para) dropped:
every ray crosses ~1 km of tidal flat. New basins micronesia (Guam, Pohnpei) and easter-island.

**North America 20, coastline pass 58, gap passes 11, Puraran moved - 4558 -> 4647 (2026-11-12, cont. 3).**
- **Great Lakes: not seedable.** GFS-Wave's global 0p25 grid has 0 wet nodes over the lakes (checked
  on a live 06Z file: 0 of 1566 in a box over Superior to Ontario; a Delmarva box had 12 of 20), so
  a lake spot gets no wave rows. 19 sourced lake pins were dropped. Covering them needs NOAA's
  Great Lakes wave model (GLW), which the pipeline does not read.
- North America kept delmarva 9, gulf-coast 6 (Alabama, Louisiana), alaska 4, haida-gwaii 1.
  New basin gulf-of-alaska (Alaska, Haida Gwaii); Delmarva joins us-east, Gulf Coast gulf-of-mexico.
- **First primary (coastline) pass on web-seeded regions:** seed.py's OSM surf-tag hits gave 1
  candidate, so the agent took one candidate per named OSM beach, screened sheltered coasts by
  bearing, rendered and judged the rest. 58 kept (South Island 24, Charente-Maritime 11, Vietnam
  11, Vendee 9, Gironde 3). About 4,900 UNNAMED coastline candidates were not looked at. OSM
  "Plage centrale d'Hourtin" sits 9 km south of the DB `hourtin` pin - one of them is wrong, unchecked.
- Gap passes: Meatworks (Kaikoura), Blacks Beach (Mahia), Patiti Point and Jack's Point (Timaru),
  Whites Bay, Nine Mile (Greymouth), Pipikaretu, Saltstein; Locso-on, Lalawigan, Llorente (Samar).
  Puraran moved 4 km north onto Majestics (the old pin was a cove south of it).
- Rays re-aimed: Notre-Dame-de-Monts, Canot de Sauvetage. Dropped: Plage des Jacinthes (Re blocks
  every bearing), Purakaunui (pin in the dunes of a sheltered inlet), Sabang and Bato (Borongan:
  river mouths in a sheltered bay).

**Coastline pass Europe + West Africa 43, leftover pass 3 - 4647 -> 4694 (2026-11-12, cont. 4).**
- Same named-OSM-beach method as cont. 3 on loire-atlantique, provence, corsica, languedoc, greece
  (Ionian and western Crete only: 35 of 1155 named candidates rendered), sierra-leone, ivory-coast,
  ghana, senegal. 54 at >= 0.65; the coordinator dropped 9 inside harbours, canals or enclosed bays
  (Vridi, Kpone Paradise, Lakka, Plage de l'Entree, Rayolet, Frejus, La Bocca, Lampes, Stomio) and
  Sandele (GEBCO reads 0 m on every bearing). **The Mediterranean pins were kept for exposure, not
  for surf seen on the tile** - the imagery is mostly flat summer days.
- The senegal seed.py box reaches into The Gambia: its 4 pins became a new `gambia` region (3 after
  Sandele), in the west-africa basin.
- Leftover web pass: Mitchells Bay (Riverton), Moore Park Beach (Bundaberg), Pansukyan (Siargao).
  One source places Curio Bay's surf about 1.5 km SW of the DB `porpoise-bay` pin - unchecked.
- Great Lakes logged as OPEN-ITEMS 44 (operator: skip for now).

**Coastline pass Americas + Asia 56 - 4694 -> 4750 (2026-11-12, cont. 5).**
- Same method on guadeloupe, martinique, jamaica, trinidad, delmarva, gulf-coast, queensland-central,
  moreton-bay, maranhao, para, sabah, pakistan, oman. 64 at >= 0.65 after dropping Maryland Beach
  (densifies Fenwick); the coordinator dropped 6 sheltered (Anse a l'Eau, La Feuillere, Manora,
  Seaview, Kimihang, Merakit) and 2 whose every ray crosses GEBCO land or a 0 m shelf (Ponta d'Areia,
  Cocos Beach). Elliot Heads ray re-aimed. The Oman beach OSM names only in Arabic (shatee Nos) is
  "Nos Beach", id `hasik`, town Hasik ~20 km away.
- **The seed.py boxes of these web-seeded regions are tight around the first pins** and miss open
  coast: Jamaica (east end only), Trinidad (east coast), Delmarva (Assateague), Maranhao (east of
  Sao Luis), Para (Salinopolis only), Pakistan (Pasni to Jiwani), Oman (Masirah to Dhofar),
  queensland-central (K'gari's east beach; the Teewah strip 26.0-26.35 S is in no box), moreton-bay
  (Stradbroke south of 27.5 S). The agent used wider boxes in its own gen.py; seed.py is unchanged.
- No named OSM beach exists on the Louisiana shore, Moreton Island's ocean side, K'gari's 75 Mile
  Beach or the Lencois Maranhenses, so a named-beach pass cannot reach them.

**Gap batch: Gippsland, Molokai/Lanai, Shikoku, Kamchatka, Chiloe, Chiapas, Atlantic Canada, East Africa,
Bangladesh, Seychelles, Baltic - 4750 -> 4805 (2026-11-12, cont. 6).** A box count over known surf coasts found
these with 0-3 spots. Four subagents (web flow, brief `tools/spot-seed/work/BRIEF-2026-11-12b.md`, batches
gap-pacific / gap-americas / gap-indian / gap-europe); 61 returned at >= 0.65, 4 below it (Palanga, Plaja Modern,
2 Mai, Batumi) left out. The coordinator re-read every tile on contact sheets and dropped Anse a Damasse (rocky
cove, no surf) and Anse Leslie (harbour bay beside Cap-aux-Meules).
- Appended: victoria 14 (Gippsland), hawaii 5 (Molokai, Lanai), japan 4 (Kochi), mexico 4 (Chiapas),
  chile-south 2 (Carelmapu, Faro Corona), kenya 2, madagascar 1. New regions: kamchatka, newfoundland,
  gulf-of-st-lawrence (Magdalen Islands + Perce, Perce on America/Toronto), seychelles, tanzania, bangladesh,
  poland, lithuania, latvia. New basins `baltic` and `kamchatka`; Newfoundland and the Gulf join us-east,
  Tanzania and Seychelles east-africa, Bangladesh bay-of-bengal.
- GFS-Wave 0p25 has wet nodes at every new area (live file, 2026-11-12: Polish coast 38/80, Lithuania-Latvia
  22/28, Kamchatka 8/20, Magdalen 20/20, Perce 7/9, Cox's Bazar 10/12, Mahe 9/9, Dar 3/6, Molokai 14/16).
- Hand `shore_normal`: perce 80 (the 120 deg ray crossed Bonaventure Island at 5 km), kaiolohia-shipwreck-beach
  45 (the 25 deg ray ended on Molokai's shore at 18 km, offshore depth 1 m). El Zapotal, Laboni Point and Puerto
  Arista keep one GEBCO land cell at 0.5 km on flat coasts, deep water beyond.
- Nothing sourced (non-competitor): Cucao, Pumillahue, Lance Cove, Middle Cove, Ferryland, Bukhta Zhirovaya,
  Polihua, Papohaku, Kobuleti, Ureki; Romania and Georgia stay empty. The agent's note: DB `libanona`
  (madagascar) may sit on Plage Ankoba, 1.2 km west of OSM's Plage Libanona - unchecked.
- Extracts downloaded: `seychelles-latest`, `newfoundland-and-labrador-latest`, `quebec-latest`. Poland,
  Lithuania, Latvia and Kamchatka pins came from Nominatim; no local extract, so towns.py has no entry for them.

**Gap batch 2: Wild Coast, Laayoune, Konkan, Christmas Island, Jalisco, Banyak, La Union, PNG north, Primorye,
Sakhalin, Orkney + Shetland, Marquesas - 4805 -> 4838 (2026-11-12, cont. 7).** A second box count; four subagents
(gap2-africa / gap2-americas / gap2-sea / gap2-north, same brief). 36 returned at >= 0.65.
- Coordinator drops: Malem (Kosrae - no located take-off, dropped by brazil-pacific before), Sobol Bay (unplaced
  inside the bay, 0.5 km from Patrokl), Playa Azul (Michoacan - every bearing crosses 1-2 km of GEBCO land on the
  Balsas delta, no open arc).
- Appended: south-africa-east 6 (Coffee Bay, Bomvu, Mdumbi, Second Beach, Cintsa East, Morgan Bay), mexico 3
  (Quimixto, Arroyo Seco, El Tecuan), papua-new-guinea 4 (Waromo, Yako, Lido Left, Moem Point), maharashtra 2,
  simeulue 1 (Treasure Island, Banyak), philippines 1 (Bacnotan). New regions laayoune (country Morocco, as Dakhla;
  basin canaries), christmas-island (indonesia), primorye + sakhalin (japan), orkney-shetland (scotland-west),
  marquesas (own basin).
- GFS-Wave wet nodes at every new area (live file): Primorye 1/6, Sakhalin 3/6 + 1/4 + 3/4, Christmas 4/4,
  Marquesas 4/4, Vanimo 2/4, Wewak 1/4, Banyak 4/4, Orkney 6/8, Tarfaya 9/20. Primorye's Ussuri Bay is marginal:
  typhoon and wind swell only.
- Hand `shore_normal`: birsay-bay 300, west-voe-sumburgh 180, flying-fish-cove 0, patrokl 140 (middle of the
  wet arc; the agents' bearings crossed GEBCO land at 1-12 km). Haatuatua keeps GEBCO land to 1 km on every bearing
  (steep volcanic bay, deep water beyond - the documented case).
- Nothing sourced: Enggano, south Flores, Panaitan's breaks (per-break coordinates only on competitor sites), east
  Samar / Aurora / east Mindanao beyond the DB, Atacama, Tierra del Fuego, Comoros, Mayotte, Rodrigues, Palau, the
  Chathams, Bougainville. Falklands (Surf Bay, Bertha's Beach) and Maruata sit at 0.6 in the agents' dropped.json.

**Gap batch 3: old gap-queue names, Kaliningrad, Estonia, Gotland, Uists, Sicily, Plett, China, long beaches,
Kodiak - 4838 -> 4862 (2026-11-12, cont. 8).** Leads taken from the older per-region gap queues below (each name
checked absent from the DB first) plus thin coasts. Five subagents (gap3-nordic / gap3-med / gap3-south /
gap3-china / gap3-beaches). All 24 at >= 0.65 kept after the contact-sheet read.
- Appended: sicily 3 (Capo San Marco, I Faraglioni Aci Trezza, Giardini Naxos), south-africa-west 2 (The Wedge,
  Goukamma River Mouth), denmark 1 (Balka, Bornholm), sweden 2 (Sudersand, Ekeviken, Faro), norway-south 1
  (Bausje), netherlands 1 (Schiermonnikoog, hand shore_normal 320 - the 331 ray met a 0 m Wadden shelf cell at
  2 km), scotland-west 2 (Hosta, Sollas, North Uist), north-scotland 1 (Sinclair's Bay), guangdong 1
  (Yangmeikeng), hong-kong 1 (Tung Wan), sunshine-coast 1 (Noosa North Shore), queensland-central 1 (Freshwater,
  Teewah), alaska 1 (Surfers Beach, Kodiak), delmarva 1 (Assateague State Park - replaces north-america's unemitted
  0.55 row of the same id). New regions estonia and kaliningrad (country Russia), both on the `baltic` basin.
- Nothing sourced: Turkey's Aegean (windsurf/kite only), western Algeria, northern Mozambique, Montevideo /
  Playa Mansa (Rio de la Plata, sheltered), the Antofagasta reefs, Maragogi, Morro dos Conventos, the Lencois
  coast (Barra da Baleia real but unlocatable), De Kelders, Jacobs Bay, Vredenburg, Port Nolloth, Nine Mile Reef,
  Sylt Ellenbogen and Fehmarn (flat-water windsurf), Spot X/Y and Point Perfect, Lampedusa, Pantelleria, Stradbroke
  south, K'gari's 75 Mile Beach. Kamikaze / Santa Lucia (Cefalu) have one source each; Santa Lucia locatable at
  38.0333, 14.0013 if a second turns up. Walker Point (Buffels Bay, named by Wesgro) was not searched.
- The China agent ran out of web-search budget mid-batch: the Liu'ao bays (Fujian) and Taiji Bay (Zhejiang)
  deserve one more pass.

**Gap batch 4: densify famous regions + old gap-queue names - 4862 -> 4988 (2026-11-12, cont. 9).** Twelve
subagents at once (gap4-*), then 7 operator-approved 0.6 leftovers from earlier batches. **The session's 200
web-search cap ran out early in this batch**: most agents sourced names by fetching official pages directly
(tourism boards, municipal pages, Peru's surf-break protection registry, Wikipedia), so yields were lower than the
breaks that exist. 121 agent pins at >= 0.65, all kept after the contact-sheet read; leftovers: Maruata, Surf Bay,
Bertha's Beach, Palanga kept, Plaja Modern dropped (pin inside a closed breakwater pool), Santa Lucia (Cefalu)
dropped (its only source puts the break on the other side of town), 2 Mai dropped (no Black Sea wave node -
OPEN-ITEMS 45).
- Added: peru 25 (names from DICAPI resolutions / the FENTA break inventory; Pico Alto and Kontiki are offshore
  reefs pinned at the registry polygon), portugal 21, canary-islands 16 (Fuerteventura 11, Tenerife 4, La Palma's
  first spot Nogales), mexico 15 (9 on the Rosarito-Ensenada corridor from the Baja California state tourism
  coordinate list), bali 10, sri-lanka 9, costa-rica 9, panama 7, morocco 4, south-africa-east 3 (Durban),
  falklands 2 (new region, own basin), mar-del-plata 1, santa-catarina 1, nicaragua 1, mentawai 1 (Burgerworld),
  lithuania 1 (Palanga).
- Hand `shore_normal` (middle of the wet arc): generoso 340 and rocky-point-corralejo 40 (the N rays hit
  Lanzarote), lobos 305 (the SW ray crossed Fuerteventura), malpaso-chicama 245, playa-caletas 175, tanjung-sari
  125, maruata 190. Maruata, Junquillal and Playa Serena keep GEBCO land to 1 km (coarse shoreline cells, deep
  water beyond).
- Nothing sourced or located: the Fraserburgh / Swakopmund / Kommetjie sub-peaks (forecast mirror sites only),
  Cantabria's La Vaca / El Muro / Cuchia, O Corvo, Huelva, Bubble (= DB el-hierro), Cave Rock (located, not
  sourced), Nungwi / Jambiani's outer reef, Bazaruto, Lajao / Sororoca, San Clemente del Tuyu, most Mentawai names
  (placed only relative to resorts). Retry with a fresh search budget: Sidi Mghait, Punta Tur, Punta Balcones,
  Ponta Backdoor (Tofo, OSM-tagged, 0.6), 365s (Kommetjie), Westbrook and the KZN South Coast.
- Agents flagged existing pins; the coordinator rendered old vs proposed at z15. **Moved:** `rifles` 14 km from
  Masokut's NW tip (a sheltered channel) onto Karangmajat's E reef (Kandui Resort + 3 operators; long right on the
  tile), shore_normal 90; `pottuvil-point` 0.7 km S from Whiskey Point's beach onto the boulder point,
  shore_normal 60 (90-120 ends on a 1 m GEBCO shoal). **Not moved, tile does not settle it:** coxos and crazy
  (Mafra council's Coxos / Cave / Crazy Left coordinates disagree with the DB and with OSM), libanona (OSM's Plage
  Libanona is 350 m from the new plage-monseigneur), bay-of-plenty / north-beach (Durban beachfront order),
  sanur-reef / hyatt-reef, bank-vaults, panic-point (= Pico Point), santa-maria-del-mar (= Playa Santa Rosa).
  la-pastora's tile shows a right point - kept. Two Peniche spots share "Praia da Baia".

**Candidates batch: gap-batch leftovers re-run with a fresh search budget - 4988 -> 5053 (2026-11-19).** The leads
the 2026-11-12 batches dropped for lack of search budget (their build.py files were recovered from the session
transcripts into `tools/spot-seed/work/prior/`). Six subagents (cand-kzn / cand-capes / cand-morocco / cand-spain /
cand-china / cand-americas), brief `tools/spot-seed/work/BRIEF-2026-11-19.md`, 25 WebSearch calls each; they used
77 in total. 66 returned at >= 0.65; the coordinator re-read every tile on contact sheets and dropped `la-curva`
(Negritos - pin in flat water inside the bay).
- Added: peru 29 (Punta Tur and Punta Balcones on the FENTA break inventory, plus 27 more FENTA names where the
  tile shows a break at the official position), south-africa-east 10 (KZN South Coast: Westbrook, Amanzimtoti,
  Warner Beach, Happy Wanderers, Uvongo, Margate, Lucien; Garvies in Durban; Alkantstrand at Richards Bay;
  Sodwana Bay), morocco 9 (Sidi Mghait, Achakar, Haouzia, Cap Sim, Unicorns, Desert Point `desert-point-tiguert`,
  three Mirleft beaches), cantabria 7 (La Vaca, Isla de Santa Marina, Gerra, La Tablia, Galizano, Luana, Orinon),
  galicia 3 (O Portino, Illa Pancha, Mar de Fora), cadiz 2 (Huelva: Mazagon, Punta del Moral - the cadiz region
  now covers the whole Andalusian Atlantic), south-africa-west 2 (365s at Kommetjie, Walker Point at Buffelsbaai),
  mexico 2 (Monuments, Playa Linda at Ixtapa), mozambique 1 (Ponta Backdoor at Tofo, `backdoor-tofo`).
- Region by nearest DB pin, with three overrides: Sodwana Bay (nearest pin is in Mozambique), Illa Pancha
  (nearest is in Asturias; Ribadeo is Galicia), Achakar (nearest is Tarifa).
- Hand `shore_normal`: isla-de-santa-marina 335 (the 285 ray crossed the Santander bay mouth onto land at 5-8 km;
  open arc 300-5). sidi-mghait, marabout-mirleft, tamahroucht, carquin, puerto-caballas keep GEBCO land to 0.5 km
  and wakama to 1 km on the shoreline cells, deep water beyond (the documented case; each bearing sits inside its
  open arc past 1 km). Every new spot has a GFS-Wave wet node within 0.6 deg (live 2026-11-19 file).
- **Mexico timezones:** the web-seeded Baja and Nayarit rows of 2026-11-04 and 2026-11-12 carried no per-spot
  `timezone`, so they fell back to the anchor's America/Mexico_City (2 h off in Baja California). Set:
  America/Tijuana on santa-rosalillita, seven-sisters and the nine Rosarito-Ensenada pins; America/Mazatlan on
  acapulquito, monuments, stoners-point, chacala, las-islitas. Sayulita / El Anclote / La Lancha / Burros carry
  America/Mazatlan but sit in Bahia de Banderas municipality (America/Bahia_Banderas, UTC-6) - not changed.
- Nothing sourced: all of the China leads (Liu'ao bays, Taiji Bay, Yuliao, Qingdao No. 1/3 Beach, Weihai,
  Beihai / Weizhou - one ranking site or an OSM name only; Qingdao papers name Shilaoren, already in the DB),
  Donkin Bay, Wreck and Guns at Swakopmund (Wreck sourced but the Strand Street sewage pipe is not locatable),
  Cave Rock (only competitor sites tie the name to the tidal pool), Vetch's, Port Edward / Southbroom / Shelly
  Beach (one source; Port Edward located at -31.0442, 30.2283), El Muro, Cuchia, Las Quebrantas, O Corvo,
  Punta Umbria, Isla Cristina, Matalascanas, El Portil, Lajao and Sororoca (Lajao now has two name sources but no
  locatable position), La Caleta (Chacala), the Punta de Mita breaks, the Casablanca and Rabat names, Plage Blanche.
- Agents flagged existing pins, not moved: `green-point` (south-africa-east) sits on Umzumbe beach - Green Point
  proper is in Clansthal, 47 km NE.

**Candidates batch 2: second pass on the 2026-10-09 / 2026-10-29 gap queues - 5053 -> 5062 (2026-11-19).** Four
subagents (cand2-sumatra / cand2-china-taiwan / cand2-korea-india / cand2-latam), same brief, 69 WebSearch calls.
Most queue names came from competitor indexes in their first pass (surf-forecast, wannasurf, surfnerd) and still
have no other source, so they stay out.
- Added: krui 2 (Way Jambu; The Slab, hand `shore_normal` 275 - the 330 ray ended on GEBCO land at 12-18 km off
  Pulau Pisang, 275 is wet end to end), simeulue 1 (The Peak, off Nancala), nias 1 (The Machine, Lagundri Bay's
  east reef), new region `bengkulu` 1 (Pantai Panjang; joins the `indonesia` basin, extract symlink
  bengkulu.osm.pbf -> sumatra), taiwan 1 (Double Lions, the Xiao'ao cove north of Wai'ao), venezuela 1 (Puerto
  Cruz, Margarita), kerala 2 (Black Beach at Varkala and Beypore - off-list finds from Kerala Tourism's official
  surf-site list, added by the coordinator after a z16 read).
- Coordinator drops: Air Manis (Padang - sheltered, no surf on the tile), Siete Olas (Tayrona - no source calls it a
  surf break).
- Still out: Simeulue's Dylan's (several reefs off Matanurung, 0.55) and Thailand; Shark Hole; Krui's The Peak;
  Aceh's A-Frame and Calang; all of Sumba's and Rote's queue names (Racetrack = DB `kalala`); West Timor;
  Hainan's Kame Rock / Xintan / Sanya Bay, Pinghai Point, Jieshi Bay, Clubhouse Point, Fung Bay, Hac Sa,
  Gwen's Mouth, Laoshan; Taiwan's Gongs, Mimi's Reef, The Barracks, Green Island, Xiaoyugang; every Korean
  name (Gwangalli is a calm SUP bay); India's Boar Rice, Akkarai, Repos, Bhatkal, Shipwreck (Vizag's wreck is
  92 m from DB `tenneti-park`) and the Vizag points; the Galapagos (Tongo Reef sourced but unplaced, 0.55;
  naval-base access closed since 2023), Colombia (Colpipe sourced but unplaced; El Bolsillo = DB pradomar) and
  Venezuela's other names. Kerala Tourism's list also names Golden Beach (Varkala, 0.6).

**Candidates batch 3: OSM surf tags fleet-wide, zero-spot coasts, thin famous coasts - 5062 -> 5123 (2026-11-26).**
Candidates came from three checks. (1) **A fleet-wide OSM sweep**: every `sport=surfing` node / way in the
175 local extracts (528 features, business-filtered) measured against the DB; 89 sat > 3 km from any spot,
most of them wave pools, schools or windsurf spots. (2) **A box count** over the coasts still at 0 spots.
(3) **Famous coasts with <= 5 spots** (Baja Sur mid-coast, Guerrero, Michoacan, Miyazaki). Seven subagents (c3-osm /
c3-wafrica / c3-micronesia / c3-caribbean / c3-misc / c3-mexico / c3-miyazaki), brief
`tools/spot-seed/work/BRIEF-2026-11-26.md`, web flow, about 25 searches each. The coordinator kept only
conf >= 0.65 (63 of 108), then dropped 2 more and re-read every kept pin on z16 contact sheets.
- Added: japan 11 (Miyazaki: Nagahama, Isegahama, Kanegahama, Ikurahama, Kaguchihama, Hitotsuba, Ibii, Kazeta,
  Umegahama, Kojima, Koigaura - names from a Coast Guard surf-accident report, japan.travel and the prefecture
  pages), mexico 11 (Baja Sur 4: Isla Natividad, Campo Rene, Punta Pequena, Punta Lobos; Guerrero 4:
  Las Escolleras, Pantla, Juluchuca, Punta Maldonado; Michoacan 3: Boca de Apiza, Las Penas, Huahua), from
  the OSM sweep 13 (Sumbawa's Dirty Hippies and Northern Rights at Kertasari; Mitirapa, Tahiti; Pontile di
  Tonfano; Greve Blanche and Trestel, Brittany; Praia de Chaves, Boa Vista; Awaiura, Niijima; Termeil Beach;
  Cordoama; Iroquois Point, Oahu; Punta Sur and Sound Bay, San Andres), Caribbean on existing regions 5
  (cuba 2: Santa Maria del Mar, Playa Verraco; dominica 2: Woodford Hill, Londonderry; saint-lucia 1: Pigeon
  Point), and 12 new regions (San Andres counted once): aruba 5, benin 5, kosrae 2, grenada 2,
  san-andres 2, togo 1, cameroon 1 (Seme Beach), cayman-islands 1, kiribati 1 (Naa, North Tarawa),
  line-islands 1 (Paris, Kiritimati; its own region because Kiritimati is UTC+14), nauru 1, libya 1
  (Janzour).
- Basins: Libya joined `sicily`, Togo / Benin `west-africa`, Cameroon `angola`, Grenada / Aruba / San Andres
  `caribbean-south`, the Caymans `caribbean-north`, Kosrae / Nauru / Kiribati `micronesia`; new basin
  `line-islands`. Every new spot has a GFS-Wave wet node within 0.6 deg (live 2026-11-26 06Z file, 61/61).
- Coordinator drops: Malem (Kosrae) again (the take-off is still not located), Playa Azul again (GEBCO land to
  2 km on the Balsas delta), and everything below 0.65, including Cambodia (one blog, flat tiles), Gabon (Cap
  Lopez and Mayumba at 0.6), Saint Vincent's Blue Lagoon, Kribi, London and Cook Islet (Kiritimati), Laje
  da Jagua, the 0.45-0.6 Baja and Guerrero names (Bahia Asuncion, La Bocana, Punta San Carlos, Barra de Potosi,
  Pie de la Cuesta, Barra Vieja, Playa Ventura, Faro de Bucerias), and ten Miyazaki / Tokushima / Kochi
  pins (Hozai, Ishinami, Tondahama, Akaehama, Uchiumi, Tsukimigaoka, Komatsu, Minorinbayashi, Uchizuma,
  Shimonokae).
- GEBCO land to 0.5 km, deep water beyond (the documented shoreline-cell case): dos-playa, andicuri,
  dunes-beach-aruba, dirty-hippies, seme-beach, punta-lobos, escolleras-ixtapa, pantla, juluchuca, las-penas;
  to 1 km: punta-maldonado, huahua.
- **Two existing pins moved** after a z15-z17 read: `le-petit-minou` 5 km E onto the cove under the Petit Minou
  lighthouse (the old pin was on another beach; OSM `sport=surfing` sits in the cove); `ikumi` 1.8 km SW from
  Shirahama's bay onto Ikumi's open surf beach (OSM). Both normals sit inside the open arc; bathy + tide re-cut.
- `bathing --match nsw` re-run: +66 NSW spots seeded since the first match. The EEA match was not re-run (the
  workbook is not on this workstation), so the new Brittany / Tuscany / Portugal spots have no EEA grade yet.
- Nothing sourced or located: Mauritania, Palau, Yap, the Marshalls, Tuvalu, Bonaire (windsurf only), Sulawesi,
  West Timor, Georgia (skipped: Black Sea, OPEN-ITEMS 45). Leads left: Beran / Ailinglaplap's named reefs
  (Amnesia, The Bowl), Tabuaeran's Cables / Whalers, Eldorado Beach (Cotonou), Oea Village (Tripoli), Shipping
  Bay (St Vincent), Pierce Point (Haiti).

**Candidates batch 4: famous-coast box count + OSM surf names - 5123 -> 5226 (2026-11-26, cont.).** A second
OSM sweep (every non-business feature with "surf" / サーフ / 冲浪 in its name, 636 features) and a box count over
~60 famous surf coasts found West Victoria at 0 spots west of Apollo Bay, Shizuoka 3, Mie / Wakayama 1,
Tottori / Shimane 0, Big Sur 1, Santiago (Cape Verde) 0. Six subagents (c4-australia / c4-japan / c4-namerica /
c4-asia / c4-africa / c4-retry), same brief.
- Added: victoria 16 (Gibson Steps, Port Campbell, Peterborough, Logans Beach, Hopkins River Mouth, Lady Bay,
  Shelly Beach, Levys Beach, East Beach Port Fairy, Narrawong, Blacknose Point, Yellow Rock, Murrells,
  Bridgewater Bay, Shelly Beach Cape Bridgewater, Whites Beach), japan 10 (Ishiwaki, Hawai, Kunizaki, Ago no
  Matsubara, Ichigo, Tatadohama, Iritahama, Kisami Ohama, Fukude, Nakatajima), california 3 (Sand Dollar,
  Andrew Molera, Willow Creek), wa-south 2 (Surfers Cove, Black Point), cape-verde 2 (Tarrafal on Santiago,
  Sandy Beach on Sao Vicente), new region gabon 2 (Cap Lopez, Mayumba; basin `angola`), and singles in
  nsw-south-coast (Surf Beach, Batemans Bay), nova-scotia (Crescent Beach, Lockeport), philippines (German
  Sunset, La Union), kerala (Surf Beach, Paravur) and benin (Eldorado Beach, found in the local extract).
- **Then 63 more Japan spots + `ikurahama` restored (operator, same day): a weather site is not a competitor.**
  The coordinator had held back every Japan pin whose only surf source was Tenkura (the Japan Weather
  Association's leisure-weather site) and removed `ikurahama` on the same rule; the operator overruled it.
  Competitors are surf-forecast / spot-guide products (CLAUDE.md legal red lines), not weather services.
  Added: Shizuoka 21 (Usami, Akazawa, Atagawa, Imaihama, Toji, Yumigahama, Ukishima, Ganyudo, Miho, Hamatoume,
  Katahama, Sagara, Shiroha, Hamaoka, Hamano, Dokasa, Samejima, Komaba, Yonezu, Maisaka, Shirasuka),
  Wakayama 12, Tottori 12, Shimane 16, Mie 2 - all 63, including the 0.55-0.6 pins (operator: "all").
  `hime` carries a hand `shore_normal` 104 (the 132 ray crossed land at 5 km; 86-122 is wet past 1 km).
  GEBCO land to 0.5 km: fukumitsu, yumigahama-izu.
- Coordinator drops: `crescent-bay` (Strait of Juan de Fuca - no GFS-Wave wet node within 0.6 deg; the strait
  is not resolved by the 0p25 grid), everything below 0.65 (Discovery Bay, Twin Rivers, Elwha, The Hawk,
  Darigayos, Pistons in Jacmel, Shipping Bay).
- GEBCO land to 0.5 km, deep water beyond: willow-creek, eldorado-beach, mayumba.
- Nothing sourced or located: Taiji Bay (Zhejiang - OSM name only, a murky cove), Baler beyond the DB,
  Fehmarn's Surfstrand (windsurf only), SW Madagascar's reefs, the Marshalls' Beran reefs (distances from the
  lodge only), Tabuaeran's channels, Oea Village. Agents flagged, not moved: `libanona` sits on OSM Plage
  Ankoba (Plage Libanona is 1.3 km E); `charlies-point` may belong at the creek mouth 280 m away. Not
  seeded: Aichi's Atsumi peninsula (Akabane, Irago) has 0 spots.

**Gap queue (whole areas with zero spots, by box count 2026-11-26):** New Zealand is thin (17). Still
empty: Mauritania, Gabon, Palau, Yap, the Marshall Islands, Tuvalu, St Vincent, Cambodia, Sulawesi, West
Timor (each searched 2026-11-26 with nothing kept), the Great Lakes (OPEN-ITEMS 44) and the Black Sea's
Georgia (OPEN-ITEMS 45). Ireland is excluded by operator decision.


**Azores 27, Madeira 25, Sumatra 28, Sumba 9 + Rote 5, 3499 -> 3593 (2026-10-29, second pass).** Four
parallel subagents, web flow end to end, Google still down; a 10-pin coordinator re-render was all on the
break. The Azores got a new `azores` basin; Madeira joined `canaries`; the Sumatran regions (`aceh`,
`simeulue`, `nias`, `krui`) and `sumba`, `rote` joined `indonesia` (now one name per line, ruff format).
- **Extracts:** the Azores are `europe/azores` (Portugal's extract excludes them; `europe/portugal/azores`
  404s). Madeira has no Geofabrik extract but sits inside `europe/portugal` - a pyosmium bbox cut. Sumatra
  is `asia/indonesia/sumatra` (283 MB), Sumba/Rote `asia/indonesia/nusa-tenggara` (177 MB).
- **The pyosmium name search of the extract placed nearly every pin** (capes, fajas, islands, bays, surf
  camps); Photon gave island or province centroids for most surf names. Madeira's village and cape nodes
  sit on the cliff-top faja 100-250 m behind the shore; Indonesian village nodes can sit 7-8 km inland
  (Tanjung Setia, Way Jambu) - anchor on capes, islands and camps instead.
- **GEBCO puts a false shoal 2-5 km off Krui**: Ujung Bocur and Pulau Pisang carry an explicit
  `shore_normal` separate from the wind normal. Steep volcanic shores (Azores north coasts, Nihiwatu,
  Cement Factory) read land to 0.5-1 km on every bearing but end in water.
- Bathing re-match: +39 (the Azores and Madeira).

Gap queue: Azores - Santa Iria, Pedra do Caldeirao, Vila Franca, Capelinhos, Graciosa, Pico. Madeira -
Pizo, Supertubes (Porto Santo). Sumatra - Simeulue's Dylan's, The Peak, Thailand Left/Right; the
Banyaks' Gunturs, Dindos, Lizards Nest, Treasure Island; Nias' The Machine, Shark Hole; Krui's
Mandiri, The Peak, The Slab, Way Jambu; Aceh's A-Frame, Calang reefs; Bengkulu and Air Manis (not
seeded). Sumba - Wainyapu, Watu Bela, The Office/Racetrack (Kalala's sub-peaks). Rote - Suckie
Mama's, the Bommie. Savu and West Timor not seeded.

**Asia, the Caribbean, the Spanish Mediterranean and five singles, 3056 -> 3499 (2026-10-29).** Nine
parallel subagents, web flow end to end (Tier A was empty or a surf school everywhere). 29 new regions;
new basins `south-china-sea`, `east-china-sea`, `taiwan`, `korea`, `arabian-sea`, `bay-of-bengal`,
`caribbean-north`, `tonga`, `western-med`; Texas joined `gulf-of-mexico`, Virginia `us-east`,
Guatemala `central-america`, Barbados `caribbean-south`, Liberia `west-africa`, Reunion `east-africa`,
the Faroes `scotland-west`. The coordinator re-rendered a 14-pin sample (one or two per group): all on
the break. **Ireland is excluded by operator decision - never seed or suggest it.**
- **Google Places answered `REQUEST_DENIED: You must enable Billing` for the whole run.** Every pin rests
  on Nominatim + Photon + the tile. Both read OSM, so their agreement is not two sources, and Photon
  returns a city centroid on a miss (six Korean names on Yangyang's centroid, six Hainan names on
  Wanning's): an identical answer for unrelated names means no hit. **A pyosmium name search of the
  local extract** (Korean `...해수욕장`, Chinese bay names, Texas piers and jetties, Liberia's wreck)
  was the best geocoder this run - try it first when Google is out.
- **Tile reads failed silently in bulk** (`[media removed: request limit]` on the first 100+ reads in
  several forks). Every final pin was re-rendered and seen; nothing was judged on a failed read.
- **`towns.py` needs a `REGION_PBF` entry per new region** (not only `seed.py`/`emit_spots.py`), and
  `tide` needs `data/tide-src` (symlink it in a worktree). On China and India, OSM's nearest place is a
  hamlet in local script: China +39, Korea +35, Taiwan +30, India +25 town overrides.
- **Extracts:** China is one 1.6 GB `asia/china` (includes Hong Kong); India is zoned
  (`asia/india/{western,southern,eastern}-zone`); Reunion is `europe/france/reunion` (`africa/reunion`
  404s); Barbados has no extract - a pyosmium bbox cut of `central-america-latest`; the DR is
  `central-america/haiti-and-domrep` with the box's W edge keeping Haiti out.
- Per group: **China + Hong Kong 39** (Hainan 11, Guangdong 9, Hong Kong 8, Fujian 4, Zhejiang 4,
  Shandong 3; 37 of 39 moved, 18 normals re-aimed in coves and tombolos). **Taiwan 33** (all moved;
  Pinyin lookalikes put names in the wrong county; the Hengchun peninsula crossed two rays).
  **South Korea 33 + Jeju 5** (Yellow Sea tidal coves dropped; Taean surfs on a 5 m tide). **India 58**
  (Goa 11, Karnataka 13, Kerala 10, Tamil Nadu 9, Andhra Pradesh 12, Odisha 3; Maharashtra skipped, two
  names only). **Texas 24, Virginia 13** (36 of 37 moved; Port O'Connor's break is the Matagorda Island
  side of the jetty). **Dominican Republic 23, Barbados 24, Guatemala 13** (Guatemala's names are towns -
  the place node snapped to the coastline candidate was right 9 of 13). **Reunion 21, Liberia 9**
  (Robertsport's three points are named by guide order). **Tonga 9, Faroe Islands 6** (islet breaks
  geocode to the island centroid; GEBCO cannot see Taula). **Spanish Mediterranean 133** (Valencia 42,
  Andalusia 32, Catalonia 29, Balearics 18, Murcia 12; 49 Valencian/Murcian spots joined
  `test_geo_seam`'s pinned seam list).
- `rosa-pipeline horizon` was not run. `bathing --match eea` (2025 workbook) and `--match nsw` were
  re-run: +357 spots matched (the 189 new EU spots plus Sicily, the Netherlands, Germany, Normandy,
  Denmark and Sweden, never matched since their seeding), none changed or removed.

Gap queue: Hainan's Riyue sub-peaks (Camel Left, Back Beach, Ghost Hotel), Kame Rock, Da'ao, Xintan,
Sanya Bay; Pinghai Point, Jieshi Bay; Clubhouse Point, Fung Bay; Funingwan, Sansha; Gwen's Mouth,
Laoshan; Macau (Hac Sa). Taiwan: Double Lions, Gongs, Mimi's Reef, The Barracks, Green Island,
Xiaoyugang. Korea: Gangjeong/Yakcheonsa, Olders, Squids, Machine Guns, Gwangalli, Songdo. India:
Boar Rice, Shipwreck (Kerala), Akkarai, Repos, Bhatkal, the Vizag points; Maharashtra, Gujarat, the
Andamans, Lakshadweep (not seeded). Texas/Virginia: Condos, Cove, S-Turns, Rock Lane, 47th/51st St
jetties. DR: the Encuentro sub-peaks, Bozo, Playa Goleta, La Boya, Banzai, Pata de Name. Barbados:
Parlour, Duppies, Tropicana, Sandbank, Surfer's Point. Guatemala: La Barrita. Reunion: Sainte-Marie,
Riviere du Mat, Le Port, Black Rocks, Cap Requin, Les Aigrettes, La Gare. Liberia: Camp International,
Outer Cotton, Tico's Point. Tonga: the Ha'atafu sub-peaks, Tommas, Middles. Faroes: Nolsoy, Eidi,
Sandagerd, Vagur. Spain: Latigo, El Socorro, Montgo di Bongo, La Manga's picos, Molino de Papel,
Fuengirola, Es Secret, and Getares/Sotogrande/Calita/La Muralla for the cadiz region.

**Northern South America + Galapagos 0 -> 77 (2026-10-09): Colombia Pacific 11, Colombia Caribbean 22,
Venezuela 39, Galapagos 5** - extracts `south-america/{colombia,venezuela}` + `ecuador` (symlinked for
the Galapagos); new basins `caribbean-south` and `galapagos`, Colombia Pacific joined `ecuador`.
1. surf-forecast's per-country index was the whole name source. The Galapagos only resolves per
   island (`/regions/Galapagos-San-Cristobal/breaks`, `Galapagos-Santa-Cruz`).
2. Google confuses same-name places across Latin America (El Paredon -> Guatemala, Las Gaviotas ->
   Cuba, Gordon Beach -> Tel Aviv): a spread over 500 km means drop or re-query, never the pin.
3. Only 3 of 77 pins were kept unmoved (village, car park or lodge 100 m to 3 km inland).
   Venezuela's Caracas coast is groin cells every few hundred metres - pin the gap where the
   whitewater runs, never the groin. The Gulfs of Cariaco and Paria are flat water.
4. GEBCO reads 0.25-0.5 km of land on every bearing along the steep Choco, Tayrona and Venezuelan
   coastal ranges (22 of 77) - re-aim only for offshore_depth_m <= 0 or land past ~1 km. Coves
   between headlands need a hand bearing (Choroni Playa Grande).
5. **Image tool failures are silent**: when a tile read returns `[media removed: request limit]`
   the tile was NOT seen - stop and re-read before writing any move or "confirmed" note (caught and
   redone here; a coordinator spot-check of 6 pins confirmed the final pins).
Gap queue: Tongo Reef, Punta Pitt, Cerro Gallina, Palmas Grandes, Seymour Norte (Galapagos); El Mystic,
Siete Olas, Playa Kasimesh, El Bolsillo, Colpipe, Las Gaviotas, El Paredon, Viento Fresco, Gordon Beach
(Colombia); Funeral Point, Puerto Cruz, Punta Arena, Piedras Negras, Los Pocitos, Puerto Arrecife,
Playa Los Cuatro (Venezuela).

**US South-East 0 -> 43 (2026-10-09): Florida Northeast 11, Florida Panhandle 6 (Central time),
Florida Gulf 8, South Carolina 11, Georgia 1, Outer Banks +6 (the Carolina gaps)** - a new
`gulf-of-mexico` basin; the Atlantic regions joined `us-east`. 0 usable OSM surf nodes: web flow end
to end, surf-forecast's state indexes as the name source.
1. Google gave the pier root, car park, park road or inlet channel almost everywhere - all 43 pins
   were moves, most off a z15 tile, three (Mayport Poles, Ormond, Wiggins Pass) needed z14.
2. Neighbours collapse onto one pin (Holden Beach onto Ocean Isle Pier - Photon had it right; The
   Washout onto Folly Pier - fixed by geocoding the street, East Arctic Ave).
3. **Gulf tiles show turquoise flat water with sandbars as their normal state** - not a no-surf
   tell there; judge on the bar and pier position.
4. Normals ran along a jetty or into a pass (St Andrews Jetty, Wiggins Pass, Surf City) - set by hand.
   Not yet queued: Destin, Calle Hermosa, Redington Breakwater, Honeymoon Island, Anclote, Bradenton
   Beach, Turtle Beach, Pelican Poles, Murrells Inlet, Dunes Cove, Ocean Lakes, 35th St IOP, Bogue Pier,
   Shackleford Banks, Chicahauk, Laundromats, Columbia St.

**New England 0 -> 54 (2026-10-09): Massachusetts 29, New Hampshire 7, Maine 18** - three regions on
`north-america/us/{massachusetts,new-hampshire,maine}`, all on `us-east`. surf-forecast's per-state
indexes were the complete name source; 65 names geocoded serially, all but one within 4 km.
1. A z15 first read again: Google gave the car park, access road or state-park lot for almost
   every name (only Nantasket and Seabrook near the water).
2. Google's pin for one name can land on a neighbouring named break ("Brant Rock" sat on
   Fieldstone) - rename to the break the tile shows, drop the duplicate row.
3. Reef names with no place behind them (Costellos, Linkys, Trayhan's, Doc Brown's) return the
   town's commercial strip - a long inland spread means gap queue, not a move.
4. Jetty-mouth beaches pull the coastline normal onto the jetty (Plum Island, Pine Point); rocky
   points and river mouths fail 3c (Rye on the Rocks, Ogunquit Rivermouth, Brace Cove) - all set to
   the middle of the open arc. OSM's only "surf" tags were beach names containing "Surf".

**Normandy 0 -> 26 (+4 held), England South 0 -> 41 (2026-10-09)** - both on `biscay-celtic`. No
single Normandy extract on Geofabrik (`normandie-latest` 404s): merge `basse-normandie` +
`haute-normandie` with pyosmium `MergeInputReader` into `data/osm/normandy.osm.pbf`; `england-south`
symlinks `england-latest`. Web flow end to end (Normandy 0 OSM surf nodes; England's one = Littlehampton).
1. Name sources: surf-forecast's France and United-Kingdom indexes (the England index page is
   empty - use United-Kingdom), mondo.surf, Dorset guides. 74 of 75 names resolved; Google gave the
   town/car park, so 70 of 71 kept pins moved at z15.
2. 13 bad normals on Channel headlands and bays; Ecalgrain's ray hit Alderney at 18 km. GEBCO reads
   Camber's and South Lancing's drying flats as land to 0.5 km - aim at the narrow open arc.
3. **The Gulf of St Malo breaks the tide sanity cap**: EOT20 amplitude sums 6.0-7.6 m at Carolles,
   Bretteville-sur-Ay, Carteret, Hatainville vs `test_committed_constants_are_sane`'s 6.0 m. Those 4
   are held pending the operator's call on the cap.
4. Spots within ~1 deg of the meridian join `test_geo_seam`'s pinned seam list (23 Channel spots).

**Iceland 0 -> 10 (2026-10-09)** - one box over the whole island on the `europe/iceland` extract, new
`iceland` basin. Zero OSM surf nodes (14 named beaches): web flow end to end. Name sources:
surf-forecast's Iceland index (9 breaks), thesurfatlas, perfectwavetravel and Icelandic rental-car
guides; English guides repeat the same four (Sandvik, Grindavik, Thorli, Gardur).
1. **Geocode in Icelandic** (thorn, eth, accents in the query): every Reykjanes name resolved within
   1 km on Google + Photon; Nominatim returned nothing for any of them.
2. **Google gave the town or lighthouse for 8 of 11 names**; a z13 read found the break on the next
   point every time. Google put Eyvik 278 km off in south Iceland - trust the provider that matches
   the guide's coast (Photon's Tjornes hit).
3. **Breidavik is two candidates 10 km apart** (Latrabjarg headland vs the golden-sand bay); the bay
   is the break. Gardur and Hafnir read dark reef shelf with no whitewater - kept, sources name them.
4. Hafnarfjordur dropped (fjord harbour, moored ships). Sandvik's normal crossed the bay's north arm
   and was re-aimed to seaward 256. Gap queue: Grindavik Antenas, Snaefellsnes (sources name no break).

**Lampedusa + Pantelleria 0 -> 0 (2026-10-09).** A temporary `sicily-islands` box on the local
`italy-isole` extract: 117 candidates past the depth gate, 0 OSM surf features, 8 named beaches - all
dropped on the tile (Lampedusa's sheltered south-coast swimming coves, Pantelleria's volcanic cliff and
harbour). No surf source names a break on either island (surf-forecast puts the nearest in Tunisia and
Malta). If the operator supplies one, add a `sicily-islands` region on the `sicily` basin.

**Operator-supplied pins (2026-10-09, user-verified, 2765 -> 2770):** Sunny Isles, Stuart Rocks,
Japanese Rock (surf-forecast's "Jap Rock"; surfnerd's neutral name used), Kavieng, Skull Island - each
rendered and seen on surf. Skull Island's coastline normal ran along the reef spit (GEBCO cannot see
it); set by hand to the open Solomon Sea from a z13 read.

**New Caledonia Tier A- check (2026-10-08): 23 candidates -> 0 kept.** The 23 named-beach
candidates are 17 distinct OSM beaches; all rendered at z15 and all sit inside the barrier-reef
lagoon or a sheltered bay - glassy water, moored boats, mudflat, no breaking line. Web search
confirms none is a surf break. **A lagoon nation's beach pipeline finds only lagoon beaches**:
where a barrier reef fronts the coast (New Caledonia, much of Fiji and the Maldives), skip the
Tier A- pass and go straight to the web flow for the passes. Gap queue: Dumbea Pass, Tenia Pass,
La Roche Percee (Bourail - widen the box west to ~165.4).

**South Florida 0 -> 24 (2026-10-07)** - one box (25.60-27.30 N) from Miami Beach to Stuart on the
existing `north-america/us/florida` extract (`south-florida.osm.pbf` is a symlink), joined `us-east`.
Zero OSM surf nodes (28 named beaches, 0 surf features): web flow end to end. surf-forecast.com's
Florida break index was the name source; queries were plain `"<place>, Florida"` (the US override).
28 names -> 24 kept (all moves), 4 dropped. What was new:
1. **Render at z15 first on this coast.** Google gave the park, car park, street or inlet channel for
   nearly every name; a z15 tile (2.7 km) always held the surf, so the move was read there and
   confirmed at z16. No name needed the z13 recovery pass.
2. **A clean single-provider geocode can still be the wrong town.** `Fort Lauderdale 14th Street`
   came back on Lauderdale-by-the-Sea's pier (spread 10 km, Google right about a *different* beach);
   the break is on A1A at NE 14th Ct, 5 km south. `Jupiter Inlet South Jetty` geocoded to the Gulf.
3. **Three normals off the coastline were wrong**: South Pointe (30, the jetty), Boynton Inlet (190,
   the inlet channel), Jensen Beach (48). Set by hand from the tile; profiles all end in water.
Dropped: First Street (South Pointe's own beach), Jupiter Inlet North Jetty (sub-spot across the
mouth), and two query proxies no surf source names (Bal Harbour, Bathtub Reef). **Gap queue:**
the Sunny Isles motel breaks (Dunes, Harbor House), Stuart Rocks, Jap Rock, Stumps, Flagpoles,
the Treasure Coast between Stuart and Sebastian (Fort Pierce Inlet, Walton Rocks - inside the
Space Coast box), Key Biscayne.


**Philippines 16 -> 32 and north Japan +74 (2026-09-29)** - two parallel forks, web flow only.
Japan: Honshu north of Tokyo +56 into `japan.yaml`, a new `hokkaido` region (18, box
41.40-45.60 N, pbf symlinked to japan, joined the `japan` basin). Best Japanese name source:
japan.surfride.net's regional point pages; geocode in Japanese. Google returned the town,
harbour or car park for most names (51 of 74 moved). `towns.py` on the 2.4 GB Japan extract
takes more than 10 minutes - run it in the background. `ca_final.py` title-cases apostrophes
(`Stimpy'S`, id `stimpy-s`) - fix by hand. Gap queue: Lindy's (Baler), Tangbo and the Guiuan
outer reefs, Dicasalarin; Japan's Takasegawa, Esan, Shiranuka and the Niigata port beaches.
The existing `cloud-9` pin is ~250 m off the reef - re-place it.



**Northern Europe 0 -> 226 (2026-09-29, DB 2410 -> 2636): Scotland West 42, Scotland East 38, Germany 34,
Netherlands 33, Denmark 26, Sweden 26, Norway South 18, Lofoten 9.** Eight boxes, eight parallel
subagents, on `europe/united-kingdom/scotland`, `europe/{norway,denmark,netherlands,sweden}` and a
LOCAL MERGE of `europe/germany/{schleswig-holstein,niedersachsen,mecklenburg-vorpommern}`
(pyosmium `MergeInputReader` -> `data/osm/germany-coast.osm.pbf`; the whole-Germany extract is
~4 GB for two short coasts). Two new basins (`scotland-west`, `lofoten`); the rest joined
`north-sea`. **Zero usable Tier-A across all eight** (Germany's 5 surf nodes were shops, clubs and
a sheltered bay; the Netherlands' one was a surf school). What was new:
1. **Nominatim answered 429 for the whole run** with eight forks sharing it, so most pins rest on
   Google + Photon + the tile. Run fewer geocoders in parallel, or pace Nominatim.
2. **Google gives the village, farm, campsite or golf course, not the sand**, on every northern
   coast: 160 of 226 pins moved. Photon put Sandend near Glasgow, Feall Bay in London and Laggan
   Bay in Shetland - long spreads are the provider, not the break.
3. **`ca_final.py` still drops Nordic letters** from ids (`lberg`, `hellest`, `nrland`): fold
   o-slash/ae/a-ring by hand, and umlauts to ae/oe/ue.
4. **Shore normals re-aimed at 54 pins**: harbour walls and groynes (Hvide Sande, Agger), Zeeland's
   corner, Baltic bays whose ray reaches the far shore at 18 km (Lubeck Bay, Eckernforde, the Firth
   of Forth, Bjare), and Hebridean islands in the ray. Steep Hebridean coves read land to 0.5-2 km
   on every bearing (Balnakiel, Hushinish, Horgabost) and St Combs to 0.5 km; all end in water.

**Gap queue:** Hanstholm's harbour reefs, Bornholm; Fraserburgh's reefs (Wisemans, Phingask,
Westpoint), Caithness east; Lewis reefs, the Uists, Kintyre's Southend sub-peaks; Norway's Spot
X/Y, Point Perfect, the Lista reefs, Karmoy; Vesteralen/Andoya (outside the Lofoten box);
Maasvlakte's Slufter and Blokken, Schiermonnikoog; Fehmarn's Wulfener Hals, Kieler Forde, Sylt's
Ellenbogen; Gotland's east coast and Faro (east of the Sweden box), Norrland. Iceland, the Faroes,
Normandy and the English south coast were seeded later; Ireland is excluded by operator decision
(2026-10-29).

**South Africa West 0 -> 82, Namibia 0 -> 11 (2026-09-29, two passes)** - two boxes on `africa/south-africa`
(symlinked) and `africa/namibia`, a new `southwest-africa` basin. Zero OSM surf nodes: web flow end
to end. **surf-forecast.com's per-country break index was the only complete name source** (every
Cape Peninsula, Overberg, Garden Route and West Coast break with its area); English guides repeat
the same ten. 104 names -> 8 keep / 70 move / 26 drop. What was new:
1. **Nearly every Cape geocode is on the sand or the promenade**, 50-250 m back from the water -
   63 of 68 kept South African pins were moves.
2. **Surf names with no place behind them do not geocode at all**: Dungeons, Guns, Lockjoint,
   Paradise. Skeleton Bay only resolved as "Donkey Bay" (three providers within 0.6 km). Try the
   local place name before dropping a marquee wave.
3. **Google resolved "Strandfontein" to Cape Town's False Bay suburb, 260 km from the West Coast
   village**; Photon had the right one. Same-name towns are common in the Western Cape.
4. **21 of 78 normals needed re-aiming** - False Bay, Hermanus and the Kommetjie points.

A second pass re-queued the pass-1 drops with better queries plus ~60 unqueued index names and
local beach names (94 in all): +15 (Melkbosstrand, Holbaai, Little Bay, Baileys Cottage, Kakapo,
Witsands, Platboom, Strand Pipe, Kanon, Dolphin Point, Wildside, Gerickes Point, Sedgefield,
Groenvlei, Grosse Bucht). Filler names that no surf source names (Camps Bay, Paternoster,
Macassar, Mnandi, Glentana, Die Dam...) were dropped even where the tile showed surf.

**Gap queue (two strikes each, need a source with coordinates):** Dungeons, Off The Wall, Guns /
Lockjoint / Paradise / Fiji / Graveyards / Last Toilet (Swakopmund), the Kommetjie sub-peaks (365s,
Extensions, Sollys, Crons, Boneyards, Horse Trails), Nine Mile Reef, Captains, Donkin Bay, Jacobs
Bay, Vredenburg Point, De Kelders, Goukamma, Ding Dangs, The Wedge (Plett), the Northern Cape
(Port Nolloth, Hondeklip Bay - no surf source), Mile 108.

**Sicily 0 -> 42 (2026-09-29)** - one box over the whole island plus the Egadi, on the
`europe/italy/isole` extract (Sicily + Sardinia; `data/osm/sicily.osm.pbf` is a symlink to it) and
a new `sicily` basin. Zero OSM surf nodes (219 named beaches): web flow end to end. Italian names
came from wannasurf's Sicily index, surfproject.it/surf/sicilia.html (39 spots with their towns -
the best single source) and mondo.surf; English "surf in Sicily" pages repeat the same ten.
54 geocoded -> 42 kept, 13 moved, 10 dropped, 16 normals re-aimed. What was new:
1. **`ca_xref.py` snapped across the island**: "Arenella, Siracusa" went to Palermo's Spiaggia
   dell'Arenella, 250 km away: Photon answered Palermo, and the snap accepts an OSM name
   within 1.5 km of ANY provider, so a wrong provider drags the pin with it (spread 210 km).
   Marina di Ragusa went to Marina di Acate the same way (spread 29 km), and two Cefalu breaks
   to the town beach. Distrust any `osm:` snap on a row whose spread is > 5 km.
   Read every `osm:` src against the web name.
2. **Google gave Terrasini's Cala Rossa for Termini Imerese's Cala Rosa** (57 km); Photon had
   the right town.
3. **The seeded coastline normal was off by 60-120 deg at 16 of 42 pins**, mostly on the
   south-east corner (Scoglitti, Punta Secca, Donnalucata, San Leone): harbour moles and small
   points next to the pin. A 2-deg sweep of the 0.5-5 km ray for the largest land-free arc,
   aimed at its middle, fixed all 16 (script in `work/sicily/arc.py`).

**Gap queue:** Cefalu's Kamikaze (3 km east of town on the SS113 - locate it on a z14 read),
Santa Lucia (Cefalu), the Granitola sub-peaks (Canada Point, Cala dei Turchi), Sciacca (San Marco,
Ciminiera), Portopalo, Aci Trezza, Lampedusa, Pantelleria. The rest of Italy (Sardinia, Tuscany,
Lazio, Liguria) is not seeded.


**South America closed 1947 -> 2254 (2026-09-16): Chile Central 51, Mar del Plata 48, Ecuador 47,
Chile South 34, Chile North 30, Uruguay 26, Alagoas 25, Paraiba 17, Patagonia Argentina 16,
Sergipe 13.** Ten boxes, ten parallel subagents, four new basins (`chile-north`, `chile-central`,
`ecuador`, `argentina-uruguay`) plus the three Brazilian states joining `brazil-northeast`.
**Four Tier-A surf nodes in the entire continent** (Chile Central's Caleta Los Piures = Punta de
Lobos, Ecuador's Las Tunas, Mar del Plata's chapadmalal and palangana): web flow end to end,
Spanish-language sources only - wannasurf's regional indexes, lineup.surf, elsurfero, surfparaiso,
waves.com.br. English "best surf in X" pages are SEO beach lists here.

What this pass taught:
1. **Exposure is the judgement, not the name.** Every region dropped names that are real beaches
   and not surf: the Rio de la Plata estuary west of Punta del Este (10 dropped), the Patagonian
   gulfs, the Gulf of Arauco, Alagoas' and Paraiba's inside-the-reef natural pools, Ecuador's
   Salinas bay, Chile North's Antofagasta balnearios. **Moored boats just offshore is a reliable
   no-surf tell** - if the tile shows an anchorage, it does not break.
2. **Google returns the settlement, not the sand, on every Spanish-language coast**: 21 of 51
   Chile Central, 22 of 26 Mar del Plata city, 15 of 17 Paraiba, 13 of 13 Sergipe, 21 of 47
   Ecuador. The fix is a 60-200 m nudge onto the waterline, or better, snapping the pin to the
   nearest bathy-passed coastline candidate - that put 12 of 13 Sergipe pins right first try.
   Las Grutas came back as San Antonio Oeste town, 15 km away, on all three providers; only the
   z14 wide read caught it.
3. **`ca_xref.py`'s snap has two failure modes left**, both caught on the render: two named peaks
   on ONE named beach (Mar del Plata's biologia / el-yacht / waikiki all snapped to "Playa
   Grande"), and a neighbouring beach within 1.5 km whose name shares the query's TOWN word
   (Penarol -> "Playa Antofagasta"). Keep the area out of the geocode NAME, and read every
   `osm:<name>` against the web name.
4. **GEBCO reads the first 0.25-1 km as land on EVERY bearing** across the Brazilian north-east,
   Uruguayan, Patagonian, Ecuadorian and urban-Chilean shelves. When no arc is clean, the grid is
   the problem, not the aim: judge `offshore_depth_m` only (OPEN-ITEMS 17/23). 49 normals were
   re-aimed across the pass, every one to the middle of the open arc.
5. **Tooling notes the forks hit:** `emit_spots.py` is the wrong tool for a 0-Tier-A region (it
   reads only `result.json["new"]` and emits no `town`) - the working path is `ca_final.py` ->
   `towns.json` -> `emit_region.py <region> <anchor>`; both it and `ca_final.py` still drop
   accented letters from ids (`chaihu-n`, `maicolpu`) and strip Spanish articles (`el-faro` ->
   `faro`), so check every emitted id; `ca_queue.py`, `bathy` and `tide` must run from the repo
   root; the scratchpad is SHARED between parallel forks, so use per-region filenames.
6. **A bbox that overruns a border re-offers an already-seeded spot as NEW** - paraiba's N edge
   at -6.00 reached past the Rio Guaju into Rio Grande do Norte and surfaced Baia Formosa's
   `pontal` again. Scope the box to the state, and check any "new" Tier-A against the whole DB.

**Gap queue:** Colombia and Venezuela (not attempted); Chiloe and the Maullin coast; Tierra del
Fuego (Rio Grande); the Galapagos; Buenos Aires' north (San Clemente to Nueva Atlantis) and
Monte Hermoso's paradores; Bahia Blanca westward; Punta del Este's Mansa side and Montevideo;
Peru-Chile's Arica reef names and the Antofagasta reefs (Andromeda, Nuluhaga, Pozo Verde...);
Manta's and Mompiche's sub-peaks; the Alagoas north coast (Maragogi) if it is ever judged
surfable; Baia da Traicao's reserve peaks; the Aracaju "Porto" pico.


**Brazil 0 -> 305 (2026-09-11): Sao Paulo 56, Rio de Janeiro 52, Santa Catarina 46, Bahia 33,
Ceara 31, Espirito Santo 29, Rio Grande do Norte 18, Rio Grande do Sul 14, Parana 9, Pernambuco 9,
Fernando de Noronha 8.** Eleven boxes on three extracts (`south-america/brazil/{sul,sudeste,
nordeste}`), two basins (`brazil-south`, `brazil-northeast`), nine parallel subagents (RS+Parana and
Pernambuco+Noronha paired). A session usage limit cut eight of them off mid-run; each resumed from its
own transcript with no work lost. **Brazil is Google country with little OSM**: 9 Tier-A nodes across
all eleven states, and Nominatim answered HTTP 429 for most of the run because ten processes shared
it, so most names were Google + Photon and the tile decided.

What was new:
1. **`ca_final.py`'s slug drops accented letters** once a rename has run (`cap-o-da-canoa`, `imb`,
   `boca-do-po-o`, `s-o-jos`): it strips non-ASCII before NFKD-folding. Every fork fixed ids in its own
   `final.json`. Fixed the same day: the rename now NFKD-folds before the slug regex.
2. **The pipeline's `gebco2020` API reads the north-east shelf as exactly 0.0 m** for kilometres (off
   Tourinhos the local grid reads -6/-8/-12/-18 m at 2/8/12/18 km, the API 0.0 at all four). Profiles
   still end in water, but their nearshore is the API's zeros. Don't re-aim or drop over a 0 m sample;
   the only hard check is the deep end. Resolved the same day: the fleet now cuts from the
   local GEBCO 2024 grid (OPEN-ITEMS 17 applied), and Tourinhos reads 10-13 m from 1 km out.
3. **Generic Portuguese names repeat across states** (Prainha, Praia Grande, Praia Mole, Praia Brava,
   Barrinha, Pontal, Havaizinho, Porto): suffix them by town or state BEFORE emitting when regions emit
   in parallel, or the second emitter clashes.
4. **Google gives the town centre 100-700 m back from the beach** almost everywhere (Ceara moved 25 of
   31 pins); Espirito Santo's towns needed a z14 read to find the surf at all.
5. **Guides list sheltered bay and channel beaches** (behind Ilhabela, inside Ubatuba / Santos / Todos
   os Santos bays) and sub-peaks of one beach (Itaparica's Secret / Barra Sol) - judge exposure on the
   tile, drop sub-peaks for the parent.
6. **OSM place nodes are hamlets and condominiums**; most Brazilian towns are hand overrides to the
   municipality (Sao Paulo 56 of 56).
7. **OSM beach nodes are often polygon centroids offshore** (Lopes Mendes, Pero) - check the pin sits
   on the waterline even when the snap is the right beach.
8. waves.com.br's state/city pages list every named pico and were the best Brazilian name source.

**Gap queue:** Alagoas, Sergipe and Paraiba; Santa Catarina's south (Morro dos Conventos, Balneario
Rincao - west of the box); Itaparica's sub-peaks; Pipa's reef sections (Lajao, Sororoca); the Amazon
coast is not surfed.

**Algeria 0 -> 20 (2026-09-11)** - one box over the whole coast on `africa/algeria` and a new
`algeria` basin. Zero OSM surf nodes (414 named beaches), so it was the web flow end to end:
26 names -> 20 kept, 9 pins moved, 6 dropped, 4 normals re-aimed (Cap Ivi's coastline normal pointed
into the dunes). **Google answers every Algerian name but gives the town centre** (Beni Saf, Dellys,
Surcouf, Ain Benian); a plain `"plage <town>, <wilaya>"` requery on Nominatim or Photon found the
beach. **English-language Algerian "surf" lists are SEO beach lists** - Tala Guilef is a ski
station - so trust only names a surf-specific source repeats. First run of the fixed `ca_xref.py`:
11 snaps, none on the wrong beach. Gap queue: Oran's west (Beni Saf, Madagh), Jijel's corniche
beyond La Crique, Annaba and El Kala.

**Spain and Cyprus 0 -> 214 (2026-09-10): Galicia 55, Canary Islands 45, Cadiz 25, Asturias 24,
Basque Country 24, Cyprus 22, Cantabria 19.** Seven boxes, one per Geofabrik extract
(`europe/spain/{pais-vasco,cantabria,asturias,galicia,andalucia}`, `africa/canary-islands` - NOT
`europe/spain/canarias`, which is the 9 KB HTML 404 - and `europe/cyprus`). The four north-coast
regions joined `biscay-celtic`, Cadiz joined `portugal`, and the Canaries and Cyprus got their own
basins. Andorra has no coast; the Spanish Mediterranean is not seeded. Judging ran as seven parallel
subagents, one per region.

**The new failure mode is `ca_xref.py`'s OSM snap in Spanish.** Its STOP set lacks `playa`, `praia`,
`de`, `da`, `do` and `del`, so "Playa de X" matches any OSM "Playa de Y" within 1.5 km and the pin
jumps to the neighbouring beach: 8 of 25 in Cantabria, 9 of 35 in Galicia, 8 in the Canaries, 7 of
27 in Cadiz, 3 of 20 in Asturias. Every one was caught on the render and reverted to the geocode.
**Fixed the same night**: `STOP` now carries the beach words and articles of every seeded language.
Replayed on Cantabria's saved geocodes, the snaps fell from 22 to 17, and Valdearenas and Cuchia now
snap to their own beaches. One kind remains: the query name carries its town
("Isla de Santa Marina Loredo"), so a beach named after the same town still matches. Keep reading
each `osm:<name>` src against the web name. Google, by contrast, was right more often than the snap
on every Spanish coast.

Other notes:
1. **OSM carried the breaks only in Galicia**: 20 Tier-A surf nodes in the Rias Baixas and Costa da
   Morte, all 20 verified. Basque Country had 0 usable Tier-A but 60 named beaches, the best second
   source there. Cyprus had none at all.
2. **Shore normals failed on a third of the spots** (14 Basque, 17 Galicia, 13 Canaries, 9 Asturias,
   6 Cantabria, 5 Cyprus): rias, cove mouths, points, and island shadow in the Canaries (El Muelle's
   ray hit Lobos at 5 km, Caleta de Caballo's ended on Lanzarote). All re-aimed to the middle of the
   open arc.
3. **Cliff-walled coves keep land at 0.5-1 km on the API grid on every bearing** (Deba, Itzurun,
   Cueva, Playa Espana, the Cadiz city shore, eight inner-ria Galicia beaches, Anaga and El Medano
   out to 1-2 km). Every ray still reaches deep water, so they were kept; this is OPEN-ITEMS 17/23.
4. **`render.py` used fixed ports (4180/9230)**, so parallel renders collided and `shoot.mjs` exited 13.
   The forks called `render.render_tiles` on private ports. Fixed the same night: both ports now
   default to a free one per run.
5. **Galicia's OSM place nodes are parish hamlets**, so all 55 towns are hand overrides to the concello.
6. A fork read `.env.local` with `cut -d= -f2-` and kept the quotes, got "API key not valid", and
   geocoded Basque Country without Google. Strip the quotes.

**Gap queue:** the Spanish Mediterranean (Barcelona, Valencia, Almeria - rarely surfed),
Huelva, Cantabria's La Vaca / El Muro / Cuchia, Fuerteventura's Bubble / Rocky Point / Generosa /
Lobos, Lanzarote's separate La Santa left and right, Tenerife's El Medio and Derecha del Cartel,
Galicia's O Corvo, and Northern Cyprus beyond Akdeniz.

**Indian Ocean 0 -> 28 (2026-09-04): Mozambique north extension +8 (-> 13 total), Madagascar 5,
Mauritius 10** - all three zero-OSM regions, web-search only with 3 rounds of sat-tile verification
and two-strikes-then-drop. Northern Mozambique bbox widened from -23.30 to -10.40, picking up
Inhambane coast spots (mussage to ponta-mamoli). Madagascar yielded only the southwest (Anakao reefs:
flameballs, jelly-baby) and south tip (lavanono, libanona, baie-maxime on the east coast); 9 of 14
candidates dropped across 3 passes. Mauritius concentrated on the southwest Le Morne peninsula (one-eye,
le-morne, manawa) and south coast (souillac, graveyards, riviere-des-galets cluster); ilot-sancho and
grand-sancho converged to 104 m on pass 3 and were reverted to pass-2 coordinates (543 m apart). All
joined the `east-africa` swellmap basin. Several bathy profiles have land samples in their nearest
ray points (diamonds, maragra, black-rocks, grand-sancho, ilot-sancho, riviere-des-galets, souillac,
graveyards, lavanono, maconde) but the geography (volcanic islands, steep reef margins) makes this
reasonable.

**US East 0 -> 84 (2026-09-03): New Jersey 25, Long Island 20, Outer Banks 16, Florida Space Coast 12,
Rhode Island 11** - a new `us-east` basin, five boxes on the `north-america/us/{new-york,new-jersey,
north-carolina,florida,rhode-island}` extracts. **All 92 web names geocoded, the best rate of any
pass** - US place names are unambiguous in a way Ghana's and Mentawai's are not. Only 1 Tier-A node
in the whole seaboard (a Sebastian Inlet node named just `jetty`, skipped as the same wave under a
name no surfer uses), so this was a web-flow region end to end.

**The failure mode here is new and worth naming: the geocode is RIGHT and still useless.** US towns
geocode to their civic centre, which on a barrier island is 0.9-2.0 km inland of the surf. A first
judging pass dropped 8 of 25 New Jersey names and 2 of the Florida marquee waves - Sebastian Inlet
and New Smyrna - not because the pin was wrong about the place but because the break fell outside a
640 px z16 tile. **A recovery pass at z13 recovered all 10.** Elsewhere the rule has been "two
strikes and drop"; here the right first move is *zoom out*, because the coast is always due east.
Add a wide read before dropping any US east-coast name.

Two more notes:
1. **The big geocoder spreads were false alarms.** Carolina Beach Pier (277 km), Montauk Point
   (485 km), Ocracoke (104 km) and The Cove (130 km) all landed on the correct named place - the
   spread came from a bad *second* provider, not a bad chosen pin. The only genuinely unusable
   candidates were the two with a single provider. **Spread flags a tile to read, not a spot to
   drop.**
2. **`ca_queue.py`'s query template collapses US geocoding.** `"{name} surf break {area} {REGION}"`
   returned nothing for 73 of 92 names; rewritten as plain `"<place>, <state>"` all 92 resolved.
   Non-US regions still need the qualifier - this is a US-specific override, not a template fix.

Dropped, all under the two-strikes rule: **K39** (a local nickname for a utility pole on Ocean Road;
nothing in the imagery identifies which break it is), **Weekapaug** (cloud over the breachway mouth
at both z16 and z14), **Rodanthe Pier** (same coordinate and tile as S-Turns), **Atlantic Beach**
(pin in Fort Macon salt marsh, ocean clipped at the tile edge), **Masonboro Inlet** (single provider,
pin in open water with no shoreline in frame), **Monster Hole** (an offshore bar with no landmark to
fix it against), **Patrick AFB** (the same wave as Second Light, 650 m of featureless beach apart),
**Ponce Inlet** (duplicate of New Smyrna Inlet).

Six shore normals needed re-aiming under 3c: Charlestown Breachway pointed into the salt pond,
Matunuck's and Green Hill's rays ended on **Block Island**, Democrat Point's ran along the Fire
Island inlet, Narragansett Town Beach's crossed the headland, and Ocean City's pointed back over the
barrier island.

**Gap queue after this pass:** Massachusetts (Cape Cod, the South Shore - the extract is already
downloaded), New Hampshire and Maine, Delaware and Maryland (Assateague, Ocean City MD), Virginia
Beach, the Carolina gaps between Emerald Isle and Wrightsville, Folly Beach and Tybee, Florida's
south-east (Miami to Stuart) and north-east (Daytona to Fernandina), the Gulf coast, and Long
Island's Montauk Point / Turtle Cove pair if one entry per headland is ever preferred.

**East Africa 0 -> 29 (2026-09-03): South Africa East 21, Mozambique 5, Zanzibar 2, Kenya 1** - a new
`east-africa` basin, four boxes on `africa/{south-africa,mozambique,kenya,tanzania}`. **South Africa is
the first region where OSM carried a whole point break**: Jeffreys Bay has 7 Tier-A `sport=surfing`
nodes (Albatross, The Point, Tubes, Boneyards, Magna Tubes, Sandkasteel, Kitchen Windows) that all
verified on the point, so the Tier-A path did the work the web flow usually does. The other three
regions produced **zero** Tier-A between them - Kenya 271 candidates, Mozambique 1394, Zanzibar 299,
none tagged for surfing - and every spot there came from the web flow.

Drops, all under the two-strikes rule: Cave Rock (the pin showed straight Bluff beach and the rock the
spot is named for was never visible), Galu and Tiwi (inside the lagoon, no break line on two passes),
**Jambiani (three passes, all on the reef flat; the breaking edge sits further east than I could fix)**.
Zanzibar and Kenya break on the **outer** reef, well past a z16 tile, so Paje and Dongwe both needed
a z13 read before the edge was findable at all.

Three process notes:
1. **Two truncated Geofabrik downloads got through the size check.** Mozambique arrived at 191 MB of
   255 MB and Tanzania at 93 MB of 705 MB, because a 10-minute command timeout killed the curl. The
   header read fine and the byte count looked plausible; the failure only appeared later as
   `RuntimeError: PBF error: unexpected EOF`. **Compare against `Content-Length`, not against a
   guess at what the file should weigh.**
2. **`cd data/osm && ... seed.py` runs the seeder from the wrong cwd** and all four flows exit 1.
   Run it from the repo root.
3. **Three shore normals pointed into land and `bathy` cut the profile anyway** - see 3c, which is
   now a required step. St Michaels' ray ran 18 km inland to a 103 m hilltop; The Point (J-Bay) ran
   over the town; Praia da Barra crossed the spit and turned out to be a misplaced pin, not just a
   bad bearing.

**Gap queue after this pass:** Durban's Cave Rock and the Bluff, Jambiani's outer edge, Zanzibar's
north (Nungwi, Matemwe), Kenya's Malindi/Watamu, Mozambique's Ponta Mamoli and the Bazaruto
archipelago, Tanzania's mainland, Madagascar, Reunion, Somalia's Indian Ocean coast.

**West Africa 0 -> 17 (2026-09-03): Senegal 8, Cape Verde 6, Ghana 3** - the first regions on a
`west-africa` basin. Three boxes on `africa/{senegal-and-gambia,cape-verde,ghana}`. 46 guide names
-> 9 keep / 9 move / 28 drop, **the worst keep rate of any pass so far, and the drops are the
point.** Google collapses hard here: Palmeira, Santa Maria, Fragata and Alibaba all returned one Sal
coordinate; Cape Three Points, Butre, Akwidaa and Cape Coast returned one Ghanaian coordinate;
Club Med (Dakar) returned Cap Skirring 250 km south. **Anything that missed twice was dropped, not
guessed** - the Almadies reef cluster (Vivier, Secret Spot) could not be told apart on two rendered
passes, and Palmeira's shore showed no break on a z15 read. Ngor's right and left were separated on
a z15 read of the island. **Two process notes worth keeping:** (1) Senegal's OSM had a Tier-A
`Ouakam` node 250 m from the break, and `ca_final` prefers Tier-A over a web move on an id clash -
it took the shore pin and dropped my rendered one, silently, with only a `duplicate id` warn. The
fix is a `skip.json` entry; **check the emitted coordinate whenever a Tier-A name matches a web
name.** (2) `ghana-togo` was one box over a Ghana-only extract, so Lome had no coastline candidate
and `ca_final` skipped it. Scoped the box to Ghana; **Togo needs its own extract and region.**
**Ghana also broke the 0/360 seam open:** it clusters with Angola 15 deg away, the box wrapped past 0, and
clamping would have dropped Ghana's cells - `gfswave.cluster_boxes` now SPLITS such a cluster and fetches
both sides (SESSIONS 51). **Gap queue:** Togo and Benin, Morocco's Atlantic south (Dakhla is seeded, Imsouane-to-Tarfaya is
not), Sierra Leone / Liberia (Robertsport), Gabon, Angola's north.


**UK and France in one pass (2026-09-03): Cornwall & Devon 0 -> 36, Wales 0 -> 14, North Scotland
0 -> 8, North East England 0 -> 10, Landes 0 -> 28, Brittany 0 -> 24.** Six boxes on four Geofabrik
extracts (`europe/united-kingdom/{england,wales,scotland}` - NOT `great-britain/...`, that path 404s to
a 9 KB HTML page that the seeder then reads as an empty extract - plus `europe/france/aquitaine` and
`bretagne`), two new basins (`biscay-celtic`: Landes, Brittany, Cornwall Devon, Wales; `north-sea`:
North East England, North Scotland). **Europe is the easy case:** Google, Nominatim and Photon all
answer and agree, the beaches are named on OSM (Brittany carried 11 surf nodes - Pen Hat, Cabestan,
Trépassés, the Trégunc and Locquirec beaches - the most of any region so far), and most pins were keeps:
across the six, 141 names -> 88 keep / 26 move / 27 drop. Moves were the usual (a pin 400 m out to
sea, a car park, a harbour instead of its reef); the drops were sheltered coves, collapses (Hunts Bay
onto Caswell, Scarborough South onto North, Murkle onto Brims) and two names outside their box. Two
placements needed the coastline candidates rather than any geocode: **Brims Ness** (Google gave the
Brims farm 4 km inland; the reef ledge was found from the candidate list at 58.667 N and a z15 read) and
**Home Reef**-style relabels (La Gravière and La Sud were OSM-snapped onto one Hossegor beach node and
spread 300 m N and S along the bank). Twenty-one normals set by hand - Cornwall's coves and Brittany's
points run every direction. Two more re-aimed by arc sweep: Godrevy's SW ray crossed St Ives Bay into Penwith
and Brims Ness's N ray hit Hoy (Orkney) at 18 km. `marbella` clashed with Costa Rica's and took `-fr`. Judge logs in `work/<region>/judge.json`. **Two seam findings, both from the UK box:** `gfswave.cluster_boxes` padded the 354-359.6 deg cluster to 360.6 and warned; only the PAD crosses, so it now clamps silently and warns only when a member does. And the Yorkshire coast (0.97 W to 0.36 W) is the first inside OISST's 1 deg search radius of the seam, so the no-op test had to be split - see SESSIONS 51. **Gap queue:** Devon's south
coast beyond Bantham, Ireland (Bundoran, Lahinch, Mullaghmore), Scotland's west (Tiree, Machrihanish),
France's Vendée / Charente (Les Sables, Oléron) and the Basque sub-breaks.


**WA South 0 -> 12 and Esperance 0 -> 6 (2026-09-03) - WA's south coast, the last gap in Australia's
mainland surf coast.** Two boxes (Augusta-Bremer Bay; Esperance-Duke of Orleans) on `australia-south`.
0 Tier-A. 24 guide names -> 12 keep / 6 move / 6 drop. The drops were sheltered water (Peaceful Bay,
Parry, Wylie Bay, Hellfire) and two Google placements on the wrong side of a bay (Windy Harbour's
village, Wharton's calm E shore - the surf beach faces S and was not placeable). Three normals set by
hand (Ocean Beach, Mutton Bird and Salmon Holes came back facing E/N off the granite-point ways). Cheynes Point's N ray hit the shelf at 18 km and was re-aimed E by arc sweep; `ocean-beach` clashes with
California's and took `-was`.
Judge logs in `work/wa-south/judge.json` and `work/esperance/judge.json`. **Australia's mainland surf
coast is now continuous from Exmouth clockwise to the Sunshine Coast**; what remains are islands and
corners: Cactus / the Eyre Peninsula, Kangaroo Island, Marrawah, Exmouth's Ningaloo reefs.


**WA Midwest 0 -> 12, Bunbury 0 -> 7, Exmouth 0 -> 2 (2026-09-03) - the west-coast gaps between
the existing WA boxes, closed in one pass.** Three boxes that butt against perth / margaret-river /
wa-north's edges, all on `australia-west`. 0 Tier-A anywhere. 29 guide names -> 21 keep / 6 move /
8 drop. Clean where there are towns (Lancelin, Jurien, Bunbury's beaches all geocode to the sand);
the drops were sheltered water (Leeman, Cervantes' front beach), inland pins (Dongara's Home Reef,
which Google put 3 km up the road while it put "Seven Mile Beach" ON the Port Denison marina - the
reef N of that seawall is Home Reef, so the pin was re-labelled rather than lost), one pin 2 km out to
sea (Preston Beach) and Exmouth's cape breaks (Lighthouse Bombie, Hunters, Wobiri) that Google collapsed
onto the town or the caravan park - **Exmouth is thin (Dunes, Mildura Wreck only) and needs a local
source for the Ningaloo reefs.** No normals needed a hand fix - a straight west coast is the easy case.
Judge logs in `work/<region>/judge.json`. With these, **Australia's west coast is continuous from Cape
Leeuwin to the North West Cape**; the south coast (Cape Leeuwin -> Esperance) is the remaining WA gap.


**Tanegashima & Amami 0 -> 17 and Okinawa 0 -> 11 (2026-09-03) - Japan's southern islands, on a
new `ryukyu` basin.** Two boxes on the Japan extract (2.5 GB - ~15 min per coastline parse), the
`japan` box's 30.0 S edge left Tanegashima out until now. Primary flow: 0 Tier-A and almost no
named beaches on Tanegashima. **What was new: geocode in Japanese.** The English queries collapsed
all thirteen Tanegashima names onto Minamitane town and put "Miyanoura" on Amami; a second
`multi_geocode.py --file` round with Japanese queries (鉄浜海岸 種子島, 残波岬, 喜屋武岬 ...) resolved
most of them, and Nominatim / Photon came back to life on kanji - the provider that was dead
outside Europe/US works here in the local script. The z15 read of the Sunabe seawall put the three
Chatan reefs on the reef edge (the first z16 placements landed in deep water 300 m out). 20 keep /
15 move / 15 drop over three rounds: drops were inland pins, sheltered coves (Urata, Mibaru) and the
Miyako / Yaeyama snorkel beaches that are not surf spots. Fourteen normals set by hand - the island
coastline ways here run every which way, so the nearest-candidate normal was wrong more often than
right. Ikei Island's N ray hit the Katsuren peninsula at 18 km and was re-aimed E by arc sweep. Towns are the municipalities (Chatan, Yomitan, Nakatane, Tatsugo). Judge logs in
`work/okinawa/judge.json` and `work/tanegashima-amami/judge.json`. **Gap queue:** the Playgrounds-
style Sunabe sub-breaks (Hawaiians, California, Hotels), Miyako's Irabu / Shimoji reefs, Amami's
Gamou and Ohama's neighbours - all need a local source.


**Mentawai 0 -> 15 (2026-09-03) - the first boat-access chain.** One box from Siberut to South
Pagai on the Indonesia extract and the `indonesia` basin. Primary flow: 0 Tier-A and 0 OSM surf
nodes of any kind - OSM has nothing here. Secondary: 31 guide names -> all geocoded (Google only) ->
all rendered -> 1 keep / 14 move / 16 drop. **The Mentawai failure mode is the surf camp:** Google
returned Kandui Villas, the Playgrounds camp islet and Katiet village for a dozen names each, so every
kept pin was placed on its reef line off the tile - which the sub-metre imagery shows unusually well
here (Rifles, Kandui, HTs, Bank Vaults, Roxies, Thunders all have a visible breaking line). What
could NOT be separated was dropped rather than guessed: the Playgrounds inner breaks (Nipussi,
Burgerworld, Hideaways, A-Frames, Four Bobs, Playgrounds Left), Sipora's Telescopes / Suicides /
Seven Palms, and the whole Rags / Hole / Bat Caves / Silabu Left group in the Silabu lagoon - the
tiles show reef everywhere and no way to tell which reef carries which name. **Those 16 are the
Mentawai gap queue and need a source with coordinates (a charter operator's map or a local), not
another geocode.** Five normals set by hand, and six more re-aimed by arc sweep: the Playgrounds breaks sit in a channel
walled by Siberut and Karangmajat, so their W rays hit land at 18 km and the open water is SW (the
direction the swell actually arrives from); HTs' SE ray ran along Sipora's shelf and was turned to ESE.
Towns are the islands / camps (Playgrounds, Nyang Nyang, Karangmajat, Katiet, Silabu). Judge log `work/mentawai/judge.json`.


**South Australia 0 -> 19, Tasmania 0 -> 13, WA North 0 -> 11 (2026-09-03) - the last three
Australian gaps, in one pass.** SA = Fleurieu + Yorke (Cactus on the Eyre and Kangaroo Island's
south left for later), Tasmania = east and south coasts (Marrawah left), WA North = Geraldton to
Gnaraloo on `australia-west`; SA and Tasmania join Victoria on `australia-south`. `wa-north.yaml`
is the first file that sets `region:` explicitly ("WA North") because the stem would have read
"Wa North". Primary flow: 2 + 0 + 0 Tier-A (OSM's Berry Bay and Middleton "Surfers Beach" nodes,
both kept - Berry Bay's node beat Google, which returned that beach for "Corny Point"). Secondary:
21 + 16 + 13 guide names -> 50 rendered -> 28 keep / 13 move / 9 drop over five rounds. Drops were
Google's inland pins (West Cape, Trespassers, Marion Bay, Headbutts had no geocode at all), a pin in
open sea (Cloudy Bay - OSM's beach node used instead), sheltered water (Adventure Bay), and
collapses (Fencies onto Tombstones, Corny Point onto Berry Bay). Remote WA came out well: Google
gives the station or camp (Gnaraloo, Quobba) and the reef line 300-400 m W is unmistakable on the
tile. Six normals set by hand (Pondalowie and Chinamans came back facing SE/N off the headland
ways; Beerbarrel and Carlton likewise), and Carlton / Park Beach re-aimed S by arc sweep - Frederick
Henry Bay is enclosed and their SE rays hit the Tasman Peninsula at 18 km. `tombstones` and
`sunset-beach` clashed with the Maldives and Hawaii and took `-wan`. Judge logs in `work/<region>/judge.json`. **Australia is
now covered end to end except Cactus / Eyre, Kangaroo Island, Esperance and Marrawah.**


**Victoria 0 -> 30 (2026-09-02) - the first south-facing Australian region, on a new
`australia-south` swellmap basin.** One box from Lorne to Phillip Island (Surf Coast, Mornington
Peninsula back beaches, Phillip Island; Port Phillip Bay inside and self-pruning), `Australia/Melbourne`
anchor with N/NW offshore. Primary flow: 2 Tier-A (Point Lonsdale Back, kept under the web name; Torquay
Back Beach, kept and renamed Torquay Surf Beach). Secondary: 30 guide names -> all rendered -> 15 keep /
14 move / 1 drop over five rounds. **Google's Victoria failure mode is returning Torquay for anything on
the Surf Coast it does not know** - Lorne Point and Steps both came back as Torquay - and OSM's Woolamai
node sits on the sheltered Cleeland Bight side, not the surf beach; both were recovered from z14/z15
reads, and the OSM `Princess Street (Steps/Boobs)`, `Urquhart Bluff` and `Summerland Beach` nodes were
better than any geocode for those three. Six normals set by hand: the Bells / Winkipop / Southside /
Steps ways run N-S so the reefs came back facing E; they face SE. Cat Bay's NW ray hit the Mornington
Peninsula across the Western Port entrance at 18 km and was re-aimed W by arc sweep. Six ids clashed
with California / Byron / Margaret River names (Steps, Bird Rock, Summerland, Cosy Corner, Southside,
Smiths Beach) and took `-vic`. Judge log `work/victoria/judge.json`.
**Next in Australia:** WA north of Perth (Geraldton, Kalbarri, Gnaraloo), Esperance, South Australia
(Yorke Peninsula, Fleurieu), Tasmania.


**Gold Coast 0 -> 20 and Sunshine Coast 0 -> 22 (2026-09-02) - south-east Queensland, joining
Sydney and Byron on the `australia-east` basin.** Two boxes (Coolangatta-The Spit; Caloundra-Noosa),
`Australia/Brisbane` anchors on the Sydney recipe, the Australia extract symlinked twice. Primary
flow: 3 + 0 Tier-A (two duplicated web names and a "Ripcurl" brand node - skipped, as in Byron).
Secondary: 22 + 22 guide names -> all rendered -> 28 keep / 14 move / 2 drop over five rounds.
The cleanest pass yet: Australian suburbs geocode to their beach, so most pins were keeps; the
moves were points (Snapper, Greenmount, Burleigh, Currumbin Alley, Moffat, Alexandra Headland,
Noosa's First Point / National Park / Tea Tree / Granite) nudged from the sand onto the rocks
where the wave starts, and the Seaway pair (The Spit, South Stradbroke) placed either side of the
wall off a z14 read after Google returned the island for four different names. Eight normals set
by hand - the Superbank points came back facing W because their coastline ways run N-S along
the headland - and three Noosa points (National Park, Johnsons, Tea Tree) re-aimed NE by arc sweep
because their N/NW rays hit the Noosa North Shore at 18 km. Judge logs in `work/gold-coast/judge.json` and `work/sunshine-coast/judge.json`.
**Next in Australia:** Victoria (Bells, Torquay, Phillip Island), then Margaret River's north
(Geraldton, Kalbarri).


**East Java 0 -> 12 and West Java 0 -> 6 (2026-09-02) - Java's south coast in two boxes.** East =
Pacitan to G-Land, West = Sawarna to Pangandaran; Central Java (Parangtritis, Kebumen) is not
seeded. Same extract, same `indonesia` basin, `Asia/Jakarta` anchors. Primary flow: 830 + 637
bathy-passed candidates, 0 + 2 Tier-A (a surf-camp node and a generic "The Reef" node, both
skipped). Secondary: 13 + 13 guide names -> all rendered -> 12 keep / 7 move / 8 drop over three
rounds. **Google collapsed every Pelabuhan Ratu break onto Cimaja** (Karang Haji, Indicators, Karang
Papak, Karang Hawu, Cikembang, Loji - one coordinate for seven names) and every Pangandaran name
onto Batu Karas 13 km away; the z14 tile of the bay is river-plume and cloud, so only Karang Haji
could be placed and the other five were dropped rather than guessed - **the bay is the gap to close
next time, ideally from a guide with coordinates or a local**. G-Land came from the z15 read: the
three sections sit along one reef N->S (Kongs at the camp, Moneytrees mid-point, Speedies at the
tip - Google had Speedies NE of Kongs, backwards), each pin nudged onto its breaking line on a
second render. Eleven normals set by hand (Batu Karas and Teleng Ria came back facing N/E). Judge
logs in `work/east-java/judge.json` and `work/west-java/judge.json`. **Next in Indonesia:**
Mentawai, Sumba, Nias; **Pelabuhan Ratu detail** as a gap-fill.


**Lombok 0 -> 16 and Sumbawa 0 -> 9 (2026-09-02) - Indonesia's second and third regions, on the
Bali recipe.** Two boxes (Lombok whole island; Sumbawa's west and south coasts only - the north
is not surfed), both symlinked to the Indonesia extract and both on the `indonesia` swellmap
basin. The boxes overlap by 0.1 deg at 116.7-116.8 E, so Supersuck and Hook surfaced as Lombok
Tier-A too and were skipped there. Primary flow: 758 + 860 bathy-passed candidates and **10
Tier-A - the first regions where OSM carried the famous breaks** (Lakey Peak, Lakey Pipe,
Periscopes, Supersuck, Hook = Yoyo's, plus Mangsit, Montong and a Gili T node). Three of the
Lakey nodes sat on the beach rather than the wave and were re-placed as moves off the tile.
Secondary: 15 + 11 guide names -> all geocoded -> all rendered -> 4 keep / 17 move / 6 drop
over three rounds (Sumbawa's Lakey Pipe / Nungas took five: the three peaks sit 200-500 m
apart on one reef and Google gave them all the beach). Wide reads located Desert Point (Google
gave Bangko-Bangko village), the Gerupuk mouth (Outside Left / Right off the E headland) and
Ekas (village 1.5 km inland). Ten normals set by hand - the south-coast bays came back E/W - and seven more re-aimed by arc sweep:
Gili T's south ray hit Lombok, and the Lakey and Ekas rays hit the far side of their own bays at 18 km
(Cempi Bay and Ekas Bay both open SOUTH, so the seaward normal is SSW even though the beach faces W).
GEBCO reads Ekas Bay's inner reef as +6..+23 m for the first 3 km - the march drops those, judge on
the 18 km end. Towns are the surf towns (Kuta Lombok, Gerupuk, Ekas, Lakey, Sekongkang, Maluk) - all
overrides, `towns.py` not run on the 1.7 GB extract. Judge logs in `work/lombok/judge.json`
and `work/sumbawa/judge.json`. **Next in Indonesia:** Java (G-Land, Cimaja, Pacitan), Mentawai,
Sumba, Nias.


**Bali 0 -> 39 (2026-09-02) - the first Indonesian region.** One box (-8.90..-8.05, 114.45..115.75)
holding both coasts plus Nusa Lembongan / Ceningan; Java's tip and Lombok stay out for their own
regions. `bali.yaml` (`&bali`, reef, Asia/Makassar, west-coast defaults), new `indonesia` swellmap
basin, Geofabrik `asia/indonesia` (1.7 GB - the coastline stage and `towns.py` each take ~10 min;
run both in the background). Primary flow: 809 bathy-passed candidates, 75 named beaches, 5 Tier-A -
all skipped (two duplicated web names, one business node, one generic "Surf break" node, one the
Suluban beach). Secondary: 43 guide names -> all geocoded (Google alone on 38) -> all rendered at
z16 -> 17 keep / 22 move / 4 drop over four rounds, with z15 reads of Uluwatu-Padang, Bingin-Dreamland,
the airport reefs, Nusa Dua, Sanur, Lembongan and Ceningan. What was new: (1) **reef-pass country
like the Maldives, but with visible whitewater** - every Bukit and Nusa Dua peak could be placed on
a breaking line, and the sub-metre ESRI imagery showed the Kuta Reef / Airport Lefts / Airport Rights
peaks as three separate lines on one reef; (2) Google's Bali failure mode is the RESORT - Nusa Dua,
Sri Lanka, Mushrooms, Hyatt Reef, Dreamland and Keramas all returned a hotel or a field, and the reef
had to be found on the wide tile; (3) ten normals set by hand where the nearest coastline way ran the
wrong direction (Serangan, Black Stone and Sri Lanka came back pointing S/N on an E-facing reef; the
airport-lefts normal pointed N along the runway). Playgrounds took four renders (the reef's southern
tip, not the bay). All five Lembongan / Ceningan normals hit Bali across the Badung Strait at 18 km
(Shipwrecks -107 m) and were re-aimed SW by the GEBCO arc sweep - the island-shadow case again, one
strait wide. Dropped Jimbaran (Google -> Balangan cliff), Pekutatan (= Medewi), Ketewel and
Klotok (inland pins). Towns are the search keys surfers use (Uluwatu, Canggu, Nusa Dua, Nusa
Lembongan) - 39 overrides. `shipwrecks` clashes with Mexico's and took `-bali`. Judge log `work/bali/judge.json`. **Next Indonesian regions:** Lombok /
Sumbawa (Desert Point, Lakey Peak), Java (G-Land, Cimaja, Pacitan), Mentawai, Sumba, Nias.


**Perth 0 -> 34 and Margaret River 0 -> 28 (2026-09-02) - the first West Australian regions.**
Two `REGIONS` boxes like Sydney/Byron: Perth = Mandurah to Two Rocks plus Rottnest; Margaret
River = Cape Naturaliste to Cape Leeuwin. `perth.yaml` (`&per`, beach) and `margaret-river.yaml`
(`&mr`, reef) are the first WEST-facing anchors (swell_window [180,300], offshore from the E),
one shared `australia-west` swellmap basin, both pbf names symlinked to the 960 MB australia
extract (`towns.py` scans the whole file - ~5 min per region, run it in the background). Primary
flow: 398 + 257 bathy-passed candidates, **1 Tier-A** (an OSM `sport=surfing` node on a Mandurah
groyne, kept under its OSM name) - web-search country again. Secondary: 40 + 36 guide names -> all
76 geocoded (Google alone on 46) -> all rendered at z16 -> 35 keep / 26 move / 15 drop over three
rounds, with z15 reads of Marmion, Cottesloe, Gracetown, Prevelly and Gnarabup and z13/z14 reads of
Wilyabrup, Rottnest and Boranup. Same Google failure modes as Hawaii: whole clusters collapsed onto
one POI (Surfers Point / Southside / Gallows -> one pin; Huzzas -> South Point; Boranup / Hamelin ->
Redgate) and out-of-region returns (Rocky Point, Gallows, Guillotines -> Margaret River town; The
Spot -> Two Rocks; Transits -> Perth CBD). Dropped the sheltered Cockburn/Warnbro/Geographe bays,
the Rottnest reefs Google could not place, and the Bombie (no visual evidence on a small day).
Eight normals set by hand off the tile (Salmon Bay and Madora Bay came back pointing N), and four more
(Cottesloe, Isolators, The Cove, Leighton) re-aimed by the GEBCO arc sweep because their due-west ray
hit Rottnest at the 18 km reference (offshore 1-2 m - wet, so the test passed, but the island's shore).
The Perth shelf is genuinely 30 m deep 18 km out; that is not a warning. Three
global id clashes took `-wa` (`the-cove`, `windmills` vs Hawaii, `south-point` vs Sri Lanka).
64 town overrides - metro OSM place nodes resolve to Joondalup / Perth / Fremantle, and the whole
Capes stretch had none inside 12 km. Judge logs in `work/perth/judge.json` and
`work/margaret-river/judge.json`.


**Hawaii 1 -> 80 (2026-09-02) - Kauai, Oahu and Maui in one box; the Big Island is not
seeded.** `REGIONS["hawaii"]` = (20.50, -159.85, 22.30, -155.90), Geofabrik `north-america/us/hawaii`
(27 MB), the existing `hawaii.yaml` `&hi` anchor reused (its `ideal.wind_dir` is metadata only -
the scorer uses `offshore_direction`). Primary flow: 1,551 bathy-passed candidates, 217 named
beaches, **2 Tier-A** (Keaau Beach, Makapuu Beach Park) - web-search country like Australia.
Secondary: 87 guide names over 10 areas -> 86 queued -> 86 geocoded (Google alone on 55; Photon
gave Kaanapali for every West Maui query) -> all 86 rendered at z16 -> 36 keep / 41 move / 9 drop.
What was new: (1) **Google collapses a whole reef cluster onto one POI** - six Waikiki breaks
(Kaisers, Threes, Fours, Pops, Publics, Cunhas) all returned the Ala Moana Bowls pin, and the three
Hanalei reefs returned Hanalei town; the fix was a **z15 read** (4.4 m/px, 2.8 km field - between
z16 and the z14 pass-finder) of the reef, then z16 confirmation of each placement (`z15_tiles/`).
(2) **Island shadow**: seven West Maui / North Shore normals reached open water on the tile but hit
Molokai or Lanai at the 18 km reference (`honolua-bay -425 m`), so `test_committed_profiles_reach_
open_water` failed after `bathy` - re-aimed with a GEBCO arc sweep that picks the deepest 18 km
sample within 35 deg of the observed seaward (`kaanapali` 250 -> 284, `lahaina-harbor` 240 -> 210).
(3) Twelve more normals were inverted by the nearest coastline way running the wrong direction
(Kealia 76 -> 250, Kalapaki 99 -> 300, Hanalei 72 -> 150, Peahi 117 -> 200) - read every `od`
against the tile before `emit_region`, it is cheaper than re-cutting. (4) Two global id clashes
(`makaha` Peru, `shipwrecks` Mexico) took the `-hi` suffix. Drops: Backdoor (the Pipeline peak's
right, 50 m from the DB pin - a sub-spot), Gas Chambers (Google -> Sharks Cove), Fours/Cunhas
(sub-spots not separable at z15), Castles (Google -> Kailua's Castles), Ewa Beach (Google -> Pokai
Bay), Barbers Point, Kawela Bay and Kahana Bay (sheltered). 47 town overrides (Waikiki / Pupukea /
Diamond Head are the search keys, not "Honolulu"/"Waiale'e"). Judge log `work/hawaii/judge.json`.

**Fiji 0 -> 11 (2026-09-01)** - see commit `ae9ff7c`: bbox scoped to SW Viti Levu / Mamanucas /
Coral Coast / Beqa / Kadavu (176.7-179.0 E) so no spot crosses the antimeridian; the swellmap
basin's +3 deg padding did, and `basin_boxes` now clamps at the seam. Cloudbreak and Frigates
have no coastline within 2.5 km - the arc sweep is their only normal source.


**French Polynesia 0 -> 17 (2026-08-31) - the first Oceania island region; the Maldives
recipe, confirmed portable.** Society Islands + Rangiroa/Tikehau box only. What transferred:
0 usable Tier-A (but OSM's `Teahupoo Reef` node IS the break - use OSM surf nodes as pin
truth even when they miss the 450 m gate), Google returning villages for pass waves, the
island-centroid normal (nearest-candidate normals were 60-130 deg off on every pass wave),
island/commune names as towns. What was new: (1) **wide z14 renders are the pass-finder** -
Matauvau, Paopao, Rautoanui and Tuheiava were all located by eye off a 6 km tile after
geocoding failed, then pinned at z16; (2) a pass wave legitimately takes 3-4 renders -
budget for it; (3) vairao dropped on the two-strikes rule even though it is a Surfline zone
(three placements failed; Teahupoo covers the stretch); (4) the north-shore-of-a-round-island
case (Temae) breaks the centroid method too - the centroid ray pointed at Tahiti 14 km east;
the GEBCO arc sweep is the fallback. OPEN-ITEMS 23 blindness confirmed here (first wet
sample 29-476 m); do not chase it per-spot.

## 5a. Australia (as of 2026-08-31, DB = 685 spots)

**Sydney 0 -> 35 and Byron Bay 0 -> 26 (2026-08-31) - the first Australian regions.** Two
`REGIONS` boxes scoped to what was asked, not the whole NSW coast between them (Sydney = Palm
Beach to Garie in the Royal NP; Byron = Tweed Heads to Ballina), `sydney.yaml` / `byron-bay.yaml`
anchors (east-facing defaults: swell_window [25,155], offshore wind from the W), one shared
`australia-east` swellmap basin, one Geofabrik `australia` pbf (960 MB) symlinked to both region
names.
- **Primary:** 16,523 coastline ways -> 401 + 172 candidates -> **1 Tier-A each**, and both were
  dropped via skip.json: Sydney's "Bower" lost to the web name Fairy Bower (same break), and
  Byron's "Ripcurl" by the Tweed mouth is a brand-name node the business filter missed. Even
  Australia, the most OSM-mature surf country attempted, is web-search country.
- **Secondary:** 41 + 29 guide names -> geocode -> z16 render of all 70 -> judge: Sydney 26 keep /
  8 move / 6 drop / 2 requery, Byron 21 keep / 2 move / 3 drop / 1 requery. Every moved pin
  re-rendered; Salt Beach needed a second nudge off the resort roof.
- **What this pass taught:** (1) Google collapses metro sub-spots onto their parent beach pin
  (Dee Why Point/Beach, Cronulla Point/North Cronulla, The Peak/Newport, Narrabeen/North
  Narrabeen) - the reef/point half of the pair needs a hand move off the tile, or a drop when it
  is genuinely the same peak (North Steyne 320 m from Queenscliff, Kiddies Corner 180 m from the
  Palm Beach pin). (2) `boat-harbour-kurnell` failed both rounds (Google returns Silver Beach
  INSIDE Botany Bay, OSM's node is mid-peninsula) - dropped, the standing two-strikes rule.
  (3) **Eight shore normals came off the nearest coastline candidate pointing into a headland or
  across an estuary** (Byron's cape spots got the cape's own normal; Palm Beach got Pittwater) -
  the Peru GEBCO arc sweep re-aimed all eight, and `test_committed_profiles_reach_open_water` +
  `horizon --spot` caught every one. (4) `horizon`'s "blocked by land" flag fires on correct
  east-facing normals here (dee-why-beach at seaward 112, freshwater at 102 - open Tasman both):
  the API grid's nearshore noise, item 17's two-GEBCO dispute again. The local-grid sweep is the
  tiebreak; do not chase the flag when the sweep and the tile agree. (5) Towns needed 33 hand
  overrides out of 61 - metro OSM place nodes resolve to the municipal centre (all of the
  Northern Beaches read "Mona Vale", all of Cronulla read "Boat Harbour"), and the suburb IS the
  search key in a city.

## 5c. Earlier log (as of 2026-08-27, DB = 624 spots, ALL sat-verified)

**Maldives 0 -> 23 (2026-08-27) - the first atoll nation, and the recipe needed three changes
to work there.** New `REGIONS` box (the whole chain, Haa Alif to Addu - it is only ~130 km wide,
so one box is the country), `maldives.yaml` anchor with `break_type: reef` throughout, own
swellmap basin, Geofabrik `maldives` 3.6 MB.
- **Primary:** 1,367 coastline ways -> 2,924 candidates -> 2,712 bathy-passed -> **3 OSM surf
  beacons** (Raalhugandu on Male, a "Surfing Point" at Kandooma, an "eff one surf point" at
  Muli). Two of the three were dropped for a web name that a surfer would actually search.
- **Secondary:** 45 atlas names from five guides -> geocode -> z16 render of 36 -> judge:
  13 keep / 8 move / 15 drop, plus Ninjas reinstated from user-supplied coordinates. Every moved pin was re-rendered and read again; two of the ten
  moves failed on the second read and were dropped rather than nudged a third time.
- **What this pass taught, and it is mostly about where the standard recipe breaks:**
  (1) **Google collapses far harder in a country whose breaks are offshore reef passes.** Eight
  Gaafu Dhaalu names came back on ONE coordinate; five more landed on Cokes' pin. When a name
  is not in its index Google returns a generic nearby surf POI, so **the dedup rule needs an
  owner**: the name that holds a coordinate is the one that got it in round 1 without a
  requery; a requeried name landing on someone else's round-1 pin is the fallback and drops.
  A first pass that dropped by bare collision killed Cokes and Pasta Point - the two most
  famous waves in the country - and kept the impostors.
  (2) **The GEBCO arc sweep from the Peru pass does NOT work on atolls.** GEBCO's ~460 m cells
  do not resolve a 300 m-wide reef island, so the "widest unobstructed arc" reads 355 deg at
  Love Charms and 270 deg at Cokes - deep in every direction, no information. What DOES work is
  **the bearing away from the island's own coastline**: take every `natural=coastline` vertex
  within 2.5 km, inverse-distance-weight it into a centroid, and point the normal straight away
  from it. That agreed with every tile read this pass and fixed the four spots where the
  nearest single coastline candidate sat on the far side of the island.
  (3) **OSM place nodes are useless as towns here** - the whole North Male chain resolved to
  "Thulusdhoo" up to 11 km away, because the resort and uninhabited islands carry no settlement
  node. The island the break sits off IS the search key, and it came from the surf guides plus
  OSM hotel/attraction names on the tile (`Cinnamon Dhonveli` 271 m confirmed Pasta Point,
  `Jail Break City` 417 m confirmed Jailbreaks). 12 of 22 needed a hand override.
  (4) The same island-amenity check killed a spot: Ninjas' pin sat 850 m along Lohi's own reef
  on Hudhuranfushi while the guides put Ninjas at Club Med Kani. Two sources disagreeing is a
  drop, not a nudge.
  (5) **The committed profiles are honest but nearly blind** - see OPEN-ITEMS 23. 10 of 22
  Maldivian spots have a first wet sample deeper than 50 m (19 of the other 600 do), because
  GEBCO steps straight from island to 2,000 m. Do NOT fix this by appending shallow samples.

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

## 5d. Earlier log (as of 2026-08-16, DB = 265 spots, ALL sat-verified)
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
Wakayama detail (Okinawa and Tanegashima seeded 2026-09-03); Philippines more (Daku, Zambales Liwliwa neighbours); Portugal
Ericeira micro-spots & the **Azores**; Nicaragua north (Puerto Sandino cluster). Regions with
zero spots today: everywhere else - Indonesia beyond Bali / Lombok / Sumbawa / Java / Mentawai (Sumba, Nias, Rote), Ireland, Spain, Chile, Ecuador, France/Spain, South Africa;
Australia's remaining corners (Cactus / Eyre Peninsula, Kangaroo Island, Marrawah, Exmouth's Ningaloo reefs); Hawaii's Big Island.
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
- a truncated Geofabrik download reads as a small-but-plausible extract and only fails later at
  `unexpected EOF` → check the byte count against `Content-Length` (Mozambique, Tanzania).
- the coastline shore-normal points inland at a headland, bay mouth or spit, and `bathy` cuts a
  land profile without failing → run `aim_normal.py` after every emit (3c).
- a US town geocodes correctly to its civic centre, 1-2 km inland of the surf, so the break falls
  outside the z16 tile and reads as "no break visible" → zoom out to z13 BEFORE dropping (10 of 10
  recovered that way on the Jersey Shore and the Florida inlets).
- `ca_queue.py`'s `"{name} surf break {area} {REGION}"` template returns nothing for US names →
  query plain `"<place>, <state>"` there.
- `ca_xref.py` snapped "Playa de X" onto any OSM "Playa de Y" within 1.5 km, because `playa` / `de`
  were not stopwords (2026-09-10: 35 wrong-beach snaps across Spain). Fixed; a beach that shares the
  query's TOWN word can still match, so read every `osm:<name>` snap against the web name.
- parallel `render.py` runs collided on fixed ports → fixed, each run now takes free ports.
