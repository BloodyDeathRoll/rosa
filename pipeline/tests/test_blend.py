"""Blended wave source (fetch-plane plan B): GRIB parse, blend math, offline end-to-end.

Fixtures: real captured NOMADS grib-filter boxes + an OM weather body for Beit Yanai's
offshore point (2026-08-14 00Z cycle, steps 0-48; the marine-light body went with the
leg on 2026-09-12 - tide is the spot's EOT20 constants). Nothing touches the
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
    fixture_weather_many,
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


def _aux(times: list[datetime]) -> dict:
    iso = [t.strftime("%Y-%m-%dT%H:%M") for t in times]
    return {
        "hourly": {
            "time": iso,
            "wind_speed_10m": [10.0] * len(iso),
            "wind_direction_10m": [90.0] * len(iso),
            "wind_gusts_10m": [12.0] * len(iso),
        }
    }


def test_compose_blends_totals_and_keeps_partitions_gfs_only():
    t = CYCLE
    sp = SpectralSea(time=t, swh=2.0, mwd=280.0, mwp=9.5, pp1d=12.0)
    raw = compose_raw([_gfs(t, swell1_h=0.8, swell1_p=9.0, swell1_d=290.0)], [sp], _aux([t]), "x")
    h = raw.marine["hourly"]
    assert h["wave_height"] == [1.5]  # 50/50 of 1.0 and 2.0
    assert h["wave_peak_period"] == [10.0]  # 50/50 of 8 and 12
    assert h["wave_period"] == [9.5]  # ECMWF mwp only - GFS gridded has no total mean
    assert h["swell_wave_height"] == [0.8]  # partitions are GFS's own, never blended
    # no OM marine body on this arm (2026-09-12): SST is the OISST daily value or None,
    # the OM tide column is schema-only and always None - EOT20 owns tide in extract
    assert h["sea_surface_temperature"] == [None]
    assert h["sea_level_height_msl"] == [None]
    # C4: the ensemble carries the RAW GFS member, never the blended total
    assert raw.ensemble["hourly"]["wave_height_ncep_gfswave016"] == [1.0]


def test_compose_direction_blend_is_circular():
    t = CYCLE
    sp = SpectralSea(time=t, swh=1.0, mwd=10.0)
    raw = compose_raw([_gfs(t, dirpw=350.0)], [sp], _aux([t]), "x")
    assert raw.marine["hourly"]["wave_direction"] == [0.0]  # mean of 350 and 10 wraps


def test_compose_past_ecmwf_horizon_is_gfs_alone():
    # B3: an hour with no ECMWF step within the join tolerance degrades honestly
    t = CYCLE + timedelta(hours=300)
    raw = compose_raw([_gfs(t)], [SpectralSea(time=CYCLE, swh=2.0)], _aux([t]), "x")
    h = raw.marine["hourly"]
    assert h["wave_height"] == [1.0]  # GFS untouched, not halved
    assert h["wave_period"] == [None]  # no fabricated total mean period


def test_offline_end_to_end_publishes_a_rated_payload(spot, point):
    src = BlendedSource(
        gfs=GfsFullFixtureSource(FIX, cycle=CYCLE),
        weather=lambda coords: fixture_weather_many(coords, FIX),
    )
    [raw] = src.fetch_many([point])
    # the blend arm's only tide is the spot's committed EOT20 constants (no OM marine
    # body since 2026-09-12) - feed them exactly as cli's `run` does
    from rosa_pipeline.tide import load_constants

    tide_c = load_constants(SPOTS_DIR / "derived" / "tide", spot.id)
    assert tide_c is not None
    hours = extract_hours(raw, tide_constants=tide_c)
    # 5 captured steps (0,6,12,24,48): the two 6 h gaps interpolate to hourly, the
    # 12 h and 24 h gaps are past INTERP_MAX_GAP_H and stay unfilled
    assert len(hours) == 15
    # partitions can drop out between steps in a calm sea (a key missing at either
    # endpoint is never invented for filled hours) - most hours must carry some
    assert sum(1 for h in hours if h.partitions) >= len(hours) // 2
    assert all(h.tide_m is not None for h in hours)  # EOT20, synthesised per hour
    # ...and without constants the arm has no tide at all - nothing stands in
    assert all(h.tide_m is None for h in extract_hours(raw))
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
    raw = compose_raw(gfs, [], _aux([t0 + timedelta(hours=h) for h in range(49)]), "x")
    times = raw.marine["hourly"]["time"]
    assert len(times) == 49  # hourly, gap-free
    assert times[1] == (t0 + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")


def test_interpolated_direction_wraps_between_steps():
    t0 = CYCLE
    gfs = [_gfs(t0, dirpw=350.0), _gfs(t0 + timedelta(hours=3), dirpw=10.0)]
    raw = compose_raw(gfs, [], _aux([t0, t0 + timedelta(hours=3)]), "x")
    dirs = raw.marine["hourly"]["wave_direction"]
    # the filled hours cross 0, never averaging to ~180
    assert all(d > 340 or d < 20 for d in dirs)


def test_sst_is_oisst_or_blank_never_an_om_number(point):
    # plan C2: the daily OISST value fills every hour. Since 2026-09-12 there is no OM
    # fallback (the marine-light leg is gone), so a missing OISST value is None - the
    # payload shows blank, never a number from a source this arm no longer fetches
    t = CYCLE
    raw = compose_raw([_gfs(t)], [], _aux([t]), "x", sst_daily=29.15)
    assert raw.marine["hourly"]["sea_surface_temperature"] == [29.15]
    raw = compose_raw([_gfs(t)], [], _aux([t]), "x", sst_daily=None)
    assert raw.marine["hourly"]["sea_surface_temperature"] == [None]
    # and the OM tide column is carried as None for the schema, never a value
    assert raw.marine["hourly"]["sea_level_height_msl"] == [None]


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
    raw = compose_raw([_gfs(t, swh=1.0, dirpw=270.0)], [sp], _aux([t]), "x")
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
    """The data credit follows the arm: names NOAA GFS-Wave always, ECMWF only when the
    spectral member was present, and keeps Open-Meteo for the weather it still serves."""
    src = BlendedSource(
        gfs=GfsFullFixtureSource(FIX, cycle=CYCLE),
        weather=lambda coords: fixture_weather_many(coords, FIX),
    )
    [raw] = src.fetch_many([point])
    scored = [score_hour(spot, h) for h in extract_hours(raw)]
    credit = build_payload(spot, scored, fetched_at=raw.fetched_at, now=CYCLE, wave_source="blend")[
        "attribution"
    ]
    # This fixture has no ECMWF spectral member and no GWAM peak periods, so the
    # dynamic attribution correctly omits both credits.
    assert "NOAA GFS-Wave" in credit and "Open-Meteo" in credit
    assert "ECMWF" not in credit
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


# --- the duplicated wind sea (2026-08-27) -----------------------------------------------
# GFS-Wave writes some cells' single wave system into BOTH shww and a shts slot; the
# transform then breaks one wave twice. Numbers below are the real 00Z f078 values at the
# grid cell serving Poleg (32.50N 34.75E): swh 1.780, shww 1.740/8.39s/280.49,
# shts1 1.830/8.38s/281.89 - which RMS to 2.52 m against a 1.78 m total.
_DUP = {
    "swh": 1.78,
    "perpw": 8.38,
    "dirpw": 286.2,
    "windsea_h": 1.74,
    "windsea_p": 8.39,
    "windsea_d": 280.49,
    "swell1_h": 1.83,
    "swell1_p": 8.38,
    "swell1_d": 281.89,
}


def test_duplicated_windsea_is_dropped_and_the_swell_kept():
    from rosa_pipeline.blend import drop_duplicate_windsea

    out = drop_duplicate_windsea(_DUP)
    assert "windsea_h" not in out
    assert out["swell1_h"] == 1.83  # the swell copy is kept verbatim, never rescaled
    rms = out["swell1_h"] ** 2
    assert rms**0.5 / out["swh"] < 1.1  # partitions now close against the source's own total


@pytest.mark.parametrize(
    "field,value",
    [
        ("windsea_d", 320.0),  # 38 deg off - a real crossed sea
        ("windsea_p", 4.9),  # 42% shorter - a young sea under an old swell
    ],
)
def test_a_genuinely_bimodal_sea_keeps_both_partitions(field, value):
    from rosa_pipeline.blend import drop_duplicate_windsea

    out = drop_duplicate_windsea({**_DUP, field: value})
    assert out["windsea_h"] == 1.74
    assert out["swell1_h"] == 1.83


def test_duplicate_is_matched_against_any_swell_slot():
    from rosa_pipeline.blend import drop_duplicate_windsea

    shifted = {
        **{k: v for k, v in _DUP.items() if not k.startswith("swell1_")},
        "swell1_h": 0.4,
        "swell1_p": 14.0,
        "swell1_d": 200.0,
        "swell2_h": 1.83,
        "swell2_p": 8.38,
        "swell2_d": 281.89,
    }
    out = drop_duplicate_windsea(shifted)
    assert "windsea_h" not in out
    assert out["swell1_h"] == 0.4 and out["swell2_h"] == 1.83


def test_a_windsea_with_no_swell_beside_it_survives():
    from rosa_pipeline.blend import drop_duplicate_windsea

    lone = {k: v for k, v in _DUP.items() if not k.startswith("swell1_")}
    assert drop_duplicate_windsea(lone)["windsea_h"] == 1.74


def test_model_run_is_the_newest_cycle_per_point_and_absent_on_fixtures():
    # Dream 2026-09-02 proposal: publish when the model RAN, per point - the GFS drop-back
    # is per box, so a fleet-wide constant would be wrong for whichever boxes fell back.
    # Back-reach steps come from earlier cycles and must not label the forecast.
    from rosa_pipeline.blend import _model_run

    t = CYCLE
    prev = CYCLE - timedelta(hours=6)
    gfs = [
        GfsSea(time=t - timedelta(hours=3), fields={"swh": 1.0}, run=prev),  # back-reach
        GfsSea(time=t, fields={"swh": 1.0}, run=CYCLE),
        GfsSea(time=t + timedelta(hours=1), fields={"swh": 1.0}),  # interpolated: no stamp
    ]
    sp = [SpectralSea(time=t, swh=1.0, run=CYCLE - timedelta(hours=12))]
    assert _model_run(gfs, sp) == {
        "gfswave": "2026-08-14T00:00+00:00",
        "ecmwf": "2026-08-13T12:00+00:00",
    }
    assert _model_run(gfs, []) == {"gfswave": "2026-08-14T00:00+00:00", "ecmwf": None}
    assert _model_run([_gfs(t)], sp) is None  # fixtures carry no cycle

    raw = compose_raw([_gfs(t)], [], _aux([t]), "x")
    assert raw.model_run is None
    raw = compose_raw([GfsSea(time=t, fields=_gfs(t).fields, run=CYCLE)], [], _aux([t]), "x")
    assert raw.model_run == {"gfswave": "2026-08-14T00:00+00:00", "ecmwf": None}


def test_parse_gfs_full_stamps_the_cycle_it_is_given(point):
    grib = next(FIX.glob("gfsfull_f000_*.grib2")).read_bytes()
    [sea] = parse_gfs_full(grib, [point], CYCLE, run=CYCLE)
    assert sea.run == CYCLE
    [sea] = parse_gfs_full(grib, [point], CYCLE)
    assert sea.run is None
