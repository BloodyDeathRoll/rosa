"""Blended wave source (fetch-plane plan B): GRIB parse, blend math, offline end-to-end.

Fixtures: real captured NOMADS grib-filter boxes + OM weather/marine-light bodies for
Beit Yanai's offshore point (2026-08-14 00Z cycle, steps 0-48). Nothing touches the
network; ``now`` is frozen to the fixture cycle, the e2e-test pattern.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rosa_pipeline.blend import (
    BlendedSource,
    GfsFullFixtureSource,
    GfsSea,
    compose_raw,
    fixture_aux_many,
    parse_gfs_full,
)
from rosa_pipeline.extract import extract_hours
from rosa_pipeline.models import SpectralSea
from rosa_pipeline.publish import build_payload
from rosa_pipeline.score import score_hour
from rosa_pipeline.spots import load_spots

FIX = Path(__file__).parent / "fixtures" / "blend"
SPOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "spots"
CYCLE = datetime(2026, 8, 14, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def spot():
    return load_spots(SPOTS_DIR)["beit-yanai"]


@pytest.fixture(scope="module")
def point(spot):
    return spot.offshore_point


def test_parse_gfs_full_reads_totals_and_partitions(point):
    grib = next(FIX.glob("gfsfull_f000_*.grib2")).read_bytes()
    [sea] = parse_gfs_full(grib, [point], CYCLE)
    assert sea is not None
    f = sea.fields
    assert 0 < f["swh"] < 10
    assert 0 < f["perpw"] < 25
    assert 0 <= f["dirpw"] < 360
    # the Med capture carries windsea + at least the primary swell partition
    assert "windsea_h" in f and "swell1_h" in f


def test_parse_gfs_full_returns_none_far_from_the_box(point):
    grib = next(FIX.glob("gfsfull_f000_*.grib2")).read_bytes()
    [sea] = parse_gfs_full(grib, [(0.0, -140.0)], CYCLE)  # mid-Pacific, not in a Med box
    assert sea is None


def _gfs(t: datetime, **fields) -> GfsSea:
    base = {"swh": 1.0, "perpw": 8.0, "dirpw": 270.0}
    base.update(fields)
    return GfsSea(time=t, fields=base)


def _aux(times: list[datetime]) -> tuple[dict, dict]:
    iso = [t.strftime("%Y-%m-%dT%H:%M") for t in times]
    weather = {
        "hourly": {
            "time": iso,
            "wind_speed_10m": [10.0] * len(iso),
            "wind_direction_10m": [90.0] * len(iso),
            "wind_gusts_10m": [12.0] * len(iso),
        }
    }
    marine = {
        "hourly": {
            "time": iso,
            "sea_surface_temperature": [28.0] * len(iso),
            "sea_level_height_msl": [0.1] * len(iso),
        }
    }
    return weather, marine


def test_compose_blends_totals_and_keeps_partitions_gfs_only():
    t = CYCLE
    sp = SpectralSea(time=t, swh=2.0, mwd=280.0, mwp=9.5, pp1d=12.0)
    raw = compose_raw([_gfs(t, swell1_h=0.8, swell1_p=9.0, swell1_d=290.0)], [sp], *_aux([t]), "x")
    h = raw.marine["hourly"]
    assert h["wave_height"] == [1.5]  # 50/50 of 1.0 and 2.0
    assert h["wave_peak_period"] == [10.0]  # 50/50 of 8 and 12
    assert h["wave_period"] == [9.5]  # ECMWF mwp only - GFS gridded has no total mean
    assert h["swell_wave_height"] == [0.8]  # partitions are GFS's own, never blended
    assert h["sea_surface_temperature"] == [28.0]
    assert h["sea_level_height_msl"] == [0.1]
    # C4: the ensemble carries the RAW GFS member, never the blended total
    assert raw.ensemble["hourly"]["wave_height_ncep_gfswave016"] == [1.0]


def test_compose_direction_blend_is_circular():
    t = CYCLE
    sp = SpectralSea(time=t, swh=1.0, mwd=10.0)
    raw = compose_raw([_gfs(t, dirpw=350.0)], [sp], *_aux([t]), "x")
    assert raw.marine["hourly"]["wave_direction"] == [0.0]  # mean of 350 and 10 wraps


def test_compose_past_ecmwf_horizon_is_gfs_alone():
    # B3: an hour with no ECMWF step within the join tolerance degrades honestly
    t = CYCLE + timedelta(hours=300)
    raw = compose_raw([_gfs(t)], [SpectralSea(time=CYCLE, swh=2.0)], *_aux([t]), "x")
    h = raw.marine["hourly"]
    assert h["wave_height"] == [1.0]  # GFS untouched, not halved
    assert h["wave_period"] == [None]  # no fabricated total mean period


def test_offline_end_to_end_publishes_a_rated_payload(spot, point):
    src = BlendedSource(
        gfs=GfsFullFixtureSource(FIX, cycle=CYCLE),
        aux=lambda coords: fixture_aux_many(coords, FIX),
    )
    [raw] = src.fetch_many([point])
    hours = extract_hours(raw)
    # 5 captured steps (0,6,12,24,48): the two 6 h gaps interpolate to hourly, the
    # 12 h and 24 h gaps are past INTERP_MAX_GAP_H and stay unfilled
    assert len(hours) == 15
    # partitions can drop out between steps in a calm sea (a key missing at either
    # endpoint is never invented for filled hours) - most hours must carry some
    assert sum(1 for h in hours if h.partitions) >= len(hours) // 2
    assert all(h.tide_m is not None for h in hours)  # marine-light joined by timestamp
    scored = [score_hour(spot, h) for h in hours]
    payload = build_payload(spot, scored, fetched_at=raw.fetched_at, now=CYCLE)
    assert payload["spot"]["id"] == "beit-yanai"
    entries = payload["hours"]
    assert entries and all(e["rating"] is not None for e in entries)


def test_interpolation_serves_any_timezone_a_whole_local_day():
    # the Hawaii bug (2026-08-14 smoke): a 3-hourly UTC series has no local-midnight
    # hour at UTC-10, so publish's whole-day filter dropped every day. Interpolated
    # hourly, every timezone finds its 8 three-hourly local hours.
    t0 = CYCLE
    gfs = [_gfs(t0 + timedelta(hours=h)) for h in range(0, 49, 3)]
    raw = compose_raw(gfs, [], *_aux([t0 + timedelta(hours=h) for h in range(49)]), "x")
    times = raw.marine["hourly"]["time"]
    assert len(times) == 49  # hourly, gap-free
    assert times[1] == (t0 + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")


def test_interpolated_direction_wraps_between_steps():
    t0 = CYCLE
    gfs = [_gfs(t0, dirpw=350.0), _gfs(t0 + timedelta(hours=3), dirpw=10.0)]
    raw = compose_raw(gfs, [], *_aux([t0, t0 + timedelta(hours=3)]), "x")
    dirs = raw.marine["hourly"]["wave_direction"]
    # the filled hours cross 0, never averaging to ~180
    assert all(d > 340 or d < 20 for d in dirs)


def test_oisst_fills_sst_over_the_om_value(point):
    # plan C2: the daily OISST value wins; the OM light value is only the fallback
    t = CYCLE
    raw = compose_raw([_gfs(t)], [], *_aux([t]), "x", sst_daily=29.15)
    assert raw.marine["hourly"]["sea_surface_temperature"] == [29.15]
    raw = compose_raw([_gfs(t)], [], *_aux([t]), "x", sst_daily=None)
    assert raw.marine["hourly"]["sea_surface_temperature"] == [28.0]  # OM fallback


def test_oisst_fixture_parses_sane_values(point):
    from rosa_pipeline.oisst import OisstFixtureSource

    [v] = OisstFixtureSource(FIX).fetch([point])
    assert v is not None and 15 < v < 35  # eastern Med in August


def test_oisst_missing_fixture_degrades_to_none(tmp_path, point):
    from rosa_pipeline.oisst import OisstFixtureSource

    assert OisstFixtureSource(tmp_path).fetch([point]) == [None]


def test_own_member_ensemble_yields_agreement_and_dir_span(spot):
    # plan C4: raw GFS totals + the ECMWF spectral member = 2 independent voices;
    # the blended total itself must NOT be a member (it is not independent)
    t = CYCLE
    sp = SpectralSea(time=t, swh=2.0, mwd=280.0)
    raw = compose_raw([_gfs(t, swh=1.0, dirpw=270.0)], [sp], *_aux([t]), "x")
    ens = raw.ensemble["hourly"]
    assert ens["wave_height_ncep_gfswave016"] == [1.0]  # raw GFS, not the 1.5 blend
    hours = extract_hours(raw, spectral=[sp])
    [h] = hours
    assert h.n_models == 2
    assert h.n_dir_members == 2
    assert h.dir_span_deg == 10  # 270 vs 280


def test_blend_is_the_default_wave_source():
    """Plan D3, promoted worldwide 2026-08-26: a bare `run --all` (publish.sh) is the
    blend arm, and OM is the explicit fallback. Pinned so a refactor cannot quietly put
    the fleet back on the per-spot quota."""
    from rosa_pipeline.cli import _build_parser

    args = _build_parser().parse_args(["run", "--all"])
    assert args.wave_source == "blend"
    assert _build_parser().parse_args(["run", "--all", "--wave-source", "om"]).wave_source == "om"


def test_blend_payload_credits_noaa_and_ecmwf(spot, point):
    """The data credit follows the arm: the promoted payload must name NOAA GFS-Wave and
    ECMWF (CC-BY, a legal red line), and keep Open-Meteo for the weather it still serves."""
    src = BlendedSource(
        gfs=GfsFullFixtureSource(FIX, cycle=CYCLE),
        aux=lambda coords: fixture_aux_many(coords, FIX),
    )
    [raw] = src.fetch_many([point])
    scored = [score_hour(spot, h) for h in extract_hours(raw)]
    credit = build_payload(spot, scored, fetched_at=raw.fetched_at, now=CYCLE, wave_source="blend")[
        "attribution"
    ]
    assert "NOAA GFS-Wave" in credit and "ECMWF" in credit and "Open-Meteo" in credit
    om_credit = build_payload(spot, scored, fetched_at=raw.fetched_at, now=CYCLE)["attribution"]
    assert "GFS-Wave" not in om_credit


def test_back_reach_plan_spans_the_previous_day():
    """OPEN-ITEMS 20: the hours before f000 come from the previous cycles' f000/f003,
    back exactly PAST_DAYS, oldest first, and never at or after this cycle's f000."""
    from rosa_pipeline.blend import BACK_REACH_H, back_reach_plan

    plan = back_reach_plan(CYCLE)
    valids = [c + timedelta(hours=s) for c, s in plan]
    assert valids == sorted(valids)
    assert valids[0] == CYCLE - timedelta(hours=BACK_REACH_H)
    assert valids[-1] == CYCLE - timedelta(hours=3)
    assert all(v < CYCLE for v in valids)
    assert len(plan) == BACK_REACH_H // 3
    assert {s for _, s in plan} == {0, 3}


