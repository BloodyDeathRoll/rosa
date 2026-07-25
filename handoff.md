# Session Handoff - 2026-07-25

## Goal
Fix the forecast's energy column (wrong unit, wrong period), then act on a batch of
user-supplied spot corrections across Israel/Sri Lanka/Japan, and add live cams where
they can be embedded without asking anyone's permission.

## Current State
- **Everything is committed and pushed** except one line in `.gitignore` (adds
  `coordinates.md` alongside `cameras.md`). 10 commits this session, `ea39f07..65f8041`.
- **239 pipeline tests green**, ruff clean, `tsc --noEmit` clean, web builds.
- **Web is deployed** (`rosa-r38p0uwx1`, aliased to rosa-rust.vercel.app).
- **CRITICAL: none of the data work is live yet.** The published payloads are still the
  188-spot set generated 08:36 UTC. The **14:20 UTC cron** is the first cycle that pulls
  today's commits. Until it runs: new spots absent, moved spots on old pins, no cams.
  The user was told to expect it by ~17:35 IDT. If it did not run, check
  `deploy/oracle/publish.sh` on the VM (82.70.218.149).
- Spot DB: **193 spots** (israel 42, sri-lanka 32, japan 23, portugal 40, costa-rica 25,
  philippines 16, nicaragua 15). **149 bathy profiles**; 44 spots still have none.
- 7 spots have live cams. Verified embeddable but **never eyeballed in a browser**.

## Active Files
- `pipeline/src/rosa_pipeline/transform.py` - new `energy_period()` + `energy_kj_per_m()`.
- `pipeline/src/rosa_pipeline/publish.py` - `energy_kj` per hour, `energy_kw` in
  `spectral.missed[]`, `spot.cam`, `cam` id in index.json.
- `pipeline/src/rosa_pipeline/models.py` / `spots.py` - `SpotCam` + loader (raises if a cam
  lacks `by`/`by_url`).
- `data/spots/{israel,sri-lanka,japan}.yaml` - the corrections; japan+portugal carry cams.
- `data/spots/derived/bathy/` - 16 profiles cut/re-cut, 3 orphans deleted.
- `web/src/pages/SpotPage.tsx` - `CamEmbed` (first element), peak period, kJ column, info icon.
- `web/src/pages/AboutPage.tsx` - `ReadingTheForecast` glossary, route `#/about/reading`.
- `web/src/pages/MapPage.tsx` + `styles.css` - cam still on map cards, LIVE CAM chip.
- `docs/CALIBRATION.md` - 2026-07-25 Hilton entry.

## Changes Made This Session
1. **Energy column rewritten.** It published `0.49*H^2*T` kW/m keyed on the MEAN period.
   Now `0.98*H^2*Te^2` kJ per metre of crest, Te = `0.9*peak_period` (mean only as
   fallback). Hilton went 6.1 -> 119. A test asserts the identity `E*L = 2*P*Te` so the
   two forms cannot drift.
2. **Keys renamed** `energy` -> `energy_kj` (hour) and `energy_kw` (missed band), because
   one name meant two units. This was breaking: production called `energy.toFixed(1)` and
   would have thrown. A `?? h.energy` shim carried the transition; **removed after
   verifying the 08:20 cycle published `energy_kj`** (values 126/133/119/107/98/83).
3. **Peak period now displayed everywhere** (hourly column, Today card, Period bar input).
   Scoring still consumes the MEAN period. This divergence is DELIBERATE and documented in
   CLAUDE.md section UI - do not "fix" it by unifying them.
4. **Glossary page** `#/about/reading`, linked from Profile and an info icon over the
   hourly table's rating rail. Explains every data point including the mean/peak split.
5. **950 dashes replaced** (810 em, 140 en) across 89 tracked files. User preference,
   saved to memory. Write plain hyphens from the start.
6. **Spot corrections** (all user-supplied DMS, verified to 0.0 m against the YAML):
   Israel +Maaravi/Reading/Kshatot/Manao Neurim, moved Dolphinarium, removed
   herzliya-marina + metzitzim, renamed acadia -> "The Marina (Herzliya)" (id kept).
   Sri Lanka: replaced the coarse ahangama-kabalana pin with South Point/Kabalana/Sticks/
   Marshmallow/Gas Station, removed momos + cove, Weligama renamed+moved, Hiriketiya moved,
   weligama-west renamed "Coconut". Japan: +Kaeda Kako/Kodomonokuni, moved Aoshima,
   **corrected the existing kisakihama pin** (it sat S of Aoshima; it is N).
