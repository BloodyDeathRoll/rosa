"""The plan C3b A/B member (rosa_pipeline.gfsatmos): raw GFS 0.25 atmos wind at the
coastal stations. Fixtures: two real NOMADS grib-filter responses for the Israel station
box (2026-09-12 00Z, f000/f003, UGRD+VGRD at 10 m), captured through the module's own
filter_url so the replay matches by box key."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rosa_pipeline import gfsatmos
from rosa_pipeline.gfswave import Box, cluster_boxes

FIX = Path(__file__).parent / "fixtures" / "gfsatmos"
LLBG = (32.011, 34.887)
LLHA = (32.809, 35.043)
CYCLE = datetime(2026, 9, 12, 0, tzinfo=UTC)


def test_wind_from_uv_is_speed_and_meteorological_from_bearing():
    assert gfsatmos.wind_from_uv(0.0, -5.0) == pytest.approx((5.0, 0.0))  # blowing S -> from N
    assert gfsatmos.wind_from_uv(-5.0, 0.0) == pytest.approx((5.0, 90.0))  # from E
    assert gfsatmos.wind_from_uv(0.0, 5.0) == pytest.approx((5.0, 180.0))  # from S
    assert gfsatmos.wind_from_uv(5.0, 0.0) == pytest.approx((5.0, 270.0))  # from W
    assert gfsatmos.wind_from_uv(3.0, 4.0)[0] == pytest.approx(5.0)


def test_filter_url_names_the_atmos_dataset_and_only_the_10m_wind():
    url = gfsatmos.filter_url(CYCLE, 123, Box(bottom=30, top=34, left=33, right=36))
    assert url.startswith(gfsatmos.FILTER_URL)
    assert "gfs.20260912%2F00%2Fatmos" in url
    assert "file=gfs.t00z.pgrb2.0p25.f123" in url
    assert "var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on" in url
    assert "toplat=34&leftlon=33&rightlon=36&bottomlat=30" in url


def test_pick_cycle_lags_past_the_last_step_landing():
    # 05:29Z: the 00Z set is not complete yet -> 18Z of the day before
    assert gfsatmos.pick_cycle(datetime(2026, 9, 12, 5, 29, tzinfo=UTC)) == datetime(
        2026, 9, 11, 18, tzinfo=UTC
    )
    assert gfsatmos.pick_cycle(datetime(2026, 9, 12, 5, 31, tzinfo=UTC)) == CYCLE


def test_steps_are_the_blend_arm_shape():
    from rosa_pipeline.blend import BLEND_STEPS

    assert gfsatmos.STEPS == BLEND_STEPS


def test_parse_samples_the_nearest_node_per_station_with_sane_wind():
    grib = next(FIX.glob("gfsatmos_f000_*.grib2")).read_bytes()
    llbg, llha = gfsatmos.parse_grib_points(grib, [LLBG, LLHA], CYCLE)
    assert llbg is not None and llha is not None
    for wp in (llbg, llha):
        assert wp.time == CYCLE and wp.hs is None and wp.tp is None and wp.dir is None
        assert wp.ws is not None and 0.0 <= wp.ws < 30.0
        assert wp.wdir is not None and 0.0 <= wp.wdir < 360.0
    assert llbg != llha  # two stations, two nodes
    # a point outside the box has no node in reach
    [far] = gfsatmos.parse_grib_points(grib, [(38.7, -9.3)], CYCLE)
    assert far is None


def test_fixture_source_replays_by_box_key_and_stamps_valid_from_the_step():
    [(box, _)] = cluster_boxes([LLBG, LLHA])
    assert (FIX / f"gfsatmos_f000_{box.key}.grib2").exists()
    src = gfsatmos.GfsAtmosFixtureSource(FIX, cycle=CYCLE)
    llbg, llha = src.fetch_series([LLBG, LLHA])
    assert [wp.time for wp in llbg] == [CYCLE, CYCLE.replace(hour=3)]
    assert len(llha) == 2
    # a station with no captured box archives nothing, silently - the member is optional
    [none] = src.fetch_series([(38.7, -9.3)])
    assert none == []
