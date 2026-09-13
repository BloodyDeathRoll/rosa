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


class _FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


def test_pacer_spaces_calls_to_the_per_minute_cap():
    ft = _FakeTime()
    pacer = gfsatmos.Pacer(per_min=40, clock=ft.clock, sleep=ft.sleep)
    for _ in range(4):
        pacer.wait()
    # first call goes at once, every later one waits its 1.5 s slot
    assert ft.slept == pytest.approx([1.5, 1.5, 1.5])
    # time that already passed counts toward the next slot
    ft.now += 10.0
    pacer.wait()
    assert ft.slept == pytest.approx([1.5, 1.5, 1.5])


def test_pacer_holds_the_cap_across_threads():
    import threading

    lock = threading.Lock()
    ft = _FakeTime()

    def sleep(s: float) -> None:
        with lock:
            ft.slept.append(s)

    pacer = gfsatmos.Pacer(per_min=60, clock=ft.clock, sleep=sleep)
    threads = [threading.Thread(target=pacer.wait) for _ in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # frozen clock: eight callers get eight distinct 1 s slots, never two at once
    assert sorted(ft.slept) == pytest.approx([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0])


def test_the_live_source_paces_every_nomads_request():
    import httpx

    calls: list[str] = []

    class Counting:
        def __init__(self) -> None:
            self.waits = 0

        def wait(self) -> None:
            self.waits += 1

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(404, content=b"<html>not present</html>")

    pacer = Counting()
    src = gfsatmos.GfsAtmosSource(steps=(0, 3, 6), pacer=pacer)  # type: ignore[arg-type]
    box = Box(bottom=30, top=34, left=33, right=36)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        for step in src.steps:
            assert src._get(client, CYCLE, step, box) is None
    assert pacer.waits == len(calls) == 3


def test_nearest_node_sees_across_greenwich():
    import numpy as np

    def grid(lons: list[float]):
        return np.meshgrid(np.array([50.0, 50.25]), np.array(lons), indexing="ij")

    # a box across 0 deg, in the 0-360 frame NOMADS returns: 359.5 .. 0.5
    glats, glons = grid([359.5, 359.75, 0.0, 0.25, 0.5])
    # 0.05 deg west of Greenwich: the 0.0 node, not 359.75 one 0.2 deg away
    assert gfsatmos.nearest_node(glats, glons, 50.0, -0.05) == (0, 2)
    # a box that starts AT Greenwich still serves a station just west of it
    glats, glons = grid([0.0, 0.25, 0.5])
    assert gfsatmos.nearest_node(glats, glons, 50.0, -0.1) == (0, 0)
    # and a station well off the box is still refused
    assert gfsatmos.nearest_node(glats, glons, 50.0, 1.5) is None
