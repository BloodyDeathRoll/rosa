# Session Handoff — 2026-07-29

## Goal
Started as a small web-polish round (Charts, Today layout, spot page) and turned into
the biggest forecast-correctness fix so far: a metre of swell offshore was rendering as
0.0-0.1 m at the spot. Root-caused, fixed, verified against Surfline, logged.

## Current State
- **All committed and pushed** (main at `5bad2aa`), working tree clean. Web deployed to
  rosa-rust.vercel.app (`index-DsHhZiAu.js` / `index-CVu7Nof3.css` verified live).
  280 pipeline tests green, ruff clean, `tsc --noEmit` clean.
- **⚠ The pipeline fixes are NOT in the served data yet.** rosa-instance has been running
  one cycle since 2026-07-28T21:58Z (started before those commits); it will publish on the
  NEXT cycle. Until then rosa-data still serves the old physics AND the 2-slot last day at
  midigama. Verify with the commands in Next Step.
- Exposure rebuild is verified locally: `run --all` gave impossible zeros **419 → 2**
  (both at ingrina), median height x1.00, **Israel x1.00 at every percentile** (so the
  five Stage-2E calibration frames are unaffected). Pipeline now matches Surfline hour by
  hour; Fishermen Bay 0.0-0.1 m -> 0.9-1.5 m.
- Open: ingrina's 2 zero hours; matapalo-osa, okanda, peanut-farm sit 65-73 deg between
  wind direction and coastline (inside the new guard, want local knowledge); Open-Meteo
  partition **direction wander** is absorbed by the fan but not solved.

## Active Files
- `pipeline/src/rosa_pipeline/transform.py` — the fix: `spread_exposure()`,
  `arriving_direction()`, `GRAZING_INCIDENCE_DEG`, energy/height on one exposure.
- `pipeline/src/rosa_pipeline/publish.py` — `_covers_day()`; drops the trailing half-day.
- `pipeline/src/rosa_pipeline/fetch.py` — `PAST_DAYS=1`, batch 100->90.
- `pipeline/src/rosa_pipeline/extract.py` — skips null-wind hours (crashed `run --all`).
- `pipeline/src/rosa_pipeline/notify.py` + `cli.py` — `send_alert()` / `rosa-pipeline alert`;
  region-locked, rotating feedback planner (`plan_feedback_push`, `spot_regions`).
- `pipeline/tests/{test_transform,test_spots,test_publish,test_pipeline_end_to_end,test_notify}.py`
- `data/spots/{sri-lanka,costa-rica}.yaml` + 10 re-cut `data/spots/derived/bathy/*.json`.
- `deploy/oracle/publish.sh` (ERR trap -> push alert), `deploy/backup/freshness-watch.py`
  (hourly watchdog on rosa-backup), `deploy/oracle/README.md` §Ops alerting.
- `deploy/push-api/api/sub.js` — accepts `home` (nearest spot id, never coordinates).
- `web/src/pages/{TodayPage,SpotPage,ChartsPage,SearchPage,MapPage}.tsx`,
  `web/src/components/CoastChart.tsx`, `web/src/{geo,push,feedback}.ts`,
  `web/public/push-sw.js`, `web/src/styles.css`, `web/public/splash.jpg`.
- `docs/CALIBRATION.md` (2026-07-29 entry), `CLAUDE.md` (spec + SESSION 9 + NEXT).

## Changes Made This Session
1. **Charts**: world-only (basin selector deleted); render to mercator's 85 deg edge — a
   79 deg trim was blanking real Arctic field; zoom floored to the covered band; opens on
   the user's coast at basin scale (`HOME_ZOOM = 3`, cached `getPosition()`).
2. **Pipeline day boundaries**: `past_days=1` + trim to local today (the first day was cut
   for spots west of UTC); then `_covers_day()` drops the trailing half-day east of UTC
   (midigama had a 2-slot 16th day). 6 tests cover both ends.
3. **Ops alerting** after two silent crash-and-serve-stale incidents: publish.sh ERR-traps
   -> Web Push to `~/rosa-push/admin-subs.json` (admin only, never the public list);
   rosa-backup runs an hourly freshness watchdog (pages if `fetched_at` > 7 h). Both tested
   end to end (two test pushes delivered).
4. **Feedback ask split in two** (user req): "Surfed X?" tick/cross then thumbs only on
   yes, in-app and on the lock screen. Selection never crosses regions (device sends its
   nearest spot id), rotates over favorites, falls back to the nearest spot with no
   favorites. Verified against the live index.
