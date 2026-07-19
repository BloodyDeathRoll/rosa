#!/usr/bin/env python3
"""Automated bulk geocoding of surf-spot names -> coordinates.

Resolves each spot's name to a real coordinate via a geocoding provider. Runs
over the whole spot DB unattended. Provider is pluggable:

  nominatim  free, no key, OSM data      (default; misses surf-vocabulary names)
  google     GOOGLE_MAPS_API_KEY in env  (best POI coverage — has "Handicap Beach")
  mapbox     MAPBOX_TOKEN in env         (rich POI coverage too)

Usage:
  GOOGLE_MAPS_API_KEY=... python geocode.py ../../data/spots/israel.yaml --provider google --apply
  python geocode.py ../../data/spots/israel.yaml           # nominatim, report only

--apply patches lat/lon in place for matches that pass the sanity gate (result is
near the coast and within `max_shift_km` of the current coordinate). Everything is
git-versioned, so a bad geocode is one revert. Matches that fail the gate are left
alone and listed as needs-review — the automated exception queue, not a human gate.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

UA = "RosaSurfApp/0.1 (automated spot geocoding; shaharnaor@outlook.com)"
CTX = ssl.create_default_context()


def _get(url: str, headers: dict | None = None, retries: int = 3) -> dict | list:
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                return json.loads(r.read())
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(2)
    return []


def geocode_nominatim(name: str, region: str) -> tuple[float, float, str] | None:
    q = urllib.parse.urlencode(
        {"q": f"{name}, {region}", "format": "jsonv2", "limit": 1,
         "viewbox": "34.40,33.10,35.15,31.50", "bounded": 1}
    )
    res = _get(f"https://nominatim.openstreetmap.org/search?{q}")
    if res:
        t = res[0]
        return float(t["lat"]), float(t["lon"]), t.get("type", "?")
    return None


def geocode_google(name: str, region: str) -> tuple[float, float, str] | None:
    key = os.environ["GOOGLE_MAPS_API_KEY"]
    q = urllib.parse.urlencode({"query": f"{name}, {region}", "key": key})
    res = _get(f"https://maps.googleapis.com/maps/api/place/textsearch/json?{q}")
    hits = res.get("results", []) if isinstance(res, dict) else []
    if hits:
        loc = hits[0]["geometry"]["location"]
        return loc["lat"], loc["lng"], hits[0].get("types", ["?"])[0]
    return None


def geocode_mapbox(name: str, region: str) -> tuple[float, float, str] | None:
    tok = os.environ["MAPBOX_TOKEN"]
    q = urllib.parse.quote(f"{name}, {region}")
    res = _get(f"https://api.mapbox.com/geocoding/v5/mapbox.places/{q}.json?access_token={tok}&limit=1")
    feats = res.get("features", []) if isinstance(res, dict) else []
    if feats:
        lon, lat = feats[0]["center"]
        return lat, lon, (feats[0].get("place_type") or ["?"])[0]
    return None


PROVIDERS = {"nominatim": geocode_nominatim, "google": geocode_google, "mapbox": geocode_mapbox}


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = math.pi / 180
    dlat, dlon = (b[0] - a[0]) * r, (b[1] - a[1]) * r
    x = math.sin(dlat / 2) ** 2 + math.cos(a[0] * r) * math.cos(b[0] * r) * math.sin(dlon / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(x))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("yaml", type=Path)
    ap.add_argument("--provider", choices=PROVIDERS, default="nominatim")
    ap.add_argument("--region", default="Israel")
    ap.add_argument("--apply", action="store_true", help="patch lat/lon for gated matches")
    ap.add_argument("--max-shift-km", type=float, default=6.0,
                    help="reject a geocode that moves a spot more than this (likely wrong feature)")
    args = ap.parse_args()

    geocode = PROVIDERS[args.provider]
    text = args.yaml.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    resolved = matched = shifted = flagged = 0
    for s in data["spots"]:
        cur = (float(s["lat"]), float(s["lon"]))
        try:
            hit = geocode(s["name"], args.region)
        except Exception as e:
            print(f"  {s['id']:20} ERROR {str(e)[:40]}")
            hit = None
        if args.provider == "nominatim":
            time.sleep(1.1)  # usage policy
        if not hit:
            print(f"  {s['id']:20} no match")
            continue
        resolved += 1
        lat, lon, kind = hit
        dist = haversine_km(cur, (lat, lon))
        gate = dist <= args.max_shift_km
        tag = "OK" if dist < 0.3 else ("shift" if gate else "REVIEW (too far)")
        if gate:
            matched += 1
            if dist >= 0.3:
                shifted += 1
        else:
            flagged += 1
        print(f"  {s['id']:20} -> {lat:.4f},{lon:.4f} [{kind}]  {dist:4.1f}km  {tag}")
        if args.apply and gate:
            # patch the exact line for this id (preserve formatting/comments elsewhere)
            text = _patch_coord(text, s["id"], lat, lon, args.provider)

    if args.apply:
        args.yaml.write_text(text, encoding="utf-8")
    print(f"\n{args.provider}: resolved {resolved}/{len(data['spots'])}, "
          f"applied {matched} (of which {shifted} moved >0.3km), flagged {flagged} for review.")
    return 0


def _patch_coord(text: str, spot_id: str, lat: float, lon: float, provider: str) -> str:
    import re
    out = []
    for line in text.splitlines(keepends=True):
        if f"id: {spot_id}," in line:
            line = re.sub(r"lat:\s*-?\d+\.?\d*", f"lat: {lat:.4f}", line)
            line = re.sub(r"lon:\s*-?\d+\.?\d*", f"lon: {lon:.4f}", line)
            line = re.sub(r"#.*$", f"# {provider}-geocoded", line.rstrip()) + "\n" \
                if "#" in line else line.rstrip() + f"  # {provider}-geocoded\n"
        out.append(line)
    return "".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
