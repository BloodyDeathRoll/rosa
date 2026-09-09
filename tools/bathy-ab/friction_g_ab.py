"""The decision in CALIBRATION.md 2026-09-09: what does fixing the `g` in the friction
term actually cost, on the profiles that ship today?

BOTTOM_FRICTION_CB is applied over g where the JONSWAP energy form divides by g^2, so the
effective coefficient is ~10x textbook. That is fine at kd > 1 and diverges below it, which
is why 63 spots publish flat. This grades the whole path between the two, on the COMMITTED
cut, against the five eye frames and the 1408-spot same-input fleet. Nothing is applied.
"""
import statistics as st
from collections import defaultdict
from pathlib import Path

import yaml

from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.models import SwellPartition
from rosa_pipeline.physics import BOTTOM_FRICTION_CB, tide_shifted_samples
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range

COM = Path("data/spots/derived/bathy")
# shipped, then toward the textbook value (0.038/g = 0.00387 in this code's units)
CBS = (0.038, 0.0247, 0.019, 0.0114, 0.0076, 0.0039)
SEAS = (("windswell 1.0/8", 1.0, 8.0), ("groundswell 1.5/12", 1.5, 12.0),
        ("long 2.5/16", 2.5, 16.0))

spots = load_spots(Path("data/spots"))
frames = yaml.safe_load(Path("data/calibration/frames.yaml").read_text())["frames"]
profs = {sid: load_profile(sid, COM) for sid in spots}


def centre(s):
    lo, hi = s.swell_window
    return (lo + ((hi - lo) % 360.0) / 2.0) % 360.0


def h(spot, prof, parts, cb, tide=0.0):
    samples = tide_shifted_samples(prof.wet_samples_deep_to_shallow(), tide)
    return breaker_range(
        breaker_height_from_profile(parts, spot.swell_window, spot.shore_normal, samples,
                                    wind_normal_ms=0.0, friction_cb=cb),
        spot.height_coeff,
    )[1]


def sea(spot, hs, tp):
    return (SwellPartition(kind="swell", height_m=hs, period_s=tp,
                           direction_deg=centre(spot), peak_period_s=tp),)


def frame_parts(f):
    return tuple(
        SwellPartition(kind=p.get("kind", "swell"), height_m=p["hs"], period_s=p["tm"],
                       direction_deg=p["dir"], peak_period_s=p.get("tp"))
        for p in f["partitions"]
    )


base = {sid: {lbl: h(sp, profs[sid], sea(sp, hs, tp), BOTTOM_FRICTION_CB)
              for lbl, hs, tp in SEAS}
        for sid, sp in spots.items() if profs[sid]}

print(f"{'cb':>8} {'x textbook':>10} | {'frames':>6} {'which':<22} | {'flat':>4} | "
      f"{'median h':>8} {'mean d':>7} {'p90 d':>6}")
per_cb_region = {}
for cb in CBS:
    ok, names = 0, []
    for f in frames:
        spot, prof = spots.get(f["spot"]), profs.get(f["spot"])
        if not spot or not prof:
            continue
        got = h(spot, prof, frame_parts(f), cb, f.get("tide_m", 0.0))
        lo, hi = f["observed_m"]
        slack = f.get("slack_m", 0.0)
        if lo - slack <= got <= hi + slack:
            ok += 1
            names.append(f["id"].split("-")[-1])
    heights, flat, deltas = [], 0, []
    region = defaultdict(list)
    for sid, spot in spots.items():
        prof = profs[sid]
        if not prof:
            continue
        for lbl, hs, tp in SEAS:
            v = h(spot, prof, sea(spot, hs, tp), cb)
            deltas.append(v - base[sid][lbl])
            if lbl.startswith("groundswell"):
                heights.append(v)
                flat += v < 0.15
                region[spot.region or "?"].append(v - base[sid][lbl])
    per_cb_region[cb] = region
    ad = sorted(abs(d) for d in deltas)
    mark = "  <- shipping" if cb == BOTTOM_FRICTION_CB else ""
    print(f"{cb:>8.4f} {cb / 0.00387:>9.1f}x | {ok:>6d} {','.join(names)[:22]:<22} | {flat:>4d} | "
          f"{st.median(heights):>8.2f} {st.fmean(deltas):>+7.3f} {ad[int(len(ad) * 0.9)]:>6.3f}{mark}")

print("\nregional mean delta at the textbook value (biggest movers):")
reg = per_cb_region[CBS[-1]]
rows = sorted(((r, st.fmean(v), len(v)) for r, v in reg.items() if len(v) >= 8),
              key=lambda t: -t[1])
for r, m, n in rows[:8]:
    print(f"  {r:26s} {m:+6.2f} m  ({n} spots)")
print("  ...")
for r, m, n in rows[-5:]:
    print(f"  {r:26s} {m:+6.2f} m  ({n} spots)")
