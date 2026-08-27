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


def test_peak_below_mean_is_discarded_as_a_join_mismatch() -> None:
    """Tp < Tm is spectrally impossible - it means the cross-model GWAM join stamped
    another sea's peak on this partition (2026-08-27: Tp 2.2 s on a 1.31 m / 7.8 s sea).
    The partition must fall back to its mean period, not carry the impostor."""
    raw = RawForecast(fetched_at="x", marine=_marine(4.0), weather=_weather())  # Tm is 9.0
    hour = extract_hours(raw)[0]
    swell = next(p for p in hour.partitions if p.kind == "swell")
    assert swell.period_s == 9.0 and swell.peak_period_s is None


def _multi_model(*, gwam_peak: float | None = 13.0, bm_hours: int = N) -> dict:
    """A three-model marine response shaped like the live one: best_match carries the sea
    state but no peak period (meteofrance_wave publishes none outside Europe), GFS-Wave
    carries the horizon tail, gwam carries the peak period."""
    nulls = [None] * N
    bm = lambda v: [v] * bm_hours + [None] * (N - bm_hours)  # noqa: E731
    hourly = {
        "time": TIMES,
        "wave_height_marine_best_match": bm(1.0),
        "wave_direction_marine_best_match": bm(270),
        "wave_period_marine_best_match": bm(8.0),
        "swell_wave_height_marine_best_match": bm(0.8),
        "swell_wave_direction_marine_best_match": bm(270),
        "swell_wave_period_marine_best_match": bm(9.0),
        "swell_wave_peak_period_marine_best_match": nulls,
        "wave_height_ncep_gfswave016": [2.0] * N,
        "wave_direction_ncep_gfswave016": [200] * N,
        "wave_period_ncep_gfswave016": [7.0] * N,
        "swell_wave_height_ncep_gfswave016": [1.9] * N,
        "swell_wave_direction_ncep_gfswave016": [200] * N,
        "swell_wave_period_ncep_gfswave016": [7.5] * N,
        "swell_wave_peak_period_ncep_gfswave016": nulls,
        # gwam disagrees on every field, so any leak shows up immediately
        "wave_height_gwam": [3.0] * N,
        "wave_direction_gwam": [100] * N,
        "wave_period_gwam": [4.0] * N,
        "swell_wave_height_gwam": [3.3] * N,
        "swell_wave_direction_gwam": [100] * N,
        "swell_wave_period_gwam": [4.4] * N,
        "swell_wave_peak_period_gwam": [gwam_peak] * N,
    }
    # the partitions extract always reads - present under every model, as in the live response
    for suffix, empty in (
        ("marine_best_match", nulls),
        ("ncep_gfswave016", nulls),
        ("gwam", nulls),
    ):
        for prefix in ("secondary_swell_wave", "tertiary_swell_wave"):
            for field in ("height", "direction", "period"):
                hourly[f"{prefix}_{field}_{suffix}"] = empty
        hourly[f"wind_wave_height_{suffix}"] = [0.3] * N
        hourly[f"wind_wave_direction_{suffix}"] = [300] * N
        hourly[f"wind_wave_period_{suffix}"] = [5.0] * N
        hourly[f"sea_surface_temperature_{suffix}"] = [28.0] * N
    hourly["wind_wave_peak_period_marine_best_match"] = nulls
    hourly["wind_wave_peak_period_ncep_gfswave016"] = nulls
    hourly["wind_wave_peak_period_gwam"] = [6.5] * N
    return {"hourly": hourly}


def test_peak_period_falls_through_to_gwam() -> None:
    """The whole point of adding gwam: outside Europe nothing else publishes a Tp."""
    raw = RawForecast(fetched_at="x", marine=_multi_model(), weather=_weather())
    swell = next(p for p in extract_hours(raw)[0].partitions if p.kind == "swell")
    assert swell.peak_period_s == 13.0


def test_gwam_supplies_only_the_peak_period() -> None:
    """The single-model-per-hour rule still holds for everything that feeds the physics -
    a Tp from another model is safe, an Hs or a direction from another model is not."""
    raw = RawForecast(fetched_at="x", marine=_multi_model(), weather=_weather())
    swell = next(p for p in extract_hours(raw)[0].partitions if p.kind == "swell")
    assert swell.height_m == 0.8  # best_match, not gwam's 3.3 or GFS-Wave's 1.9
    assert swell.direction_deg == 270  # not gwam's 100
    assert swell.period_s == 9.0  # not gwam's 4.4


def test_gwam_does_not_become_the_horizon_tail() -> None:
    """gwam stops ~2 days short of best_match, so GFS-Wave must still own the tail hours
    even though gwam has data there."""
    raw = RawForecast(fetched_at="x", marine=_multi_model(bm_hours=1), weather=_weather())
    tail = next(p for p in extract_hours(raw)[1].partitions if p.kind == "swell")
    assert tail.height_m == 1.9 and tail.direction_deg == 200  # GFS-Wave
    assert tail.peak_period_s == 13.0  # gwam still fills the Tp it does cover


def test_two_model_response_without_gwam_still_merges() -> None:
    """Captured fixtures predate gwam - they must keep merging exactly as before."""
    marine = _multi_model()
    marine["hourly"] = {k: v for k, v in marine["hourly"].items() if not k.endswith("_gwam")}
    raw = RawForecast(fetched_at="x", marine=marine, weather=_weather())
    swell = next(p for p in extract_hours(raw)[0].partitions if p.kind == "swell")
    assert swell.height_m == 0.8 and swell.peak_period_s is None


def test_tide_carried_onto_hours() -> None:
    marine = _marine(11.0)
    marine["hourly"]["sea_level_height_msl"] = [0.5, 1.2]  # Stage 2D
    raw = RawForecast(fetched_at="x", marine=marine, weather=_weather())
    assert [h.tide_m for h in extract_hours(raw)] == [0.5, 1.2]


def test_missing_tide_column_is_none() -> None:
    raw = RawForecast(fetched_at="x", marine=_marine(11.0), weather=_weather())
    assert all(h.tide_m is None for h in extract_hours(raw))
