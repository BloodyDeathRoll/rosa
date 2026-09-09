"""OPEN-ITEMS 26: is "dry at chart datum" land, or seabed the tide floods?

GEBCO depths are datum depths, so a sandbar with water over it at high tide reads as dry
land and `wet_samples_deep_to_shallow` drops it - which is why five estuary and reef-flat
spots still publish flat. This admits samples up to N metres above datum and lets
`tide_shifted_samples` flood or dry each one at the hour's tide, then grades the result on
the eye frames, the flat count, fleet movement and - the thing that killed the last
candidate - tide response. Nothing is applied.
"""
import statistics as st
from pathlib import Path

import yaml

from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.models import SwellPartition
from rosa_pipeline.physics import tide_shifted_samples
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range

BATHY = Path("data/spots/derived/bathy")
BANDS = (0.0, 0.5, 1.0, 2.0, 3.0)
WATCH = ("pen-hat", "new-brighton", "lucky-bay", "cottesloe", "broughton-bay")

spots = load_spots(Path("data/spots"))
profs = {s: load_profile(s, BATHY) for s in spots}
frames = yaml.safe_load(Path("data/calibration/frames.yaml").read_text())["frames"]


def centre(s):
    lo, hi = s.swell_window
    return (lo + ((hi - lo) % 360.0) / 2.0) % 360.0


def h(spot, prof, parts, band, tide=0.0):
    samples = tide_shifted_samples(prof.wet_samples_deep_to_shallow(band), tide)
    return breaker_range(
        breaker_height_from_profile(parts, spot.swell_window, spot.shore_normal, samples,
                                    wind_normal_ms=0.0),
        spot.height_coeff,
    )[1]


def sea(spot, hs=1.5, tp=12.0):
    return (SwellPartition(kind="swell", height_m=hs, period_s=tp,
                           direction_deg=centre(spot), peak_period_s=tp),)


def frame_parts(f):
    return tuple(
        SwellPartition(kind=p.get("kind", "swell"), height_m=p["hs"], period_s=p["tm"],
                       direction_deg=p["dir"], peak_period_s=p.get("tp"))
        for p in f["partitions"]
    )


base = {s: h(sp, profs[s], sea(sp), 0.0) for s, sp in spots.items() if profs[s]}
print(f"{'band':>5} | {'frames':>6} | {'flat':>4} | {'mean d':>7} {'p90':>6} | "
      f"tide bigger/smaller/none | the five")
for band in BANDS:
    ok = 0
    for f in frames:
        sp, pr = spots.get(f["spot"]), profs.get(f["spot"])
        if not sp or not pr:
            continue
        got = h(sp, pr, frame_parts(f), band, f.get("tide_m", 0.0))
        lo, hi = f["observed_m"]
        ok += lo - f.get("slack_m", 0.0) <= got <= hi + f.get("slack_m", 0.0)
    flat, dd, up, dn, fl = 0, [], 0, 0, 0
    for sid, sp in spots.items():
        pr = profs[sid]
        if not pr:
            continue
        v = h(sp, pr, sea(sp), band)
        flat += v < 0.15
        dd.append(v - base[sid])
        d = h(sp, pr, sea(sp), band, 1.0) - h(sp, pr, sea(sp), band, -0.5)
        if d > 0.01:
            up += 1
        elif d < -0.01:
            dn += 1
        else:
            fl += 1
    ad = sorted(abs(x) for x in dd)
    five = " ".join(f"{h(spots[s], profs[s], sea(spots[s]), band):.2f}" for s in WATCH)
    print(f"{band:>5.1f} | {ok:>6d} | {flat:>4d} | {st.fmean(dd):>+7.3f} "
          f"{ad[int(len(ad) * 0.9)]:>6.3f} | {up:5d}/{dn:4d}/{fl:4d} | {five}")
