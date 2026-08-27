#!/usr/bin/env python3
"""Append a seeded region's final.json (from ca_final.py) + towns.json (from towns.py) to
data/spots/<region>.yaml as one sat-verified block. Every entry carries its source tag
(osm-seeded / websearch-seeded) and the sat-verified date; offshore_direction is the
nearest coastline candidate's shore normal; swell_window = seaward +/-65 deg (TODO
calibrate); offshore_km casts the sample point along the spot's own normal.
Usage: emit_region.py <region> <anchor>     e.g. emit_region.py oregon or
"""
import datetime
import json
import sys
from pathlib import Path

region, anchor = sys.argv[1], sys.argv[2]
W = Path(__file__).resolve().parent / "work" / region
final = json.loads((W / "final.json").read_text())
towns = json.loads((W / "towns.json").read_text())
ov = json.loads((Path(__file__).resolve().parent / "town_overrides.json").read_text())
stamp = datetime.date.today().isoformat()


def wrap(a):
    return round(a % 360)


lines = []
for f in final:
    # the hand override wins: it exists because OSM's nearest place node was wrong
    # (a hamlet named after the break, a typo, a beach that is not a settlement)
    t = ov.get(f["id"]) or (towns.get(f["id"]) or {}).get("town")
    if not t:
        raise SystemExit(f"no town for {f['id']} - add it to town_overrides.json")
    od = f["offshore_direction"]
    sea = (od + 180) % 360
    name = f["name"].replace('"', "")
    parts = [
        f"id: {f['id']}", f'name: "{name}"', f'town: "{t}"', f"lat: {f['lat']:.4f}", f"lon: {f['lon']:.4f}",
        f"offshore_direction: {od}", f"swell_window: [{wrap(sea - 65)}, {wrap(sea + 65)}]",
        "offshore_km: 5.0", f"<<: *{anchor}",
    ]
    lines.append("  - { " + ", ".join(parts) + " }  # sat-verified " + stamp + f" ({f['src']})")
osm = sum(1 for f in final if f["src"] == "osm-seeded")
block = (
    f"\n  # ==== SEEDED {stamp} - {region}, {len(final)} spots (primary coastline flow: {osm} OSM surf beacons,\n"
    f"  # © OpenStreetMap contributors, ODbL; secondary web-search flow: {len(final) - osm} named breaks, multi-geocoded\n"
    "  # then read against OSM named beaches). EVERY pin was rendered on ESRI imagery at z16 and\n"
    "  # judged before entering; moved pins were re-rendered until they sat on the break (judge log in\n"
    f"  # tools/spot-seed/work/{region}/judge.json). offshore_direction is the nearest coastline\n"
    "  # candidate's shore normal; swell_window = seaward +/-65 deg, TODO calibrate; towns from OSM\n"
    "  # place nodes (tools/spot-seed/towns.py). North to south.\n"
    + "\n".join(lines) + "\n"
)
path = Path(__file__).resolve().parents[2] / "data" / "spots" / f"{region}.yaml"
text = path.read_text()
if text.rstrip().endswith("spots: []"):
    text = text.rstrip()[: -len("spots: []")] + "spots:\n"
path.write_text(text.rstrip("\n") + "\n" + block)
print(f"{region}: appended {len(lines)} spots -> {path}")
