"""Swell-event detection (CLAUDE.md spec): >= 12 h contiguous window of >= 2x
trailing-48h-median energy, GOOD+ at peak → {start, peak, end, peak_height, direction}."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rosa_pipeline.events import detect_events
from rosa_pipeline.models import HourForecast, ScoredHour, Spot, SwellPartition

T0 = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)

SPOT = Spot(
    id="test-spot",
    name="Test Spot",
    lat=32.2,
    lon=34.55,
    timezone="Asia/Jerusalem",
    offshore_point=(32.2, 34.55),
    offshore_direction=90.0,
    shore_normal=270.0,
    swell_window=(250.0, 320.0),
    height_coeff=1.0,
    break_type="beach",
    ideal_wind_dir=(60.0, 120.0),
    ideal_size_m=(0.8, 2.0),
)


def _hour(i: int, energy: float, rating: int, h_mid: float = 1.0) -> ScoredHour:
    dominant = SwellPartition(height_m=1.0, period_s=10.0, direction_deg=290.0)
    hf = HourForecast(
        time=T0 + timedelta(hours=i),
        partitions=(dominant,),
        sst_c=25.0,
        wind_speed_kph=10.0,
        wind_dir_deg=90.0,
        wind_gusts_kph=None,
    )
    bucket = "GOOD" if rating >= 50 else "POOR"
    return ScoredHour(
        hour=hf,
        h_break_lo=h_mid * 0.8,
        h_break_mid=h_mid,
        h_break_hi=h_mid * 1.2,
        phrase="waist-high",
        wind_class="offshore",
        energy=energy,
        dominant=dominant,
        size_score=20.0,
        period_score=10.0,
        wind_score=rating - 30.0,
        rating=rating,
        bucket=bucket,  # type: ignore[arg-type]
        wetsuit=None,
    )


def _series(pulse_start: int, pulse_len: int, pulse_energy: float, peak_rating: int):
    """5 days hourly at baseline energy 1.0 with one rectangular pulse."""
    hours = []
    for i in range(120):
        in_pulse = pulse_start <= i < pulse_start + pulse_len
        mid_pulse = i == pulse_start + pulse_len // 2
        hours.append(
            _hour(
                i,
                energy=pulse_energy + (1.0 if mid_pulse else 0.0) if in_pulse else 1.0,
                rating=peak_rating if in_pulse else 20,
                h_mid=1.8 if mid_pulse else 1.0,
            )
        )
    return hours


def test_detects_one_event_with_correct_shape() -> None:
    scored = _series(pulse_start=72, pulse_len=18, pulse_energy=6.0, peak_rating=55)
    (event,) = detect_events(scored)
    assert event.start == T0 + timedelta(hours=72)
    assert event.end == T0 + timedelta(hours=89)
    assert event.peak == T0 + timedelta(hours=72 + 9)  # the mid-pulse energy bump
    assert event.peak_height_m == 1.8
    assert event.direction_deg == 290.0
    assert event.peak_rating == 55 and event.peak_bucket == "GOOD"


def test_short_pulse_is_not_an_event() -> None:
    scored = _series(pulse_start=72, pulse_len=8, pulse_energy=6.0, peak_rating=55)
    assert detect_events(scored) == []


def test_poor_peak_is_not_an_event() -> None:
    # elevated energy but never surfable — windswell mush stays un-evented
    scored = _series(pulse_start=72, pulse_len=18, pulse_energy=6.0, peak_rating=35)
    assert detect_events(scored) == []


def test_no_baseline_no_event() -> None:
    # a swell already running at the series start has no trailing baseline to be 2x of
    scored = _series(pulse_start=0, pulse_len=18, pulse_energy=6.0, peak_rating=55)
    assert detect_events(scored) == []


def test_flat_baseline_is_floored() -> None:
    # near-zero baseline: 2x nothing must not make a ripple an event
    hours = [_hour(i, energy=0.01, rating=20) for i in range(60)]
    for i in range(24, 44):
        hours[i] = _hour(i, energy=0.4, rating=55)  # 40x the (unfloored) median
    assert detect_events(hours) == []  # 0.4 < 2 x MEDIAN_FLOOR(0.5)


def test_events_land_in_payload() -> None:
    from rosa_pipeline.publish import build_payload

    scored = _series(pulse_start=72, pulse_len=18, pulse_energy=6.0, peak_rating=55)
    payload = build_payload(SPOT, scored, fetched_at="2026-07-20T00:00:00+00:00", now=T0)
    (event,) = payload["events"]
    assert event["rating"] == 55 and event["bucket"] == "GOOD"
    assert event["h_peak"] == 1.8 and event["dir"] == 290.0
    assert event["start"] < event["peak"] < event["end"]
