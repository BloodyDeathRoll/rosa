# Spot mapping: the satellite-verification loop (2026-07-20)

## The problem, precisely

Accurate surf-spot coordinates can't be looked up from any single source:

- **From-memory coordinates are fake** (the original sin - the whole seed set).
- **OSM beach-polygon centroids are the wrong semantic layer** - the centroid of "Yordei Yam
  beach" is not the Zvulun surf peak (the Herzliya error).
- **Geocoders fail on surf vocabulary** - Nominatim returns `[]` for "Beit Yanai Beach"
  (verified 2026-07-20). Surfer names aren't in general gazetteers.

What *does* work is what a human does: **look at satellite imagery and place the pin on the
actual surf coastline.** Shahar verified all of Herzliya that way by eye. This doc automates it.

## The loop (proven 2026-07-20)

For a candidate `{id, name, lat, lon}`:

1. Render ESRI World Imagery centered on the coordinate with a red crosshair at the exact
   point (`tools/spot-verify/satverify.html`, screenshotted headless).
2. A vision model looks at the tile and judges: is the crosshair on a surfable coastline
   (beach / reef / point at the water's edge), in open water, or inland? If off, where should
   it move?
3. Emit a proposed correction with a confidence and a one-line reason. **Never auto-applied** -
   a human approves (Rosa's authority ladder: user-verified > sat-verified > OSM > approximation).

Proof from the first run:
- `sdot-yam` @ (32.494, 34.881) → crosshair in **open water**, ~1 km offshore. Caught instantly.
- corrected → (32.497, 34.891) → crosshair on the **Caesarea harbor/reef** coastline. ✓
- `beit-yanai` (OSM control) → crosshair on the **beach water's edge**. ✓ (good coords pass)

ESRI World Imagery is used for **build-time visual verification only** (the automated equivalent
of eyeballing a satellite map) - never redistributed. Basemap for the shipped app stays
CARTO/OSM per the app's own attribution.

## Why this scales where manual entry doesn't

The judgment per spot is seconds of looking, and it's the same judgment every time - ideal for
a patient autonomous agent. Run it over the whole spot DB, worldwide, as an off-hours batch that
proposes a correction queue for one human approval pass. That is the Dream assignment below.

## Utilizing Dream - `rosa-spot-mapper` assignment

Dream (`~/Projects/Dream`) is the off-hours autonomous host: budget-gated `claude -p` steps,
persists to disk, **proposes changes for human approval** (its core principle, which is exactly
Rosa's authority ladder). Assignments may use the network (wtw-catalog does) - no sandbox needed
here since the mapper runs no untrusted code.

Two phases per run (split so the deterministic part costs zero model quota):

1. **Render (deterministic, network, zero quota)** - `run.sh` calls
   `tools/spot-verify/run-local.sh` to shoot a crosshair tile for each queued spot into
   `work/<date>/`. Queue = spots not yet `user-verified`/`sat-verified`, lowest-confidence first.
2. **Judge (claude step, Read PNGs + Write proposals only)** - the model reads each tile +
   current coord and writes `proposals/<date>/corrections.yaml`:
   `{id, old:[lat,lon], new:[lat,lon], confidence, reason}`. It NEVER edits `data/spots/*.yaml`.

**Approval** - a `spot-map-apply.sh` (mirrors Dream's `review-apply.sh`) shows before/after tiles
side by side; on confirm it patches the YAML and tags the spot `sat-verified <date>`. Nothing
auto-commits.

Cadence: **weekly** (slow-burn curation, not nightly). Priority below the Phase-1 assignments.
Registry entry ships `enabled: false` - enable after one manual `start-dreaming`-style test run
and a look at the first proposals batch.

### Worldwide extension

Same loop, fed by the open seed layer from `docs/spot-db-research.md` (Overture + broad-OSM +
Wikipedia names). New regions enter as candidate `{name, rough coord}` rows; the mapper's job is
exactly to turn "rough coord near the named place" into "pin on the actual break," region by
region, proposing as it goes. The seed gives names + approximate location; the satellite loop
gives *accurate* coordinates. That is the practical, non-manual path to a worldwide spot DB.
