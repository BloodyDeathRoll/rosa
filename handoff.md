# Session Handoff — 2026-09-10

## Goal
Fix two desktop-map complaints, then work the accuracy backlog (bathymetry source swap,
coastal wind correction) — which uncovered a live production physics defect. Then stand up
Google Analytics 4 end to end.

## Current State
Everything below is committed and pushed to `main`; `web` is deployed to rosa.surf and the
pipeline change ships on the VM's next cron cycle. Suite green at 601.

**Working and verified live:**
- Desktop map: `+`/`−` zoom fabs (wide screens only); the world-zoom freeze is fixed.
- Forecast data is fresh again — the publish cycle had been dead for 55 h.
- Friction domain limit `kdtaper` at kd 0.6 is SHIPPED: 63 spots that published flat now
  read real surf. Heights moved **up only**; Israel +0.04 m; zvulun/uluwatu unchanged.
- natadola re-aimed and re-cut; publishes 1.38 m for a 1.5 m 12 s swell (was 0.00).
- GA4 collecting: property `553528140`, `G-NKQNM6YLQ1`, BigQuery daily link, 7 custom
  dimensions. Verified in-browser: `page_view`, `spot_view`, user properties all landing.

**Partial / not applied:**
- **Bathymetry swap (local GEBCO 2024) is measured, wins on merit, NOT applied.** Blocked
  on two coordinate calls (below), not on evidence.
- **Five spots still publish flat** (verified 2026-09-10 at 1.5 m / 12 s down each spot's
  own window centre): broughton-bay, cottesloe, lucky-bay, new-brighton, pen-hat. It was
  six until natadola was re-aimed. Cause is known: their ray never reaches deep water.
- **Coastal wind correction: nothing shipped.** Measured, and no candidate is defensible.
- `tools/ga-report/report.py` runs and authenticates, but standard GA reports were still
  empty at session end (GA4 lags hours). Not yet seen with real data.

**Known-untrue in docs:** CLAUDE.md says waves are "blended 50/50". Only the TOTALS are
blended. All four partitions are GFS-Wave alone and partitions are what the transform eats,
so published heights are GFS-only. ECMWF open data has no swell partitions to fix this with.

## Active Files
- `web/src/pages/MapPage.tsx` — zoom fabs; carousel now one card per pin; `groupPoints()`.
- `web/src/styles.css` — `.map-screen` grid column fix; `.map-fab.zoom-*`; `.nudge-drop`;
  `.consent-bar`.
- `web/src/components/ReportNudge.tsx` — was a full-screen page, now a self-dismissing drop.
- `web/src/ga.ts`, `consent.ts`, `geoconsent.ts`, `components/ConsentBar.tsx` — GA4 + consent.
- `pipeline/src/rosa_pipeline/physics.py` — `FRICTION_MODE`/`FRICTION_KD_MIN`, the march.
- `pipeline/src/rosa_pipeline/bathymetry.py` — `LocalGebcoSource`, `grid_label`.
- `pipeline/src/rosa_pipeline/verify.py` — `station_bias_profile`, `fit_diurnal_correction`.
- `pipeline/src/rosa_pipeline/cli.py` — `bathy --source/--grid`, `run --bathy-dir`,
  `verify --stations --archive --bias-profile`.
- `deploy/oracle/publish.sh:151` — `--archive=tgz`.
- `tools/bathy-ab/`, `tools/wind-bias/`, `tools/ga-report/` — the A/B and reporting scripts.
- `docs/CALIBRATION.md`, `docs/OPEN-ITEMS.md`, `docs/SESSIONS.md` — all updated.

## Changes Made This Session
1. **Map freeze (`ba51a13`).** `.map-screen` is a grid with no explicit column track, so it
   sized to max-content — and the card track's scroll width IS content. At world zoom the
   column hit 371,778 px and the canvas clamped to a 7 px sliver. Fixed with
   `grid-template-columns: minmax(0,1fr)` + `min-width:0`. Also capped the carousel to one
   card per pin (was 601–1300 cards).
2. **Outage (`ee63704`).** Data deploy uploaded ~1500 files/cycle → ~6000/day against
   Vercel's free 5000/24 h; broke when the fleet passed ~1250 spots. `--archive=tgz`.
3. **Report nudge → drop (`46429f1`).** Full-screen modal replaced with a 9-second toast.
4. **Bathymetry tooling + A/B (`42e6397`, `837a175`).** h5py reads GEBCO_2024.nc (NetCDF4 is
   HDF5) so no new dependency; whole fleet cuts in 3.2 s.
