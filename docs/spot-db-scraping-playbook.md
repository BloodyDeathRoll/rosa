# Rosa Spot-DB Scraping Playbook

**Purpose.** Build Rosa's own exact, worldwide surf-spot database, region by region,
over a long period. This is the moat. It does **not** need to be fast — it needs to be
**exact, and exact about *locations* above names.** A wrong name is a cosmetic fix; a
wrong pin silently poisons every forecast for that spot. Work in chunks; verify everything.

> **Iron rule (from `docs/spot-mapping-approach.md`): from-memory coordinates are fake.**
> Every coordinate that enters the DB must be either coastline-geometry-derived, geocoded
> **and** sat-verified, or user-verified. Never type a lat/lon from knowledge. This session
> proved it twice — a from-memory "Uchiumi" landed on an inland river town; "Monaliza" on
> open water. The geocoder+render caught both.

## Authority ladder (coordinate trust, highest first)
`user-verified` > `sat-verified` (ESRI crosshair, human/vision judged) > `geocoded+rendered`
(multi-provider agreement, then sat-verified) > `osm-name-confirmed` > `coastline-generated`
> `approximation`. Never let a lower tier overwrite a higher one. Tag every spot with its tier.

---

## 0. One-time foundations (download once, never again)
The whole pipeline runs **offline** — no request-time API caps, no Overpass roulette. Both
big datasets are gitignored (`data/bathy/`, `data/osm/`).

- **Local GEBCO grid** — `data/bathy/GEBCO_2024.nc` (~7.5 GB, 15 arc-sec global). Sampled by
  `tools/spot-seed/local_bathy.py`. Replaces the OpenTopoData API (1000 calls/day cap).
  Redownload: the CEDA direct link the GEBCO/BODC portal redirects to (`GEBCO_2024_CF.nc`).
- **Local OSM Geofabrik extracts** — `data/osm/<region>.osm.pbf` per country
  (`download.geofabrik.de/<continent>/<country>-latest.osm.pbf`). Read by
  `tools/spot-seed/osm_local.py` (pyosmium). Replaces Overpass (which 504s under load).
- **Tool venv** — `tools/spot-seed/.venv` (`uv venv` + `uv pip install netCDF4 numpy osmium pyyaml`).
  Run every tool with `tools/spot-seed/.venv/bin/python`.
- Headless render needs `google-chrome` + `node` (already present); tiles via
  `tools/spot-verify/shoot.mjs`.

## Tooling map (`tools/spot-seed/`)
| file | role |
|---|---|
| `seed.py` | **primary pipeline** CLI: coastline → generate → bathy-prune → OSM-validate → tier + review |
| `coast_generate.py` | coastline→candidate geometry (segment, shore-normal, openness) — pure helpers reused by seed |
| `bathy_gate.py` | seabed pruning + `destination()` / `gebco_elevations()` (API path) |
| `local_bathy.py` | local GEBCO sampler (`--bathy local`, default when grid present) |
| `osm_local.py` | local Geofabrik extractor (`--osm local`, default when pbf present); applies `is_business` |
| `osm_seed.py` | `BIZ_NAME_RE` + `is_business()` (tag AND name business filter, multilingual) |
| `render.py` | **sat-verify**: renders ESRI crosshair tiles for candidates → read+judge |
| `multi_geocode.py` | secondary: Google Places + Nominatim + Photon, agreement-spread cross-check |
| `emit_spots.py` | turn a region's reviewed `result.json` into DB YAML (offshore_point/swell derived) |
| `work/<region>/` | cached stages: coastline / candidates / bathy / beacons / result.json (resumable) |

---

## 1. PRIMARY FLOW — coastline generation (comprehensive, physics-first)
Generates the candidate-break *universe* from the coast itself, then confirms names via OSM.
Comprehensive by construction; OSM only **confirms/names**, never rejects (its absence ≠ absence).

