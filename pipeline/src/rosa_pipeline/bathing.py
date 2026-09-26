"""Water pollution: official bathing-water quality at the spots that have a site nearby.

Two kinds of source (docs/WATER-SOURCES.md), one per spot, chosen once by the match tool
(``bathing --match``) and committed in ``data/water/bathing.yaml``:

* ``nsw`` - NSW Beachwatch (CC BY): a daily pollution forecast and the latest enterococci
  grade per site, one GeoJSON request for the whole state per cycle.
* ``eea`` - the EU Bathing Water Directive yearly class (EEA, CC-BY 4.0): read from the
  committed yaml, zero network; the operator re-runs the match once a year when a new
  season is published.

Daily beats yearly: a spot matched to a daily source keeps it. England's daily feed (the
Environment Agency bathing-water API) answered 403 to every request on 2026-09-26, so
England has no source yet and shows "no data" (OPEN-ITEMS 42).

Everything normalises to ``grade`` 1-4 (4 best) plus the source's own ``label``, an
``alert`` flag when the daily forecast says pollution is likely, the ``cadence``
("daily" | "sample" | "yearly") and the ``date`` it describes. Display only.
"""

from __future__ import annotations

import math
from pathlib import Path

import httpx
import yaml

NSW_URL = "https://api.beachwatch.nsw.gov.au/public/sites/geojson"
ATTRIBUTION_NSW = "Beach pollution (NSW): Beachwatch, NSW DCCEEW, CC BY"
ATTRIBUTION_EEA = "Bathing water quality (EU): European Environment Agency, CC-BY 4.0"
SITES_FILE = Path("data/water/bathing.yaml")
MATCH_RADIUS_KM = 2.0

# EEA "quality" strings -> grade (4 best). "0 - Not classified" and friends get no grade.
EEA_GRADE = {"1": (4, "Excellent"), "2": (3, "Good"), "3": (2, "Sufficient"), "4": (1, "Poor")}
# NSW latestResultRating is already 4 best (Good 4, Fair 3, Poor 2, Bad 1).
NSW_LABEL = {4: "Good", 3: "Fair", 2: "Poor", 1: "Bad"}


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def load_sites(path: Path = SITES_FILE) -> dict[str, dict]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def eea_entry(site: dict) -> dict | None:
    q = str(site.get("quality") or "")
    g = EEA_GRADE.get(q.split(" ", 1)[0])
    if g is None:
        return None
    return {
        "grade": g[0],
        "label": g[1],
        "alert": False,
        "cadence": "yearly",
        "date": str(site["season"]),
        "src": "eea",
    }


def nsw_entry(props: dict) -> dict | None:
    rating = props.get("latestResultRating")
    if rating not in NSW_LABEL:
        return None
    forecast = str(props.get("pollutionForecast") or "")
    grade = int(rating)
    if forecast == "Possible":
        grade = min(grade, 2)  # the agency's own "pollution possible" caps the reading
    has_forecast = forecast in ("Unlikely", "Possible", "Likely")
    when = props.get("pollutionForecastTimeStamp") if has_forecast else None
    when = when or props.get("latestResultObservationDate") or ""
    return {
        "grade": grade,
        "label": NSW_LABEL[int(rating)],
        "alert": forecast == "Likely",
        "cadence": "daily" if has_forecast else "sample",
        "date": str(when)[:10],
        "src": "nsw",
    }


def fetch_nsw(timeout_s: float = 30.0, transport: httpx.BaseTransport | None = None) -> dict:
    with httpx.Client(timeout=timeout_s, transport=transport) as client:
        resp = client.get(NSW_URL)
        resp.raise_for_status()
        return resp.json()


def nsw_by_id(geojson: dict) -> dict[str, dict]:
    return {
        f["properties"]["id"]: {
            **f["properties"],
            "lon": f["geometry"]["coordinates"][0],
            "lat": f["geometry"]["coordinates"][1],
        }
        for f in geojson.get("features", [])
        if f.get("properties", {}).get("id") and f.get("geometry")
    }


