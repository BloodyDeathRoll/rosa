"""Cross-check California geocodes against OSM named beaches/surf beacons (beacons.json)
and the primary flow's Tier-A hits, then emit render_in.json for the sat-verify pass.
Rule (playbook §5): a geocode confirmed by an OSM name within 1 km is two-source; a
provider spread > 5 km means one provider is wrong - the OSM feature wins if it is
within 1.5 km of ANY provider, else the spot is flagged for a wide render.
Usage: ca_xref.py <work/california>
"""
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

work = Path(sys.argv[1])
geo = json.loads((work / "geocode.json").read_text())
beacons = json.loads((work / "beacons.json").read_text())
result = json.loads((work / "result.json").read_text())


def km(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


STOP = {"beach", "state", "park", "pier", "surf", "break", "the", "st", "street", "county",
        "california", "reef", "point", "cove", "creek", "harbor", "jetty", "bay"}


def toks(s):
    return {t for t in norm(s).split() if t not in STOP}


rows, flags = [], []
for sid, g in geo.items():
    provs = g.get("providers") or {}
    best = g.get("best")
    spread = g.get("spread_km")
    qname = g["name"].split(" surf break ")[0]
    qt = toks(qname)
    # OSM name match within 1.5 km of any provider point
    osm_hit = None
    for b in beacons:
        bt = toks(b["name"])
        if not bt or not (qt & bt):
            continue
        for p in provs.values():
            d = km(p, (b["lat"], b["lon"]))
            if d <= 1.5 and (osm_hit is None or d < osm_hit[1]):
                osm_hit = (b, d)
    if best is None and osm_hit is None:
        flags.append((sid, qname, "no geocode, no OSM"))
        continue
    if osm_hit is not None:
        b, d = osm_hit
        lat, lon, src = b["lat"], b["lon"], f"osm:{b['name']} ({d:.2f} km from geocode)"
    else:
        lat, lon = best
        n = len(provs)
        src = f"geocode x{n} spread {spread} km"
        if spread is not None and spread > 5:
            flags.append((sid, qname, f"providers disagree {spread} km - wide render"))
        elif n < 2:
            flags.append((sid, qname, "single provider - render decides"))
    rows.append({"id": sid, "name": qname, "lat": round(lat, 5), "lon": round(lon, 5), "src": src})

(work / "render_in.json").write_text(json.dumps(rows, indent=1))
(work / "xref_flags.json").write_text(json.dumps(flags, indent=1))
two = sum(1 for r in rows if r["src"].startswith("osm:"))
print(f"geocoded {len(geo)}: render {len(rows)} (OSM-confirmed {two}), skipped {len(geo)-len(rows)}, flags {len(flags)}")
for f in flags:
    print("  flag:", *f)
