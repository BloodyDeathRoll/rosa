# Session Handoff — 2026-07-20

## Goal
Extend Rosa to a 16-day forecast and rebuild the day-selection UX into a draggable
date bar + finger-following day carousel on both Home and the spot screen. Also a
long run of design polish (Surfline-style home, calibration, colors).

## Current State
All committed (`a117aa9`) and deployed to https://rosa-rust.vercel.app (CLI-only
deploy via `cd web && npm run deploy`). Verified live: Hilton serves 16 days
(Jul 20 → Aug 4, 128 hourly rows), extended tail flagged `low` confidence.

Working: 16-day pipeline; draggable DateBar; DayCarousel (native scroll-snap, whole
card block drags + snaps per day, coupled to the date bar both ways, virtualized to
±1 day); Home shows the 4 latest-viewed spots (newest = extended card, next 3 = list,
nearest-fill when <4 viewed). 58 pipeline tests green. Web build clean (JS 17.9 KB gz).

Known gaps: **4 southern spots (zikim, ashkelon, palmachim, ashdod-lido) are still
10-day** — their shared offshore point (il_south 31.9,34.35) keeps ConnectTimeout on
`api.open-meteo.com` (the weather fetch, not marine). UI handles the short array fine.
Spot switching on the spot screen is now **tap-only** on the chips (content-swipe was
repurposed to change the day) — flagged to user, not yet re-confirmed.

## Active Files
- `pipeline/src/rosa_pipeline/fetch.py` — requests `models=best_match,ncep_gfswave016`.
- `pipeline/src/rosa_pipeline/extract.py` — `_merge_models()` collapses suffixed multi-model
  fields per hour (best_match days 0-9, GFS-Wave 10-16); carries SST into the tail.
- `pipeline/src/rosa_pipeline/publish.py` — `TABLE_DAYS=16`; confidence high(0-3)/med(4-9)/low.
- `pipeline/tests/fixtures/32.2_34.55.json` — re-captured 16-day 2-model fixture.
- `pipeline/src/rosa_pipeline/transform.py` — calibration row 2: `q(T)=clamp((T/10)^1.4,0.3,1.2)`
  (`PERIOD_EXP=1.4`), breaker range widened to ≥0.1 m gap.
- `pipeline/src/rosa_pipeline/score.py` — wind-gate denominator 30→60.
- `web/src/components/DateBar.tsx` — draggable date strip; snap via `scrollend`.
- `web/src/components/DayCarousel.tsx` — native scroll-snap day pager, virtualized ±1.
- `web/src/pages/TodayPage.tsx` — greeting, SatMap header, DateBar+DayCarousel, latest-4 logic.
- `web/src/pages/SpotPage.tsx` — minimal header, spot chips (8 nearest, tap), DateBar+DayCarousel.
- `web/src/components/MiniMap.tsx` (`SatMap`) — ESRI satellite header on extended card.
- `web/src/components/TideSection.tsx`, `web/src/styles.css`, `web/src/format.ts`.
- Deleted this session: `web/src/daySwipe.ts` (replaced by DayCarousel).

## Changes Made This Session
1. Design handoff import (Rosa App.dc.html): Uptake tokens, 4 tabs, spot switcher, etc.
2. Iterated Home: light default; removed "your coast ranked" chrome; extended last-viewed
   card + nearby; 20 km→closest-3→**latest-4-viewed**; surf range big under name; spark
   moved onto range row; hour-scrub widget added then removed.
3. Spot screen: back→home; 1a chip switcher capped to 8 nearest within 20 km; swapped table
   surf rows (range over mid); satellite map (halved) + tide on extended card.
4. Colors: ramp red→orange→yellow→green→dark-green (FLAT..FIRING).
5. Calibration row 2 (docs/CALIBRATION.md): quadratic q under-called Med windswell vs
   Surfline; linear over-called + reopened night-fire; settled `q^1.4` + wind-gate 60.
6. Map: tried CARTO Voyager (Google-style) then **reverted** at user request (back to ESRI
   satellite card + prior CARTO basemap on Map tab).
7. 16-day forecast (see Active Files) + DateBar + DayCarousel.
8. Sparklines auto-scale to each day's own min/max (were flat-lined on small Med surf).

## Failed Attempts
- **`run --all` for all 40 spots repeatedly fails on il_south** — `httpx.ConnectTimeout`
  handshake on `api.open-meteo.com` (weather). marine-api responds fine; central/north
  succeed. Polling the endpoint healthy right before the run did NOT prevent it. 4 south
  spots remain 10-day. Retry later or leave for the cron job.
- **Voyager basemap**: user said "previous looked better" → reverted.
- **DateBar fixed-timeout settle**: fired mid-smooth-scroll and mis-snapped far taps
  (tapped Sat25 → landed Thu23). Fixed by switching to the `scrollend` event.
- **Linear q (calibration)**: matched Surfline height but over-rated Friday to FAIR and
  made a clean knee-high night read GOOD. Reverted to exponent 1.4 + wind-gate 60.
- **`captureBeyondViewport` headless screenshots** render the spot screen blank (sticky
  backdrop-filter compositing quirk) — NOT a real bug; viewport-only screenshots are fine.
- **Google Maps tiles**: can't use (ToS) — Voyager was the free look-alike, since reverted.

## Next Step
1. Top up the 4 south spots to 16 days: retry `uv run --project pipeline rosa-pipeline
   run --all` when `api.open-meteo.com` is reachable (`curl -m12 ".../v1/forecast?...
   latitude=31.9&longitude=34.35..."` returns 200), then `cd web && npm run deploy`.
2. Confirm with user: spot screen swipe now changes the DAY (spot change is tap-only on
   chips) — is that the intended trade, or restore spot-swipe?
3. Outstanding pre-session task: GitHub Actions cron (task 4) — `run --all`, one fetch per
   offshore point, generous spacing (Open-Meteo throttles); needs VERCEL_TOKEN secret.
4. Watch: does GFS-Wave's absolute height agree with best_match at the day-9 seam across
   spots (measured 0.10 m mean diff at beit-yanai — fine there).
