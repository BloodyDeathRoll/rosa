"""DWD GWAM peak periods (docs/rosa-peak-period-plan.md, plan A): parse, plan, join.

Fixtures: three real DWD files captured 2026-08-26 (00Z run, ppts f000/f003, ppww f000)
in tests/fixtures/blend - global fields, bz2 as served. Nothing touches the network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from rosa_pipeline.blend import GfsSea, _tp_at, compose_raw
from rosa_pipeline.extract import extract_hours
from rosa_pipeline.gwam import (
    PARAMS,
    GwamFixtureSource,
    GwamSource,
    GwamStep,
    file_url,
    parse_points,
    pick_cycle,
)

FIX = Path(__file__).parent / "fixtures" / "blend"
CYCLE = datetime(2026, 8, 14, 0, tzinfo=UTC)
BEIT_YANAI = (32.3817, 34.8035)
MIDIGAMA = (-5.9, 80.6)  # Sri Lanka, Indian Ocean groundswell
BAVARIA = (48.0, 10.0)  # no wet cell within reach


def test_pick_cycle_is_00_or_12z_behind_the_publish_lag():
    # measured 2026-08-26: the 00Z run lands ~03:39Z, the 12Z run ~15:39Z
    assert pick_cycle(datetime(2026, 8, 26, 8, 20, tzinfo=UTC)) == datetime(
        2026, 8, 26, 0, tzinfo=UTC
    )
    assert pick_cycle(datetime(2026, 8, 26, 15, 50, tzinfo=UTC)) == datetime(
        2026, 8, 26, 0, tzinfo=UTC
    )  # 12Z not ready until ~15:39Z + lag
    assert pick_cycle(datetime(2026, 8, 26, 20, 20, tzinfo=UTC)) == datetime(
        2026, 8, 26, 12, tzinfo=UTC
    )
    assert pick_cycle(datetime(2026, 8, 26, 2, 20, tzinfo=UTC)) == datetime(
        2026, 8, 25, 12, tzinfo=UTC
    )


def test_file_url_matches_the_dwd_layout():
    assert file_url(datetime(2026, 8, 26, 0, tzinfo=UTC), "ppts", 24) == (
        "https://opendata.dwd.de/weather/maritime/wave_models/gwam/grib/00/ppts/"
        "GWAM_PPTS_2026082600_024.grib2.bz2"
    )


def test_parse_points_reads_bz2_global_field_at_nearest_wet_cell():
    data = (FIX / "gwam_ppts_f000.grib2.bz2").read_bytes()
    assert data[:3] == b"BZh"  # as served; the parser decodes it
    med, sl, land = parse_points(data, [BEIT_YANAI, MIDIGAMA, BAVARIA])
    assert med is not None and 2 < med < 12  # Med summer swell
    assert sl is not None and 10 < sl < 22  # Indian Ocean groundswell peak
    assert land is None  # nothing wet within NEAREST_MAX_DEG of Bavaria


def test_fixture_source_assembles_steps_per_point():
    [series] = GwamFixtureSource(FIX, cycle=CYCLE).fetch_series([BEIT_YANAI])
    assert [s.time for s in series] == [CYCLE, CYCLE + timedelta(hours=3)]
    assert series[0].swell_tp is not None and series[0].windsea_tp is not None
    assert series[1].windsea_tp is None  # no ppww f003 in the fixture - never invented


def test_live_source_probes_then_fetches_both_params(monkeypatch):
    """The cycle probe runs alone and drops back 12 h on a miss; every (param, step)
    then goes through the pool; a bad file costs its step only."""
    from rosa_pipeline import gwam as gwam_mod

    grib = (FIX / "gwam_ppts_f000.grib2.bz2").read_bytes()
    asked: list[tuple[datetime, str, int]] = []
    fresh = datetime(2026, 8, 26, 12, tzinfo=UTC)

    class Canned(GwamSource):
        def _get(self, client, cycle, param, step):
            asked.append((cycle, param, step))
            if cycle == fresh:
                return None  # not published yet
            if step == 6:
                return b"BZhjunk"  # unreadable - must cost only this step
            return grib

    monkeypatch.setattr(gwam_mod, "pick_cycle", lambda now: fresh)
    [series] = Canned(steps=(0, 3, 6)).fetch_series([BEIT_YANAI])
    assert asked[0] == (fresh, "ppts", 0)
    assert asked[1] == (fresh - timedelta(hours=12), "ppts", 0)
    assert {(p, s) for _, p, s in asked[1:]} == {(p, s) for s in (0, 3, 6) for p in PARAMS}
    assert [s.time for s in series] == [
        fresh - timedelta(hours=12) + timedelta(hours=h) for h in (0, 3)
    ]
    assert all(s.swell_tp is not None and s.windsea_tp is not None for s in series)


def test_tp_at_interpolates_only_between_close_steps():
    t0 = CYCLE
    series = [
        GwamStep(t0, 10.0, 4.0),
        GwamStep(t0 + timedelta(hours=3), 13.0, None),
        GwamStep(t0 + timedelta(hours=12), 16.0, 5.0),
    ]
    assert _tp_at(series, t0, "swell_tp") == 10.0  # exact step
    assert _tp_at(series, t0 + timedelta(hours=1), "swell_tp") == 11.0  # linear
    assert _tp_at(series, t0 + timedelta(hours=1), "windsea_tp") is None  # one side None
    assert _tp_at(series, t0 + timedelta(hours=6), "swell_tp") is None  # 9 h gap
    assert _tp_at(series, t0 + timedelta(hours=13), "swell_tp") is None  # past the end
    assert _tp_at(series, t0 - timedelta(hours=1), "swell_tp") is None  # before the start
    assert _tp_at([], t0, "swell_tp") is None


def _gfs(t: datetime, **fields) -> GfsSea:
    base = {"swh": 1.0, "perpw": 8.0, "dirpw": 270.0}
    base.update(fields)
    return GfsSea(time=t, fields=base)


def _aux(times):
    iso = [t.strftime("%Y-%m-%dT%H:%M") for t in times]
    n = len(iso)
    return (
        {
            "hourly": {
                "time": iso,
                "wind_speed_10m": [10.0] * n,
                "wind_direction_10m": [90.0] * n,
                "wind_gusts_10m": [12.0] * n,
            }
        },
        {
            "hourly": {
                "time": iso,
                "sea_surface_temperature": [28.0] * n,
                "sea_level_height_msl": [0.1] * n,
            }
        },
    )


def test_compose_puts_peaks_only_under_published_partitions():
    t = CYCLE
    tp = [GwamStep(t, 12.5, 4.5)]
    # a swell partition and a wind sea -> both peaks land
    raw = compose_raw(
        [_gfs(t, swell1_h=0.8, swell1_p=9.0, swell1_d=290.0, windsea_h=0.3)],
        [],
        *_aux([t]),
        "x",
        tp=tp,
    )
    h = raw.marine["hourly"]
    assert h["swell_wave_peak_period"] == [12.5]
    assert h["wind_wave_peak_period"] == [4.5]
    assert "secondary_swell_wave_peak_period" not in h  # never had one on either arm
    # no wind sea published this hour -> its peak is dropped, not attached to nothing
    raw = compose_raw([_gfs(t, swell1_h=0.8)], [], *_aux([t]), "x", tp=tp)
    h = raw.marine["hourly"]
    assert h["swell_wave_peak_period"] == [12.5]
    assert h["wind_wave_peak_period"] == [None]
    # no GWAM at all -> the pre-plan shape, both None
    h = compose_raw([_gfs(t, swell1_h=0.8, windsea_h=0.3)], [], *_aux([t]), "x").marine["hourly"]
    assert h["swell_wave_peak_period"] == [None] and h["wind_wave_peak_period"] == [None]


def test_offline_end_to_end_primary_swell_carries_a_peak(monkeypatch):
    """The fixture replay reaches extract with a peak on the primary swell for the hours
    GWAM covers, and the partition keys on it (peak_period_s set, mean untouched)."""
    from rosa_pipeline.blend import BlendedSource, GfsFullFixtureSource, fixture_aux_many

    src = BlendedSource(
        gfs=GfsFullFixtureSource(FIX, cycle=CYCLE),
        aux=lambda coords: fixture_aux_many(coords, FIX),
        tp=GwamFixtureSource(FIX, cycle=CYCLE),
    )
    [raw] = src.fetch_many([BEIT_YANAI])
    hours = extract_hours(raw)
    covered = [h for h in hours if h.time <= CYCLE + timedelta(hours=3)]
    swells = [p for h in covered for p in h.partitions if p.kind == "swell"]
    assert swells and all(p.peak_period_s is not None for p in swells)
    assert all(p.peak_period_s != p.period_s for p in swells)  # a real second number
    later = [p for h in hours if h.time > CYCLE + timedelta(hours=3) for p in h.partitions]
    assert later and all(p.peak_period_s is None for p in later)  # never extrapolated
