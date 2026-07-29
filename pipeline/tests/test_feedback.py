"""Surfer 👍👎 feedback: contract, prediction snapshot, bucket bias, report."""

from __future__ import annotations

from datetime import UTC, datetime

from rosa_pipeline.feedback import (
    FeedbackRecord,
    bucket_delta,
    markdown_rows,
    predicted_from_payload,
    summarize,
)

PAYLOAD = {
    "current": {"rating": 60, "bucket": "GOOD", "h": [0.5, 0.8], "phrase": "waist-high"},
    "hours": [
        {
            "t": "2026-07-21T06:00+03:00",
            "rating": 55,
            "bucket": "GOOD",
            "h": [0.5, 0.8],
            "phrase": "waist-high",
        },
        {
            "t": "2026-07-21T12:00+03:00",
            "rating": 20,
            "bucket": "POOR",
            "h": [0.1, 0.2],
            "phrase": "shin-high",
        },
    ],
}


def test_predicted_snapshot_picks_nearest_hour() -> None:
    at = datetime(2026, 7, 21, 3, 30, tzinfo=UTC)  # = 06:30 +03:00, nearest the 06:00 row
    pred = predicted_from_payload(PAYLOAD, at)
    assert pred == {"rating": 55, "bucket": "GOOD", "h": [0.5, 0.8], "phrase": "waist-high"}


def test_predicted_falls_back_to_current_when_no_hours() -> None:
    pred = predicted_from_payload({"current": PAYLOAD["current"]}, datetime.now(UTC))
    assert pred["bucket"] == "GOOD" and pred["rating"] == 60


def test_bucket_delta_sign_and_guard() -> None:
    assert bucket_delta("GOOD", "POOR") == 2  # predicted 2 buckets hot
    assert bucket_delta("POOR", "GOOD") == -2
    assert bucket_delta("GOOD", None) is None
    assert bucket_delta("NOPE", "POOR") is None


def test_record_row_roundtrips() -> None:
    r = FeedbackRecord(
        spot="beit-yanai",
        at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        verdict="down",
        predicted={"bucket": "GOOD", "rating": 55, "h": [0.5, 0.8], "phrase": "waist-high"},
        observed={"bucket": "POOR", "h_mid": 0.15, "note": "cam ankle-high"},
    )
    assert FeedbackRecord.from_row(r.to_row()) == r


def _rec(pred_bucket, obs_bucket, verdict, pred_h=None, obs_h=None) -> FeedbackRecord:
    return FeedbackRecord(
        spot="s",
        at=datetime(2026, 7, 21, 9, 0, tzinfo=UTC),
        verdict=verdict,
        predicted={"bucket": pred_bucket, "rating": 0, "h": pred_h, "phrase": ""},
        observed={k: v for k, v in (("bucket", obs_bucket), ("h_mid", obs_h)) if v is not None},
    )


def test_summarize_agreement_and_hot_bias() -> None:
    records = [
        _rec("GOOD", "POOR", "down", pred_h=[0.5, 0.9], obs_h=0.2),  # +2 hot, +0.5 m hot
        _rec("FAIR", "POOR", "down", pred_h=[0.3, 0.5], obs_h=0.3),  # +1 hot, +0.1 m hot
        _rec("POOR", "POOR", "up"),  # spot on, no height
    ]
    s = summarize(records)
    assert s["n"] == 3
    assert abs(s["agreement"] - 1 / 3) < 1e-9
    assert s["n_bucketed"] == 3
    assert abs(s["bucket_bias"] - 1.0) < 1e-9  # (2+1+0)/3 → systematically hot
    assert s["n_height"] == 2
    assert abs(s["height_bias_m"] - 0.3) < 1e-9  # (0.5+0.1)/2


def test_summarize_empty_is_safe() -> None:
    s = summarize([])
    assert s["n"] == 0 and s["agreement"] is None and s["bucket_bias"] is None


def test_markdown_rows_render() -> None:
    md = markdown_rows([_rec("GOOD", "POOR", "down")])
    assert md.startswith("| 2026-07-21 | 09:00 | s | GOOD 0")
    assert "👎" in md and "POOR" in md