def test_live_source_reaches_back_a_day(point, monkeypatch):
    """The live fetcher asks for the back-reach after each box's forecast steps and the
    series carries the previous day. No network: every request is answered with the
    committed f000 grib, and the cycle is pinned to the fixture's."""
    from rosa_pipeline import blend as blend_mod
    from rosa_pipeline.blend import GfsFullSource

    grib = next(FIX.glob("gfsfull_f000_*.grib2")).read_bytes()
    asked: list[tuple[datetime, int]] = []

    class Canned(GfsFullSource):
        def _get(self, client, cycle, step, box):
            asked.append((cycle, step))
            return grib

    monkeypatch.setattr(blend_mod, "pick_cycle", lambda now: CYCLE)
    [series] = Canned(steps=(0, 3)).fetch_series([point])
    times = sorted(s.time for s in series)
    assert times[0] == CYCLE - timedelta(hours=24)
    assert times[-1] == CYCLE + timedelta(hours=3)
    assert len(times) == 2 + 8  # the two forecast steps + eight back-reach windows
    assert (CYCLE - timedelta(hours=6), 0) in asked
    assert (CYCLE - timedelta(hours=24), 3) in asked
    # the forecast steps are asked first, so a late cycle drops back before any history
    assert asked[0] == (CYCLE, 0)


