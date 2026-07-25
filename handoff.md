# Session Handoff - 2026-07-25

## Goal
Build Rosa's own worldwide surf-spot database from first principles (not by
harvesting a list), and keep the live pipeline healthy as it scaled from 140 to
188 spots. Emphasis for all spot work: **locations exact, above names.**

## Current State
- **Live: 188 spots** on `rosa-data-opal` (verified - the 20:20 UTC cron published
  188 clean, no 429; `run --all` batching holds well under ~200 spots).
- **Web app (`rosa-rust`) is deployed** with two UI fixes and reads 188 spots live.
  ⚠️ **The web fixes are DEPLOYED but UNCOMMITTED** (`web/src/pages/SpotPage.tsx`,
  `web/src/styles.css`) - commit them.
- **Spot-seed pipeline works end-to-end, both flows** (primary coastline-generation
  + secondary web-search), fully offline via local datasets. Committed & pushed
  (37e70e0 tools, bfa2166 data, f5faa5c playbook).
- **234 pipeline tests green.** Everything on `main`, pushed, except the web fixes.
- **A1 seekers:** both alive, both shut out - Jerusalem VM (4/24, ~1.7 d) and
  Frankfurt local **desktop** (4/24, 3 ADs, ~18 h; desktop stays on, doesn't sleep).
  Zero A1 landed in either tenancy. No action - pure Always-Free contention.
- Claude Code updated to 2.1.220 (active next launch).

## Active Files
- `tools/spot-seed/` - the toolchain: `seed.py` (primary: coastline→bathy→OSM-validate),
  `local_bathy.py` (local GEBCO), `osm_local.py` (local Geofabrik + business filter),
  `render.py` (ESRI sat-verify tiles), `multi_geocode.py` (Google+Nominatim+Photon),
  `emit_spots.py`, `osm_seed.py` (`is_business`), `coast_generate.py`, `bathy_gate.py`.
  Working outputs (`work/`, `candidates/`, `.venv`) gitignored.
- `data/bathy/GEBCO_2024.nc` (7.5 GB) + `data/osm/*.osm.pbf` - local datasets, gitignored.
- `data/spots/{sri-lanka,portugal,japan,philippines,nicaragua}.yaml` - +48 spots.
- `docs/spot-db-scraping-playbook.md` - the full runbook (also in memory).
- `web/src/pages/SpotPage.tsx`, `web/src/styles.css` - UI fixes (uncommitted).
- `pipeline/src/rosa_pipeline/fetch.py` - Open-Meteo batching (committed 9852cac).

## Changes Made This Session
1. **Open-Meteo 429 fix (9852cac, deployed):** `fetch_many` batches ≤100 unique
   points (600/min ÷ ~5.94 weight/pt) + 60 s pause between batches, staying under
   the per-HOST marine cap. Fixed the 140-spot cron crash.
2. **Frankfurt A1 seeker** relaunched on the desktop at 4/24 (`grab-arm-frankfurt.sh`),
   in parallel to the Jerusalem VM seeker. Both 4/24.
3. **Built the spot-DB scaling pipeline** and grew 140→188: coastline-generate →
   bathy-prune (local GEBCO) → OSM-name confirm (business-filtered) → **render
   sat-verify** → add. Then a **secondary web-search flow**: country/area searches →
   cross-ref DB → **3-way multi-geocode** → render sat-verify → add. Local GEBCO +
   local Geofabrik make it offline/uncapped.
4. **Two UI fixes (deployed, uncommitted):** map cards now use the dark treatment in
   both themes (light matches dark); forecast scroll "blink" fixed with
   `overflow-anchor:none` on `<html>` + wider hysteresis (root cause: scroll-anchoring
   nudged scrollY across the collapse threshold).
5. `/doctor`: deleted a stray `~/.claude/skills/sessions-skills.zip`, updated to 2.1.220.

## Failed Attempts
- **from-memory coordinates are fake** (proven twice): a memory-typed "Uchiumi" hit an
  inland river town, "Monaliza" hit open water. ALWAYS geocode + render-verify.
- **Two tool bugs surfaced at scale, both fixed:** local OSM extractor wasn't applying
  the business filter (Portugal surf schools/shops leaked as spots); name-matching
  lacked PT/ES stopwords + a distance cap (garbage 68 km "corrections").
- **O(n²) clustering hung** on Japan/Philippines 100k/23k-way coastlines → O(n) spatial grid.
- **"Corrections" are guilty until proven:** 0 of ~10 name-match-flagged pin corrections
  were real (sub-spots, spelling variants `kizakihama`≠`kisakihama`, two OSM nodes on one
  beach). NEVER move a good pin on a weak match.
- **OSM alone is too sparse** (Latin America 0 named, Philippines 3) → the web-search flow
  is required to catch famous-but-unmapped spots.
- **External caps/flakiness:** OpenTopoData 1000/day + Overpass 504s → local GEBCO +
  Geofabrik ("download once"). The playbook documents this.
- Manual `publish.sh` at 20:10 would have raced the 20:20 cron (double Open-Meteo
  requests → 429, deploy race) → killed it, let cron deploy clean.

## Next Step
1. **Commit the web fixes** (they're live on `rosa-rust` but uncommitted):
   `git add web/src/pages/SpotPage.tsx web/src/styles.css` →
   `feat(web): light-mode map cards match dark; fix forecast scroll blink`.
2. **Continue spot-DB scaling** per `docs/spot-db-scraping-playbook.md`, one region at a
   time. Gap queue: Japan Hokkaido/Okinawa/Wakayama; Portugal Azores + Ericeira detail;
   Philippines more; Latin-America Tier-B (needs sat-verify, not OSM). Held from this
   session: La Union Monaliza/Carrile Points (fuzzy vs `san-juan-la-union`), Uchiumi
   (needs a Nichinan-coast geocode - Google returned Aoshima).
3. **~07-30 (archive matures):** Stage 2E calibration tune + the 3-way source verdict.
4. Eyeball the autonomous **~0.8 m Hilton swell push** (calibration-suspect) vs reality.
