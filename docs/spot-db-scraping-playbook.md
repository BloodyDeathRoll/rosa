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

## 5. Session log & queue (as of 2026-09-03, DB = 1253 spots, ALL sat-verified)

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