def pollution_for(spot_ids: list[str], sites: dict[str, dict], nsw_fetch=fetch_nsw) -> dict:
    """spot id -> pollution entry (or None). One NSW request when any spot needs it; a
    failed request costs those spots their reading for the cycle, never the run."""
    import sys

    nsw: dict[str, dict] | None = None
    if any(sites.get(s, {}).get("src") == "nsw" for s in spot_ids):
        try:
            nsw = nsw_by_id(nsw_fetch())
        except Exception as e:
            print(f"warn: NSW Beachwatch skipped ({e!r})", file=sys.stderr)
    out: dict[str, dict | None] = {}
    for sid in spot_ids:
        site = sites.get(sid)
        entry = None
        if site and site.get("src") == "eea":
            entry = eea_entry(site)
        elif site and site.get("src") == "nsw" and nsw is not None:
            props = nsw.get(site.get("site_id"))
            entry = nsw_entry(props) if props else None
        out[sid] = entry
    return out


# -- match tool (hand-run; writes the committed yaml for review) ------------------------


def eea_sites_from_xlsx(path: Path) -> list[dict]:
    """Latest graded season per coastal/transitional EU bathing water, with coordinates."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    head = [str(h) for h in next(rows)]
    ix = {h: i for i, h in enumerate(head)}
    latest: dict[str, dict] = {}
    for r in rows:
        if r[ix["bathingWaterType"]] not in ("coastalBathingWater", "transitionalBathingWater"):
            continue
        lat, lon = r[ix["lat"]], r[ix["lon"]]
        if lat is None or lon is None:
            continue
        sid = str(r[ix["bathingWaterIdentifier"]])
        season = int(r[ix["season"]])
        if sid in latest and latest[sid]["season"] >= season:
            continue
        latest[sid] = {
            "site_id": sid,
            "name": str(r[ix["bathingWaterName"]] or "").strip(),
            "lat": float(lat),
            "lon": float(lon),
            "season": season,
            "quality": str(r[ix["quality"]] or ""),
        }
    # A site whose last report is older than the previous season is gone from the
    # scheme - the UK's last EU report is 2020 (Brexit), which must not publish as
    # current - and an unclassified site has no grade to show.
    newest = max((v["season"] for v in latest.values()), default=0)
    return [
        v
        for v in latest.values()
        if v["season"] >= newest - 1 and v["quality"].split(" ", 1)[0] in EEA_GRADE
    ]


def match(
    spots: dict, candidates: list[dict], src: str, radius_km: float = MATCH_RADIUS_KM
) -> dict[str, dict]:
    """Nearest candidate site within ``radius_km`` of each spot's pin."""
    out: dict[str, dict] = {}
    for spot_id, spot in spots.items():
        best: tuple[float, dict] | None = None
        for c in candidates:
            if abs(c["lat"] - spot.lat) > 0.1:  # cheap prefilter, ~11 km
                continue
            d = km_between((spot.lat, spot.lon), (c["lat"], c["lon"]))
            if d <= radius_km and (best is None or d < best[0]):
                best = (d, c)
        if best is not None:
            d, c = best
            entry = {"src": src, "site_id": c["site_id"], "name": c["name"], "km": round(d, 2)}
            if src == "eea":
                entry.update(season=c["season"], quality=c["quality"])
            out[spot_id] = entry
    return out


def merge_sites(existing: dict[str, dict], new: dict[str, dict], src: str) -> dict[str, dict]:
    """Replace every ``src`` match with ``new`` (a re-run drops spots that lost theirs);
    daily beats yearly, so a yearly match never replaces a daily one."""
    merged = {k: v for k, v in existing.items() if v.get("src") != src}
    for sid, entry in new.items():
        old = merged.get(sid)
        if old and old.get("src") != "eea" and entry["src"] == "eea":
            continue
        merged[sid] = entry
    return dict(sorted(merged.items()))
