import json, sys
from pathlib import Path
import rosa_pipeline.physics as ph
from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.models import SwellPartition
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range
print(ph.__file__, file=sys.stderr)
spots = load_spots(Path("data/spots")); out = {}
for sid, spot in spots.items():
    p = load_profile(sid, Path("data/spots/derived/bathy"))
    if p is None: continue
    lo, hi = spot.swell_window; c = (lo + ((hi - lo) % 360.0) / 2.0) % 360.0
    out[sid] = []
    for hs, tp in ((1.0, 8.0), (1.5, 12.0), (2.5, 16.0)):
        part = SwellPartition(kind="swell", height_m=hs, period_s=tp, direction_deg=c, peak_period_s=tp)
        h = breaker_height_from_profile((part,), spot.swell_window, spot.shore_normal, p.wet_samples_deep_to_shallow(), wind_normal_ms=0.0)
        out[sid].append(breaker_range(h, spot.height_coeff)[1])
json.dump(out, open(sys.argv[1], "w"))
