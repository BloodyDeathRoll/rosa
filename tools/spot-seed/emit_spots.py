#!/usr/bin/env python3
"""Turn a region's reviewed result.json 'new' spots into DB YAML lines and append
an osm-seeded block to data/spots/<region>.yaml. offshore_point is pushed along the
per-spot seaward normal; swell_window is derived from it where the region needs one.
All entries tagged osm-seeded + TODO verify (below sat/user-verified on the ladder)."""

from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bathy_gate import destination
from seed import load_existing, slug, WORK, SPOTS

# region -> (anchor, needs_swell_window, break_default, push_km)
CFG = {
    "portugal": ("pt", False, None, 5.0),
    "japan": ("jp", True, None, 5.0),
    "philippines": ("phe", True, None, 5.0),
}
DROP_NAME = re.compile(r"kizakiham", re.I)  # dup of existing kisakihama (z/s spelling)
GENERIC = re.compile(r"^(surf(ing)?\s*spot|spot\s*(de\s*)?surf|sport\s*de\s*surf)$", re.I)


def wrap(a):
    return round(a % 360)


def main():
    region = sys.argv[1]
    anchor, needs_sw, brk, push = CFG[region]
    res = json.loads((WORK / region / "result.json").read_text())
    existing = load_existing(region)
    taken = {e["id"] for e in existing}
    lines = []
    for r in sorted(res["new"], key=lambda r: (-r["lat"], r["lon"])):
        nm = r["name"]
        if nm and DROP_NAME.search(nm):
            continue  # duplicate of an existing spot under a spelling variant
        # id
        base = (
            slug(nm)
            if nm and not GENERIC.match(nm.strip())
            else f"{region[:2]}-{slug(nm) or 'spot'}"
        )
        sid, k = base, 2
        while sid in taken:
            sid = f"{base}-{k}"
            k += 1
        taken.add(sid)
        od = r["offshore_direction"]
        seaward = (od + 180) % 360
        oplat, oplon = destination(r["lat"], r["lon"], seaward, push)
        parts = [
            f"id: {sid}",
            f'name: "{nm}"',
            f"lat: {round(r['lat'], 4)}",
            f"lon: {round(r['lon'], 4)}",
            f"offshore_direction: {od}",
        ]
        if needs_sw:
            parts.append(f"swell_window: [{wrap(seaward - 65)}, {wrap(seaward + 65)}]")
        parts.append(f"offshore_point: [{round(oplat, 4)}, {round(oplon, 4)}]")
        parts.append(f"<<: *{anchor}")
        lines.append("  - { " + ", ".join(parts) + " }  # osm-seeded 2026-07-24 - TODO verify")

    block = (
        "\n  # ==== OSM-SEEDED (2026-07-24, © OpenStreetMap contributors, ODbL) ====\n"
        "  # coastline-generated → bathy-pruned → OSM-name confirmed; offshore_direction from\n"
        "  # coastline geometry; offshore_point pushed seaward. SOURCE = osm-seeded (below\n"
        "  # sat/user-verified). sat-verify coords + break_type + swell_window before trusting.\n"
        + "\n".join(lines)
        + "\n"
    )
    path = SPOTS / f"{region}.yaml"
    with open(path, "a", encoding="utf-8") as f:
        f.write(block)
    print(f"{region}: appended {len(lines)} spots -> {path}")


if __name__ == "__main__":
    main()
