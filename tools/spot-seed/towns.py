"""Derive each spot's `town` - the nearest OSM settlement - from the local Geofabrik extracts.

The town is a SEARCH key (docs/SPOT-DB.md): a break is famous under its town's name at least
as often as its own, and until this existed a search for "Puerto Escondido" or "Tel Aviv"
returned nothing. Nearest `place` node within 12 km wins, except that a town or city inside
1.6x the nearest hamlet's distance outranks it - a hamlet named after the break itself
("Punta Roca Surf") is useless as a town. Roughly one spot in twelve still needs a hand
override; those live in tools/spot-seed/town_overrides.json.

Usage: towns.py <spots.json> <out.json>   where spots.json is [{id, name, region, lat, lon}].
"""

import json
import math
import sys

import osmium

PLACES = ("city", "town", "village", "hamlet")
REGION_PBF = {
    "Israel": "israel",
    "Portugal": "portugal",
    "Japan": "japan",
    "Sri Lanka": "sri-lanka",
    "Costa Rica": "costa-rica",
    "Nicaragua": "nicaragua",
    "Philippines": "philippines",
    "California": "california",
    "Oregon": "oregon",
    "Washington": "washington",
    "Mexico": "mexico",
    "El Salvador": "el-salvador",
}


def hav(a, b, c, d):
    R = 6371000
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


class Places(osmium.SimpleHandler):
    def __init__(self, box):
        super().__init__()
        self.hits = []
        self.box = box

    def node(self, n):
        t = n.tags
        p = t.get("place")
        if p not in PLACES:
            return
        nm = t.get("name:en") or t.get("name")
        if not nm:
            return
        la, lo = n.location.lat, n.location.lon
        s, w, nn, e = self.box
        if s <= la <= nn and w <= lo <= e:
            self.hits.append((nm, la, lo, p))


spots = json.load(open(sys.argv[1]))  # [{id, name, region, lat, lon}]
out = {}
for region, stem in REGION_PBF.items():
    rows = [s for s in spots if s["region"] == region]
    if not rows:
        continue
    box = (
        min(s["lat"] for s in rows) - 0.4,
        min(s["lon"] for s in rows) - 0.4,
        max(s["lat"] for s in rows) + 0.4,
        max(s["lon"] for s in rows) + 0.4,
    )
    h = Places(box)
    h.apply_file(f"data/osm/{stem}.osm.pbf")
    rank = {"city": 0, "town": 1, "village": 2, "hamlet": 3}
    for s in rows:
        cands = [(hav(s["lat"], s["lon"], p[1], p[2]), p) for p in h.hits]
        cands = [c for c in cands if c[0] <= 12000]
        if not cands:
            out[s["id"]] = None
            continue
        # nearest wins, but a town/city inside 1.6x the nearest hamlet's distance outranks it
        cands.sort(key=lambda c: c[0])
        best = cands[0]
        for d, p in cands:
            if d <= best[0] * 1.6 and rank[p[3]] < rank[best[1][3]]:
                best = (d, p)
        out[s["id"]] = {"town": best[1][0], "m": round(best[0]), "kind": best[1][3]}
    print(f"{region}: {len(rows)} spots", file=sys.stderr)
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
