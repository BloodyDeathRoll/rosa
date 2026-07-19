# Surfline Full Teardown → Rosa Blueprint

**Reviewed sources:** Premium web session (Beit Yanai spot page, full SSR data payload extracted), 24 app screenshots (Popoyo Outer Reef + others, all five spot tabs plus maps/favorites), standalone forecast screenshot, and your prior reverse-engineering notes.

---

## 1. Complete Product Surface

### Per-spot experience (5 tabs in app; 3 on web)

**Live** — Cam player (HLS stream), cam-rewind timeline scrubber with 5-minute clips ("Find Clips"), current-conditions cards (rating, surf height + human phrase, primary swell, wind, tide with next high/low, water/air temp), wetsuit + SPF recommendation, "Was our forecast accurate?" feedback prompt, cam host attribution, nearby-spots list with live height/rating per spot.

**Forecast** — The core surface (your standalone JPG). 16-day outlook (premium; free tier is gated to ~3 days by the API `permissions` object). Collapsible day sections with AM/PM or hourly rows. Columns per timestep: surf height range + color-coded rating bar, swell components (height, period, direction arrow + degrees), wind (speed, gust in red, direction arrow + compass label, offshore/onshore color coding). Expanded rows add: wave energy (kJ), optimal score (0–100), air temp, pressure (mb), forecast probability (%). Tide chart with high/low markers, sunlight times (first light/sunrise/sunset/last light), weather icons. Table/Graph toggle, "Observed heights" overlay toggle, "Historical" tab (premium), model-run timestamp footer ("Model run: 18 Jul 9pm IDT · Swell: LOTUS").

**Analysis** — Graph-based deep dive: stacked surf-height bars colored by rating across days, individual swell-train charts (each swell event as its own timeseries), wave-energy graph, swell spectra (period/direction distribution — `spectraDataAvailable` flag per spot), consistency graph. This tab is forecast-nerd territory.

**Charts** — Regional animated map: WebGL gridded overlays for Wind, Wave Height, Wave Energy, Wave Period, plus Pressure and Sun toggles and a "Nearshore Model" option. Timeline scrubber Now→8 days hourly. Spot pins showing per-spot heights. Google basemap.

**Guide** — Editorial spot metadata (extracted in full from the payload): description, ideal-conditions quadrant (best swell dir, wind dir, tide, size, season), rated attributes 1–10 (Local Vibe, Crowd Factor, Spot Rating, Shoulder Burn, Water Quality), bottom type, break type, hazards, access notes, ability levels, board types.

### Global / cross-spot features

Favorites list with live rating+height per spot · Multi-Cam (4-up cam grid, premium) · Search (spots, subregions, geonames, travel, editorial — 5 suggest indexes) · Maps (surf spots, wave buoys, wind stations layers) · Buoys & wind-station detail pages · Regional forecast text (human forecaster write-ups; "inactive" for Israel — no human forecaster coverage there) · Editorial: WaveFax, Incoming, Outlooks, Hurricanes, Swell Stories, Surfline TV, Meet the Forecasters · Travel guides · Learn content (etiquette, safety, mechanics) · Alerts/notifications · Sessions (smartwatch surf tracking, cam clip of your wave) · Account/premium upsells throughout (Premium+ tier now exists above Premium).

---

## 2. Data Architecture (from the extracted payload)

The SSR Redux state confirmed and extended your notes. Key field-level findings:

**Conditions rating** is an enum (`POOR`, `POOR_TO_FAIR`, `FAIR`, `FAIR_TO_GOOD`, `GOOD`…) with `sortableCondition` int and a `human` flag (false everywhere in Israel → pure LOTUS model output, no forecaster override).

**Swells** come as exactly **6 component slots** per timestep, each `{height, period, direction, directionMin, event, power}` — `event` links a component to a named swell train across time (this is how the Analysis tab draws per-swell curves), `power` is the energy metric that feeds the kJ column.

