# Water clarity and pollution sources

Researched 2026-09-26 (a web-research agent, then the v1 sources probed live by hand). Anything marked
UNVERIFIED was not confirmed against a licence page or a live call. What Rosa ships is in "In use";
the rest is the map for later.

Two limits apply to everything here. **Satellite clarity** has cloud gaps and a coastal-pixel
problem at 300 m to 4 km, so it reads the water off the beach, not at it. **Bacteria** data is
mostly sampled weekly and only in the bathing season.

## In use (v1, 2026-09-26)

| Reading | Source | Coverage | Cadence | Access | Licence |
|---|---|---|---|---|---|
| Clarity | CMEMS GlobColour `OCEANCOLOUR_GLO_BGC_L3_NRT_009_101`, dataset `cmems_obs-oc_glo_bgc-transp_nrt_l3-multi-4km_P1D`, `ZSD` (Secchi depth, m) | global, 4 km | daily, ~2 days behind | anonymous ARCO Zarr on CloudFerro (`clarity.ZARR_URL`), no toolbox, no login | Copernicus Marine licence: commercial use + redistribution OK, attribution "E.U. Copernicus Marine Service Information" + DOI 10.48670/moi-00278, free to 2028-06-30 |
| Pollution, daily | NSW Beachwatch `https://api.beachwatch.nsw.gov.au/public/sites/geojson` | New South Wales, 246 sites | pollution forecast 2x a day; enterococci sample weekly | GeoJSON, no key | CC BY (data.nsw) |
| Pollution, yearly | EEA "Bathing Water Directive - Status of bathing water" (2025 v1.0, published 2026-06-02) | EU-27 + AL + CH, ~22k sites, with lat/lon | yearly | `.xlsx` in a zip via sdi.eea.europa.eu (the datahub page links it) | CC-BY 4.0 (DG ENV, EEA) |

**How it runs** (`clarity.py`, `bathing.py`, `cli._water_for`): on the VM, inside every `run`.
- Clarity is sampled once per UTC day and cached in `data/cache/clarity/<date>.json`. The other three
  cycles read that file. Each spot takes its newest cloud-free day within 7 days, from the nearest
  clear pixel within 3 cells (~14 km).
- Measured 2026-09-26 on the workstation: all 2290 spots in **11.9 s**, 82 chunks (66 MB on disk),
  **2290/2290 with a reading**. 1716 were from the newest day (2026-09-24); the oldest was 2026-09-19.
- Pollution: `data/water/bathing.yaml` (committed) ties each spot to one site within 2 km, made by the
  hand-run `bathing --match {eea,nsw}`. The yearly EEA grade lives in that file, so there is zero network
  for it. NSW is one GeoJSON request a cycle.
- First match, 2026-09-26: 281 EU spots, 35 NSW spots. EU sites whose last report is older than the
  previous season are dropped, and so are unclassified sites. The UK's last EU report is 2020, which
  would publish as current, so UK spots read "no data".
- No LLM calls anywhere.

**Yearly refresh:** when the EEA publishes a new season (June), download the zip, then run
`uv run --project pipeline rosa-pipeline bathing --match eea --xlsx <workbook>`. Review the diff of
`data/water/bathing.yaml` and commit it. **New spots:** re-run both matches (`--match nsw` needs no
file).

## Blocked

- **England, Environment Agency bathing-water API** (`environment.data.gov.uk/bwq`, `/doc/bathing-water`,
  `/data/...`): OGL, with a daily pollution-risk forecast. Every path answered **403** (Azure Application
  Gateway) from both the workstation and the VM on 2026-09-26, while the same host's flood API answered
  200. England reads "no data" until it opens (OPEN-ITEMS 42).

## Candidates (not built)

