"""Pre-registered question (CALIBRATION.md 2026-09-09): does stopping bottom friction
once the sea starts breaking clear the reef flats WITHOUT inflating the fleet or losing
a graded frame?

Friction is a propagation term; inside the surf zone breaking dominates it. Integrating it
across the kilometre of shallow shelf a 460 m GEBCO cell smears in front of a reef destroys
the wave before it reaches a breaking substep, so the published height collapses to ~0.

Three modes x two bathymetry cuts, scored on: the five graded eye frames, the flat-spot
count, ten named reef waves, and same-input fleet movement against today's published
baseline (committed profiles, mode "always"). Nothing is applied.
"""
import statistics as st
import sys
from pathlib import Path

import yaml

from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.models import SwellPartition
from rosa_pipeline.physics import FRICTION_MODES, tide_shifted_samples
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range

CAND = Path(sys.argv[1])
COM = Path("data/spots/derived/bathy")
SEAS = (("windswell 1.0 m 8 s", 1.0, 8.0), ("groundswell 1.5 m 12 s", 1.5, 12.0),
        ("long swell 2.5 m 16 s", 2.5, 16.0))
WATCH = ["uluwatu", "g-land-speedies", "hikkaduwa", "weligama-west", "koggala",
         "jelly-baby", "villingili", "kabalana", "playa-cocles", "periscopes"]

spots = load_spots(Path("data/spots"))
frames = yaml.safe_load(Path("data/calibration/frames.yaml").read_text())["frames"]


def centre(s):
    lo, hi = s.swell_window
    return (lo + ((hi - lo) % 360.0) / 2.0) % 360.0


def h(spot, prof, parts, mode, tide=0.0):
    samples = tide_shifted_samples(prof.wet_samples_deep_to_shallow(), tide)
    hb = breaker_height_from_profile(
        parts, spot.swell_window, spot.shore_normal, samples,
        wind_normal_ms=0.0, friction_mode=mode,
    )
    return breaker_range(hb, spot.height_coeff)[1]


def sea(spot, hs, tp):
    return (SwellPartition(kind="swell", height_m=hs, period_s=tp,
                           direction_deg=centre(spot), peak_period_s=tp),)


def frame_parts(f):
    return tuple(
        SwellPartition(kind=p.get("kind", "swell"), height_m=p["hs"], period_s=p["tm"],
                       direction_deg=p["dir"], peak_period_s=p.get("tp"))
        for p in f["partitions"]
    )


base = {}
for sid, spot in spots.items():
    p = load_profile(sid, COM)
    if p:
        base[sid] = {lbl: h(spot, p, sea(spot, hs, tp), "always") for lbl, hs, tp in SEAS}

print(f"{'arm':>9} {'mode':>7} | {'frames':>6} | {'flat':>5} {'watch':>5} | "
      f"{'median h':>8} | {'mean d vs today':>15}")
for cut, arm in ((COM, "committed"), (CAND, "local")):
    for mode in FRICTION_MODES:
        ok = 0
        for f in frames:
            spot, prof = spots.get(f["spot"]), load_profile(f["spot"], cut)
            if not spot or not prof:
                continue
            got = h(spot, prof, frame_parts(f), mode, f.get("tide_m", 0.0))
            lo, hi = f["observed_m"]
            slack = f.get("slack_m", 0.0)
            ok += lo - slack <= got <= hi + slack
        heights, flat, watch, deltas = [], 0, 0, []
        for sid, spot in spots.items():
            prof = load_profile(sid, cut)
            if not prof:
                continue
            for lbl, hs, tp in SEAS:
                v = h(spot, prof, sea(spot, hs, tp), mode)
                if sid in base:
                    deltas.append(v - base[sid][lbl])
                if lbl.startswith("groundswell"):
                    heights.append(v)
                    if v < 0.15:
                        flat += 1
                        watch += sid in WATCH
        mark = "  <- shipping" if (arm == "committed" and mode == "always") else ""
        print(f"{arm:>9} {mode:>7} | {ok:>6d} | {flat:>5d} {watch:>5d} | "
              f"{st.median(heights):>8.2f} | {st.fmean(deltas):>+14.3f}{mark}")
