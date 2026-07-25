# Rosa - Build Plan v1

**Product:** Worldwide, mobile-first web app (PWA) for surf forecasting. Free, lean, slick, shareable. Daily-use tool for dedicated surfers. No paywall, no bloat.

---

## 1. Product Principles

1. **Answer the question** - "Should I surf, when, and where?" Every screen serves that; anything that doesn't is out.
2. **Speed is a feature** - first load < 2 s on 4G, forecast visible instantly from cache while fresh data loads. A surfer checks Rosa 3× a day for 20 seconds; respect that.
3. **Honest data** - always show model, run time, and confidence. No fake precision, no forecaster theater.
4. **Shareable by design** - every forecast state and every swell animation has a URL and an auto-generated share card.
5. **Free forever core** - sustained by near-zero infra cost (static data on CDN, no per-request backend). If revenue is ever needed: donations/partnerships, never a forecast paywall.

## 2. Feature Set

### MVP (v0.1 - one region to calibrate, but architecture worldwide from day 1)
- **Spot page** (the product): current summary card (rating, height phrase, swell, wind + offshore/onshore tag, water temp) → 7-day forecast table, 3-hourly, collapsible days: height range, rating color, primary+secondary swell, wind. Tide sparkline + sun times below.
- **Home = favorites list** with live rating chip, height, wind tag per spot; geolocated "spots near me" for first-time users.
- **Search** (spot name, region).
- **16-day outlook strip** (daily bars) - free, because it costs nothing; degrade gracefully with confidence shading.
- **PWA**: installable, offline-cached last forecast.

### v0.2 - the signature
- **Swell time-lapse** (the ISRAMAR-inspired feature): animated basin map of wave height/period/direction, scrubbable Now→+7d, auto-playable. Per-spot "swell story" mode: when a swell event is detected in the forecast, generate a shareable animated clip (map animation + arrival ETA + predicted peak at the spot). This is the growth loop: surfers share the incoming swell, the clip is branded Rosa.
- **Alerts**: "swell alert" (rating ≥ threshold at a favorite in next N days), web push.

