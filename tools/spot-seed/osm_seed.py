#!/usr/bin/env python3
"""OSM surf-spot seed extractor (ODbL source).

Pulls `sport=surfing` features from the Overpass API per country, splits real
breaks from businesses (shops / schools / rentals - by tag AND by name), and
dedupes against the spots already committed in data/spots/<region>.yaml. Prints
a north→south candidate list and writes JSON per region for review.

This is a SEED/PROPOSAL tool - it never edits the spot DB. Candidates still go
through the authority ladder (sat-verify → user-verify) before being added, and
anything published from OSM data must be attributed to OpenStreetMap (© OSM
contributors, ODbL).

Usage:
    python tools/spot-seed/osm_seed.py japan
    python tools/spot-seed/osm_seed.py all
"""

from __future__ import annotations
import json
import math
import re
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

# public Overpass instances - tried in order, with backoff, on 429/504/timeout
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
ROOT = Path(__file__).resolve().parents[2]
SPOTS_DIR = ROOT / "data" / "spots"
OUT_DIR = Path(__file__).resolve().parent / "candidates"

# region yaml stem -> ISO 3166-1 alpha-2 (Overpass area code)
REGIONS = {
    "israel": "IL",
    "costa-rica": "CR",
    "sri-lanka": "LK",
    "japan": "JP",
    "portugal": "PT",
    "nicaragua": "NI",
    "philippines": "PH",
}

DEDUPE_KM = 3.0  # a break within this of an existing spot = same spot

# a facility/business, by tag...
BIZ_TAG_KEYS = {"shop", "office", "craft"}
BIZ_TOURISM = {"hotel", "guest_house", "hostel", "apartment", "motel", "chalet"}
BIZ_LEISURE = {"sports_centre", "fitness_centre"}
# ...or by name (OSM often tags a surf school as bare sport=surfing)
BIZ_NAME_RE = re.compile(
    r"(\b(school|escola|shop|store|rental|rentals|lesson|lessons|camp|campismo|camping|"
    r"hostel|hostal|hotel|pousada|guest\s?house|surfboard|repair|ding|caf[eé]|bar|"
    r"club|clube|academy|resort|lodge|villa|apartments?|rooms?|surfhouse|lounge|"
    r"cent(er|re|ro)|kite\w*|\bsup\b|yoga|scuba|div(e|ing)|pesqueiro|rendimento|"
    r"collective|co\.?|inc\.?)\b|surfshop|surf\s?camp)",
    re.I,
)


def haversine_km(a_lat, a_lon, b_lat, b_lon):
    R = 6371.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def load_existing(region: str):
    """(id, lat, lon) for every spot in data/spots/<region>.yaml, regex-parsed
    so the tool needs no pipeline env / yaml semantics."""
    text = (SPOTS_DIR / f"{region}.yaml").read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"\bid:\s*([a-z0-9-]+)", text):
        seg = text[m.start() : m.start() + 400]
        lat = re.search(r"\blat:\s*(-?[0-9.]+)", seg)
        lon = re.search(r"\blon:\s*(-?[0-9.]+)", seg)
        if lat and lon:
            out.append((m.group(1), float(lat.group(1)), float(lon.group(1))))
    return out


def is_business(tags):
    if any(k in tags for k in BIZ_TAG_KEYS):
        return True
    if "amenity" in tags:
        return True
    if tags.get("tourism") in BIZ_TOURISM:
        return True
    if "club" in tags or tags.get("leisure") in BIZ_LEISURE:
        return True
    name = " ".join(v for k, v in tags.items() if k.startswith("name"))
    if name and BIZ_NAME_RE.search(name):
        return True
    return False


def name_of(tags):
    return tags.get("name:en") or tags.get("name") or tags.get("name:ja") or "(unnamed)"


def query_overpass(iso: str):
    q = (
        f'[out:json][timeout:180];area["ISO3166-1"="{iso}"][admin_level=2]->.a;'
        f'(nwr["sport"="surfing"](area.a););out center tags;'
    )
    data = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt in range(4):
        endpoint = OVERPASS_ENDPOINTS[attempt % len(OVERPASS_ENDPOINTS)]
        try:
            req = urllib.request.Request(
                endpoint, data=data, headers={"User-Agent": "rosa-spot-seed/0.1"}
            )
            with urllib.request.urlopen(req, timeout=200) as r:
                return json.load(r).get("elements", [])
        except Exception as e:  # 429/504/timeout - back off and try next mirror
            last = e
            print(
                f"    {endpoint.split('//')[1].split('/')[0]} failed ({e}); retrying",
                file=sys.stderr,
            )
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"all Overpass endpoints failed: {last}")


