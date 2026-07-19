"""Daylight restriction on the day-strip summary (calibration fix #1)."""

from datetime import UTC, datetime

from rosa_pipeline.models import HourForecast, ScoredHour, Spot
from rosa_pipeline.publish import build_payload
from rosa_pipeline.score import bucket

SPOT = Spot(
    id="test",
    name="Test",
    lat=32.39,
    lon=34.86,
    timezone="Asia/Jerusalem",
    offshore_point=(32.2, 34.55),
    offshore_direction=90.0,
    swell_window=(250.0, 340.0),
    height_coeff=1.0,
    break_type="beach",
    ideal_wind_dir=(45.0, 135.0),
    ideal_size_m=(0.6, 1.5),
)


def scored(hour_utc: int, rating: int) -> ScoredHour:
    h = HourForecast(
        time=datetime(2026, 7, 19, hour_utc, tzinfo=UTC),
        partitions=(),
        sst_c=None,
        wind_speed_kph=5.0,
        wind_dir_deg=90.0,
        wind_gusts_kph=None,
    )
    return ScoredHour(
        hour=h,
        h_break_lo=0.0,
        h_break_mid=0.0,
        h_break_hi=0.0,
        phrase="shin-high",
        wind_class="offshore",
        energy=0.0,
        dominant=None,
        size_score=0.0,
        period_score=0.0,
        wind_score=0.0,
        rating=rating,
        bucket=bucket(rating),
        wetsuit=None,
    )


def test_day_max_ignores_night_hours():
    # 00:00 UTC = 03:00 local (pre-dawn) rates 90; 09:00 UTC = 12:00 local rates 42.
    # The day summary must report the daylight max, not the night land-breeze spike.
    hours = [scored(0, 90), scored(9, 42), scored(12, 38)]
    payload = build_payload(SPOT, hours, fetched_at="t", now=hours[0].hour.time)
    assert payload["days"][0]["rating_max"] == 42
    assert payload["days"][0]["bucket"] == "FAIR"


def test_all_night_day_falls_back_to_all_hours():
    hours = [scored(0, 90), scored(1, 20)]  # 03:00-04:00 local only, both pre-dawn
    payload = build_payload(SPOT, hours, fetched_at="t", now=hours[0].hour.time)
    assert payload["days"][0]["rating_max"] == 90