**Per-spot `offshoreDirection`** (e.g. 90° for Israel's west-facing coast — the shore-normal) — this single number drives the Offshore/Onshore/Cross-shore wind classification. Trivial to replicate: angle between wind direction and shore-normal.

**Per-subregion `offshoreSwellLocation`** — the lat/lon where they sample the offshore wave model (34.4E, 32.0N for Southern Israel, sitting in deep water off the coast). This is the "extraction point" pattern you'd use with any grid model.

**`optimalScore` (0–100)** appears per timestep alongside energy — this is the blend of swell/wind/tide vs. the spot's ideal conditions from the Guide data. Rating enum is almost certainly bucketed from it.

**Wetsuit/SPF** are simple lookups from water temp (+UV): 28°C → "Rashguard, SPF 50."

**Tide** payload is previous/current/next extrema plus a timeseries for the chart; Beit Yanai shows ~0.1–0.4 m range (Med micro-tides — tides are almost irrelevant for your market, a useful simplification).

**Cams** are plain CDN assets, no auth on this spot: HLS `playlist.m3u8`, `latest_small.jpg`/`latest_full.jpg` stills, and rewind MP4s at a guessable pattern `{alias}.{HHMM}.{YYYY-MM-DD}.mp4`. Feature flags per cam: highlights, insights, smart rewinds, crowd counts, lineup cam.

**Gating** lives in a `permissions.violations` object on API responses (e.g. forecast-days beyond free limit), not in the data itself — the model output is the same, just truncated.

**Forecast probability (%)** per timestep in the table — a model-confidence figure that degrades over the horizon (100% near-term → "--%" beyond ~day 10).

---

## 3. What Surfers Actually Use (the lean thesis)

The daily core loop is narrow: **"Is it worth surfing today/this week, and where?"** Answered by: forecast table (height, period, wind, rating), the cam for ground truth, and for a minority the tide. Session frequency data isn't needed to see that Analysis spectra, editorial video, travel guides, hurricanes tracking, Sessions tracking, and Multi-Cam serve small niches — they exist to justify the subscription and feed content marketing, not the loop.

**Keep (core):** forecast table with rating + wind classification, current conditions summary, cam still/stream where available, favorites list with at-a-glance ratings, basic tide/sunlight, alerts ("your spot goes GOOD on Saturday").
**Keep (differentiators, cheap):** per-swell breakdown (surfers do read primary swell), 7–10 day horizon free (undercuts their main paywall), model-run timestamp transparency.
**Drop:** editorial, Sessions, travel, hurricanes, Multi-Cam, spectra graphs, human forecaster content (doesn't exist for Israel anyway — their own subregion is `forecastStatus: inactive`).
**Community-source later:** Guide content (their guide data is human-authored and copyrighted — Rosa needs its own, user-generated).

---

## 4. Free Data Sources — Full Map

| Need | Best free source | Notes |
|---|---|---|
| Offshore waves (height, period, dir, partitioned swells) | **Copernicus Marine MEDSEA_ANALYSISFORECAST_WAV** (~2.5 km Med-specific WAM) | Free account; far better Med resolution than global WW3 (~25 km). Includes partitioned swell components — maps directly to Surfline's 6-slot model. |
| | NOAA **WW3** via NOMADS GRIB2 | Global fallback; what Surfline itself builds on. |
| | **ECMWF open data** (IFS+WAM, 0.25°) | Free since 2023, generally beats GFS in the Med. |
| Wind, pressure, air temp, weather | **GFS** (NOMADS) / **ECMWF open data** / **IMS** (Israel Met Service open data) | |
| **Shortcut for both** | **Open-Meteo** (Marine + Weather APIs) | Free JSON API, no GRIB pipeline, hourly, multiple models incl. MFWAM/ECMWF-WAM. Fastest possible MVP path. Check license terms for your usage model (free tier is non-commercial). |
| Tides | **EOT20** global tide model + **pyTMD** (fully open, CC-BY) | NOAA CO-OPS is US-only. For the Med this barely matters (0.3 m range) — compute harmonics offline once per spot, or even ship a static monthly table. |
| Water temp | **CMEMS SST** or NOAA **OISST** | Feeds wetsuit recommendation. |
| Sun times | Astronomical calc (SunCalc / astral) | Client-side, free. |
| Observed waves (validation/"observed heights") | **ISRAMAR** wave buoys (Haifa, Ashdod) — public real-time data | Surfline has no Israeli buoy integration; this is a genuine local edge. |
| Bathymetry (nearshore transform) | **GEBCO** (global) / EMODnet (Europe/Med, higher res) | Needed only if/when you build refraction-shoaling per spot. |
| Basemaps | OpenStreetMap / MapLibre + free tiles | Replaces their Google-attributed charts base. |
| Webcams | Existing free Israeli beach cams (e.g. the Beit Yanai cam is hosted by a surf shop and unauthenticated) | Partner with shops/municipalities the way Surfline does — hosting is the moat, not tech. |

---

## 5. The Transforms to Build (Rosa's real work)

1. **Extraction points** — one offshore lat/lon per coast segment (copy the `offshoreSwellLocation` pattern), sample the wave grid there.
2. **Spot transformation** — v1: per-spot exposure window (min/max swell direction that reaches the break) + a fixed height coefficient. v2: refraction/shoaling from bathymetry. Surfline's LOTUS nearshore layer is fancier, but for straight Israeli beachbreaks a calibrated coefficient gets ~90% of the value.
3. **Wind classification** — angle vs. per-spot `offshoreDirection` → Offshore / Cross / Onshore. One line of trig.
4. **Rating score** — 0–100 blend of swell energy in the exposure window, period bonus, wind penalty (onshore speed), calibrated per spot; bucket into POOR→EPIC labels. Start with a hand-tuned formula, refine with ISRAMAR buoy ground truth and user feedback (their "was our forecast accurate?" prompt is worth copying).
5. **Human phrasing** — height→body-relation table ("shin to knee", "waist to chest"); wetsuit/SPF lookup from water temp.

---

## 6. Suggested Lean MVP Cut

Single screen per spot: current summary card (rating, height phrase, wind, water temp) + 7-day forecast table (3-hourly: height, rating color, primary swell, wind w/ classification) + cam still where available. A favorites home list with live rating chips. One alert type. Hebrew+English. Everything else — charts map, graphs, guide, tide detail — is a later layer, added only if usage demands it.

Pipeline: scheduled fetch (Open-Meteo API to start; CMEMS GRIB pipeline when you want independence) → per-spot transform+score → static JSON per spot on a CDN → thin client. No backend at request time, near-zero hosting cost, honest "model run" timestamp like theirs.

---

## 7. Legal/ToS Cautions

Their processed API output, guide text, cam streams, and editorial are copyrighted — don't proxy or scrape them in the product. Everything in §4 is independently sourced and defensible. The saved session here is competitive research only.
