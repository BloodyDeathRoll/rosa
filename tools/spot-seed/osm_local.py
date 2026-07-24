#!/usr/bin/env python3
"""Local OSM extractor — pulls coastline + surf beacons from a Geofabrik .osm.pbf on
disk instead of the public Overpass API. Download the regional extract once
(data/osm/<region>.osm.pbf, gitignored), then generation + validation are offline,
reliable, and unlimited — the Overpass companion to the local GEBCO grid.

extract_region(pbf) -> (coast_ways, beacons):
  coast_ways : list[ list[(lat,lon)] ]      natural=coastline geometries
  beacons    : list[ {name,lat,lon,surf} ]  sport=surfing + natural=beach features

Requires pyosmium (tools/spot-seed/.venv).
"""
from __future__ import annotations
import osmium
from osm_seed import is_business  # tag- AND name-based (shop/amenity/school/...) — never a spot


class _Extract(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.coast = []
        self.beacons = []

    def _beacon(self, td, lat, lon):
        if is_business(td):
            return  # a surf school/shop/hotel marks a break but is never a spot name
        nm = td.get("name:en") or td.get("name")
        surf = td.get("sport") == "surfing" or (nm is not None and "surf" in nm.lower())
        self.beacons.append({"name": nm, "lat": lat, "lon": lon, "surf": bool(surf)})

    def node(self, n):
        t = n.tags  # cheap pre-check on the osmium taglist; build the dict only for matches
        if t.get("sport") == "surfing" or t.get("natural") == "beach":
            self._beacon({x.k: x.v for x in t}, n.location.lat, n.location.lon)

    def way(self, w):
        t = w.tags
        if t.get("natural") == "coastline":
            pts = [(nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
            if len(pts) >= 2:
                self.coast.append(pts)
        elif t.get("sport") == "surfing" or t.get("natural") == "beach":
            pts = [(nd.location.lat, nd.location.lon) for nd in w.nodes if nd.location.valid()]
            if pts:
                self._beacon({x.k: x.v for x in t},
                             sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))


def extract_region(pbf_path):
    h = _Extract()
    h.apply_file(str(pbf_path), locations=True)  # locations=True resolves way geometry
    return h.coast, h.beacons


if __name__ == "__main__":
    import sys
    coast, beacons = extract_region(sys.argv[1])
    surf = [b for b in beacons if b["surf"] and b["name"]]
    print(f"coastline ways: {len(coast)} | beacons: {len(beacons)} "
          f"({len(surf)} named surf features)")
    for b in surf[:15]:
        print(f"  surf: {b['lat']:.4f},{b['lon']:.4f}  {b['name']}")