7. **Bathymetry**: 16 profiles cut. Verified the physics, not just the files - South Point
   renders 1.0-1.4 m vs neighbouring Koggala 1.1-1.6 m on the same swell.
8. **Bay shore-normals** from user-drawn map arrows: hiriketiya 172, weligama 209, set as
   explicit `shore_normal` while leaving `offshore_direction` alone (beach faces S so N wind
   is still offshore; the swell's path is the bay mouth - the arugam-bay precedent).
   Weligama's deep reference dropped 1512 m -> 558 m.
9. **Live cams**: 7 spots (nazare-norte, kugenuma, chigasaki, hebara, shirahama-izu,
   kamogawa-malibu, tsurigasaki). All public YouTube live streams, each verified via oEmbed
   (200 = embeddable). Embedded as the first element on the spot page with a credit line
   linking the channel. Map cards show the YouTube still + a LIVE CAM chip.

## Failed Attempts
- **Automated bay shore-normal detection does not work.** Built a 360-degree GEBCO scan
  (max-of-min-depth along the ray). It could NOT reproduce either hand-drawn arrow
  (proposed 195 for weligama vs the user's 209; no change for hiriketiya) and wanted a
  70-degree swing at aoshima that is an artifact of the pin sitting beside Aoshima island.
  Inside a bay every bearing hits a land-classified GEBCO cell, so the objective ranks grid
  resolution, not geometry. **Do not apply it. Ask for a map arrow instead.**
- **Land-sample warnings on bathy profiles are NOT fixable by re-aiming the ray.** GEBCO
  cells are ~460 m and Hiriketiya's bay is ~400 m across, so it reads as land whichever way
  the ray points. 30 previously committed profiles already had them;
  `wet_depths_deep_to_shallow()` drops them. Not a bug.
- **WebFetch cannot inspect any cam site** - beachcam.co.il, webcamtaxi, beachcam.meo.pt,
  lankasurf all render players in JS, so the HTML is navigation only. YouTube oEmbed +
  `youtube.com/results?...&sp=EgJAAQ%3D%3D` (ytInitialData JSON) answered it without a
  browser. **No Chrome/browser tool is exposed to this session** despite the user having a
  Claude Chrome extension running.
- **A python filter removed both Aoshima lines** because my replacement comment contained
  the same phrase as the match pattern. Re-added by hand. Check filter patterns against the
  text you just wrote.
- Cams for Israel/Costa Rica/Sri Lanka/Nicaragua/Philippines/rest of Portugal all sit
  behind operator-owned players. They need a partnership and the user has ruled out
  outreach for now. Surfline covers many of the same spots and is a hard legal red line;
  the search script filters it by channel name.

## Next Step
1. **Verify the 14:20 UTC cycle published cleanly** (this is the gate on everything):
   `curl -s https://rosa-data-opal.vercel.app/data/index.json | python3 -c "import json,sys; d=json.load(sys.stdin)['spots']; print(len(d), 'reading' in d, d.get('chigasaki',{}).get('cam'))"`
   Expect `193 True OJYcNsIpyx0`. Then eyeball a cam spot page and a map card.
2. Commit the pending `.gitignore` line.
3. **Ask the user for map arrows** on the 11 bay spots still on derived normals:
   unawatuna, fishermen, onjuku, okuragahama, isonoura, shizunami, pagudpud, sabang-baler,
   matosinhos, arrifana, acadia. `fishermen` is the most suspect (derived 78 = ENE from an
   osm-seeded offshore_direction of 258).
4. **~07-30, Stage 2E** (archive-gated): the Hilton 2026-07-25 entry in docs/CALIBRATION.md
   is the first eye-verified data point and it says the hybrid breaker **under-called 1.6x**
   (0.5-0.8 m predicted vs 1.0-1.2 m observed, on Hs 1.5 m / Tp 8.4 s / Tm 5.9 s). Opposite
   sign to rows 1-2. Pre-registered question: is `period_rideability` keyed on Tm the cause?
   Any fix must satisfy BOTH regimes.
5. Smaller: rescale the Period bar (`min(1, per/9)` in SpotPage `DayBars` saturates now that
   it reads peak periods, ~/13); re-derive the borrowed `offshore_direction` on the 14 new
   spots; 44 spots still lack bathy profiles.
