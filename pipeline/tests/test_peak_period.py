"""Peak period is carried through extract → payload as an additive display field."""

from __future__ import annotations

from rosa_pipeline.extract import extract_hours
from rosa_pipeline.fetch import RawForecast

TIMES = ["2026-07-21T00:00", "2026-07-21T01:00"]
N = len(TIMES)


def _marine(peak_swell: float | None) -> dict:
    nulls = [None] * N
    hourly = {
        "time": TIMES,
        "wave_height": [1.0] * N,
        "wave_direction": [270] * N,
        "wave_period": [8.0] * N,
        "wave_peak_period": [12.0] * N,
        "swell_wave_height": [0.8] * N,
        "swell_wave_direction": [270] * N,
        "swell_wave_period": [9.0] * N,
        "wind_wave_height": [0.3] * N,
        "wind_wave_direction": [300] * N,
        "wind_wave_period": [5.0] * N,
        "wind_wave_peak_period": [6.0] * N,
        # secondary/tertiary present but empty (no peak column exists for them)
        "secondary_swell_wave_height": nulls,
        "secondary_swell_wave_direction": nulls,
        "secondary_swell_wave_period": nulls,
        "tertiary_swell_wave_height": nulls,
        "tertiary_swell_wave_direction": nulls,
        "tertiary_swell_wave_period": nulls,
        "sea_surface_temperature": [28.0] * N,
    }
    if peak_swell is not None:
        hourly["swell_wave_peak_period"] = [peak_swell] * N
    return {"hourly": hourly}


def _weather() -> dict:
    return {
        "hourly": {
            "time": TIMES,
            "wind_speed_10m": [10.0] * N,
            "wind_direction_10m": [90] * N,
            "wind_gusts_10m": [14.0] * N,
        }
    }


def test_peak_period_carried_onto_partitions() -> None:
    raw = RawForecast(fetched_at="x", marine=_marine(11.0), weather=_weather())
    hour = extract_hours(raw)[0]
    swell = next(p for p in hour.partitions if p.kind == "swell")
    wind = next(p for p in hour.partitions if p.kind == "wind")
    assert swell.period_s == 9.0 and swell.peak_period_s == 11.0  # mean unchanged, peak added
    assert wind.peak_period_s == 6.0


def test_missing_peak_column_is_none_not_error() -> None:
    raw = RawForecast(fetched_at="x", marine=_marine(None), weather=_weather())
    hour = extract_hours(raw)[0]
    swell = next(p for p in hour.partitions if p.kind == "swell")
    assert swell.period_s == 9.0 and swell.peak_period_s is None  # graceful


def test_tide_carried_onto_hours() -> None:
    marine = _marine(11.0)
    marine["hourly"]["sea_level_height_msl"] = [0.5, 1.2]  # Stage 2D
    raw = RawForecast(fetched_at="x", marine=marine, weather=_weather())
    assert [h.tide_m for h in extract_hours(raw)] == [0.5, 1.2]


def test_missing_tide_column_is_none() -> None:
    raw = RawForecast(fetched_at="x", marine=_marine(11.0), weather=_weather())
    assert all(h.tide_m is None for h in extract_hours(raw))
