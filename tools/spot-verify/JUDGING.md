# Judging satellite tiles — the sat-verification procedure

The judge leg of the loop in `docs/spot-mapping-approach.md`. Rendering is deterministic;
this step is a **vision pass** — a person or a Claude session looks at each crosshair tile and
decides whether the pin is on the actual break. Run it in a session rooted at this repo.

## Run the loop

```bash
python3 tools/spot-verify/queue.py --status                  # what's outstanding, per region
python3 tools/spot-verify/queue.py --batch 12 [--region israel]
python3 tools/spot-seed/render.py --file tools/spot-verify/work/<date>/queue.json \
                                  --out  tools/spot-verify/work/<date>
# ← judge the tiles (below), apply approved moves, then:
python3 tools/spot-verify/queue.py --mark tools/spot-verify/work/<date>/queue.json
```

`queue.py` skips spots already tagged `user-verified` / `sat-verified` and those recorded in
`.state/judged.txt`, so successive batches walk **through** the DB instead of re-judging the
same 12 spots. It orders weakest-authority-first (approx → osm → websearch → geocoded).
Read `work/<date>/queue.md` for the batch's current coordinates and source tags.

## Inputs

- `work/<date>/<id>.png` — ESRI World Imagery centered on the spot's **current** coordinate,
  red crosshair on that exact point, ~zoom 16.
- `work/<date>/queue.md` — id · name · region · current lat,lon · current source.

## What a correct surf-spot coordinate looks like

A break sits at the **water's edge on a surfable coastline** — sandy beach, reef, point,
jetty/harbor wall. The crosshair should land ON that shoreline, NOT:

- in open water offshore (coordinate too far to sea),
- inland — streets, parking lots, buildings, fields,
- on the wrong feature for the name (a marina's inner basin when the spot is the beach break
  outside the wall).

Use the spot NAME as a strong hint (a "Marina" spot is by the harbor; a "Caesarea"/"Aqueduct"
spot is by the visible Roman structures; a plain beach name is the open sandy stretch).

## Decide, per spot

- **keep** — crosshair is already on the break (within ~50 m). No correction.
- **move** — crosshair is off. Read the offset off the image: the tile is 640 px at zoom 16,
  which spans **0.01373° of longitude** (2.146e-5 ° per px) and that times cos(latitude) of
  latitude — about 1.5 km across, centre at (320, 320). North is up. Move to the shoreline of
  the named feature. **If the coast is out of frame, do not extrapolate**: re-render wide
  (`--zoom 13`, or 10 for a pin kilometres out), pick a coordinate off that, then **re-render it
  at z16 to confirm before proposing it.** A z13 eyeball alone put 4 of 10 pins in the wrong
  place on the 2026-08-04 batch; every one was right after one confirm pass.
- **flag** — genuinely can't tell (cloud, ambiguous coast, name matches nothing visible).
  **Do not invent a coordinate.** Leave the pin, note why, and let the next pass or local
  knowledge settle it.

Give each a confidence 0.0–1.0 that the NEW coordinate is on the break.

**Be conservative.** If unsure whether a small offset matters, `keep`. Only `move` when the pin
is clearly wrong. A confident wrong move is worse than a keep — it silently outranks the tag it
replaces.

## Present, then apply

Show the batch as a table — id, action, old → new, confidence, one-line reason — and get
approval **before editing any YAML**.

A **`keep` still gets retagged** `# sat-verified <date>` — the pin WAS checked against imagery, and
that is what the tag records. Only the coordinate is unchanged, so a keep skips the bathy re-cut and
the horizon re-derive below. Leaving a keep tagged `approx` strands it a rung too low on the
authority ladder and makes the next `--status` read it as unchecked. `flag` rows change nothing.

For each approved **move**, in `data/spots/<region>.yaml`:

1. Update `lat`/`lon` to 4 decimal places.
2. Retag the line `# sat-verified <date>` (per the authority ladder in `docs/SPOT-DB.md`:
   user-verified > sat-verified > OSM > google-geocoded > approximation). A user pin always
   wins — never overwrite `user-verified`.
3. **The pin moved, so its bathymetry profile is stale.** Delete
   `data/spots/derived/bathy/<id>.json` and re-cut it: `rosa-pipeline bathy --spot <id>`.
   Never leave a profile cast from the old pin (`test_committed_bathy_profiles_match_their_spots`
   enforces this).
4. A materially different position may also invalidate the spot's three coastline angles
   (`shore_normal`, `offshore_bearing`, `offshore_direction`) — they are guard-tested against
   each other. Re-derive the swell window with `rosa-pipeline horizon --spot <id>` and apply the
   adoption rule in `docs/SPOT-DB.md`.

Then run `queue.py --mark` so the batch doesn't come back, and commit — spot moves are
`data:` commits; `.state/judged.txt` rides along. `work/` is gitignored (tiles are regenerable,
and ESRI imagery is build-time verification only, never redistributed).
