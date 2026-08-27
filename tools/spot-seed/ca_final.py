"""Assemble the California add-list from the judge file + Tier-A result, derive each spot's
offshore_direction from the nearest coastline candidate, and write:
  work/california/final.json  - the list (id, name, lat, lon, offshore_direction, src, conf)
  work/california/spots.json  - towns.py input [{id, name, region, lat, lon}]
"""
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

REGION_ID = sys.argv[1]
REGION = REGION_ID.replace("-", " ").title()
W = Path("tools/spot-seed/work") / REGION_ID
# judge log: argv[2], else the region's own work dir (the California pass wrote it to a
# session scratchpad, which does not survive the session)
J = Path(sys.argv[2]) if len(sys.argv) > 2 else W / "judge.json"
j = json.loads(J.read_text())
rows = {r["id"]: r for r in json.loads((W / "render_in_ca.json").read_text())}
res = json.loads((W / "result.json").read_text())
cands = json.loads((W / "candidates.json").read_text())


def km(a, b, c, d):
    R = 6371.0
    p1, p2 = math.radians(a), math.radians(c)
    dp, dl = math.radians(c - a), math.radians(d - b)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def offdir(lat, lon):
    best = None
    for c in cands:
        if abs(c["lat"] - lat) > 0.03 or abs(c["lon"] - lon) > 0.04:
            continue
        d = km(lat, lon, c["lat"], c["lon"])
        if best is None or d < best[0]:
            best = (d, c["offshore_direction"])
    return best


def title(s):
    s = re.sub(r"\s+", " ", s.strip())
    return s if s.isupper() or any(ch.isupper() for ch in s[1:]) else s.title()


final = []
# Per-region skips, {"tierA": {id: why}, "web": {id: why}}. The California pass hardcoded
# these; every later region carries its own file next to the judge log.
_skip = json.loads((W / "skip.json").read_text()) if (W / "skip.json").exists() else {}
skipA = _skip.get("tierA", {})
for r in res["new"]:
    if r["id"] in skipA:
        continue
    final.append({"id": r["id"], "name": r["name"], "lat": r["lat"], "lon": r["lon"],
                  "offshore_direction": r["offshore_direction"], "src": "osm-seeded", "conf": 0.9})
# web-sourced keeps/moves
drop_now = _skip.get("web", {})
for sid, v in j.items():
    if v["action"] not in ("keep", "move") or sid in drop_now:
        continue
    if v["action"] == "move" and not v.get("confirmed"):
        raise SystemExit(f"{sid}: moved but never re-rendered")
    lat = v.get("lat", rows.get(sid, {}).get("lat"))
    lon = v.get("lon", rows.get(sid, {}).get("lon"))
    name = v.get("rename") or rows.get(sid, {}).get("name") or sid
    od = offdir(lat, lon)
    if od is None:
        print(f"warn: {sid}: no coastline candidate within reach - skipped")
        continue
    out_id = re.sub(r"[^a-z0-9]+", "-", title(name).lower()).strip("-") if v.get("rename") else sid
    final.append({"id": out_id, "name": title(name), "lat": round(lat, 4), "lon": round(lon, 4),
                  "offshore_direction": od[1], "coast_km": round(od[0], 2),
                  "src": "websearch-seeded", "conf": v.get("conf", 0.7)})
# ids must be unique and not clash with the DB
db_ids = set(re.findall(r"\bid:\s*([a-z0-9-]+)", Path(f"data/spots/{REGION_ID}.yaml").read_text()))
seen = set()
out = []
for f in final:
    sid = re.sub(r"-+", "-", unicodedata.normalize("NFKD", f["id"]).encode("ascii", "ignore").decode().lower()).strip("-")
    if sid in db_ids or sid in seen:
        print(f"warn: duplicate id {sid} - skipped")
        continue
    seen.add(sid)
    f["id"] = sid
    out.append(f)
out.sort(key=lambda f: -f["lat"])  # north to south, the DB's ordering preference
(W / "final.json").write_text(json.dumps(out, indent=1))
(W / "spots.json").write_text(json.dumps([{"id": f["id"], "name": f["name"], "region": REGION, "lat": f["lat"], "lon": f["lon"]} for f in out], indent=1))
far = [f for f in out if f.get("coast_km", 0) > 0.6]
print(f"final {len(out)} spots ({sum(1 for f in out if f['src']=='osm-seeded')} osm, {sum(1 for f in out if f['src']=='websearch-seeded')} web); {len(far)} more than 600 m from a coastline candidate:")
for f in far:
    print(f"   {f['id']:28} {f['coast_km']} km")
