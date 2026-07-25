"""Stage 3b - spectral-lite pure functions (missed-swell guard, consistency proxy,
parametric spread) and their wiring through extract (join + agreement) and publish."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rosa_pipeline.extract import extract_hours
from rosa_pipeline.fetch import RawForecast
from rosa_pipeline.models import SpectralSea, Spot, SwellPartition
from rosa_pipeline.publish import build_payload
from rosa_pipeline.score import score_hour
from rosa_pipeline.spectral import (
    consistency_score,
    missed_swells,
    parametric_spread_deg,
)

T0 = datetime(2026, 7, 22, 0, 0, tzinfo=UTC)


def _sea(**kw) -> SpectralSea:
    return SpectralSea(time=T0, **kw)


def _swell(h: float, t: float, d: float = 270.0, kind: str = "swell", peak=None):
    return SwellPartition(height_m=h, period_s=t, direction_deg=d, kind=kind, peak_period_s=peak)


# --- missed-swell guard ---


def test_missed_swell_surfaces_unaccounted_band() -> None:
    sea = _sea(bands=(("h1417", 0.8),))
    (m,) = missed_swells(sea, partitions=())
    assert (m.period_lo_s, m.period_hi_s) == (14.0, 17.0)
    assert abs(m.height_m - 0.8) < 1e-9


def test_missed_swell_suppressed_by_matching_partition() -> None:
    # partition peak 15 s accounts for the 14-17 s band
    sea = _sea(bands=(("h1417", 0.8),))
    assert missed_swells(sea, (_swell(0.8, 11.0, peak=15.0),)) == []


def test_missed_swell_pad_credits_boundary_partition() -> None:
    # a 13.5 s partition sits within the 1 s pad of the 14-17 s band edge
    sea = _sea(bands=(("h1417", 0.8),))
    assert missed_swells(sea, (_swell(0.8, 13.5),)) == []


def test_missed_swell_residual_is_rms() -> None:
    # band 1.0 m, partition 0.6 m in-band → residual sqrt(1 - 0.36) = 0.8
    sea = _sea(bands=(("h1721", 1.0),))
    (m,) = missed_swells(sea, (_swell(0.6, 18.0),))
    assert abs(m.height_m - 0.8) < 0.01


def test_missed_swell_ignores_noise_bands() -> None:
    # below MISSED_MIN_HS_M - spectral noise, not a missed swell
    sea = _sea(bands=(("h2530", 0.2),))
    assert missed_swells(sea, ()) == []


# --- consistency proxy ---


def test_consistency_narrow_swell_scores_high() -> None:
    # old clean groundswell: the three periods converge
    assert consistency_score(_sea(pp1d=14.5, mwp=13.3, mp2=13.0)) == 100


def test_consistency_broad_windsea_scores_low() -> None:
    # wide windsea: Tp/Tm02 = 1.5, Tm-1,0/Tm02 = 1.17
    assert consistency_score(_sea(pp1d=9.0, mwp=7.0, mp2=6.0)) == 0


def test_consistency_mid_spectrum_scores_between() -> None:
    score = consistency_score(_sea(pp1d=12.0, mwp=9.7, mp2=9.0))
    assert score is not None and 20 < score < 80


def test_consistency_none_without_all_periods() -> None:
    assert consistency_score(_sea(pp1d=12.0, mwp=9.7)) is None


# --- parametric spread ---


def test_parametric_spread_by_class() -> None:
    assert parametric_spread_deg(_swell(1.0, 5.0, kind="wind")) == 35.0
    assert parametric_spread_deg(_swell(1.0, 8.0)) == 25.0
    assert parametric_spread_deg(_swell(1.0, 12.0)) == 20.0
    assert parametric_spread_deg(_swell(1.0, 12.0, peak=16.0)) == 24.0  # peak wins


# --- extract join + agreement ---


def _raw(n_hours: int = 2) -> RawForecast:
    times = [(T0 + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(n_hours)]
    marine = {
        "hourly": {
            "time": times,
            "wave_height": [1.0] * n_hours,
            "wave_direction": [270.0] * n_hours,
            "wave_period": [8.0] * n_hours,
            "wind_wave_height": [None] * n_hours,
            "wind_wave_direction": [None] * n_hours,
            "wind_wave_period": [None] * n_hours,
            "swell_wave_height": [1.0] * n_hours,
            "swell_wave_direction": [270.0] * n_hours,
            "swell_wave_period": [8.0] * n_hours,
            "secondary_swell_wave_height": [None] * n_hours,
            "secondary_swell_wave_direction": [None] * n_hours,
            "secondary_swell_wave_period": [None] * n_hours,
            "tertiary_swell_wave_height": [None] * n_hours,
            "tertiary_swell_wave_direction": [None] * n_hours,
            "tertiary_swell_wave_period": [None] * n_hours,
            "sea_surface_temperature": [25.0] * n_hours,
        }
    }
    weather = {
        "hourly": {
            "time": times,
            "wind_speed_10m": [10.0] * n_hours,
            "wind_direction_10m": [90.0] * n_hours,
            "wind_gusts_10m": [12.0] * n_hours,
        }
    }
    ensemble = {
        "hourly": {
            "time": times,
            "wave_height_ewam": [1.0] * n_hours,
            "wave_height_gwam": [1.0] * n_hours,
        }
    }
    return RawForecast(fetched_at="2026-07-22T00:00:00+00:00", marine=marine,
                       weather=weather, ensemble=ensemble)


def test_extract_joins_nearest_spectral_within_tolerance() -> None:
    spectral = [_sea(swh=1.0, mwp=7.0)]
    h0, h1 = extract_hours(_raw(2), spectral=spectral)
    assert h0.spectral is spectral[0]  # exact hour
    assert h1.spectral is spectral[0]  # 1 h gap - within the 3 h join tolerance


def test_extract_leaves_spectral_none_beyond_tolerance() -> None:
    far = [SpectralSea(time=T0 + timedelta(hours=12), swh=1.0)]
    h0, _h1 = extract_hours(_raw(2), spectral=far)
    assert h0.spectral is None


def test_ecmwf_swh_joins_agreement_pool() -> None:
    without = extract_hours(_raw(1))[0]
    assert without.n_models == 2
    # a third, agreeing member tightens nothing but must be counted
    with_member = extract_hours(_raw(1), spectral=[_sea(swh=1.0)])[0]
    assert with_member.n_models == 3
    assert with_member.agreement_score == 1.0
    # a wildly disagreeing ECMWF pulls agreement down
    disagree = extract_hours(_raw(1), spectral=[_sea(swh=3.0)])[0]
    assert disagree.agreement_score is not None
    assert disagree.agreement_score < with_member.agreement_score


# --- publish rendering ---

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


def test_publish_renders_spectral_block_and_spread() -> None:
    spectral = [
        _sea(swh=1.0, mwd=280.0, mwp=13.3, pp1d=14.5, mp2=13.0, bands=(("h1417", 0.8),))
    ]
    hours = extract_hours(_raw(2), spectral=spectral)
    scored = [score_hour(SPOT, h, None) for h in hours]
    payload = build_payload(SPOT, scored, fetched_at="2026-07-22T00:00:00+00:00", now=T0)

    hour = payload["hours"][0]
    assert hour["spectral"]["consistency"] == 100
    # the 8 s partition can't account for the 14-17 s band → missed swell surfaced
    (missed,) = hour["spectral"]["missed"]
    assert missed["t"] == [14.0, 17.0]
    assert missed["h"] == 0.8
    assert missed["energy_kw"] > 0
    # every published partition carries its modeled spread
    assert all(s["spread"] > 0 for s in hour["swells"])
    assert payload["spectral_meta"]["member"] == "ecmwf-ifs-0p25 (open data)"
    assert payload["spectral_meta"]["spread"] == "parametric (modeled)"
    assert "ECMWF" in payload["attribution"]


def test_publish_omits_spectral_when_member_absent() -> None:
    hours = extract_hours(_raw(2))
    scored = [score_hour(SPOT, h, None) for h in hours]
    payload = build_payload(SPOT, scored, fetched_at="2026-07-22T00:00:00+00:00", now=T0)
    assert "spectral" not in payload["hours"][0]
    assert payload["spectral_meta"]["member"] is None
    assert "ECMWF" not in payload["attribution"]
