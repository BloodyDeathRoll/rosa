"""Geometry A/B: committed gebco2020-via-API profiles vs the local GEBCO 2024 cut."""
import json
import statistics as st
import sys
from pathlib import Path

A = Path("data/spots/derived/bathy")          # committed (API)
B = Path(sys.argv[1])                          # candidate (local grid)

def load(p):
    d = json.loads(p.read_text())
    return d

def wet(d):
    return [s["depth_m"] for s in reversed(d["samples"]) if s["depth_m"] is not None and s["depth_m"] > 0]

rows = []
for pa in sorted(A.glob("*.json")):
    pb = B / pa.name
    if not pb.exists():
        continue
    a, b = load(pa), load(pb)
    sa = [s["depth_m"] for s in a["samples"]]
    sb = [s["depth_m"] for s in b["samples"]]
    rows.append({
        "id": a["spot"],
        "near_a": sa[0], "near_b": sb[0],
        "ref_a": a["offshore_depth_m"], "ref_b": b["offshore_depth_m"],
        "land_a": a["land_samples"], "land_b": b["land_samples"],
        "nm_a": a["non_monotone_samples"], "nm_b": b["non_monotone_samples"],
        "dir_a": a["deepest_is_reference"], "dir_b": b["deepest_is_reference"],
        "wet_a": len(wet(a)), "wet_b": len(wet(b)),
        "sa": sa, "sb": sb,
    })

n = len(rows)
def num(x):
    return x if isinstance(x, (int, float)) else None

changed = [r for r in rows if r["sa"] != r["sb"]]
print(f"spots compared              {n}")
print(f"profiles that differ at all {len(changed)}  ({100*len(changed)/n:.1f}%)")

# nearshore (first sample, 0.25 km) - the one that sets where the wave breaks
dn = [(r["id"], r["near_a"], r["near_b"]) for r in rows
      if num(r["near_a"]) is not None and num(r["near_b"]) is not None]
deltas = [b - a for _, a, b in dn]
print(f"\n0.25 km sample: median A {st.median(a for _,a,_ in dn):8.1f} m   "
      f"median B {st.median(b for _,_,b in dn):8.1f} m")
print(f"                median delta (B-A) {st.median(deltas):+.1f} m   "
      f"mean {st.fmean(deltas):+.1f} m")
big = sorted(dn, key=lambda t: -(abs(t[2]-t[1])))
print(f"                |delta| > 50 m at {sum(1 for _,a,b in dn if abs(b-a)>50)} spots; "
      f"> 100 m at {sum(1 for _,a,b in dn if abs(b-a)>100)}")
print("\nlargest nearshore disagreements (0.25 km):")
for sid, a, b in big[:14]:
    print(f"  {sid:26s} API {a:8.1f} m   local {b:8.1f} m   delta {b-a:+8.1f}")

# geometry-quality counters
for k, lab in (("land", "land samples"), ("nm", "non-monotone samples")):
    ta = sum(r[f"{k}_a"] for r in rows)
    tb = sum(r[f"{k}_b"] for r in rows)
    print(f"\ntotal {lab:24s} API {ta:5d}   local {tb:5d}")
print(f"deepest sample IS the reference   API {sum(1 for r in rows if r['dir_a']):5d}   "
      f"local {sum(1 for r in rows if r['dir_b']):5d}   (of {n})")
print(f"spots with NO wet sample          API {sum(1 for r in rows if r['wet_a']==0):5d}   "
      f"local {sum(1 for r in rows if r['wet_b']==0):5d}")
print(f"spots with <3 wet samples         API {sum(1 for r in rows if r['wet_a']<3):5d}   "
      f"local {sum(1 for r in rows if r['wet_b']<3):5d}")

# the reef set item 23 names
reef = [r for r in rows if r["id"] in {
    "pasta-point","sultans","madihera","teahupoo","chickens","jailbreaks","honkys",
    "cokes","lohis","ninjas","pipeline","cloudbreak","restaurants","namotu-lefts"}]
if reef:
    print("\nreef spots named in OPEN-ITEMS 23:")
    for r in reef:
        print(f"  {r['id']:26s} API {r['near_a']:8.1f} m   local {r['near_b']:8.1f} m")