def test_live_source_fetches_a_box_concurrently(point, monkeypatch):
    """The 1h42m promotion run was 1,032 requests one at a time. After the cycle probe,
    a box's remaining steps go through a pool of NOMADS_WORKERS; the probe itself stays
    alone because it decides the cycle. Observed concurrency, not timing, so no flake."""
    import threading
    import time

    from rosa_pipeline import blend as blend_mod
    from rosa_pipeline.blend import NOMADS_WORKERS, GfsFullSource

    grib = next(FIX.glob("gfsfull_f000_*.grib2")).read_bytes()
    lock = threading.Lock()
    active = 0
    peak = 0
    first_seen_alone = []

    class Canned(GfsFullSource):
        def _get(self, client, cycle, step, box):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                if not first_seen_alone:
                    first_seen_alone.append(active)
            time.sleep(0.02)
            with lock:
                active -= 1
            return grib

    monkeypatch.setattr(blend_mod, "pick_cycle", lambda now: CYCLE)
    [series] = Canned(steps=tuple(range(0, 49, 3))).fetch_series([point])
    assert first_seen_alone == [1]  # the probe ran before anything else was in flight
    assert 2 <= peak <= NOMADS_WORKERS
    assert len(series) == 17 + 8  # every forecast step and every back-reach window landed
