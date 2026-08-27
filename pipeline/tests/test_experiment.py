"""Stage-2E experiment harness: offline, against the committed frames + profiles."""

from pathlib import Path

import pytest

from rosa_pipeline.bathymetry import load_profile
from rosa_pipeline.experiment import (
    BASELINE,
    EXPONENT_GRID,
    Candidate,
    load_frames,
    predict_frame,
    render_report,
    run_experiment,
)
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import breaker_height_from_profile, breaker_range

ROOT = Path(__file__).resolve().parents[2]
FRAMES = ROOT / "data" / "calibration" / "frames.yaml"
SPOTS_DIR = ROOT / "data" / "spots"
BATHY_DIR = SPOTS_DIR / "derived" / "bathy"


def test_frames_load_and_reference_real_spots():
    frames = load_frames(FRAMES)
    assert len(frames) >= 4
    spots = load_spots(SPOTS_DIR)
    for fr in frames:
        assert fr.spot_id in spots, fr.id
        assert load_profile(fr.spot_id, BATHY_DIR) is not None, fr.id
        assert fr.observed_lo_m <= fr.observed_hi_m
        assert fr.partitions


def test_baseline_reproduces_production_path():
    """The harness must BE the production path: BASELINE has to reproduce, exactly, what
    ``breaker_height_from_profile`` computes with no candidate injected. This is what makes
    every other row in the report a like-for-like comparison against what ships, so it is
    pinned against the real function rather than a copied constant."""
    frames = {f.id: f for f in load_frames(FRAMES)}
    spots = load_spots(SPOTS_DIR)
    for fr in frames.values():
        spot = spots[fr.spot_id]
        wet = load_profile(fr.spot_id, BATHY_DIR).wet_samples_deep_to_shallow()
        depths = [(x, d + fr.tide_m) for x, d in wet if d + fr.tide_m > 0]
        production = (
            breaker_height_from_profile(fr.partitions, spot.swell_window, spot.shore_normal, depths)
            * spot.height_coeff
        )
        assert predict_frame(fr, spot, wet, BASELINE) == pytest.approx(production), fr.id


def test_shipping_transform_on_the_2026_07_26_hilton_frame_is_pinned():
    """Pins the shipping transform's answer on the 07-26 Hilton frame so any physics or
    rideability change shows up here deliberately, not silently.

    History: under Stage 2E's monochromatic march this asserted the mid landed inside the
    frame's observed 0.5-0.6 m eye band (docs/CALIBRATION.md 2026-07-30). The random-sea
    march (2026-08-28) grades this frame under that band - a KNOWN, accepted divergence:
    the July frames' inputs are OM hindcast reconstructions, not the blend production now
    serves, and they conflict internally under the new physics (07-19 demands the transform
    go down at ~7 s where 07-26 demands it up). Product call 2026-08-28: physics ships on
    its own; the frames recalibrate the day fresh eye reports arrive - they no longer gate.
    If a fresh eye frame lands, re-fit and re-pin; do not tune blind to un-break the band."""
    frames = {f.id: f for f in load_frames(FRAMES)}
    fr = frames["2026-07-26-hilton-undercall"]
    spot = load_spots(SPOTS_DIR)["hilton"]
    wet = load_profile("hilton", BATHY_DIR).wet_samples_deep_to_shallow()
    mid = predict_frame(fr, spot, wet, BASELINE)
    lo, _, hi = breaker_range(mid, spot.height_coeff)
    assert (lo, hi) == (0.3, 0.4), f"transform moved on the pinned frame: mid={mid:.3f}"


def test_peak_keyed_candidate_raises_the_hilton_frames():
    """Mechanism check, not a verdict: Tp exceeds Tm on both Hilton frames, so the
    peak-keyed shipping baseline must predict strictly higher than a mean-keyed one."""
    frames = {f.id: f for f in load_frames(FRAMES)}
    spot = load_spots(SPOTS_DIR)["hilton"]
    wet = load_profile("hilton", BATHY_DIR).wet_samples_deep_to_shallow()
    mean = Candidate(key="mean", exp=BASELINE.exp)
    for fid in ("2026-07-25-hilton-undercall", "2026-07-26-hilton-undercall"):
        fr = frames[fid]
        assert predict_frame(fr, spot, wet, BASELINE) > predict_frame(fr, spot, wet, mean), fid


def test_run_experiment_and_report():
    frames = load_frames(FRAMES)
    spots = load_spots(SPOTS_DIR)
    results = run_experiment(frames, spots, BATHY_DIR)
    assert len(results) == 3 * len(EXPONENT_GRID)  # 3 period keys x the exponent grid
    report = render_report(results)
    assert "shipping" in report
    # the report never crashes on the no-winner case and always states an outcome
    assert "satisfying every frame" in report or "least-bad" in report


def test_bad_frame_fails_before_any_candidate_is_graded():
    """Dream review 2026-08-05: spot + profile resolution was inside the per-candidate
    loop, so a frame pointing at a missing spot only surfaced when the first candidate
    reached it - and with no candidates at all it never surfaced. Resolution now runs
    up front, before any grading."""
    from dataclasses import replace

    frames = load_frames(FRAMES)
    bad = replace(frames[0], spot_id="no-such-spot")
    spots = load_spots(SPOTS_DIR)
    with pytest.raises(KeyError, match="no-such-spot"):
        run_experiment([bad], spots, BATHY_DIR, candidates=())


def test_missing_peak_period_falls_back_to_mean():
    """Frames may omit tp (old fixtures, secondary swells) - a peak-keyed candidate
    must then behave exactly like the mean-keyed one, not crash or zero out."""
    from rosa_pipeline.models import SwellPartition

    p = SwellPartition(height_m=1.0, period_s=6.0, direction_deg=290.0)
    peak = Candidate(key="peak", exp=1.4)
    mean = Candidate(key="mean", exp=1.4)
    assert peak.rideability(p) == mean.rideability(p)
