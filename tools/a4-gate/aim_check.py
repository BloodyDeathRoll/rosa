import json, sys
from pathlib import Path
sys.path.insert(0, "tools/spot-seed")
from aim_normal import aim
from local_bathy import LocalGebco
from rosa_pipeline.spots import load_spots
from rosa_pipeline.bathymetry import load_profile
rows = [r for r in json.load(open(sys.argv[1])) if r["dh"] > 0.1]
ids = [r["id"] for r in rows if any(k in sys.argv[2:] for k in [r["id"]])] if len(sys.argv) > 2 else None
spots = load_spots(Path("data/spots")); g = LocalGebco()
for sid in sys.argv[2].split(","):
    sp = spots[sid]; p = load_profile(sid, Path("data/spots/derived/bathy"))
    cur = round(p.bearing_seaward_deg)
    table = {b: dep for _s, b, dep in aim(g, sp.lat, sp.lon)}
    def ok(dep):  # open-ocean ray: no land past 0.25 km, far end deep, never shallower than 60% of the sample inside it
        return all(d > 0 for d in dep[1:]) and dep[-1] >= 30 and all(b >= 0.6 * a for a, b in zip(dep[1:], dep[2:]))
    good = [b for b in range(0, 360, 2) if ok(table[b])]
    # contiguous arcs
    arcs, run = [], []
    for b in list(range(0, 360, 2)) + [360]:
        if b < 360 and b in good: run.append(b)
        elif run: arcs.append((run[0], run[-1])); run = []
    if len(arcs) > 1 and arcs[0][0] == 0 and arcs[-1][1] == 358: arcs = [(arcs[-1][0], arcs[0][1] + 360)] + arcs[1:-1]
    def dist(a, b): return abs((a - b + 180) % 360 - 180)
    near = min(arcs, key=lambda ar: min(dist(cur, x % 360) for x in range(ar[0], ar[1] + 1, 2)), default=None)
    mid = ((near[0] + near[1]) / 2) % 360 if near else None
    cb = round(cur / 2) * 2 % 360
    print(f"{sid:24s} {sp.region if hasattr(sp,'region') else '':14s} seaward now {cur:3d}  ray {[round(d) for d in table[cb]]}")
    print(f"{'':24s} nearest open arc {near} mid {mid}  off by {dist(cur, mid) if mid is not None else '-'} deg  ray@mid {[round(d) for d in table[int(round(mid/2)*2)%360]] if mid is not None else '-'}")
