#!/usr/bin/env python3
"""Turn a region's reviewed result.json 'new' spots into DB YAML lines and append
an osm-seeded block to data/spots/<region>.yaml. The deep-water sample is emitted as
offshore_km along the spot's own seaward normal; swell_window is derived from it where
the region needs one.
All entries tagged osm-seeded + TODO verify (below sat/user-verified on the ladder)."""

from __future__ import annotations
import datetime as _dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed import load_existing, slug, WORK, SPOTS

STAMP = _dt.date.today().isoformat()

# region -> (anchor, needs_swell_window, break_default, push_km)
CFG = {
    "portugal": ("pt", False, None, 5.0),
    "japan": ("jp", True, None, 5.0),
    "philippines": ("phe", True, None, 5.0),
    "el-salvador": ("sv", True, None, 5.0),
    "mexico": ("mx", True, None, 5.0),
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
        parts = [
            f"id: {sid}",
            f'name: "{nm}"',
            f"lat: {round(r['lat'], 4)}",
            f"lon: {round(r['lon'], 4)}",
            f"offshore_direction: {od}",
        ]
        if needs_sw:
            parts.append(f"swell_window: [{wrap(seaward - 65)}, {wrap(seaward + 65)}]")
        # offshore_km casts the deep-water sample along the spot's own seaward normal, so
        # the sample follows the pin. An absolute offshore_point is rejected by the loader.
        parts.append(f"offshore_km: {push}")
        parts.append(f"<<: *{anchor}")
        lines.append("  - { " + ", ".join(parts) + " }  # osm-seeded " + STAMP + " - TODO verify")

    block = (
        f"\n  # ==== OSM-SEEDED ({STAMP}, © OpenStreetMap contributors, ODbL) ====\n"
        "  # coastline-generated → bathy-pruned → OSM-name confirmed; offshore_direction from\n"
        "  # coastline geometry; sample point pushed seaward via offshore_km. SOURCE = osm-seeded (below\n"
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
