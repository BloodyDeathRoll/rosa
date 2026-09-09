"""Re-fit BOTTOM_FRICTION_CB against the local-GEBCO profiles (CALIBRATION.md 2026-09-09).

The grid and the coefficient are coupled: the local cut resolves 3-5 km reef flats the API
never showed, and the eye-tuned coefficient annihilates a wave crossing one. This sweeps the
coefficient over BOTH cuts and reports, per candidate:

  * the five graded eye frames - does it still fit the sea it was tuned on?
  * how many named waves read flat - the failure the swap is blocked on
  * fleet movement against today's published baseline (committed profiles, shipped Cb)

Nothing is applied. Run from the repo root.
"""
import statistics as st
import sys
from pathlib import Path

import yaml

from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.models import SwellPartition
from rosa_pipeline.physics import BOTTOM_FRICTION_CB
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range

CAND = Path(sys.argv[1])
COM = Path("data/spots/derived/bathy")
CBS = (0.038, 0.019, 0.0095, 0.0038, 0.0019, 0.00038)  # shipped, then /2 /4 /10 /20 /100

spots = load_spots(Path("data/spots"))
frames = yaml.safe_load(Path("data/calibration/frames.yaml").read_text())


def h(spot, prof, parts, cb, tide=0.0):
    from rosa_pipeline.physics import tide_shifted_samples

    samples = tide_shifted_samples(prof.wet_samples_deep_to_shallow(), tide)
    hb = breaker_height_from_profile(
        parts, spot.swell_window, spot.shore_normal, samples,
        wind_normal_ms=0.0, friction_cb=cb,
    )
    return breaker_range(hb, spot.height_coeff)[1]


def centre(s):
    lo, hi = s.swell_window
    return (lo + ((hi - lo) % 360.0) / 2.0) % 360.0


def test_sea(spot, hs=1.5, tp=12.0):
    return (SwellPartition(kind="swell", height_m=hs, period_s=tp,
                           direction_deg=centre(spot), peak_period_s=tp),)


def frame_parts(f):
    return tuple(
        SwellPartition(
            kind=p.get("kind", "swell"), height_m=p["hs"], period_s=p["tm"],
            direction_deg=p["dir"], peak_period_s=p.get("tp"),
        )
        for p in f["partitions"]
    )


# the reef spots the swap breaks, and the Israeli spots every constant was tuned on
WATCH = ["uluwatu", "g-land-speedies", "hikkaduwa", "weligama-west", "koggala",
         "jelly-baby", "villingili", "kabalana", "playa-cocles", "periscopes"]

baseline = {}
for sid, spot in spots.items():
    p = load_profile(sid, COM)
    if p:
        baseline[sid] = h(spot, p, test_sea(spot), BOTTOM_FRICTION_CB)

print(f"{'cb':>9} {'arm':>9} | frames within slack | flat spots | watch flat | "
      f"median h | vs today")
for cut, label in ((COM, "committed"), (CAND, "local")):
    for cb in CBS:
        ok = 0
        for f in frames["frames"]:
            spot = spots.get(f["spot"])
            prof = load_profile(f["spot"], cut)
            if not spot or not prof:
                continue
            got = h(spot, prof, frame_parts(f), cb, f.get("tide_m", 0.0))
            slack = f.get("slack_m", 0.0)
            lo, hi = f["observed_m"]
            if lo - slack <= got <= hi + slack:
                ok += 1
        heights, flat, watch_flat, deltas = [], 0, [], []
        for sid, spot in spots.items():
            prof = load_profile(sid, cut)
            if not prof:
                continue
            v = h(spot, prof, test_sea(spot), cb)
            heights.append(v)
            if v < 0.15:
                flat += 1
                if sid in WATCH:
                    watch_flat.append(sid)
            if sid in baseline:
                deltas.append(v - baseline[sid])
        mark = "  <- shipping" if (cb == BOTTOM_FRICTION_CB and cut == COM) else ""
        print(f"{cb:>9.5f} {label:>9} | {ok:>17d} | {flat:>10d} | {len(watch_flat):>10d} | "
              f"{st.median(heights):>8.2f} | {st.fmean(deltas):+7.3f}{mark}")
