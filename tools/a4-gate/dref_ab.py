"""OPEN-ITEMS 15 same-input A/B: reference = the ray's DEEPEST wet sample instead of its
FARTHEST. Candidate = the committed profile with the march started at the deepest sample
(samples seaward of it dropped). Same three synthetic seas as tools/bathy-ab/ab_height.py."""
import statistics as st
from pathlib import Path
from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.models import SwellPartition
from rosa_pipeline.score import bucket, size_score, period_score
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range

BATHY = Path("data/spots/derived/bathy")
SEAS = (("windswell 1.0 m 8 s", 1.0, 8.0), ("groundswell 1.5 m 12 s", 1.5, 12.0),
        ("long swell 2.5 m 16 s", 2.5, 16.0))

def centre(spot):
    lo, hi = spot.swell_window
    return (lo + ((hi - lo) % 360.0) / 2.0) % 360.0

def height(spot, samples, hs, tp):
    part = SwellPartition(kind="swell", height_m=hs, period_s=tp,
                          direction_deg=centre(spot), peak_period_s=tp)
    return breaker_height_from_profile((part,), spot.swell_window, spot.shore_normal,
                                       samples, wind_normal_ms=0.0)

spots = load_spots(Path("data/spots"))
prof, affected, nonmono = {}, [], 0
for sid in spots:
    p = load_profile(sid, BATHY)
    if p is None: continue
    s = p.wet_samples_deep_to_shallow()
    if not s: continue
    i = max(range(len(s)), key=lambda k: s[k][1])
    prof[sid] = (s, s[i:])
    if any(b[1] > a[1] for a, b in zip(s, s[1:])): nonmono += 1
    if i: affected.append((sid, s[0][1], s[i][1], i))
print(f"{len(prof)} spots with a wet profile; {nonmono} non-monotone; "
      f"{len(affected)} where the deepest wet sample is not the reference")
for label, hs, tp in SEAS:
    rows, rmoves, bmoves, errs = [], 0, 0, 0
    for sid, (a, b) in prof.items():
        spot = spots[sid]
        try:
            ma = breaker_range(height(spot, a, hs, tp), spot.height_coeff)[1]
            mb = breaker_range(height(spot, b, hs, tp), spot.height_coeff)[1]
        except Exception:
            errs += 1; continue
        rows.append((sid, ma, mb))
        ra = round(size_score(ma, spot.ideal_size_m) + period_score(tp))
        rb = round(size_score(mb, spot.ideal_size_m) + period_score(tp))
        rmoves += ra != rb; bmoves += bucket(ra) != bucket(rb)
    d = [b - a for _, a, b in rows]; ad = sorted(abs(x) for x in d); n = len(d)
    print(f"\n=== {label} ({n} spots, {errs} errors)")
    print(f"  changed at all {sum(1 for x in ad if x > 0)}   mean {st.fmean(d):+.4f} m   "
          f"p99 {ad[int(n*.99)]:.3f}  max {ad[-1]:.3f} m   >1 cm {sum(1 for x in ad if x>=0.01)}"
          f"   >10 cm {sum(1 for x in ad if x>0.1)}")
    print(f"  rating changes {rmoves}   bucket changes {bmoves}")
    for sid, a, b in sorted(rows, key=lambda r: -abs(r[2]-r[1]))[:8]:
        print(f"    {sid:28s} {a:5.2f} -> {b:5.2f}  {b-a:+.3f}")
print("\naffected:", ", ".join(f"{s}({d0:.0f}->{d1:.0f}m,i={i})" for s, d0, d1, i in affected[:60]))
