#!/usr/bin/env python3
"""Multi-provider geocoder for the web-search gap spots. Queries Google Places
(POI coverage), Nominatim and Photon (free/keyless, OSM), cross-checks their
agreement, and prints a best candidate per spot for sat-verify before adding.
Google needs GOOGLE_MAPS_API_KEY in env. Coords still go through sat-verify -
this only gets us onto the right stretch of coast, never straight into the DB."""

from __future__ import annotations
import json, math, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spot-verify"))
from geocode import geocode_google, geocode_nominatim  # (name, region) -> (lat,lon,src)|None


def geocode_photon(name, region):
    q = urllib.parse.urlencode({"q": f"{name}, {region}", "limit": 1})
    req = urllib.request.Request(
        f"https://photon.komoot.io/api/?{q}", headers={"User-Agent": "rosa-spot-seed/0.1"}
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        feats = json.load(r).get("features") or []
    if not feats:
        return None
    lon, lat = feats[0]["geometry"]["coordinates"]
    return float(lat), float(lon), "photon"


def km(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


SPOTS = [
    ("monaliza-point", "Monaliza Point San Juan La Union", "Philippines"),
    ("carrile-point", "Carrile Point San Juan La Union", "Philippines"),
    ("charlies-point", "Charlie's Point Baler Aurora", "Philippines"),
    ("magic-left", "Pundaquit beach San Antonio Zambales", "Philippines"),
    ("aoshima", "Aoshima Beach Miyazaki", "Japan"),
    ("uchiumi", "Uchiumi Nichinan Miyazaki surf", "Japan"),
    ("odeceixe", "Praia de Odeceixe", "Portugal"),
    ("foz-do-lizandro", "Praia da Foz do Lizandro Ericeira", "Portugal"),
    ("ingrina", "Praia da Ingrina Sagres", "Portugal"),
    ("manzanillo-ni", "Playa Manzanillo surf Tola", "Nicaragua"),
]
PROV = [("google", geocode_google), ("nominatim", geocode_nominatim), ("photon", geocode_photon)]


def main():
    out = {}
    for sid, name, region in SPOTS:
        res = {}
        for pv, fn in PROV:
            try:
                r = fn(name, region)
            except Exception as e:
                r = None
                print(f"  {sid} {pv} error: {str(e)[:50]}", file=sys.stderr)
            if r:
                res[pv] = (round(r[0], 5), round(r[1], 5))
            time.sleep(1.1)  # be polite to the free providers
        coords = list(res.values())
        # agreement: max pairwise distance among providers
        spread = max((km(a, b) for a in coords for b in coords), default=0.0)
        # pick Google if present (best POI), else nominatim, else photon
        best = res.get("google") or res.get("nominatim") or res.get("photon")
        out[sid] = {
            "name": name,
            "region": region,
            "providers": res,
            "spread_km": round(spread, 1),
            "best": best,
        }
        ps = "  ".join(f"{pv}={res[pv]}" for pv in res)
        print(f"{sid:16} spread {spread:5.1f} km | best {best} | {ps}")
    json.dump(out, open(Path(__file__).resolve().parent / "geocode_gaps.json", "w"), indent=1)


if __name__ == "__main__":
    main()