def run_region(region: str, iso: str):
    existing = load_existing(region)
    els = query_overpass(iso)
    breaks, biz = [], []
    for e in els:
        tags = e.get("tags", {})
        lat = e.get("lat") or (e.get("center") or {}).get("lat")
        lon = e.get("lon") or (e.get("center") or {}).get("lon")
        if lat is None or lon is None:
            continue
        rec = {
            "type": e["type"],
            "id": e["id"],
            "name": name_of(tags),
            "lat": round(lat, 5),
            "lon": round(lon, 5),
            "tags": tags,
        }
        (biz if is_business(tags) else breaks).append(rec)
    new, matched = [], []
    for b in breaks:
        if existing:
            near = min(existing, key=lambda e: haversine_km(b["lat"], b["lon"], e[1], e[2]))
            dmin = haversine_km(b["lat"], b["lon"], near[1], near[2])
            b["km_to_nearest"] = round(dmin, 1)
            b["nearest_existing"] = near[0]
        else:
            dmin = 999
        (matched if dmin < DEDUPE_KM else new).append(b)
    new.sort(key=lambda b: -b["lat"])
    OUT_DIR.mkdir(exist_ok=True)
    summary = {
        "region": region,
        "iso": iso,
        "existing_spots": len(existing),
        "raw": len(els),
        "business": len(biz),
        "candidates": len(breaks),
        "matched_existing": len(matched),
        "new": len(new),
    }
    json.dump(
        {"summary": summary, "new": new, "matched": matched, "business": biz},
        open(OUT_DIR / f"{region}.json", "w"),
        ensure_ascii=False,
        indent=1,
    )
    return summary, new


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return
    regions = list(REGIONS) if args[0] == "all" else [args[0]]
    rows = []
    for region in regions:
        iso = REGIONS.get(region)
        if not iso:
            print(f"unknown region '{region}' (known: {', '.join(REGIONS)})", file=sys.stderr)
            continue
        print(f"\n### {region} ({iso}) - querying Overpass ...", file=sys.stderr)
        try:
            summary, new = run_region(region, iso)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        rows.append(summary)
        s = summary
        print(
            f"  existing {s['existing_spots']:>3} | raw {s['raw']:>3} | "
            f"biz {s['business']:>3} | breaks {s['candidates']:>3} | "
            f"match {s['matched_existing']:>3} | NEW {s['new']:>3}"
        )
        if len(regions) == 1:
            for b in new:
                extra = [
                    f"{k}={b['tags'][k]}"
                    for k in ("natural", "leisure", "name:ja")
                    if k in b["tags"]
                ]
                print(
                    f"    {b['lat']:.4f},{b['lon']:.4f}  {b['name'][:36]:36} "
                    f"[{b['type']}/{b['id']}]  {' '.join(extra)}"
                )
        if len(regions) > 1:
            time.sleep(3)  # be polite to the public Overpass instance
    if len(rows) > 1:
        print("\n=== 7-country OSM yield ===")
        print(
            f"{'region':13} {'have':>5} {'raw':>5} {'biz':>4} {'break':>6} {'match':>6} {'NEW':>5}"
        )
        tot = {
            k: 0
            for k in ("existing_spots", "raw", "business", "candidates", "matched_existing", "new")
        }
        for s in rows:
            print(
                f"{s['region']:13} {s['existing_spots']:>5} {s['raw']:>5} "
                f"{s['business']:>4} {s['candidates']:>6} {s['matched_existing']:>6} {s['new']:>5}"
            )
            for k in tot:
                tot[k] += s[k]
        print(
            f"{'TOTAL':13} {tot['existing_spots']:>5} {tot['raw']:>5} "
            f"{tot['business']:>4} {tot['candidates']:>6} {tot['matched_existing']:>6} {tot['new']:>5}"
        )


if __name__ == "__main__":
    main()
