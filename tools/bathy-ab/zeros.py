import sys
from pathlib import Path
from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.models import SwellPartition
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range

CAND = Path(sys.argv[1])
COM = Path("data/spots/derived/bathy")


def centre(s):
    lo, hi = s.swell_window
    return (lo + ((hi - lo) % 360.0) / 2.0) % 360.0


def h(spot, prof, hs, tp):
    p = SwellPartition(kind="swell", height_m=hs, period_s=tp,
                       direction_deg=centre(spot), peak_period_s=tp)
    return breaker_range(breaker_height_from_profile(
        (p,), spot.swell_window, spot.shore_normal,
        prof.wet_samples_deep_to_shallow(), wind_normal_ms=0.0), spot.height_coeff)[1]

spots = load_spots(Path("data/spots"))
new_zero, was_zero, both = [], [], 0
for sid, spot in spots.items():
    pa, pb = load_profile(sid, COM), load_profile(sid, CAND)
    if pa is None or pb is None:
        continue
    a = h(spot, pa, 1.5, 12.0)
    b = h(spot, pb, 1.5, 12.0)
    if a >= 0.15 and b < 0.15:
        new_zero.append((sid, a, b))
    elif b >= 0.15 and a < 0.15:
        was_zero.append((sid, a, b))
    elif a < 0.15 and b < 0.15:
        both += 1
print(f"1.5 m / 12 s down the window centre, {len(spots)} spots")
print(f"  flat on BOTH cuts                {both}")
print(f"  goes flat only on the CANDIDATE  {len(new_zero)}")
print(f"  goes flat only on the COMMITTED  {len(was_zero)}  (candidate rescues these)")
print("\n  newly flat on the candidate (would publish ~0 m):")
for sid, a, b in sorted(new_zero, key=lambda r: -r[1])[:25]:
    print(f"    {sid:28s} {a:5.2f} -> {b:.2f}")
print("\n  rescued by the candidate:")
for sid, a, b in sorted(was_zero, key=lambda r: -r[2])[:15]:
    print(f"    {sid:28s} {a:5.2f} -> {b:.2f}")
