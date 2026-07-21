"""Skill metrics, model/obs pairing, and the end-to-end scorecard on real fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rosa_pipeline.buoys import Buoy
from rosa_pipeline.observe import BuoyObs, NDBCFixtureSource
from rosa_pipeline.verify import (
    WavePoint,
    ang_diff,
    build_scorecard,
    pair_series,
    parse_marine_waves,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "verify"


def test_ang_diff_wraps() -> None:
    assert ang_diff(10, 350) == 20  # across 0, not -340
    assert ang_diff(350, 10) == -20
    assert ang_diff(90, 90) == 0


def _obs(t: datetime, **kw) -> BuoyObs:
    base = dict(hs_m=None, dpd_s=None, apd_s=None, mwd_deg=None, wtmp_c=None)
    base.update(kw)
    return BuoyObs(station="x", time=t, **base)


def test_pairing_matches_nearest_within_tolerance() -> None:
    t0 = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.5, tp=10.0, dir=250.0)]
    obs = [
        _obs(t0 + timedelta(minutes=10), hs_m=1.2, apd_s=8.0, mwd_deg=245.0),  # in tol
        _obs(t0 + timedelta(minutes=90), hs_m=9.9, apd_s=9.9, mwd_deg=9.9),  # out of tol
    ]
    pairs = pair_series(model, obs, tol_min=30)
    assert pairs["hs"] == [(1.5, 1.2)]
    assert pairs["tp"] == [(10.0, 8.0)]  # model MEAN period vs obs APD
    assert pairs["dir"] == [(250.0, 245.0)]


def test_missing_values_drop_from_that_variable_only() -> None:
    t0 = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.5, tp=10.0, dir=250.0)]
    obs = [_obs(t0, hs_m=1.2, apd_s=None, mwd_deg=245.0)]  # no period
    pairs = pair_series(model, obs, tol_min=30)
    assert pairs["hs"] and pairs["dir"]
    assert pairs["tp"] == []


def test_scorecard_metrics_math() -> None:
    t = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    # two hours; model hs over-predicts by +0.2 then +0.4 → bias +0.3, rmse sqrt(0.1)
    model = [
        WavePoint(time=t, hs=1.2, tp=None, dir=None),
        WavePoint(time=t + timedelta(hours=1), hs=1.4, tp=None, dir=None),
    ]
    obs = [_obs(t, hs_m=1.0), _obs(t + timedelta(hours=1), hs_m=1.0)]
    hs = build_scorecard(model, obs, tol_min=30)["hs"]
    assert hs.n == 2
    assert abs(hs.bias - 0.3) < 1e-9
    assert abs(hs.mae - 0.3) < 1e-9
    assert abs(hs.rmse - (0.1**0.5)) < 1e-9
    assert hs.scatter_index is not None and abs(hs.scatter_index - (0.1**0.5)) < 1e-9


def test_empty_scorecard_is_safe() -> None:
    scores = build_scorecard([], [], tol_min=30)
    assert all(s.n == 0 for s in scores.values())
    assert scores["dir"].scatter_index is None


def test_end_to_end_on_real_fixtures() -> None:
    marine = json.loads((FIX / "marine_46042.json").read_text(encoding="utf-8"))
    model = parse_marine_waves(marine)
    buoy = Buoy(id="46042", name="Monterey", lat=36.785, lon=-122.408, source="ndbc")
    obs = NDBCFixtureSource(FIX).fetch(buoy)
    scores = build_scorecard(model, obs, tol_min=30)
    # the captured forecast and buoy obs overlap on 2026-07-21 morning → real pairs exist
    assert scores["hs"].n > 0
    assert scores["hs"].rmse >= 0
    # Monterey summer swell ~1-2 m; a sane model shouldn't be off by more than a metre RMS
    assert scores["hs"].rmse < 1.0
