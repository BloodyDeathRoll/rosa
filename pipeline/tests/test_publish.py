"""Daylight restriction on the day-strip summary (calibration fix #1)."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from rosa_pipeline.models import HourForecast, ScoredHour, Spot, SwellPartition
from rosa_pipeline.publish import build_payload
from rosa_pipeline.score import bucket

SWELL = SwellPartition(height_m=1.0, period_s=10.0, direction_deg=290.0)

SPOT = Spot(
    id="test",
    name="Test",
    lat=32.39,
    lon=34.86,
    timezone="Asia/Jerusalem",
    offshore_point=(32.2, 34.55),
    offshore_direction=90.0,
    shore_normal=270.0,
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


# ---- the forecast never shows a half day -------------------------------------
# The model horizon lands at a fixed UTC moment, so east of UTC the last local
# day can hold a couple of pre-dawn hours: a day with no daypart bars and a
# range read off two hours (seen live at Midigama, Asia/Colombo, 2026-07-29).


def scored_utc(t: datetime, rating: int = 45) -> ScoredHour:
    """Same as scored() but at an explicit instant, for multi-day series."""
    return replace(scored(0, rating), hour=replace(scored(0, rating).hour, time=t))


def series(start: datetime, slots: int, step_h: int = 3) -> list[ScoredHour]:
    return [scored_utc(start + timedelta(hours=step_h * i)) for i in range(slots)]


def day_span(payload: dict, date: str) -> tuple[int, int]:
    """First and last published hour-of-day for one local date."""
    hours = [int(h["t"][11:13]) for h in payload["hours"] if h["t"].startswith(date)]
    return (min(hours), max(hours)) if hours else (-1, -1)


def test_trailing_partial_day_is_dropped():
    # Israel is UTC+3: 21:00 UTC starts the next local day. Three full local days
    # then two pre-dawn slots of a fourth - the fourth must not be published.
    hours = series(datetime(2026, 7, 19, 21, tzinfo=UTC), 3 * 8 + 2)
    payload = build_payload(SPOT, hours, fetched_at="t", now=hours[0].hour.time)
    dates = [d["date"] for d in payload["days"]]
    assert dates == ["2026-07-20", "2026-07-21", "2026-07-22"]
    assert not any(h["t"].startswith("2026-07-23") for h in payload["hours"])


def test_trailing_partial_day_dropped_on_a_half_hour_offset():
    # Asia/Colombo is +05:30 - the live case. 18:30 UTC = 00:00 local.
    spot = replace(SPOT, timezone="Asia/Colombo", lat=5.95, lon=80.39)
    hours = series(datetime(2026, 7, 19, 18, 30, tzinfo=UTC), 2 * 8 + 2)
    payload = build_payload(spot, hours, fetched_at="t", now=hours[0].hour.time)
    assert [d["date"] for d in payload["days"]] == ["2026-07-20", "2026-07-21"]


def test_every_published_day_spans_its_local_day():
    hours = series(datetime(2026, 7, 19, 21, tzinfo=UTC), 4 * 8 + 5)
    payload = build_payload(SPOT, hours, fetched_at="t", now=hours[0].hour.time)
    assert payload["days"], "a payload must publish at least one day"
    for day in payload["days"]:
        first, last = day_span(payload, day["date"])
        assert first <= 1 and last >= 21, f"{day['date']} is a partial day ({first}..{last})"


def test_short_series_still_publishes_rather_than_nothing():
    # a spot whose feed has no complete day at all reports what it has - an empty
    # payload would be worse than an honest short one
    hours = series(datetime(2026, 7, 19, 21, tzinfo=UTC), 3)
    payload = build_payload(SPOT, hours, fetched_at="t", now=hours[0].hour.time)
    assert len(payload["days"]) == 1


def test_closure_published_when_the_source_gives_a_total():
    """2026-07-30: the four Open-Meteo partition fields do not always hold all of the
    model's energy, and the transform only ever sees partitions. The payload carries the
    ratio so a short sea is visible instead of silent."""
    parts = (
        SwellPartition(height_m=1.02, period_s=4.0, direction_deg=248.0, kind="wind"),
        SwellPartition(height_m=1.04, period_s=10.0, direction_deg=186.0),
        SwellPartition(height_m=0.72, period_s=17.0, direction_deg=188.0),
    )
    s = scored(9, 40)
    s = replace(s, hour=replace(s.hour, partitions=parts, total_hs_m=2.24))
    payload = build_payload(SPOT, [s], fetched_at="x", now=datetime(2026, 7, 19, tzinfo=UTC))
    entry = payload["hours"][0]
    # 1.62 m of partitions against a 2.24 m sea: 73% of the height, and since energy
    # goes as H^2, only ~53% of the energy is in a partition the transform can see
    assert entry["closure"] == 0.73


def test_closure_omitted_when_the_source_gives_no_total():
    """Older captures have no wave_height for the hour - omit the key rather than
    publishing a null that reads like 'measured, and it was nothing'."""
    s = scored(9, 40)
    s = replace(s, hour=replace(s.hour, partitions=(SWELL,), total_hs_m=None))
    payload = build_payload(SPOT, [s], fetched_at="x", now=datetime(2026, 7, 19, tzinfo=UTC))
    assert "closure" not in payload["hours"][0]


def test_closure_is_one_when_partitions_are_the_whole_sea():
    s = scored(9, 40)
    s = replace(s, hour=replace(s.hour, partitions=(SWELL,), total_hs_m=1.0))
    payload = build_payload(SPOT, [s], fetched_at="x", now=datetime(2026, 7, 19, tzinfo=UTC))
    assert payload["hours"][0]["closure"] == 1.0


def test_confidence_keyed_on_lead_days_not_list_position():
    """Dream review 2026-08-05: _horizon_ceiling is a claim about model skill at a lead
    time, but the published day list has holes by construction - _covers_day drops any day
    the model half-covers. Keyed on list position, one dropped mid-series day promoted
    every later day a whole tier: a day-10, GFS-Wave-only forecast shipped as 0.85 "high"
    instead of 0.4 "low"."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(SPOT.timezone)
    base = scored(0, 40)
    start = datetime(2026, 7, 18, 21, tzinfo=UTC)  # local midnight - day 0 is 2026-07-19
    hours = []
    for i in range(24 * 11):  # local days 0..10, hourly
        t = start + timedelta(hours=i)
        local = t.astimezone(tz)
        if local.date().isoformat() == "2026-07-20" and local.hour > 12:
            continue  # cut day 1 short so _covers_day drops it
        hours.append(replace(base, hour=replace(base.hour, time=t)))
    payload = build_payload(SPOT, hours, fetched_at="t", now=start + timedelta(hours=6))
    days = {d["date"]: d for d in payload["days"]}

    assert "2026-07-20" not in days  # the half-covered day is gone...
    # ...and its absence must not promote the days behind it: lead 10 is the
    # GFS-Wave-only tier no matter where the day lands in the list.
    assert days["2026-07-29"]["confidence_score"] == 0.4
    assert days["2026-07-29"]["confidence"] == "low"
    assert days["2026-07-28"]["confidence_score"] == 0.85  # lead 9 keeps the mid tier


