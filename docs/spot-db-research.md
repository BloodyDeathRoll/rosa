# Spot database: worldwide source-of-truth research (2026-07-19)

Deep-research pass on open/licensable worldwide surf-spot data sources. Verification status
noted per finding: **[verified]** = adversarially confirmed against the primary source (3-vote);
**[primary-source]** = extracted directly from the cited primary source but the verification
votes were cut short by a usage limit — treat as reliable, re-check before betting the company.

## Headline finding

**There is no adequate open worldwide source of truth for surf breaks.** Every existing option
is either too sparse (OSM, Wikidata), or proprietary (WannaSurf, Surfline). This is *why* the
spot DB is the long-term moat. The viable strategy is to build one — openly.

## The candidates

### OpenStreetMap — best open seed, far too sparse alone
- `sport=surfing` has only ~1,217 uses worldwide (799 nodes, 31 relations, 387 areas) vs.
  ~10k+ known breaks. [verified — tagfinder.osm.ch]
- The tag marks "any physical feature related to surfing": raw extracts mix breaks with surf
  shops, schools, beaches, reefs — co-tag filtering required. [verified]
- No first-class "surf break" entity; tag rides on beach/reef/facility geometries.
  [primary-source — OSM wiki]
- BUT: where surf nodes exist they are often true break markers placed by surfers (the Israeli
  `#S*` nodes anchored our Backdoor fix). Quality where present is good; coverage is the problem.

### WannaSurf — the right data, locked
- 9,511 spots, 181 countries, 6,262 GPS waypoints, surfer-vocabulary names — the largest
  dedicated atlas. [verified]
- All-rights-reserved, no open license, no API/dump/export. NOT legally reusable without an
  explicit agreement from Wannasurf.com ltd. [verified]
- → It is a *licensing target* (small operator, plausibly receptive), not a source to ingest.

### Wikidata — ontology exists, coverage is a joke
- `surf spot` class exists (Q2368508). [primary-source]
- Live SPARQL 2026-07-19: **48 instances worldwide, zero in Israel/Levant** — famous waves only
  (Pipeline, Mavericks, Teahupo'o…). Useless as a source; fine as ontology glue / ID linking.
  [primary-source]

### Explicitly NOT usable
- **Surfline/MSW**: ToU prohibit scraping/automated extraction; all content incl. "data" and
  "API data" asserted proprietary; user license is personal, display-only, revocable.
  [primary-source — surfline.com/terms-of-use] (Also a Rosa legal red line regardless.)
- **WannaSurf without an agreement**, and all the webcam/spot aggregator sites (they re-frame
  others' data and confer no rights).

## Licensing mechanics that shape the strategy (OSMF guidance, primary-source)

- OSM is ODbL: share-alike for data. A DB built by *correcting/extending* OSM data is a
  **Derivative Database** → must be ODbL when published.
- A **Collective Database** (OSM columns cleanly segregated from non-OSM columns) escapes
  share-alike for the non-OSM part — but mixing user-corrected values into an OSM-sourced
  column breaks that separation.
- Rosa's `israel.yaml` already interleaves OSM coords with user corrections → it is effectively
  a derivative. The clean answer is also the strategically right one:

## Recommendation (ranked)

1. **Build and publish Rosa's spot DB as an open ODbL dataset** ("open surf spots"), seeded from
   OSM (all surf-related tags + beach/reef co-tags + surf-school anchors), enriched region by
   region exactly like the Israel pass (authority ladder: user-verified > OSM > approximation,
   already in CLAUDE.md). Openness converts the "not practical to rely on users" problem into
   an OSM-style commons: contributors maintain a shared public dataset rather than doing Rosa a
   favor. Contribute corrections back into OSM (`sport=surfing` nodes) so the commons compounds.
2. **Email WannaSurf for a license** — the only worldwide surfer-vocabulary atlas that is
   plausibly licensable. One agreement would legally seed the world map (9.5k spots).
3. **Wikidata/Wikipedia** as ID-linking and notability glue only.
4. Follow-up not yet investigated: Overture Maps places layer (likely POI-centric, low hope);
   national coastal-recreation open datasets (AU/NZ/US state GIS) for regional enrichment.

## Ingestion sketch for #1 (next session)

Overpass worldwide pull of `sport=surfing` + co-tagged beach/reef features → per-region YAML
skeletons with `source:` tags → name-reconciliation against Wikidata/Wikipedia lists → publish
dataset repo under ODbL with attribution stack ("© OpenStreetMap contributors" + contributors)
→ regional curation passes (the Israel model) → periodic OSM re-sync that respects the
authority ladder (never overwrite user-verified).
