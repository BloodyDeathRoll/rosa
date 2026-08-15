"""The automated wind-coefficient fit from the surfer feedback stream (item 4)."""

from __future__ import annotations

from datetime import UTC, datetime

from rosa_pipeline.feedback import (
    WIND_FIT_MIN_N,
    FeedbackRecord,
    predicted_from_payload,
    render_wind_fit,
    wind_fit,
)


def _rec(obs_h: float, pred_h: float, kph: float, cls: str) -> FeedbackRecord:
    return FeedbackRecord(
        spot="x",
        at=datetime(2026, 8, 15, tzinfo=UTC),
        verdict="up",
        predicted={"h": [pred_h - 0.1, pred_h + 0.1], "wind": {"kph": kph, "class": cls}},
        observed={"h_mid": obs_h},
    )


def test_fit_recovers_a_planted_coefficient() -> None:
    # synthesise rows from the model itself with c = 0.05 and confirm the fit finds it
    import math

    c = 0.05
    recs = []
    for i, (kph, cls) in enumerate(
        [(25, "onshore"), (35, "onshore"), (45, "onshore"), (30, "offshore"), (40, "offshore")] * 3
    ):
        pred = 1.0 + (i % 4) * 0.3
        sign = 1.0 if cls == "offshore" else -1.0
        w = (sign * kph / 3.6) / math.sqrt(9.81 * pred / 0.78)
        recs.append(_rec(pred * (1 + c * w), pred, kph, cls))
    fit = wind_fit(recs)
    assert fit["n_windy"] == 15
    assert abs(fit["coeff"] - c) < 0.005
    assert fit["usable"]  # n >= floor and clearly significant
    assert "FITTABLE" in render_wind_fit(fit)


def test_calm_and_cross_rows_carry_no_signal() -> None:
    recs = [
        _rec(1.0, 1.0, 10, "onshore"),  # under the wind floor
        _rec(1.0, 1.0, 40, "cross-shore"),  # no usable normal component
        _rec(1.0, 1.0, 40, "onshore"),  # the one usable row
    ]
    fit = wind_fit(recs)
    assert fit["n_windy"] == 1
    assert not fit["usable"]
    assert str(WIND_FIT_MIN_N) in render_wind_fit(fit)


def test_no_rows_renders_the_accumulation_note() -> None:
    fit = wind_fit([])
    assert fit == {"n_windy": 0, "coeff": None, "stderr": None, "usable": False}
    assert "accumulates on its own" in render_wind_fit(fit)


def test_predicted_snapshot_now_carries_the_wind() -> None:
    payload = {
        "hours": [
            {
                "t": "2026-08-15T12:00+03:00",
                "rating": 50,
                "bucket": "FAIR",
                "h": [0.5, 0.8],
                "wind": {"kph": 32.0, "class": "onshore"},
            }
        ]
    }
    snap = predicted_from_payload(payload, datetime.fromisoformat("2026-08-15T12:00+03:00"))
    assert snap["wind"] == {"kph": 32.0, "class": "onshore"}
