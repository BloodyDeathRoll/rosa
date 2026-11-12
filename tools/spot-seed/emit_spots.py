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
    "new-zealand": ("nz", True, None, 5.0),
    "goa": ("ga", True, None, 5.0),
    "karnataka": ("ka", True, None, 5.0),
    "kerala": ("kl", True, None, 5.0),
    "tamil-nadu": ("tn", True, None, 5.0),
    "andhra-pradesh": ("ap", True, None, 5.0),
    "odisha": ("od", True, None, 5.0),
    "portugal": ("pt", False, None, 5.0),
    "japan": ("jp", True, None, 5.0),
    "taiwan": ("tw", True, None, 5.0),
    "philippines": ("phe", True, None, 5.0),
    "el-salvador": ("sv", True, None, 5.0),
    "mexico": ("mx", True, None, 5.0),
    "california": ("ca", True, None, 5.0),
    "oregon": ("or", True, None, 5.0),
    "washington": ("wa", True, None, 5.0),
    "morocco": ("ma", True, None, 5.0),
    "angola": ("ao", True, None, 5.0),
    "peru": ("pe", True, None, 5.0),
    "panama": ("pa", True, None, 5.0),
    "dominican-republic": ("do", True, None, 5.0),
    "barbados": ("bb", True, None, 5.0),
    "puerto-rico": ("pr", True, None, 5.0),
    "vancouver-island": ("vi", True, None, 5.0),
    "nova-scotia": ("ns", True, None, 5.0),
    "liguria": ("lig", True, None, 5.0),
    "tuscany": ("tus", True, None, 5.0),
    "lazio": ("laz", True, None, 5.0),
    "sardinia": ("srd", True, None, 5.0),
    "campania": ("cmp", True, None, 5.0),
    "basilicata": ("bas", True, None, 5.0),
    "calabria": ("cal", True, None, 5.0),
    "puglia": ("pug", True, None, 5.0),
    "dakhla": ("dak", True, None, 5.0),
    "tobago": ("tob", True, None, 5.0),
    "british-virgin-islands": ("bvi", True, None, 5.0),
    "malaysia": ("my", True, None, 5.0),
    "thailand": ("th", True, None, 5.0),
    "nsw-mid-north-coast": ("mnc", True, None, 5.0),
    "nsw-south-coast": ("nsc", True, None, 5.0),
    "nsw-central-coast": ("ncc", True, None, 5.0),
    # seeded 2026-11-12 (web flow): Asia, France Atlantic, Caribbean, Mediterranean
    "andaman": ("an", True, None, 5.0),
    "antigua": ("ag", True, None, 5.0),
    "bahamas": ("bs", True, None, 5.0),
    "bermuda": ("bm", True, None, 5.0),
    "brunei": ("bn", True, None, 5.0),
    "bulgaria": ("bg", True, None, 5.0),
    "charente-maritime": ("chm", True, None, 5.0),
    "corsica": ("cor", True, None, 5.0),
    "curacao": ("cw", True, None, 5.0),
    "egypt": ("eg", True, None, 5.0),
    "emilia-romagna": ("emr", True, None, 5.0),
    "gironde": ("gir", True, None, 5.0),
    "greece": ("gr", True, None, 5.0),
    "congo": ("cg", True, None, 5.0),
    "ivory-coast": ("ci", True, None, 5.0),
    "nigeria": ("ng", True, None, 5.0),
    "sao-tome": ("st", True, None, 5.0),
    "sierra-leone": ("sl", True, None, 5.0),
    "moreton-bay": ("mb", True, None, 5.0),
    "norway-north": ("non", True, None, 5.0),
    "queensland-central": ("qc", True, None, 5.0),
    "guadeloupe": ("gp", True, None, 5.0),
    "iran": ("ir", True, None, 5.0),
    "jamaica": ("jm", True, None, 5.0),
    "languedoc": ("lng", True, None, 5.0),
    "lebanon": ("lb", True, None, 5.0),
    "loire-atlantique": ("la", True, None, 5.0),
    "maharashtra": ("mh", True, None, 5.0),
    "malta": ("mt", True, None, 5.0),
    "maluku": ("mlk", True, None, 5.0),
    "marche": ("mar", True, None, 5.0),
    "martinique": ("mq", True, None, 5.0),
    "myanmar": ("mm", True, None, 5.0),
    "oman": ("om", True, None, 5.0),
    "pakistan": ("pk", True, None, 5.0),
    "papua": ("ppa", True, None, 5.0),
    "provence": ("prv", True, None, 5.0),
    "sabah": ("sbh", True, None, 5.0),
    "saint-barthelemy": ("bl", True, None, 5.0),
    "saint-martin": ("sxm", True, None, 5.0),
    "savu": ("svu", True, None, 5.0),
    "timor-leste": ("tl", True, None, 5.0),
    "trinidad": ("tt", True, None, 5.0),
    "turkey-black-sea": ("trb", True, None, 5.0),
    "turkey-med": ("trm", True, None, 5.0),
    "united-arab-emirates": ("ae", True, None, 5.0),
    "us-virgin-islands": ("vi2", True, None, 5.0),
    "vendee": ("ven", True, None, 5.0),
    "vietnam": ("vn", True, None, 5.0),
    "guatemala": ("gt", True, None, 5.0),
    "maldives": ("mv", True, None, 5.0),
    "paraiba": ("pb", True, None, 5.0),
    "alagoas": ("al", True, None, 5.0),
    "sergipe": ("se", True, None, 5.0),
    "chile-north": ("cln", True, None, 5.0),
    "chile-central": ("clc", True, None, 5.0),
    "chile-south": ("cls", True, None, 5.0),
    "ecuador": ("ec", True, None, 5.0),
    "uruguay": ("uy", True, None, 5.0),
    "mar-del-plata": ("mdp", True, None, 5.0),
    "patagonia-argentina": ("cbt", True, None, 5.0),
    "south-korea": ("kr", True, None, 5.0),
    "jeju": ("jj", True, None, 5.0),
    "tonga": ("to", True, None, 5.0),
    "faroe-islands": ("fo", True, None, 5.0),
    "azores": ("az", True, None, 5.0),
    "texas": ("tx", True, None, 5.0),
    "madeira": ("mad", True, None, 5.0),
    "virginia": ("va", True, None, 5.0),
    "sumba": ("smb", True, None, 5.0),
    "rote": ("rot", True, None, 5.0),
    "aceh": ("ach", True, None, 5.0),
    "simeulue": ("smu", True, None, 5.0),
    "nias": ("nia", True, None, 5.0),
    "krui": ("kru", True, None, 5.0),
    "reunion": ("re", True, None, 5.0),
    "liberia": ("lr", True, None, 5.0),
    "catalonia": ("cat", True, None, 5.0),
    "valencia": ("vlc", True, None, 5.0),
    "murcia": ("mur", True, None, 5.0),
    "andalusia": ("and", True, None, 5.0),
    "balearic-islands": ("bal", True, None, 5.0),
    "hainan": ("hn", True, None, 5.0),
    "guangdong": ("gd", True, None, 5.0),
    "hong-kong": ("hk", True, None, 5.0),
    "fujian": ("fj", True, None, 5.0),
    "zhejiang": ("zj", True, None, 5.0),
    "shandong": ("sd", True, None, 5.0),
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
