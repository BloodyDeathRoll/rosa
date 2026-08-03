#!/usr/bin/env python3
"""Coastline break GENERATOR - proof (Israel Mediterranean coast).

Instead of harvesting a list of named spots (all such lists are tiny-open or
proprietary), this generates the candidate-break universe from the coast itself:
pull OSM natural=coastline (ODbL), resample it, and at each point derive the
shore-normal orientation → offshore_direction + swell exposure. Comprehensive by
construction - bounded by the length of coast, not by who mapped a spot.

This proof does the geometric core (segment → orientation → openness gate →
cluster) and validates against the 40 spots already in israel.yaml. The bathy +
swell-climatology gates (which prune the over-generation) are the next layer.

Usage: python tools/spot-seed/coast_generate.py [spacing_m]
"""

from __future__ import annotations
import json
import math
import re
import sys
import urllib.request
import urllib.parse
from pathlib import Path

OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
ROOT = Path(__file__).resolve().parents[2]
YAML = ROOT / "data" / "spots" / "israel.yaml"
OUT = Path(__file__).resolve().parent / "candidates" / "israel-generated.json"

# Israel Mediterranean coast bbox (S,W,N,E) - excludes Dead Sea / Galilee / Eilat
BBOX = (31.40, 34.20, 33.25, 35.20)
# open-Med seaward facing: keep points whose seaward normal points roughly W (±70°)
OPEN_MIN, OPEN_MAX = 200.0, 340.0
CLUSTER_M = 800.0


def hav_m(a_lat, a_lon, b_lat, b_lon):
    R = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp = math.radians(b_lat - a_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def bearing(a_lat, a_lon, b_lat, b_lon):
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dl = math.radians(b_lon - a_lon)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def load_existing():
    text = YAML.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(r"\bid:\s*([a-z0-9-]+)", text):
        seg = text[m.start() : m.start() + 400]
        la = re.search(r"\blat:\s*(-?[0-9.]+)", seg)
        lo = re.search(r"\blon:\s*(-?[0-9.]+)", seg)
        if la and lo:
            out.append((m.group(1), float(la.group(1)), float(lo.group(1))))
    return out


def fetch_coastline():
    s, w, n, e = BBOX
    q = f'[out:json][timeout:120];way["natural"="coastline"]({s},{w},{n},{e});out geom;'
    data = urllib.parse.urlencode({"data": q}).encode()
    for ep in OVERPASS:
        try:
            req = urllib.request.Request(
                ep, data=data, headers={"User-Agent": "rosa-coast-gen/0.1"}
            )
            with urllib.request.urlopen(req, timeout=150) as r:
                return json.load(r).get("elements", [])
        except Exception as ex:
            print(f"  {ep.split('//')[1].split('/')[0]} failed: {ex}", file=sys.stderr)
    raise RuntimeError("all Overpass endpoints failed")


def generate(spacing_m):
    ways = fetch_coastline()
    total_m = 0.0
    raw = []  # candidate points before gates
    for wy in ways:
        geom = wy.get("geometry") or []
        pts = [(g["lat"], g["lon"]) for g in geom]
        acc = spacing_m  # emit at the first node
        for i in range(1, len(pts)):
            a, b = pts[i - 1], pts[i]
            seg = hav_m(*a, *b)
            total_m += seg
            acc += seg
            if acc >= spacing_m:
                acc = 0.0
                tang = bearing(*a, *b)  # along-coast direction
                seaward = (tang + 90) % 360  # OSM: water on the right of way dir
                offshore_dir = (seaward + 180) % 360  # wind comes FROM land
                raw.append(
                    {
                        "lat": round(b[0], 5),
                        "lon": round(b[1], 5),
                        "seaward": round(seaward),
                        "offshore_direction": round(offshore_dir),
                    }
                )
    # openness gate: seaward must face the open Med (roughly west)
    open_pts = [p for p in raw if OPEN_MIN <= p["seaward"] <= OPEN_MAX]
    # cluster within CLUSTER_M
    clustered = []
    for p in sorted(open_pts, key=lambda p: -p["lat"]):
        if all(hav_m(p["lat"], p["lon"], c["lat"], c["lon"]) > CLUSTER_M for c in clustered):
            clustered.append(p)
    return ways, total_m, raw, open_pts, clustered


def main():
    spacing = float(sys.argv[1]) if len(sys.argv) > 1 else 1000.0
    print(
        f"generating candidate breaks from OSM coastline @ {spacing:.0f} m spacing ...",
        file=sys.stderr,
    )
    ways, total_m, raw, open_pts, clustered = generate(spacing)
    existing = load_existing()

    # rediscovery: does each known spot have a generated candidate within 1.5 km?
    found = 0
    for _id, la, lo in existing:
        d = min(hav_m(la, lo, c["lat"], c["lon"]) for c in clustered) if clustered else 9e9
        if d <= 1500:
            found += 1

    print("\n=== Israel Mediterranean coast - break generator (proof) ===")
    print(f"coastline ways (OSM)      : {len(ways)}")
    print(f"coastline length          : {total_m / 1000:.1f} km")
    print(f"sample points @ {spacing:.0f} m    : {len(raw)}")
    print(f"  pass open-sea gate      : {len(open_pts)}")
    print(f"  after {CLUSTER_M:.0f} m cluster   : {len(clustered)}  <- candidate breaks")
    print(f"\nground truth (israel.yaml): {len(existing)} spots")
    print(
        f"  rediscovered (<1.5 km)  : {found}/{len(existing)}  ({100 * found // max(len(existing), 1)}%)"
    )
    print(f"  net NEW candidates       : ~{len(clustered) - found}")
    od = [c["offshore_direction"] for c in clustered]
    if od:
        import statistics

        print(
            f"\noffshore_direction of candidates: median {statistics.median(od):.0f}° "
            f"(Israel Med should be ~90° = East; sanity check)"
        )
    OUT.parent.mkdir(exist_ok=True)
    json.dump(
        {
            "spacing_m": spacing,
            "coastline_km": round(total_m / 1000, 1),
            "candidates": clustered,
            "existing": len(existing),
            "rediscovered": found,
        },
        open(OUT, "w"),
        indent=1,
    )
    print(f"\ncandidates → {OUT}")


if __name__ == "__main__":
    main()