5. **Today planner** (`planToday()`): chips from where you are + favorites + the ONE
   last-viewed spot; >=5 spots per region; anchor leads; payloads load per region.
6. **The exposure rebuild** — full argument in docs/CALIBRATION.md 2026-07-29. Three
   faults, one mistake (treating a partition as a single bearing): exposure judged the mean
   only; refraction re-judged it the same way and cancelled the rest; a window reaching past
   the shore normal was overruled by the derived normal. Plus 10 misaimed depth rays re-cut
   and fishermen's `offshore_direction` corrected (it called the SW monsoon offshore).
   Guards added: ray vs sample point, deep end underwater, wind from the land.
7. **Web polish**: bar scale shared + piecewise 60/40 + units joined + 3.4 day columns +
   bars at 50%; region blocks padded; equal-height cards; date bar padding; one-row spot
   header (SpotSwitcher deleted); "Other nearby spots" strip reusing `MapCard`; cam icons
   on search rows; nearby cam opens the whole spot page; new splash artwork; tamarindo's
   dead cam removed; rating rail is now a grey track with a tier-coloured fill (flat = red
   stub at 1/5 ... epic = full).

## Failed Attempts
- **Declaring Pipeline's zeros "correct physics" was wrong.** The first assessment argued a
  north-shore break is legitimately flat in July. The user's Surfline screenshot disproved
  it (0.3-0.6 m from the same 1.8 m ENE swell). Check a reference forecast before calling a
  zero legitimate.
- **Spread-aware exposure alone did not fix it** — Pipeline went 0.0-0.1 -> 0.1-0.2, still
  3x under Surfline, because refraction still measured incidence from the fan's *mean* and
  cancelled it as arriving from behind the beach. Both halves are required.
- **Spread integration does not rescue hiriketiya's 276 deg hours** (2.6 sigma outside the
  arc). That is Open-Meteo partition direction wander (a 12 s swell reported
  189->276->192 deg in one day), a separate problem.
- **Bathy audit false negative**: comparing the profile's bearing to `spot.offshore_bearing`
  via `getattr` returned None (the loader consumes that key into `offshore_point`), so the
  first audit reported "0 mismatches". Reading the YAML directly found 13.
- **Reading `data/out` before `run --all` finished** reported 77 remaining zeros; those were
  the previous run's files. Wait for the run.
- **CSS specificity**: `.nearby-cards` lost to `.map-cards` (equal specificity, defined
  later), so the cards sat flush against the screen edge. Needed `.map-cards.nearby-cards`.
- **`git commit -m` with nested double quotes** in the message broke shell parsing — use
  `-F <file>` for long messages.
- **Vercel deploy failed twice with `ETIMEDOUT` to api.vercel.com**, transient; the third
  attempt succeeded. A failed deploy leaves the old bundle serving, so always verify the
  hash after deploying.
- Background watchers timed out twice waiting on VM cycles: a full publish cycle now takes
  ~60-90 min (3-way archive + 199 spots + swellmap), so poll windows must exceed that.

## Next Step
1. **Confirm the pipeline fixes reached the served data** once the current VM cycle ends:
   ```bash
   ssh -i web/.oracle/ssh-key-2026-07-23.key ubuntu@82.70.218.149 \
     'grep -E "=== 2026-07-29" ~/rosa/publish.log | tail -3; pgrep -f publish.sh || echo idle'
   curl -s "https://rosa-data-opal.vercel.app/data/spots/pipeline.json" | \
     python3 -c "import json,sys; d=json.load(sys.stdin); print([h['h'] for h in d['hours'][:8]])"
   # expect ~0.3-0.6, not 0.0-0.1; fishermen ~0.9-1.5; midigama last day 8 slots not 2
   ```
   A failed cycle should have pushed an alert; `grep 'FAILED at:' ~/rosa/publish.log`.
2. **Stage 2E** (archives mature ~07-30): input de-bias + Israel refit + re-run
   `rosa-pipeline experiment`. The five frames are unaffected by this session's work
   (Israel x1.00), so the Tm-vs-Tp under-call question stands exactly as logged.
3. Watch items: ingrina's 2 zero hours; matapalo-osa/okanda/peanut-farm wind vs coastline;
   partition direction wander (temporal smoothing of long-period partition direction is the
   next candidate if it recurs).
4. Backlog: Period bar rescale (`min(1, per/9)` -> ~/13) in SpotPage `DayBars`; cam verify
   for chigasaki/aoshima (`tools/cam-scan/scan.py verify`); Nazare's temps row overflows its
   card (user said leave it).