5. **Friction (`ae1f968` → `6828e3e`).** See Failed Attempts for the path. Shipped
   `kdtaper` at kd 0.6, chosen as the largest threshold `test_tide_shifts_breaker_height`
   accepts.
6. **natadola (`257ae39`).** `horizon` independently refused the stored normal; ESRI imagery
   confirmed. offshore_direction 152→70, window [267,37]→[170,290], profile + tide re-cut.
7. **Wind (`8589234`).** Extended the harness rather than reimplementing; measured; shipped
   nothing.
8. **GA4 (`5a3519e`, `671a4db`, `3fd57c7`, `c86bf57`).** Consent Mode v2; mandatory outside
   the EEA/UK, asked inside it, zone from device timezone.

## Failed Attempts
- **"Put ECMWF into the partitions."** Impossible as framed — ECMWF open data publishes no
  swell partitions, only totals + six period-band heights. Do not re-propose without a
  spectral-construction plan.
- **Friction coefficient re-fit.** No value works: clearing the reef spots costs +0.21 to
  +0.49 m fleet-wide. The eye frames do not discriminate at all — the same single frame
  passes from 1× to 9.8×, so they cannot be cited for the current value either.
- **"Stop friction once breaking starts."** Never fires; the wave is destroyed before it
  ever breaks (traced substep by substep at uluwatu).
- **Depth-limit height floor.** +0.77 m fleet mean — worse than a textbook rescale.
- **Hard `kd` cut-off (`kdfloor`).** Caught by `test_tide_shifts_breaker_height`: a
  discontinuity in `kd` MOVES WITH THE TIDE. Fleet-wide, spots reading smaller on a higher
  tide went 53 → 152.
- **"The last flat spots are intertidal."** Tested and dead — admitting samples above chart
  datum makes it WORSE (5 flat → 12), because `tide_shifted_samples` truncates at a drying
  sample rather than deleting it.
- **Applying the bathymetry swap.** Reverted within the hour on
  `test_spots.test_committed_profiles_reach_open_water`.
- **`aim_normal`'s suggestions for the flat spots.** Unsafe — proposes flipping natadola
  166° to another wrong bearing, and for broughton-bay picks a ray through 15 km of 1 m
  estuary. Do not apply its output unattended.
- **Pooled diurnal wind correction.** 0.5 % of MAE out of sample. Worthless.
- **Per-station constant wind correction.** 12 % out of sample, but it fits each airfield's
  SITING — sign is a coin flip (38 of 85 hot), so it would remove wind at nearly half the
  fleet, the same direction as the complaint it exists to fix.
- **GA4 sending nothing while all tests passed.** gtag.js only processes `arguments` objects
  on the dataLayer queue; a plain array is accepted by `push` and silently ignored. Found
  only by watching the network on the deployed site.

## Next Step
**First:** confirm the friction fix reached production. The VM cron runs 02:20/08:20/14:20/
20:20 UTC and `publish.sh` does `git pull` first, so the 2026-09-10 cycles carry it. Check a
previously-flat spot on the CDN:
```
curl -s https://rosa-data-opal.vercel.app/data/spots/rockaway-beach.json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['generated_at'], max(h['h_mid'] for h in d['hours']))"
```
It published a median `h_mid` of 0.00 m before. If it is still 0.00 with a fresh
`generated_at`, the deploy did not carry the change — check `deploy/oracle/publish.sh` ran a
`git pull` that landed `6828e3e`.

**Then, in order:**
1. **Two coordinate calls unblock the bathymetry swap** (OPEN-ITEMS 17/23, CALIBRATION.md
   2026-09-09). `fort-point`: ray at 303° crosses the Marin headlands; nearest fully-wet
   bearing is 275°, 28° off. `lebih`: NO bearing at 5° resolution has a fully wet 18 km ray —
   it is walled in by Nusa Penida. These need the user, not a derived value. Once decided:
   `rosa-pipeline bathy --all --source local --out <dir>` (3 s) then the four scripts in
   `tools/bathy-ab/`.
2. **The five remaining flat spots** need a ray that extends until it finds deep water rather
   than stopping at `RAY_DISTANCES_KM`'s 18 km. Cannot be unbounded: new-brighton needs
   >120 km. Changes how every profile is cut — own pre-registered question, both A/Bs.
3. **GA reports with real data:**
   `GA_SA_KEY=~/.config/rosa/ga-sa.json uv run --project pipeline python tools/ga-report/report.py`
4. **IMS token** (mail ims@ims.gov.il) — the only thing that can answer whether the beach is
   windier than the model's coastal cell (OPEN-ITEMS 25).
