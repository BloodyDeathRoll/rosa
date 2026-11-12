# CLAUDE.md — Rosa

Rosa is a **worldwide, mobile-first PWA surf forecast app**: free, lean, fast, shareable. A daily-use tool replacing Surfline for dedicated surfers, minus the bloat and paywall.

## Where the detail lives — read the doc for the area you're touching

| Working on | Read first |
|---|---|
| `pipeline/` — transform, score, physics, spectral, extract | `docs/ALGORITHM.md` |
| `data/spots/`, `tools/spot-verify/`, `bathy` / `horizon` commands | `docs/SPOT-DB.md` |
| `data/stations/`, `stations.py`, `verify --stations --wind-model` (coastal wind truth, GFS vs the gfs_grib candidate) | `docs/CALIBRATION.md` 2026-08-29 + 2026-08-30 + 2026-09-16, `docs/OPEN-ITEMS.md` 25 |
| `web/` | `docs/UI.md` |
| Water clarity / pollution (`clarity.py`, `bathing.py`, `data/water/`) | `docs/WATER-SOURCES.md` |
| Tuning a constant, running a sweep, grading a frame | `docs/CALIBRATION.md` (method rules at top) |
| "What's still open?" | `docs/OPEN-ITEMS.md` |
| "Why is it like this?" | `docs/SESSIONS.md` (session log) |
| Live machine / deploy state | `handoff.md`, `deploy/oracle/README.md` |
| **Where forecast data comes from, what replaces it, scale** | `docs/rosa-accuracy-roadmap.md` (§2 keep/join/replace, §4 stages, §9 scale) · `docs/rosa-stage3-plan.md` · `docs/rosa-stage4-plan.md` (SWAN nearshore, SoCal pilot - planned, not built) · `docs/rosa-fetch-plane-plan.md` (off the OM quota) · `docs/rosa-peak-period-plan.md` (Tp for the blend arm, from DWD GWAM) |
| Product plan · competitor teardown | `docs/rosa-build-plan.md` · `docs/rosa-surfline-teardown.md` |

