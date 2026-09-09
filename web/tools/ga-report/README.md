# ga-report

Pulls Rosa's GA4 data and prints the questions worth asking, rather than a dashboard.

## Setup (once)

1. **Google Cloud** (console.cloud.google.com), project `rosa-502921`:
   - APIs & Services → enable **Google Analytics Data API**
   - IAM → Service Accounts → Create → Keys → **Add key → JSON** → download
2. **GA4** → Admin → **Property Access Management** → add the service account's email
   (`...@rosa-502921.iam.gserviceaccount.com`) as **Viewer**
3. Put the JSON outside the repo and point at it:

```
export GA_SA_KEY=~/.config/rosa/ga-sa.json     # never in the repo
uv run --project pipeline python tools/ga-report/report.py            # last 28 days
uv run --project pipeline python tools/ga-report/report.py --days 7
uv run --project pipeline python tools/ga-report/report.py --json     # machine-readable
```

Property `553528140` (rosa.surf, stream RosaSurf, measurement id G-NKQNM6YLQ1).

## What it reports

- **Where** - users by country and city, and the split between them
- **What they open** - top spots by `spot_view`, and the same grouped by region
- **Who converts** - spots opened often but rarely favourited, which is the closest thing
  Rosa has to "the forecast disappointed them"
- **Preferences** - units, theme, signed-in and installed shares, as GA4 user properties
- **Screens** - page views by screen, so the Map/Charts/Spots split is visible

No SDK: the Data API is REST and a service-account JWT, which `report.py` signs itself.
GA4's API is aggregated and sampled - for raw per-event analysis use the BigQuery export
(linked 2026-09-10, daily, dataset `analytics_553528140` in `rosa-502921`).