```
tools/spot-seed/.venv/bin/python tools/spot-seed/seed.py <region> --osm local --bathy local
```
Stages (all cached under `work/<region>/`):
1. **coastline** — `natural=coastline` ways from the local pbf (whole country; scoped to the
   region's surf bbox after generate).
2. **generate** — resample every ~400 m; shore-normal from OSM way direction (water on the
   right) → `offshore_direction` (= inland-pointing normal, the wind-FROM azimuth). **O(n)
   spatial-grid clustering** (an O(n²) all-pairs check chokes on Japan's 106k / Philippines'
   23k coastline ways).
3. **bathy prune** — march a seaward transect on the local GEBCO grid; drop land-on-ray
   (enclosed/inland), mudflat, no-shelf. GEBCO 15" is noisy in the first ~500 m → judge on the
   **1–3 km shelf band**, not near-shore slope. **Recall gate: must keep ~all known spots**
   (validated 40/40 on Israel).
4. **OSM validate** — surf beacons (`sport=surfing` + named `natural=beach`), business-filtered.
   Tier **A** (a surf beacon within ~450 m → confirmed + named), **A-** (named beach), **B**
   (physics-valid, unnamed → sat-verify/community later).
5. **review** — name-aware dedup: `have` (name-match or <400 m), `pin correction` (same name
   **and** <5 km), `new distinct`. Emits `result.json`.

Then **sat-verify** every *new* candidate before adding:
```
tools/spot-seed/.venv/bin/python tools/spot-seed/render.py <region>      # tiles → work/<region>/tiles/
```
Read each PNG; keep only crosshairs on surfable coast (beach/reef/point at the water's edge).
Add with `emit_spots.py` (osm-seeded block, ODbL attribution, `TODO verify`).

## 2. SECONDARY FLOW — web-search discovery (catches famous-but-unmapped)
OSM is sparse where surfers didn't map (Latin America, much of the Philippines). Surf guides
name the real spots. This flow fills that gap.

**Phase 1 — country.** Web-search each country several ways and extract *areas* + spot names:
- `best surf spots and surfing regions in <country> for beginner intermediate advanced`
- `complete surf guide <country>` · `surfing in <country>` · `top surf beaches <country>`

**Cross-reference** the found names against the DB (fuzzy token match, accent-fold, drop
surf/geo stopwords). Matches = validated coverage; misses = gap queue. (This session: Costa
Rica 9/9, Israel 6/6, Sri Lanka 6/6 confirmed complete; gaps found in PT/JP/PH/NI.)

**Phase 2 — area.** For each gap area, search again:
- `best place to surf in <area>, <country>` · `surfing <sub-region>` · `<area> surf spots list`
Extract the specific break names.

**Locate — multi-geocoder + render (the exactness core).**
```
GOOGLE_MAPS_API_KEY=<from .env.local> tools/spot-seed/.venv/bin/python tools/spot-seed/multi_geocode.py
```
- Query **Google Places** (best POI), **Nominatim**, **Photon** (both free/keyless).
- **Agreement spread** is the confidence signal: <1 km = trust; ~2 km = must sat-verify to
  pick; >5 km = one provider is wrong (this session: Uchiumi spread 27 km — Google returned
  Aoshima). Google often returns the *town or resort POI, not the peak* → render to refine.
- **Render + sat-verify EVERY result** (`render.py --file`); correct the pin off the tile or
  drop. Only sat-passed spots get added.

Add via a `websearch-seeded` block (provenance + `TODO verify`).

---

## 3. Quality gates (never skip — this is where "exact" lives)
- **Render before every add.** No coordinate enters the DB unseen on satellite. Non-negotiable.
- **Multi-source or geometry for coords.** Single-source or from-memory = not allowed.
- **Business filter** (`is_business`, tag AND name, multilingual): drops surf schools/shops/
  hostels/kitesurf/dive/`clube`/`lounge`/`centro`/`escola`/… Surf schools mark a break but are
  never a spot *name*. (They can be a weak proximity beacon, but not a name.)
- **Dedup discipline.** Name-token + distance. Hold **sub-spots** (Ahangama Bay ≠ our Kabalana;
  Praia do Baleal beach ≠ Lagide reef) and **spelling variants** (kizakihama ≠ our kisakihama)
  — surfacing them as "new" or "correction" is usually wrong.
- **"Corrections" are guilty until proven.** A flagged pin move is real only if the OSM feature
  is the **same spot** (exact name) AND <5 km AND not a sub-spot/second node on a long beach.
  This session: 0 of ~10 flagged corrections were genuine (Shichirigahama had two OSM nodes and
  our pin sat between them; Weligama→Marriott and Baleal→beach were different spots). **Never
  move a good pin on a weak match.**
- **offshore params, derived not guessed.** `offshore_direction` from coastline geometry (the
  shore normal). `offshore_point` pushed ~5 km along the seaward normal to open water — per
  region convention (Israel/Portugal push W; Japan/Philippines-Pacific push E; the YAML loader
  default is 0.06° **W**, correct only for W-facing coasts). `swell_window` ≈ seaward ± ~65°,
  or the region anchor's default. All `TODO verify` until calibrated.
- **Provenance tag** on every seeded spot; OSM-derived carries `© OpenStreetMap contributors,
  ODbL`. A DB built by correcting/extending OSM is a Derivative Database → publish ODbL.

## 4. Chunked, long-running workflow
- Do **one region (or one gap area) at a time**; the `work/<region>/` cache makes every stage
  resumable and re-runnable cheaply (`--fresh <stage>` forces a refetch).
- After each chunk: `uv run --project pipeline python -c "…load_spots…"` to confirm it parses,
  then `cd pipeline && uv run pytest -q`. Commit per region (`data(spots): …`).
- Keep the primary and secondary flows **both** running on a region — they find different
  spots (primary = comprehensive coastline incl. unnamed Tier-B; secondary = famous named).

## 5. Session log & queue (as of 2026-07-24, DB = 188 spots)
**Done (generation + web-search seeded):** Sri Lanka 16→31, Portugal 16→40, Japan 17→24,
Philippines 12→16, Nicaragua +1 — all coordinate-verified.
**Validated already-complete:** Costa Rica, Israel (OSM/curation solid; web cross-ref clean).
**Held (need better locate before add):** La Union Monaliza Point & Carrile Point (fuzzy vs
`san-juan-la-union`); Uchiumi (geocoder failed — needs a Nichinan-coast query or manual sat pin).
**Next gap queue:** Japan Hokkaido / Okinawa / Wakayama detail; Philippines more (Daku, Zambales
Liwliwa neighbours); Portugal Ericeira micro-spots & the **Azores**; Nicaragua north (Puerto
Sandino cluster).
**The real frontier = Tier-B.** Tens of thousands of physics-valid, *unnamed* coastline
stretches (Japan 22k, Philippines 37k). OSM/guides never named them; this is the sat-verify +
community-contribution layer, and it's where "all the spots" ultimately lives.

## 6. Common failure modes (seen this session — don't repeat)
- from-memory coords → inland/offshore (Uchiumi, Monaliza). Always geocode+render.
- business leakage when the extractor skips the tag+name filter (Portugal "G3 Store", "Koala
  Surf School" surfaced as spots until `is_business` was applied in `osm_local.py`).
- name-match over-merge without accent/`Praia`/`Playa` stopwords → garbage 68 km "corrections".
- O(n²) clustering hangs on 100k-way coastlines → use the spatial grid.
- whole-country coastline explodes candidate counts → scope to the surf bbox.
- external API caps/flakiness (Open-Meteo, OpenTopoData, Overpass) → the local grids above.
