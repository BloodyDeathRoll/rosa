import json, math, sys, collections
from pathlib import Path
from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.spots import load_spots
S = Path(sys.argv[1])
base, mx = json.load(open(S/"h_base.json")), json.load(open(S/"h_max.json"))
spots = load_spots(Path("data/spots")); rows = []
for sid, spot in spots.items():
    p = load_profile(sid, Path("data/spots/derived/bathy"))
    if p is None or p.deepest_is_reference: continue
    far = list(reversed(p.samples))                      # seaward first
    wet = [(s.dist_km, s.depth_m) for s in far if s.depth_m > 0]
    d0 = wet[0][1]; kmax, dmax = max(wet, key=lambda t: t[1])
    land_seaward = sum(1 for s in far if s.depth_m <= 0 and s.dist_km > kmax)
    land_total = p.land_samples
    if land_seaward: cls = "land-beyond"          # ray runs onto land seaward of its deep point
    elif d0 >= 50: cls = "deep-wiggle"            # reference already in deep water
    elif dmax >= 50 and d0 < 0.5 * dmax: cls = "far-shoal"   # reef/bank at the far end, deep water inside it
    elif dmax < 30 and dmax - d0 <= 5: cls = "flat-shelf"    # shallow flat, +-few m of grid noise
    else: cls = "shelf-step"
    dh = max(abs(b - a) for a, b in zip(base[sid], mx[sid]))
    rows.append((cls, dh, sid, spot.region if hasattr(spot, "region") else "", d0, dmax, kmax, land_total,
                 " ".join(f"{('L' if s.depth_m <= 0 else round(s.depth_m))}" for s in far), base[sid], mx[sid]))
c = collections.Counter(r[0] for r in rows)
print(len(rows), dict(c))
for cls in c:
    rs = sorted((r for r in rows if r[0] == cls), key=lambda r: -r[1])
    big = sum(1 for r in rs if r[1] > 0.1); half = sum(1 for r in rs if r[1] > 0.5)
    print(f"\n## {cls}: {len(rs)} spots, {big} move >10 cm, {half} move >50 cm (under d_ref=max)")
    for r in rs[:12]:
        print(f"  {r[2]:26s} dH {r[1]:.2f}  ref {r[4]:.0f} m  deepest {r[5]:.0f} m @ {r[6]:g} km  land {r[7]}  ray[18->0.2km]: {r[8]}   h {[round(x,2) for x in r[9]]} -> {[round(x,2) for x in r[10]]}")
json.dump([dict(cls=r[0], dh=round(r[1],3), id=r[2], ref_m=r[4], deepest_m=r[5], deepest_km=r[6], land=r[7], ray=r[8], h_now=r[9], h_max=r[10]) for r in rows], open(S/"rays.json","w"))
