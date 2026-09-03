#!/usr/bin/env python3
"""Re-aim a spot's shore normal off the GEBCO grid.

seed.py derives offshore_direction from the nearest OSM coastline segment. On a
headland, in a bay, or where the coastline way is coarse, that normal can point
along the shore or straight into land - and `bathy` then cuts its profile over
dry ground (land_samples > 0, or a depth that never deepens).

This sweeps every 2 deg of seaward bearing, scores the 0.25-18 km ray on the
GEBCO grid, and reports the best one. It REPORTS ONLY - it never edits a YAML.
"""

from __future__ import annotations
import json
import math
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from local_bathy import LocalGebco

DISTS = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 18.0)
R = 6371.0088


def destination(lat, lon, brg, d):
    la, lo, b, ad = (
        map(math.radians, (lat, lon, brg, 0)),
        None,
        math.radians(brg),
        d / R,
    )
    la = math.radians(lat)
    lo = math.radians(lon)
    la2 = math.asin(
        math.sin(la) * math.cos(ad) + math.cos(la) * math.sin(ad) * math.cos(b)
    )
    lo2 = lo + math.atan2(
        math.sin(b) * math.sin(ad) * math.cos(la),
        math.cos(ad) - math.sin(la) * math.sin(la2),
    )
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


def score(depths):
    """depths: metres positive-down. Higher score = a better open-ocean ray."""
    land = sum(1 for d in depths if d <= 0)
    mono = sum(1 for a, b in zip(depths, depths[1:]) if b >= a - 0.5)
    # land anywhere on the ray is disqualifying-ish; then reward monotone deepening
    return (-land * 100) + mono * 5 + min(depths[-1], 400) / 100.0


def aim(g, lat, lon, prefer=None, span=360.0):
    pts = []
    brgs = [
        b
        for b in range(0, 360, 2)
        if prefer is None or abs((b - prefer + 180) % 360 - 180) <= span / 2
    ]
    for b in brgs:
        for d in DISTS:
            pts.append(destination(lat, lon, b, d))
    ev = g.elevations(pts)
    out = []
    for i, b in enumerate(brgs):
        dep = [-e for e in ev[i * len(DISTS) : (i + 1) * len(DISTS)]]
        out.append((score(dep), b, dep))
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


if __name__ == "__main__":
    import argparse
    import pathlib
    import re

    ap = argparse.ArgumentParser()
    ap.add_argument("--yaml", required=True)
    ap.add_argument("--only", default=None, help="comma-separated spot ids")
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    g = LocalGebco()
    txt = pathlib.Path(a.yaml).read_text()
    rx = re.compile(
        r"id: ([a-z0-9-]+), name: \"([^\"]+)\".*?lat: (-?[\d.]+), lon: (-?[\d.]+), offshore_direction: (\d+)"
    )
    rows = []
    for m in rx.finditer(txt):
        sid, name, lat, lon, cur = (
            m.group(1),
            m.group(2),
            float(m.group(3)),
            float(m.group(4)),
            int(m.group(5)),
        )
        if only and sid not in only:
            continue
        best = aim(g, lat, lon)
        s, b, dep = best[0]
        cur_seaward = (cur + 180) % 360
        curscore = next(x for x in best if x[1] == round(cur_seaward / 2) * 2 % 360)
        rows.append(
            {
                "id": sid,
                "name": name,
                "cur_dir": cur,
                "cur_seaward": cur_seaward,
                "cur_score": round(curscore[0], 1),
                "cur_land": sum(1 for d in curscore[2] if d <= 0),
                "best_seaward": b,
                "best_score": round(s, 1),
                "best_land": sum(1 for d in dep if d <= 0),
                "best_dir": (b + 180) % 360,
                "best_prof": [round(d) for d in dep],
            }
        )
    print(json.dumps(rows, indent=1))
