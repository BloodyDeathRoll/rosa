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

## Where the loop lives - in this repo (2026-08-04)

The whole loop is rosa-side, driven from an interactive session. Three legs:

1. **Queue (deterministic)** - `tools/spot-verify/queue.py` picks the next batch of spots whose
   pin is not yet `user-verified`/`sat-verified` and not already judged
   (`tools/spot-verify/.state/judged.txt`), weakest-authority-first, and writes
   `work/<date>/queue.json` + `queue.md`.
2. **Render (deterministic, network)** - `tools/spot-seed/render.py --file work/<date>/queue.json
   --out work/<date>` shoots a crosshair tile per spot. Zero model cost.
3. **Judge (vision pass)** - a session reads the tiles per `tools/spot-verify/JUDGING.md`,
   presents keep/move/flag with a confidence and a reason, and on approval edits
   `data/spots/<region>.yaml`, retags `sat-verified <date>`, re-cuts the moved spot's bathy
   profile, and marks the batch judged. Nothing is applied without that approval.

**This was briefly scaffolded as a `rosa-spot-mapper` assignment in Dream (`~/Projects/Dream`),
the off-hours autonomous host. It was never registered, never ran, and was deleted 2026-08-04.**
Two reasons it came back here: the judgement is the part that benefits most from being
interactive (re-render, zoom, argue with an ambiguous coast, act on local knowledge in the same
breath), and applying a move has rosa-side consequences an isolated proposal file can't carry -
a moved pin invalidates its bathymetry profile and may invalidate its three coastline angles.
Dream's contribution would have been unattended scheduling at ~12 spots/week; a focused session
clears a region in an afternoon. If the DB later grows faster than sessions can keep up,
re-hosting the queue+render legs off-hours is the thing to revisit.

### Worldwide extension

Same loop, fed by the open seed layer from `docs/spot-db-research.md` (Overture + broad-OSM +
Wikipedia names). New regions enter as candidate `{name, rough coord}` rows; the mapper's job is
exactly to turn "rough coord near the named place" into "pin on the actual break," region by
region, proposing as it goes. The seed gives names + approximate location; the satellite loop
gives *accurate* coordinates. That is the practical, non-manual path to a worldwide spot DB.