### v0.3+
- Per-swell-train breakdown graphs (the useful 20% of Surfline's Analysis tab).
- Observed-vs-forecast overlay where buoys exist (NDBC worldwide, ISRAMAR partnership for Israel).
- Community spot guides (user-generated ideal-conditions, hazards, access) with light moderation. Never copy Surfline's guide text.
- Cams: embed free public cams where they exist; partner program later.

### Explicitly out
Editorial/video content, travel guides, sessions tracking, hurricanes center, multi-cam, human forecaster notes, accounts-as-gate (account only needed for favorites sync + alerts, and favorites work logged-out via local storage).

## 3. Architecture

**Pattern: precompute everything, serve static.**

```
[Model sources]            [Pipeline (scheduled, 4×/day)]         [Serving]
GFS + WW3 (NOMADS)  ──┐
ECMWF open data     ──┤→  fetch grids → extract at offshore  →  per-spot JSON on CDN
CMEMS regional      ──┤    points → spot transform + score       (~5 KB/spot, cache-busted
OISST / SST         ──┘    → phrase/wetsuit/tide/sun merge        by model run)
                           → render map frame tiles (PNG/WebP)→  animation tiles on CDN
EOT20 tides (offline harmonics, computed at build per spot)
```

- **Pipeline**: Python (xarray + cfgrib + pyTMD), runs on a scheduled worker (GitHub Actions is enough at first; then a small VM/Cloud Run). Each run: download GRIB subsets → sample extraction points → transform → write JSON + frames to object storage behind a CDN.
- **Frontend**: React/Preact PWA, MapLibre GL for the animated map (vector basemap + raster/particle overlay tiles), no server-side rendering needed beyond static hosting. Share cards via a tiny edge function (or pre-rendered per model run).
- **No request-time backend** for forecasts. Only alerts/accounts need a small API + push service (v0.2).
- **Start with Open-Meteo Marine+Weather API** in the pipeline instead of raw GRIBs to ship v0.1 in weeks, then swap the fetch layer for NOMADS/ECMWF/CMEMS without touching anything downstream. (Open-Meteo is CC-BY / free for non-commercial; a free app with attribution is compatible, verify before launch.)

## 4. Data Sources (worldwide + regional enhancers)

| Layer | Global default | Regional upgrades (same interface) |
|---|---|---|
| Waves (partitioned swells) | NOAA WW3 0.25° / ECMWF-WAM 0.25° (open) | CMEMS MEDSEA WAM ~2.5 km (Med), CMEMS IBI/other regional wave models (Atlantic Europe), PacIOOS (Hawaii) |
| Wind/weather/pressure | GFS 0.25° / ECMWF IFS open | National meteo open data where better |
| Tides | EOT20 harmonics via pyTMD (offline, global) | NOAA CO-OPS stations (US) for exactness |
| SST → wetsuit | NOAA OISST / CMEMS | - |
| Sun times | computed (astral) | - |
| Observations (validation) | NDBC buoy network | ISRAMAR buoys (partnership), CDIP (US West), EMODnet |
| Bathymetry (later, nearshore v2) | GEBCO 2024 | EMODnet (Europe) |
| Basemap | OSM vector tiles (MapLibre) | - |

## 5. Spot Model (per-spot config = the product's real database)

```yaml
id: beit-yanai
name: Beit Yanai
lat: 32.391, lon: 34.862
timezone: Asia/Jerusalem
offshore_point: [32.0, 34.4]        # deep-water extraction point (shared per coast segment)
offshore_direction: 90              # direction the offshore WIND blows FROM (Israel coast faces W → E wind = offshore → 90)
swell_window: [250, 340]            # directions that reach the break
height_coeff: 1.0                   # offshore→breaker calibration (v1 scalar)
# Example only - canonical values always live in data/spots/*.yaml.
ideal:
  swell_dir: [280, 320]
  wind_dir: [60, 120]               # offshore = E sector
  size_m: [0.6, 1.5]
break_type: beach
```

Seed strategy: start from open spot lists (OSM `sport=surfing` nodes, Wikipedia/wannasurf-style open data, community submissions), auto-derive `offshore_direction` from coastline geometry (OSM coastline vector → shore normal), default `height_coeff`=1.0, refine by community feedback + buoy comparison. Never import Surfline's spot database.

## 6. Rating Score v1 (transparent, published)

```
energy_in_window = Σ over swell partitions within swell_window of (H² × T)
size_score  = clamp01(ramp(energy vs. spot ideal size))        # 0-40 pts
period_bonus = scaled T of dominant partition                  # 0-20 pts
wind_score  = f(angle to offshore_direction, speed)            # 0-40 pts
              offshore light = max; onshore >25 kph = 0
score = size + period + wind → buckets: FLAT / POOR / FAIR / GOOD / FIRING
```
Tunable per break type; publish the formula in-app ("why this rating") - transparency is a differentiator against LOTUS's black box and builds trust.

## 7. Design Direction

Dark-first (surfers check pre-dawn), one accent color per rating scale, generous type, thumb-reachable day navigation, zero interstitials. The forecast table is the hero - Surfline's table layout is genuinely good; keep the information density, lose the chrome, upsells, and tab sprawl. Target: everything a surfer needs within two taps of open.

## 8. Milestones

1. **Week 1-2 - Skeleton**: pipeline on Open-Meteo for ~20 Israeli+Med spots, spot JSON on CDN, PWA with spot page + favorites. Internal daily use begins (dogfood at Beit Yanai).
2. **Week 3-4 - Calibrate**: compare vs. ISRAMAR buoys + your own eyes; tune height_coeff and score; add tide (EOT20) + sun; polish table UI.
3. **Week 5-8 - Signature + scale**: swell time-lapse map (render frames from WW3/ECMWF grids), share cards, search, expand spot DB to first worldwide batch (Med, Portugal, Sri Lanka, Central America - where you have contacts to validate), soft launch to local crew.
4. **Quarter 2**: alerts + push, per-swell graphs, community guide fields, migrate pipeline off Open-Meteo to raw grids, regional model upgrades, public launch.

## 9. Risks & Watch-outs

- **Licensing**: Open-Meteo attribution/commercial terms; CMEMS requires registration + attribution (fine); ISRAMAR data is all-rights-reserved - partner, don't scrape; never reproduce Surfline content, spot text, or their processed API output.
- **Nearshore accuracy** on reefs/points (coefficient model is crude there) - mitigate with per-spot community calibration feedback ("was this accurate?" one-tap, like Surfline's prompt).
- **Spot DB quality** is the long-term moat and the long-term grind - design the contribution flow early.
- **Cost creep**: map frame rendering is the only expensive step; pre-render at fixed zooms per basin, WebP, aggressive CDN caching.