| Source | Measures | Coverage | Cadence | Access | Licence |
|---|---|---|---|---|---|
| CMEMS HR-OC (e.g. `OCEANCOLOUR_MED_BGC_HR_L4_NRT_009_211`) | turbidity, SPM, CHL from Sentinel-2, **100 m**, strip to 20 km | European seas | daily L3, monthly L4 (latency UNVERIFIED) | CMEMS store | CMEMS |
| NOAA CoastWatch ERDDAP `noaacwNPPN20S3AkdSCIDINEOF2kmDaily` | gap-filled Kd490 | global 2 km | daily, ~16 days behind when checked | ERDDAP | free redistribution, no registration |
| NASA OB.DAAC (PACE OCI, MODIS, VIIRS) | Kd490, chl | global ~1 km L2 | NRT < 3 h | HTTPS, Earthdata login | CC0 |
| EUMETSAT Sentinel-3 OLCI L2 `OL_2_WFR` | TSM, KD490, chl | global 300 m swaths | NRT < 3 h | Data Store, registration | Copernicus free access (licence page 403: UNVERIFIED) |
| UK water-company storm-overflow layers (Anglian, Northumbrian, United Utilities, Severn Trent, South West, Yorkshire, Thames) | live sewage overflow events | England | near real time | ArcGIS FeatureServer | CC BY 4.0 for those 7; Wessex and Scottish Water UNVERIFIED |
| EPA Victoria enterococci (DataVic) | enterococci | Port Phillip Bay, 36 beaches | Sep-May | CKAN | CC BY 4.0 |
| Queensland / Brisbane enterococci | enterococci | Brisbane | seasonal files | CKAN | CC BY 4.0 |
| California beach advisories + bacteria (data.ca.gov) | postings, results | California | CSVs, not live | CSV | ODC-BY; the bacteria set has no licence stated: UNVERIFIED |
| US Water Quality Portal | bacteria from 400+ agencies | USA | per agency | REST | UNVERIFIED |
| EPA BEACON 2.0 | advisories, closures | USA | yearly/quarterly | web, downloads | UNVERIFIED |
| Portugal APA bathing waters (dados.gov.pt) | sites + class | Portugal | UNVERIFIED | INSPIRE WFS/WMS | CC-BY |
| Japan MoE pre-season survey | fecal coliform, transparency | Japan ~730 beaches | yearly | PDF, map | PDL1.0 (attribution, mark edits, no framing) |
| NOAA IncidentNews | oil/chemical spills | US | per incident | CSV | public domain |
| SkyTruth Cerulean `api.cerulean.skytruth.org` | satellite oil slicks | global | NRT | OGC API | ToS UNVERIFIED |
| NOAA NCCOS HAB forecasts, HABSOS | algal blooms | Gulf, Gulf of Maine, Lake Erie, partners | 1-2x a week | ArcGIS, NCEI | UNVERIFIED |
| Hawaii DOH Clean Water Branch | bacteria, brown-water advisories | Hawaii | per event | web viewer | UNVERIFIED |
| Florida Healthy Beaches | enterococci | Florida | weekly/biweekly | county pages | UNVERIFIED |
| Israel Ministry of Health clean-shores map | bacteria per beach | Israel | several a day | web map only | UNVERIFIED - ask before building |
| INEA Rio de Janeiro | weekly bulletins, history since 2005 | RJ, 291 points | weekly | files | UNVERIFIED |
| Cape Town Beach Alerts | enterococci | Cape Town | weekly | web/app | UNVERIFIED |

## Excluded

- **Surfers Against Sewage (Safer Seas and Rivers):** terms say personal use only, "not for reproduction
  on any other website or for commercial gain". Its inputs (EA data and the overflow layers above) are open.
- **EMSA CleanSeaNet:** only for EU/EFTA authorities.
- **CETESB (Sao Paulo):** the QUALIPRAIA service needs a token. Only the weekly PDF bulletin is public, so
  using it would mean scraping.
- **France (baignades.sante.gouv.fr):** no licence stated, PDFs only. The EEA yearly grade covers France.
- **Spain NAYADE:** no licence found (UNVERIFIED). The EEA yearly grade covers Spain.
- **Swim Guide:** app terms not found (UNVERIFIED), and mostly Canadian.
