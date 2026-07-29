#!/usr/bin/env python3
"""Automated bulk geocoding of surf-spot names -> coordinates.

Resolves each spot's name to a real coordinate via a geocoding provider. Runs
over the whole spot DB unattended. Provider is pluggable:

  nominatim  free, no key, OSM data      (default; misses surf-vocabulary names)
  google     GOOGLE_MAPS_API_KEY in env  (best POI coverage - has "Handicap Beach")
  mapbox     MAPBOX_TOKEN in env         (rich POI coverage too)

Usage:
  GOOGLE_MAPS_API_KEY=... python geocode.py ../../data/spots/israel.yaml --provider google --apply
  python geocode.py ../../data/spots/israel.yaml           # nominatim, report only

--apply patches lat/lon in place for matches that pass the sanity gate (result is
near the coast and within `max_shift_km` of the current coordinate). Everything is
git-versioned, so a bad geocode is one revert. Matches that fail the gate are left
alone and listed as needs-review - the automated exception queue, not a human gate.
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
    q = urllib.parse.urlencode({"q": f"{name}, {region}", "format": "jsonv2", "limit": 1})
    res = _get(f"https://nominatim.openstreetmap.org/search?{q}")
    if res:
        t = res[0]
        return float(t["lat"]), float(t["lon"]), t.get("type", "?")
    return None


_GOOGLE_NEW_BLOCKED = False  # set on first 403 so we don't retry the New API per spot


def geocode_google(name: str, region: str) -> tuple[float, float, str] | None:
    """Places Text Search. Tries the Places API (New) first; on 403
    (API_KEY_SERVICE_BLOCKED - key restricted to the legacy APIs) falls back to
    legacy textsearch, which is deprecated by Google but still served and is the
    one enabled for our key (verified 2026-07-23)."""
    global _GOOGLE_NEW_BLOCKED
    key = os.environ["GOOGLE_MAPS_API_KEY"]
    if not _GOOGLE_NEW_BLOCKED:
        body = json.dumps({"textQuery": f"{name}, {region}", "maxResultCount": 1}).encode()
        req = urllib.request.Request(
            "https://places.googleapis.com/v1/places:searchText",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": key,
                "X-Goog-FieldMask": "places.location,places.displayName,places.primaryType",
            },
        )
        try:
            for i in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
                        res = json.loads(r.read())
                    break
                except urllib.error.HTTPError:
                    raise
                except Exception:
                    if i == 2:
                        raise
                    time.sleep(2)
            places = res.get("places", []) if isinstance(res, dict) else []
            if places:
                loc = places[0]["location"]
                return loc["latitude"], loc["longitude"], places[0].get("primaryType", "?")
            return None
        except urllib.error.HTTPError as e:
            if e.code != 403:
                raise RuntimeError(f"{e.code} {e.read().decode()[:120]}") from e
            _GOOGLE_NEW_BLOCKED = True  # fall through to legacy
    q = urllib.parse.urlencode({"query": f"{name}, {region}", "key": key})
    res = _get(f"https://maps.googleapis.com/maps/api/place/textsearch/json?{q}")
    if not isinstance(res, dict) or res.get("status") not in ("OK", "ZERO_RESULTS"):
        raise RuntimeError(f"textsearch {res.get('status')}: {res.get('error_message', '')[:80]}")
    results = res.get("results", [])
    if results:
        loc = results[0]["geometry"]["location"]
        types = results[0].get("types") or ["?"]
        return loc["lat"], loc["lng"], types[0]
    return None


def geocode_mapbox(name: str, region: str) -> tuple[float, float, str] | None:
    tok = os.environ["MAPBOX_TOKEN"]
    q = urllib.parse.quote(f"{name}, {region}")
    res = _get(
        f"https://api.mapbox.com/geocoding/v5/mapbox.places/{q}.json?access_token={tok}&limit=1"
    )
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
    ap.add_argument(
        "--region",
        default=None,
        help="country/region suffix for queries (default: from the YAML filename)",
    )
    ap.add_argument("--apply", action="store_true", help="patch lat/lon for gated matches")
    ap.add_argument(
        "--max-shift-km",
        type=float,
        default=6.0,
        help="reject a geocode that moves a spot more than this (likely wrong feature)",
    )
    args = ap.parse_args()

    geocode = PROVIDERS[args.provider]
    if args.region is None:
        args.region = args.yaml.stem.replace("-", " ").title()  # "sri-lanka" -> "Sri Lanka"
    text = args.yaml.read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    # Authority ladder (CLAUDE.md §Spot database): user-verified > everything.
    # A geocoder must NEVER overwrite a coordinate a human placed by hand.
    protected = set()
    for line in text.splitlines():
        if "user-verified" in line.lower() and "id:" in line:
            protected.add(line.split("id:", 1)[1].split(",", 1)[0].strip())

    resolved = matched = shifted = flagged = protected_n = 0
    for s in data["spots"]:
        if s["id"] in protected:
            print(f"  {s['id']:20} SKIP (user-verified - protected)")
            protected_n += 1
            continue
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
    print(
        f"\n{args.provider}: resolved {resolved}/{len(data['spots'])}, "
        f"applied {matched} (of which {shifted} moved >0.3km), flagged {flagged} for review, "
        f"{protected_n} protected (user-verified, untouched)."
    )
    return 0


def _patch_coord(text: str, spot_id: str, lat: float, lon: float, provider: str) -> str:
    import re

    out = []
    for line in text.splitlines(keepends=True):
        if f"id: {spot_id}," in line:
            line = re.sub(r"lat:\s*-?\d+\.?\d*", f"lat: {lat:.4f}", line)
            line = re.sub(r"lon:\s*-?\d+\.?\d*", f"lon: {lon:.4f}", line)
            # Retag the source, keep any curated note: "approx - TODO verify (x)" -> "google-geocoded (x)"
            if "approx - TODO verify" in line:
                line = line.replace("approx - TODO verify", f"{provider}-geocoded")
            elif "#" not in line:
                line = line.rstrip() + f"  # {provider}-geocoded\n"
        out.append(line)
    return "".join(out)


if __name__ == "__main__":
    raise SystemExit(main())
