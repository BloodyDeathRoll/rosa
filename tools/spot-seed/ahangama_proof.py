#!/usr/bin/env python3
"""End-to-end proof on the Ahangama (Sri Lanka) coast:
   generate (coastline) -> prune (bathy) -> validate/name (OSM).

Target: three famous breaks our DB conflates into one -- Kabalana, Sticks,
Marshmallow -- should each fall out as a generated candidate CONFIRMED + NAMED
by an OSM surf feature. Composes the reusable pieces from coast_generate.py and
bathy_gate.py."""

from __future__ import annotations
import json
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from coast_generate import bearing, hav_m
from bathy_gate import destination, gebco_elevations, classify, XSECT_KM, SHELF_MIN_KM

OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
CACHE = Path(__file__).resolve().parent / "candidates" / "ahangama-kept.json"
BBOX = (5.950, 80.350, 5.980, 80.390)  # S, W, N, E - Kabalana → Marshmallow
SPACING_M = 250
CLUSTER_M = 300
NAME_MATCH_M = 400  # OSM beacon within this = confirmed + named
TARGETS = ["kabalana", "sticks", "marshmallow"]


def overpass(q):
    data = urllib.parse.urlencode({"data": q}).encode()
    for rnd in range(3):
        for ep in OVERPASS:
            try:
                req = urllib.request.Request(
                    ep, data=data, headers={"User-Agent": "rosa-ahangama/0.1"}
                )
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.load(r).get("elements", [])
            except Exception as ex:
                print(f"  {ep.split('//')[1].split('/')[0]} failed: {ex}", file=sys.stderr)
                time.sleep(3)
        time.sleep(8 * (rnd + 1))
    raise RuntimeError("overpass failed on all mirrors after retries")


def generate():
    s, w, n, e = BBOX
    ways = overpass(f'[out:json][timeout:90];way["natural"="coastline"]({s},{w},{n},{e});out geom;')
    raw = []
    for wy in ways:
        pts = [(g["lat"], g["lon"]) for g in wy.get("geometry", [])]
        acc = SPACING_M
        for i in range(1, len(pts)):
            a, b = pts[i - 1], pts[i]
            acc += hav_m(*a, *b)
            if acc >= SPACING_M:
                acc = 0.0
                tang = bearing(*a, *b)
                seaward = (tang + 90) % 360
                raw.append(
                    {
                        "lat": round(b[0], 6),
                        "lon": round(b[1], 6),
                        "seaward": round(seaward),
                        "offshore_direction": round((seaward + 180) % 360),
                    }
                )
    # cluster
    clustered = []
    for p in sorted(raw, key=lambda p: p["lon"]):
        if all(hav_m(p["lat"], p["lon"], c["lat"], c["lon"]) > CLUSTER_M for c in clustered):
            clustered.append(p)
    return len(ways), clustered


def bathy_prune(cands):
    pts = []
    for c in cands:
        pts += [destination(c["lat"], c["lon"], c["seaward"], d) for d in XSECT_KM]
    elev = gebco_elevations(pts)
    kept = []
    for i, c in enumerate(cands):
        ev = elev[i * len(XSECT_KM) : (i + 1) * len(XSECT_KM)]
        shelf = [ev[j] for j, d in enumerate(XSECT_KM) if d >= SHELF_MIN_KM]
        ok, why = classify(shelf)
        if ok:
            kept.append(c)
    return kept


def osm_beacons():
    s, w, n, e = BBOX
    q = (
        f"[out:json][timeout:45];("
        f'node["sport"="surfing"]({s},{w},{n},{e});'
        f'way["sport"="surfing"]({s},{w},{n},{e});'
        f'node["natural"="beach"]({s},{w},{n},{e});'
        f'way["natural"="beach"]({s},{w},{n},{e});'
        f");out center tags;"
    )
    out = []
    for el in overpass(q):
        t = el.get("tags", {})
        nm = t.get("name:en") or t.get("name")
        if not nm:
            continue
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        if lat is None:
            continue
        kind = (
            "surf"
            if (t.get("sport") == "surfing" or "surf" in nm.lower())
            else t.get("natural", "?")
        )
        out.append({"name": nm, "lat": lat, "lon": lon, "kind": kind})
    return out


def main():
    if CACHE.exists():
        kept = json.load(open(CACHE))
        print(
            f"1-2) GENERATE+PRUNE: loaded {len(kept)} pruned candidates from cache", file=sys.stderr
        )
    else:
        nways, cands = generate()
        print(
            f"1) GENERATE: {nways} coastline ways -> {len(cands)} candidates "
            f"@ {SPACING_M} m spacing",
            file=sys.stderr,
        )
        kept = bathy_prune(cands)
        print(
            f"2) PRUNE (bathy): {len(cands)} -> {len(kept)} survive the seabed gate",
            file=sys.stderr,
        )
        json.dump(kept, open(CACHE, "w"), indent=1)
    beacons = osm_beacons()
    print(f"3) OSM beacons found: {len(beacons)}", file=sys.stderr)

    # Tier A: each surviving candidate that has an OSM beacon within NAME_MATCH_M
    tierA = []
    for c in kept:
        near = [(hav_m(c["lat"], c["lon"], b["lat"], b["lon"]), b) for b in beacons]
        near.sort(key=lambda x: x[0])
        if near and near[0][0] <= NAME_MATCH_M:
            c2 = dict(c)
            c2["osm_name"] = near[0][1]["name"]
            c2["osm_m"] = round(near[0][0])
            tierA.append(c2)

    print("\n=== RESULT: generated candidates CONFIRMED + NAMED by OSM (Tier A) ===")
    seen = set()
    for c in sorted(tierA, key=lambda c: c["lon"]):
        key = c["osm_name"]
        if key in seen:
            continue
        seen.add(key)
        print(
            f"  {c['lat']:.5f},{c['lon']:.5f}  offshore_dir {c['offshore_direction']:>3}°  "
            f'<- "{c["osm_name"]}" ({c["osm_m"]} m)'
        )

    print("\n=== target check (the 3 spots the user named) ===")
    names_l = " ".join(s for s in seen).lower()
    for t in TARGETS:
        hit = t in names_l
        print(f"  {'FOUND ' if hit else 'MISS  '} {t}")
    print(
        f"\nAll OSM surf beacons on this coast: "
        f"{sorted(set(b['name'] for b in beacons if b['kind'] == 'surf'))}"
    )


if __name__ == "__main__":
    main()
