"""Forecast archive store + lead-time skill scoring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rosa_pipeline.archive import FileArchiveStore, rows_from_model
from rosa_pipeline.observe import BuoyObs
from rosa_pipeline.verify import WavePoint, lead_time_scorecard


def test_rows_from_model_shape() -> None:
    run = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)
    model = [WavePoint(time=datetime(2026, 7, 22, 0, 0, tzinfo=UTC), hs=1.5, tp=10.0, dir=250.0)]
    rows = rows_from_model(run, model)
    assert rows == [
        {
            "run": "2026-07-20T00:00:00+00:00",
            "valid": "2026-07-22T00:00:00+00:00",
            "hs": 1.5,
            "tp": 10.0,
            "dir": 250.0,
        }
    ]


def test_file_store_appends_and_survives_partial_line(tmp_path) -> None:
    store = FileArchiveStore(tmp_path)
    assert store.read("46042") == []  # nothing yet
    store.append("46042", [{"run": "a", "valid": "b", "hs": 1.0}])
    store.append("46042", [{"run": "c", "valid": "d", "hs": 2.0}])  # append-only, adds bytes
    # simulate an interrupted write leaving a trailing partial line
    (tmp_path / "46042.jsonl").open("a", encoding="utf-8").write('{"run": "e", "va')
    rows = store.read("46042")
    assert [r["hs"] for r in rows] == [1.0, 2.0]  # partial line skipped, good rows intact


def _obs(t: datetime, **kw) -> BuoyObs:
    base = dict(hs_m=None, dpd_s=None, apd_s=None, mwd_deg=None, wtmp_c=None)
    base.update(kw)
    return BuoyObs(station="x", time=t, **base)


def test_lead_time_buckets_and_scoring() -> None:
    valid = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    # two forecasts for the SAME valid time: one made 6 h ahead (0-1d), one 4 days ahead (4-5d)
    rows = [
        {
            "run": (valid - timedelta(hours=6)).isoformat(),
            "valid": valid.isoformat(),
            "hs": 1.1,
            "tp": None,
            "dir": None,
        },
        {
            "run": (valid - timedelta(days=4)).isoformat(),
            "valid": valid.isoformat(),
            "hs": 1.6,
            "tp": None,
            "dir": None,
        },
    ]
    obs = [_obs(valid, hs_m=1.0)]  # truth: 1.0 m
    by_lead = lead_time_scorecard(rows, obs, tol_min=30)
    # near lead is accurate, far lead drifts hot - exactly the signal the archive exists to show
    assert by_lead["0-1d"]["hs"].n == 1
    assert abs(by_lead["0-1d"]["hs"].bias - 0.1) < 1e-9
    # a 96 h lead lands in 4-5d: buckets split at 96 h / 240 h so each ceiling
    # tier is priced only from the leads of the days it covers (2026-08-07)
    assert by_lead["4-5d"]["hs"].n == 1
    assert abs(by_lead["4-5d"]["hs"].bias - 0.6) < 1e-9
    # buckets with no matured forecasts stay empty, not errored
    assert by_lead["3-4d"]["hs"].n == 0
    assert by_lead["7-9d"]["hs"].n == 0
    assert by_lead["9d+"]["hs"].n == 0


def test_lead_scorecard_ignores_unmatched_valid_times() -> None:
    valid = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    rows = [
        {
            "run": (valid - timedelta(hours=6)).isoformat(),
            "valid": valid.isoformat(),
            "hs": 1.1,
            "tp": None,
            "dir": None,
        }
    ]
    obs = [_obs(valid + timedelta(hours=3), hs_m=1.0)]  # obs 3 h off - outside 30-min tol
    by_lead = lead_time_scorecard(rows, obs, tol_min=30)
    assert all(by_lead[b]["hs"].n == 0 for b in by_lead)