# --- per-hour provenance, published as one boundary stamp (2026-08-21 proposal) ---


def test_merge_models_reports_which_hours_came_from_the_tail():
    from rosa_pipeline.extract import _merge_models

    hourly = {
        "time": ["2026-08-23T00:00", "2026-08-23T01:00", "2026-08-23T02:00"],
        "wave_height_marine_best_match": [1.0, None, None],
        "wave_height_ncep_gfswave016": [9.0, 2.0, 3.0],
    }
    merged, from_tail = _merge_models(hourly)
    assert merged["wave_height"] == [1.0, 2.0, 3.0]  # unchanged merge
    assert from_tail == [False, True, True]


def test_merge_models_calls_a_single_model_response_all_best_match():
    from rosa_pipeline.extract import _merge_models

    hourly = {"time": ["2026-08-23T00:00", "2026-08-23T01:00"], "wave_height": [1.0, 2.0]}
    merged, from_tail = _merge_models(hourly)
    assert merged is hourly  # passthrough preserved
    assert from_tail == [False, False]


def test_tail_from_marks_the_first_tail_hour_and_is_none_without_one():
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo

    from rosa_pipeline.publish import _tail_from

    tz = ZoneInfo("UTC")

    class _H:
        def __init__(self, t, tail):
            self.time = t
            self.from_tail = tail

    class _S:
        def __init__(self, h):
            self.hour = h

    t0 = datetime(2026, 9, 2, 0, tzinfo=UTC)
    hours = [_S(_H(t0.replace(hour=h), h >= 2)) for h in range(4)]
    assert _tail_from(hours, tz) == "2026-09-02T02:00+00:00"
    assert _tail_from([_S(_H(t0, False))], tz) is None
    assert _tail_from([], tz) is None


def test_model_run_is_published_only_when_the_source_knew_it():
    hours = [scored(9, 42)]
    payload = build_payload(SPOT, hours, fetched_at="t", now=hours[0].hour.time)
    assert "model_run" not in payload  # OM arm / fixtures: omitted, not null
    run = {"gfswave": "2026-09-08T06:00+00:00", "ecmwf": None}
    payload = build_payload(SPOT, hours, fetched_at="t", now=hours[0].hour.time, model_run=run)
    assert payload["model_run"] == run
