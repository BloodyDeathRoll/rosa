"""Build the secondary-flow geocode queue for California from web_names.json, skipping
names the primary flow (result.json) or the DB already covers (fuzzy token match).
Usage: ca_queue.py <region> <work/<region>> <out queue.json>
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

region = sys.argv[1]
REGION = region.replace("-", " ").title()
work = Path(sys.argv[2])
out = Path(sys.argv[3])
STOP = {"beach", "state", "park", "pier", "point", "surf", "surfing", "the", "st", "street",
        "ave", "avenue", "reef", "cove", "creek", "harbor", "jetty", "county", "bay"}


def slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def toks(s):
    return {t for t in re.split(r"[^a-z0-9]+", slug(s).replace("-", " ")) if t and t not in STOP}


web = json.loads((work / "web_names.json").read_text())
have = []
res = work / "result.json"
if res.exists():
    r = json.loads(res.read_text())
    for k in ("have", "new", "correction"):
        for e in r.get(k, []):
            if e.get("name"):
                have.append(e["name"])
db = Path(f"data/spots/{region}.yaml").read_text()
have += re.findall(r'name:\s*"([^"]+)"', db)
have_t = [toks(h) for h in have]

queue, matched, seen = [], [], set()
for area, names in web["areas"].items():
    for n in names:
        sid = slug(n)
        if sid in seen:
            continue
        seen.add(sid)
        t = toks(n)
        if t and any(t <= h or h <= t for h in have_t if h):
            matched.append((n, area))
            continue
        queue.append([sid, f"{n} surf break {area} {REGION}", REGION])
out.write_text(json.dumps(queue, indent=1))
print(f"web names {len(seen)}, matched by primary/DB {len(matched)}, queued {len(queue)} -> {out}")
for n, a in matched:
    print("  matched:", n, "|", a)
