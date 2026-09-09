"""Same-input fleet A/B: identical sea states through both bathymetry cuts.

Weather is held fixed by construction - every spot sees the same three synthetic seas,
arriving down the centre of its own swell window - so the only thing that varies is the
depth profile. That isolates the source swap exactly as CALIBRATION.md's same-input rule
requires, and covers all 1408 spots rather than the handful a live capture could reach.
"""
import statistics as st
import sys
from pathlib import Path

from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.models import SwellPartition
from rosa_pipeline.score import bucket, size_score, period_score
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range

CAND = Path(sys.argv[1])
COMMITTED = Path("data/spots/derived/bathy")

# windswell, mid groundswell, long groundswell - the three regimes the fleet lives in
SEAS = (("windswell 1.0 m 8 s", 1.0, 8.0), ("groundswell 1.5 m 12 s", 1.5, 12.0),
        ("long swell 2.5 m 16 s", 2.5, 16.0))

def window_centre(spot):
    lo, hi = spot.swell_window
    span = (hi - lo) % 360.0
    return (lo + span / 2.0) % 360.0

def height(spot, profile, hs, tp):
    part = SwellPartition(kind="swell", height_m=hs, period_s=tp,
                          direction_deg=window_centre(spot), peak_period_s=tp)
    return breaker_height_from_profile(
        (part,), spot.swell_window, spot.shore_normal,
        profile.wet_samples_deep_to_shallow(), wind_normal_ms=0.0)

spots = load_spots(Path("data/spots"))
for label, hs, tp in SEAS:
    deltas, rating_moves, bucket_moves, rows = [], 0, 0, []
    for sid, spot in spots.items():
        pa, pb = load_profile(sid, COMMITTED), load_profile(sid, CAND)
        if pa is None or pb is None:
            continue
        try:
            ha, hb = height(spot, pa, hs, tp), height(spot, pb, hs, tp)
        except Exception:
            continue
        ma = breaker_range(ha, spot.height_coeff)[1]
        mb = breaker_range(hb, spot.height_coeff)[1]
        deltas.append(mb - ma)
        rows.append((sid, ma, mb))
        # rating movement with wind and period held identical
        ra = round(size_score(ma, spot.ideal_size_m) + period_score(tp))
        rb = round(size_score(mb, spot.ideal_size_m) + period_score(tp))
        if ra != rb:
            rating_moves += 1
        if bucket(ra) != bucket(rb):
            bucket_moves += 1
    n = len(deltas)
    absd = sorted(abs(d) for d in deltas)
    print(f"\n=== {label}   ({n} spots)")
    print(f"  median h_mid    committed {st.median(a for _, a, _ in rows):.2f} m"
          f"   candidate {st.median(b for _, _, b in rows):.2f} m")
    print(f"  delta (cand-committed)   mean {st.fmean(deltas):+.3f} m   "
          f"median {st.median(deltas):+.3f} m")
    print(f"  |delta| p50 {absd[n//2]:.3f}  p90 {absd[int(n*.9)]:.3f}  "
          f"p99 {absd[int(n*.99)]:.3f}  max {absd[-1]:.3f} m")
    print(f"  unchanged (<1 cm) {sum(1 for d in absd if d < 0.01):5d}"
          f"   moved >0.1 m {sum(1 for d in absd if d > 0.1):5d}"
          f"   moved >0.5 m {sum(1 for d in absd if d > 0.5):5d}")
    print(f"  size+period rating changes {rating_moves:5d}   bucket changes {bucket_moves:5d}"
          f"   ({100*bucket_moves/n:.1f}%)")
    big = sorted(rows, key=lambda r: -abs(r[2] - r[1]))[:8]
    print("  largest movers:")
    for sid, a, b in big:
        print(f"    {sid:26s} {a:5.2f} m -> {b:5.2f} m   {b-a:+.2f}")