**Do not re-derive the data-source strategy from first principles.** Stage 3a (raw NOAA GFS-Wave source + dual-source buoy A/B) and Stage 3b (ECMWF spectral-lite) are BUILT — `gfswave.py`, `ecmwf.py`, `verify --archive --source {om,gfswave,ecmwf,blend}` (`blend` rebuilds the shipped blend from both member archives, GFS-Wave alone past ECMWF's horizon as published; **since 2026-10-08 skill.json - the published confidence ceilings - comes from the blend card**, `docs/CALIBRATION.md` 2026-10-08 / OPEN-ITEMS 37a; `om` stays writable as the comparison arm), and a dual-source archive that has been accumulating since 2026-07-23. **Since 2026-08-26 the GFS-Wave+ECMWF blend (`blend.py`) IS the primary wave source, worldwide** - `run --wave-source` defaults to `blend`; `om` is the explicit fallback arm. The promotion was a product decision (`docs/CALIBRATION.md` 2026-08-26): buoys covered 45 of the 265 spots the fleet had when the call was made (2026-08-26; it is 624 now, and the added regions registered no buoys) and never will cover the rest, so a per-region buoy gate was a decision never to scale. Weather stays on Open-Meteo (plan C3, measured); **its 10 m wind model is GFS (`fetch.WEATHER_MODEL`) since 2026-08-30** - ICON (`best_match`) damped the beach wind and the beach was graded by eye (`docs/CALIBRATION.md` 2026-08-30); ICON was archived at the stations as the A/B member until 2026-09-16, when that A/B confirmed GFS and the leg was dropped. Do not re-open either without new buoy evidence. **Since 2026-09-12 the blend arm makes no Open-Meteo marine request at all** (the SST/tide fallback leg was removed - it never fired and its per-spot weight refused the 20:20Z cycle daily at 1947 spots); **since 2026-10-08 the weather leg asks a self-hosted Open-Meteo on `rosa-arm` first** (same code and GFS data as the public API, byte-identical on all 5 fields; `ROSA_WEATHER_URL` in `~/rosa/.env`, falls back to api.open-meteo.com on any failure; `deploy/oracle/README.md`), so spot count no longer spends public-API quota; the marine host (buoy archive, `om` arm) followed the same day (`ROSA_MARINE_URL`). Plan C3b (GFS atmos GRIB) lost its station A/B to Open-Meteo on 2026-09-26 and was not built; `docs/OPEN-ITEMS.md` 34 has the history.

## Non-negotiable principles
1. Every screen answers "should I surf, when, where?" — cut anything that doesn't.
2. **Precompute everything, serve static.** Pipeline runs on schedule → per-spot JSON + map frames on CDN. No request-time forecast backend, ever. This is what keeps the app free.
3. Always display run timestamp and confidence. Rating formula is public ("why this rating" in-app) — transparency vs. Surfline's black box is a core differentiator. **No model name**: the payload is stitched per hour from several models, so one label was wrong on ~40% of rows and nothing rendered it (retired 2026-08-14). Re-introduce it only as per-hour provenance, never as a constant.
4. Mobile-first, dark-first, < 2 s first load on 4G, forecast readable in a 20-second pre-dawn check. Installable PWA, offline-cache last forecast.
5. Every forecast state and swell animation has a shareable URL + auto share card.

## Legal red lines
- NEVER fetch, proxy, or reproduce Surfline API output, spot guide text, cams, or their spot database. The teardown is for structural understanding only.
- NEVER scrape third-party camera streams (any provider). Cams enter Rosa only as officially embeddable/permitted public streams (per-spot `cam_url`) or via partnerships.
- ISRAMAR (isramar.ocean.org.il) is all-rights-reserved: manual validation during calibration only; partnership before any integration.
- Open-Meteo: free tier non-commercial, attribution required (in footer); re-verify before public launch. CMEMS/Copernicus: free with registration, attribution required. **CMEMS coastal SDB** (`sdb.py`, DOI 10.48670/mds-00364): royalty-free, commercial use permitted, attribution required, free of charge only **to 2028-06-30 - re-verify before then**. **ICESat-2 ATL24** (`atl24.py`): NASA CC0, citation requested. **Water clarity** (`clarity.py`, CMEMS GlobColour, DOI 10.48670/moi-00278): same CMEMS terms as SDB, attribution in the footer. **Bathing water** (`bathing.py`): EEA CC-BY 4.0, NSW Beachwatch CC BY - both credited in the footer. NEVER use Surfers Against Sewage data (personal use only); sources and licences: `docs/WATER-SOURCES.md`.
- Free to build on: NOAA (WW3/GFS/OISST/NDBC/CO-OPS), ECMWF open data, EOT20 tides (CC-BY), GEBCO, OSM.

## Standing prohibitions
Each was learned the hard way and each has a rationale in the linked doc. **Do not re-litigate from first principles — read the doc.**

- **Never import competitor spot data.** (`docs/SPOT-DB.md`)
- **Never append invented shallow samples** to a bathy profile — the answer becomes γ × a made-up depth. (`docs/ALGORITHM.md`) Patching a ray point from a *measured* grid (`sdb`) is a source swap, not this — but it moves published heights, so it needs the A/B in OPEN-ITEMS 23 first.
- **Combine partitions by wave field, never `sqrt(Σ Hb²)`.** (`docs/ALGORITHM.md`)
- **Do NOT scale partitions to close `closure`** — it is diagnostic only, nothing scores on it. (`docs/ALGORITHM.md`)
- **Period display ≠ scoring is deliberate — do not "fix" it by unifying.** (`docs/ALGORITHM.md`)
- **Do not build temporal smoothing for partition direction wander** — closed, the transform is order-independent. (`docs/CALIBRATION.md`)
- **The `horizon`, `atl24`, `sdb` and `aim_normal` tools report, never apply.** `sdb --apply` is not safe unattended. (`docs/SPOT-DB.md`) **The cam tool is the exception since 2026-08-28**: `verify --resolve --apply` runs in every publish cycle, because it only ever swaps a dead id for a same-TITLE replacement and its patch is reset before the next `git pull`. Committing the new id is still the durable fix.
- **Swell events surface ONLY as push** — do not rebuild in-app event banners, cards, or alert strips. (`docs/UI.md`)
- **Tune knobs only from `docs/CALIBRATION.md` + the Stage-0 scorecard.** `height_coeff` is 1.0 at all 4558 spots. Fleet impact is only valid as a same-input A/B, scored with the shipped harness.
- **Inspect live infra before designing for it.** A session once built a competing scheduler off a stale handoff while another had already provisioned the box.

## Architecture
```
pipeline/ (Python 3.11+, uv)              web/ (Vite + Preact PWA, TS strict)
  fetch    → GFS-Wave + ECMWF global files   MapLibre GL for maps
             blended 50/50 (blend.py);       Static hosting: Vercel
             weather: Open-Meteo (self-hosted); SST: OISST Reads /data/spots/{id}.json via VITE_DATA_BASE
             (--wave-source om = fallback)
  extract  → sample at derived offshore_point (+ tide from committed EOT20 constants)
  transform→ spread exposure; hybrid physics breaker
  score    → rating 0-100 → bucket
  publish  → data/out/spots/{id}.json (~5 KB), index.json, share-card data
```
Frontend never computes forecasts; it renders pipeline JSON. Keep the fetch layer behind an interface so a raw-grid migration touches one module.

**User plane (since 2026-09-07):** `deploy/user-api/` = Cloudflare Worker + D1 (`rosa-user-api.einhanamer.workers.dev`): Google sign-in (Identity Services in the browser, ID token verified in the Worker), one `users` row per Google `sub` with favorites as a JSON column, `GET /admin/stats` for "how many users". Saving a favorite needs sign-in; the forecast never does. `deploy/push-api/` (Vercel Blob) keeps push subscriptions, contact and feedback. Cloudflare over Supabase on price at scale (per request, not per MAU) - see `deploy/user-api/README.md`; do not re-open.

**Scheduler:** Oracle VM `rosa-arm` (A1.Flex 4 OCPU/24 GB, since 2026-08-30; 153 GB disk; `rosa-instance`, the micro it replaced, was terminated 2026-10-07), cron 4×/day (02:20/08:20/14:20/20:20 UTC) → `deploy/oracle/publish.sh` = git pull → buoy archive → `run --all` → prebuilt Vercel deploy of `data/out` to the separate `rosa-data` project. **NO GitHub Actions, NO systemd** for the cycle - `.github/workflows/` is PR checks and the @claude review only, never scheduling or deploying. `rosa-backup` VM runs an hourly freshness watchdog (pages if `fetched_at` > 8 h). Crash alerts go to the admin push snapshot, never the public list.

**Spot DB: 4558 spots** - california 156, south-africa-west 83, hawaii 105, japan 81, sao-paulo 56, galicia 55, rio-de-janeiro 52, chile-central 51, peru 49, mar-del-plata 48, ecuador 47, santa-catarina 46, canary-islands 45, mexico 48, israel 42, morocco 43, portugal 42, sicily 42, scotland-west 42, england-south 48, bali 39, venezuela 39, scotland-east 38, oregon 37, cornwall-devon 36, sydney 35, chile-south 34, perth 34, sri-lanka 34, germany 34, bahia 33, netherlands 33, el-salvador 32, philippines 34, ceara 31, chile-north 30, victoria 31, espirito-santo 29, massachusetts 30, landes 28, margaret-river 28, byron-bay 26, uruguay 26, denmark 26, sweden 26, normandy 32, alagoas 25, cadiz 25, costa-rica 25, new-jersey 25, asturias 24, basque-country 24, brittany 24, south-florida 32, maldives 24, panama 23, cyprus 22, colombia-caribbean 22, sunshine-coast 22, south-africa-east 32, algeria 20, gold-coast 21, long-island 20, washington 20, cantabria 19, south-australia 37, rio-grande-do-norte 18, hokkaido 18, norway-south 21, maine 19, french-polynesia 18, paraiba 17, tanegashima-amami 17, lombok 16, outer-banks 22, patagonia-argentina 16, mentawai 16, nicaragua 22, rio-grande-do-sul 14, wales 14, mozambique 13, sergipe 13, tasmania 21, east-java 12, florida-space-coast 14, wa-midwest 12, wa-south 12, fiji 11, namibia 11, okinawa 11, rhode-island 11, wa-north 11, florida-northeast 11, south-carolina 11, colombia-pacific 11, mauritius 10, north-east-england 10, iceland 11, angola 9, parana 9, pernambuco 9, sumbawa 9, lofoten 9, fernando-de-noronha 8, north-scotland 8, senegal 8, florida-gulf 8, bunbury 7, new-hampshire 9, cape-verde 6, esperance 6, west-java 6, florida-panhandle 6, madagascar 5, galapagos 5, ghana 6, new-zealand 17, exmouth 2, zanzibar 2, kenya 1, georgia 1, papua-new-guinea 4, vanuatu 6, new-caledonia 4, solomon-islands 3, cook-islands 3, samoa 11, valencia 42, taiwan 33, south-korea 33, andalusia 32, catalonia 29, texas 24, barbados 24, dominican-republic 23, reunion 21, balearic-islands 18, karnataka 13, virginia 13, guatemala 13, andhra-pradesh 12, murcia 12, hainan 11, goa 11, kerala 10, guangdong 9, tamil-nadu 9, liberia 9, tonga 9, hong-kong 8, faroe-islands 6, jeju 5, fujian 4, zhejiang 4, shandong 3, odisha 3, azores 27, madeira 25, nias 9, sumba 9, krui 9, aceh 7, rote 5, simeulue 4, puerto-rico 35, nova-scotia 20, vancouver-island 13, liguria 8, tuscany 16, lazio 7, sardinia 18, dakhla 3, tobago 5, british-virgin-islands 5, malaysia 7, thailand 10, nsw-mid-north-coast 68, nsw-south-coast 43, nsw-central-coast 25, campania 10, basilicata 3, calabria 15, puglia 13, greece 17, charente-maritime 16, gironde 16, vendee 16, provence 14, guadeloupe 12, vietnam 12, corsica 8, martinique 8, trinidad 8, emilia-romagna 6, languedoc 5, pakistan 5, bahamas 4, jamaica 4, loire-atlantique 4, sabah 4, saint-martin 4, lebanon 3, maharashtra 3, papua 3, saint-barthelemy 3, bermuda 2, malta 2, marche 2, oman 2, turkey-black-sea 2, turkey-med 2, andaman 1, antigua 1, brunei 1, bulgaria 1, curacao 1, egypt 1, iran 1, maluku 1, myanmar 1, savu 1, timor-leste 1, united-arab-emirates 1, us-virgin-islands 1, queensland-central 7, moreton-bay 4, ivory-coast 3, nigeria 2, sierra-leone 2, congo 1, norway-north 1, sao-tome 1, northland 65, taranaki 64, wellington 51, auckland 31, south-island 24, coromandel 18, bay-of-plenty 12, waikato 12, hawkes-bay 11, gisborne 7, pohnpei 5, easter-island 5, cuba 4, dominica 3, guam 3, maranhao 3, para 2, haiti 1, saint-lucia 1. One committed bathy profile each. Changing the count updates `docs/SPOT-DB.md` AND `test_every_committed_spot_picks_the_same_oisst_cell_as_before` - no approval needed.

## Conventions
- Lint gates run locally too (2026-09-26): `pipeline/tests/test_lint.py` runs ruff check + format inside pytest, and `.githooks/pre-push` refuses a push that fails them - enable per clone with `git config core.hooksPath .githooks`. Commits go straight to main, so CI only reports after the fact.
- Python: uv, ruff, pytest; type hints everywhere; pipeline stages pure functions (input → output, no hidden state) so fixtures test everything offline.
- TS strict; Preact if bundle size threatened; no UI framework bloat; PWA via vite-plugin-pwa.
- Fixtures: `pipeline/tests/fixtures/` holds captured responses so tests never need network.
- Commits small, conventional (feat:/fix:/data:). Data outputs are build artifacts — never committed.
- Vercel Git integration stays **DISCONNECTED**; deploys are CLI-only (forecast data is gitignored, so a Git-triggered build ships a dataless app).

## Doc precedence
CLAUDE.md and `data/spots/*.yaml` are authoritative. The area docs above are current spec — **including `docs/rosa-accuracy-roadmap.md` and the stage plans, which are LIVE spec for every stage not yet marked BUILT, not history** (`gfswave.py` cites `rosa-stage3-plan.md` as its live-verified source). `docs/SESSIONS.md` and `docs/CALIBRATION.md` are history and rationale; the remaining `docs/` are historical context. **When docs disagree, stop and reconcile before implementing.**

At the end of every working session: append to `docs/SESSIONS.md`, and update `docs/OPEN-ITEMS.md` if the open list moved.
