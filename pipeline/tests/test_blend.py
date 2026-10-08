"""Blended wave source (fetch-plane plan B): GRIB parse, blend math, offline end-to-end.

Fixtures: real captured NOMADS grib-filter boxes + an OM weather body for Beit Yanai's
offshore point (2026-08-14 00Z cycle, steps 0-48; the marine-light body went with the
leg on 2026-09-12 - tide is the spot's EOT20 constants). Nothing touches the
network; ``now`` is frozen to the fixture cycle, the e2e-test pattern.
"""

from __future__ import annotations

import json
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


def _swells(t: datetime, *slots: tuple[float, float, float], **extra) -> GfsSea:
    fields = {
        f"swell{n}_{k}": v for n, s in enumerate(slots, 1) for k, v in zip("hpd", s, strict=True)
    }
    return _gfs(t, **fields, **extra)


def test_filled_hours_follow_the_swell_not_the_slot():
    # GFS-Wave ranks its slots: two systems crossing in size swap slots at t3. A filled
    # hour must carry the two real systems, never a blend of both (Dream 09-14,
    # CALIBRATION.md 2026-09-14)
    t0 = CYCLE
    gfs = [
        _swells(t0, (1.2, 13.0, 200.0), (1.0, 8.0, 290.0)),
        _swells(t0 + timedelta(hours=3), (1.3, 8.0, 290.0), (0.9, 13.0, 200.0)),
    ]
    h = compose_raw(gfs, [], _aux([t0]), "x").marine["hourly"]
    assert h["swell_wave_period"][1] == pytest.approx(13.0)
    assert h["swell_wave_direction"][1] == pytest.approx(200.0)
    assert h["swell_wave_height"][1] == pytest.approx(1.1)
    assert h["secondary_swell_wave_period"][1] == pytest.approx(8.0)
    assert h["secondary_swell_wave_direction"][1] == pytest.approx(290.0)
    assert h["secondary_swell_wave_height"][1] == pytest.approx(1.1)
    # native steps are never touched
    assert h["swell_wave_period"][3] == 8.0


def test_a_swell_born_or_dying_is_never_paired_with_another():
    # jameos-del-agua 2026-09-18 06z -> 09z (the A/B's regression): 328 -> 331 deg is one
    # swell, but a 37 deg swell dies and a 240 deg one is born. An unguarded permutation
    # paired them, invented a 352 deg 10 s swell and deleted the 2.08 m wind sea as its
    # "duplicate". The guard re-pairs only same-system pairs, so here it keeps the slots.
    t0 = CYCLE
    wind = {"windsea_h": 2.11, "windsea_p": 9.82, "windsea_d": 8.04}
    gfs = [
        _swells(t0, (0.47, 11.06, 327.8), (0.08, 13.82, 211.26), (0.14, 8.69, 37.35), **wind),
        _swells(
            t0 + timedelta(hours=3),
            (0.44, 10.67, 331.13),
            (0.25, 12.52, 240.27),
            (0.07, 13.6, 212.77),
            **{**wind, "windsea_h": 2.07, "windsea_p": 10.01, "windsea_d": 7.17},
        ),
    ]
    h = compose_raw(gfs, [], _aux([t0]), "x").marine["hourly"]
    assert h["swell_wave_direction"][2] == pytest.approx(330.0, abs=0.1)
    assert h["wind_wave_height"][2] == pytest.approx(2.083, abs=0.001)


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


def test_blend_archive_rows_join_on_run_and_valid_and_combine_like_compose_raw() -> None:
    """verify --source blend (Dream 2026-09-12, recording only): one row per (run, valid)
    both member archives carry, combined with compose_raw's own _wavg/_circ."""
    from rosa_pipeline.blend import blend_archive_rows

    run = "2026-09-13T02:20:00+00:00"
    v3, v4 = "2026-09-13T03:00:00+00:00", "2026-09-13T04:00:00+00:00"
    gfs = [
        {"run": run, "valid": v3, "hs": 1.0, "tp": 10.0, "dir": 350.0, "ws": 5.0},
        {"run": run, "valid": v4, "hs": 1.2, "tp": 11.0, "dir": 0.0},  # no ECMWF step
        None,  # a damaged archive line costs itself
    ]
    ecmwf = [
        {"run": run, "valid": v3, "hs": 2.0, "tp": None, "dir": 10.0},
        # same valid hour from an EARLIER cycle - a different forecast, never joined
        {"run": "2026-09-12T20:20:00+00:00", "valid": v4, "hs": 9.0, "tp": 9.0, "dir": 90.0},
    ]
    (row,) = blend_archive_rows(gfs, ecmwf)
    assert row == {"run": run, "valid": v3, "hs": 1.5, "tp": 10.0, "dir": 0.0}


def test_a_sea_that_changes_slot_between_steps_stays_in_the_filled_hours():
    # anglesea 2026-09-16 06z: one 14.3 s 208 deg sea is "wind sea" at f000 and swell 1 at
    # f003. Filled hours interpolated only keys present at both steps, so it vanished and
    # published FLAT between two FIRING steps (CALIBRATION.md 2026-09-16). One system by
    # the dedupe test -> one partition, under the swell label.
    t0 = CYCLE
    gfs = [
        _gfs(t0, windsea_h=2.01, windsea_p=14.3, windsea_d=208.0),
        _swells(t0 + timedelta(hours=3), (1.94, 14.3, 208.0)),
    ]
    h = compose_raw(gfs, [], _aux([t0]), "x").marine["hourly"]
    for i in (1, 2):
        assert h["swell_wave_period"][i] == pytest.approx(14.3)
        assert h["swell_wave_direction"][i] == pytest.approx(208.0)
        assert not h["wind_wave_height"][i]
    assert h["swell_wave_height"][1] == pytest.approx(1.987, abs=0.001)
    assert h["wind_wave_height"][0] == 2.01  # native steps are never touched


def test_a_partition_at_one_step_only_is_held_from_the_nearer_step():
    # a swell present at t0 and gone at t3 (not the same system as anything at t3) is held
    # verbatim in the hour nearer t0 and absent in the hour nearer t3 - never interpolated
    # toward a value that does not exist, never dropped from both
    t0 = CYCLE
    gfs = [
        _swells(t0, (1.0, 12.0, 270.0), (0.6, 7.0, 20.0)),
        _swells(t0 + timedelta(hours=3), (1.1, 12.0, 270.0)),
    ]
    h = compose_raw(gfs, [], _aux([t0]), "x").marine["hourly"]
    assert h["secondary_swell_wave_height"][1] == 0.6
    assert h["secondary_swell_wave_period"][1] == 7.0
    assert not h["secondary_swell_wave_height"][2]


def test_a_slot_holding_two_different_swells_is_held_not_blended():
    # slot 1's swell dies between the steps and slot 2's moves up (Dream 2026-09-17): slot 1
    # is filled at both steps by two different systems. Blending them publishes a 13 s / 268
    # deg swell that exists at neither step - each filled hour holds the nearer step's instead
    t0 = CYCLE
    gfs = [
        _swells(t0, (1.6, 16.0, 250.0), (0.8, 8.0, 310.0)),
        _swells(t0 + timedelta(hours=3), (0.85, 8.1, 308.0)),
    ]
    h = compose_raw(gfs, [], _aux([t0]), "x").marine["hourly"]
    assert (h["swell_wave_height"][1], h["swell_wave_period"][1]) == (1.6, 16.0)
    assert (h["swell_wave_height"][2], h["swell_wave_period"][2]) == (0.85, 8.1)
    assert h["swell_wave_direction"][1] == 250.0
    assert h["swell_wave_direction"][2] == 308.0


def _fake_pygrib(monkeypatch, fields: dict[str, list[float | None]]) -> None:
    """A 1 x 3 row of 0.25 deg nodes at lat 0, lon 0/0.25/0.5; None = masked. Hands over
    arrays only - the node choice under test is the real parse_gfs_full + nearest_wet."""
    import sys
    import types

    import numpy as np

    lats = np.zeros((1, 3))
    lons = np.array([[0.0, 0.25, 0.5]])
    names = {"swh": ("swh", 1), "windsea_h": ("shww", 1), "windsea_p": ("mpww", 1)}
    names |= {"windsea_d": ("wvdir", 1)}
    names |= {f"swell1_{k}": (s, 1) for k, s in zip("hpd", ("shts", "mpts", "swdir"), strict=True)}

    class Msg:
        def __init__(self, sn, vals):
            self.shortName = sn
            self.values = np.ma.masked_invalid(
                np.array([[np.nan if v is None else v for v in vals]])
            )

        def latlons(self):
            return lats, lons

    msgs = [Msg(names[k][0], v) for k, v in fields.items()]

    class Grbs:
        def __iter__(self):
            return iter(msgs)

        def close(self):
            pass

    monkeypatch.setitem(sys.modules, "pygrib", types.SimpleNamespace(open=lambda _p: Grbs()))


def test_parse_gfs_full_reads_every_field_at_the_points_own_node(monkeypatch):
    # GFS-Wave masks a partition where that PARTITION is absent. The point's node has swh
    # and a swell but no wind sea; the next node has a wind sea. It is not borrowed
    # (Dream 2026-09-16: 49.6% of point-steps did, CALIBRATION.md 2026-09-16).
    _fake_pygrib(
        monkeypatch,
        {
            "swh": [1.2, 1.5, 1.6],
            "swell1_h": [1.0, 1.0, 1.0],
            "swell1_p": [8.5, 8.5, 8.5],
            "swell1_d": [290.0, 290.0, 290.0],
            "windsea_h": [None, 0.6, 0.6],
            "windsea_p": [None, 4.5, 4.5],
            "windsea_d": [None, 300.0, 300.0],
        },
    )
    [sea] = parse_gfs_full(b"", [(0.0, 0.0)], CYCLE)
    assert sea.fields == {
        "swh": 1.2,
        "swell1_h": 1.0,
        "swell1_p": 8.5,
        "swell1_d": 290.0,
    }


def test_a_node_with_a_sea_and_no_partition_takes_one_whole_set_from_the_nearest(monkeypatch):
    # every partition masked at the own node: its total alone publishes FLAT. The WHOLE
    # set comes from the nearest node that has one - never field by field - and the
    # totals stay the own node's.
    _fake_pygrib(
        monkeypatch,
        {
            "swh": [1.2, 1.5, 1.6],
            "swell1_h": [None, 1.1, 0.9],
            "swell1_p": [None, 10.0, 9.0],
            "swell1_d": [None, 250.0, 240.0],
            "windsea_h": [None, None, 0.4],
            "windsea_p": [None, None, 3.0],
            "windsea_d": [None, None, 90.0],
        },
    )
    [sea] = parse_gfs_full(b"", [(0.0, 0.0)], CYCLE)
    assert sea.fields == {
        "swh": 1.2,
        "swell1_h": 1.1,
        "swell1_p": 10.0,
        "swell1_d": 250.0,
    }


# --- weather leg: a refused batch falls back to each point's cached body (2026-09-30) ---


_REAL_CLIENT = __import__("httpx").Client  # captured before any test patches it


def _weather_transport(monkeypatch, handler):
    """Route fetch_weather_many's own httpx.Client through a MockTransport."""
    import httpx

    from rosa_pipeline import blend as blend_mod

    monkeypatch.setattr(
        blend_mod.httpx,
        "Client",
        lambda **kw: _REAL_CLIENT(transport=httpx.MockTransport(handler), **kw),
    )


def _weather_body(tag: float) -> dict:
    return {"hourly": {"time": ["2026-09-29T00:00"], "wind_speed_10m": [tag]}}


_DAILY_429 = {
    "error": True,
    "reason": "Daily API request limit exceeded. Please try again tomorrow.",
}


def test_refused_weather_batch_is_served_from_the_cache(monkeypatch, tmp_path, capsys):
    """2026-09-29 20:20Z: a daily-bucket 429 on the weather host killed the whole cycle.
    With a cache the run survives on the previous cycle's bodies, and stops asking."""
    import httpx

    from rosa_pipeline import blend as blend_mod

    monkeypatch.setattr(blend_mod, "AUX_BATCH_SIZE", 2)
    coords = [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0), (5.0, 5.0)]
    calls: list[int] = []

    def ok(request):
        n = len(request.url.params["latitude"].split(","))
        calls.append(n)
        lats = [float(x) for x in request.url.params["latitude"].split(",")]
        bodies = [_weather_body(lat) for lat in lats]
        return httpx.Response(200, json=bodies if n > 1 else bodies[0])

    _weather_transport(monkeypatch, ok)
    first = blend_mod.fetch_weather_many(coords, cache_dir=tmp_path)
    assert [w["hourly"]["wind_speed_10m"] for w in first] == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    (tmp_path / "weather_4_4.json").unlink()  # a point seeded since the last good cycle

    calls.clear()

    def second_batch_refused(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, json=[_weather_body(10.0), _weather_body(20.0)])
        return httpx.Response(429, json=_DAILY_429)

    _weather_transport(monkeypatch, second_batch_refused)
    got = blend_mod.fetch_weather_many(coords, cache_dir=tmp_path)
    # batch 1 fresh; batch 2 refused -> cache (3) and empty (4, no cache); batch 3 never asked
    assert [w["hourly"].get("wind_speed_10m") for w in got] == [[10.0], [20.0], [3.0], None, [5.0]]
    assert got[3]["hourly"]["time"] == []
    assert len(calls) == 2
    err = capsys.readouterr().err
    assert "Daily API request limit" in err
    assert "2 of 5 point(s)" in err and "1 had no usable cache" in err


def test_weather_batch_is_attributed_by_location_id_and_coordinate(monkeypatch, tmp_path):
    """Dream 2026-10-07: the default arm's weather leg zipped batch bodies by list
    position - the one Open-Meteo batch site the 2026-09-14 attribution missed. A swapped
    batch must come back in request order; a body far from its point must be refused."""
    import httpx

    from rosa_pipeline import blend as blend_mod

    coords = [(32.875, 34.75), (32.958, 34.75)]  # 0.083 deg apart: only the id can tell

    def body(i: int, lat: float) -> dict:
        b = {"latitude": lat, "longitude": 34.75, **_weather_body(lat)}
        if i:
            b["location_id"] = i
        return b

    swapped = [body(1, 32.958), body(0, 32.875)]
    _weather_transport(monkeypatch, lambda request: httpx.Response(200, json=swapped))
    got = blend_mod.fetch_weather_many(coords, cache_dir=tmp_path)
    assert [w["hourly"]["wind_speed_10m"] for w in got] == [[32.875], [32.958]]
    cached = json.loads((tmp_path / "weather_32.875_34.75.json").read_text())
    assert cached["latitude"] == 32.875  # the cache holds each point's own body

    far = [body(0, 36.625), body(1, 32.958)]
    _weather_transport(monkeypatch, lambda request: httpx.Response(200, json=far))
    with pytest.raises(ValueError, match="came back at"):
        blend_mod.fetch_weather_many(coords, cache_dir=tmp_path)


def test_blended_source_asks_for_weather_before_the_wave_download():
    """Dream 2026-10-07: the weather leg is the arm's only essential per-spot request, so
    it runs first - a refusal with nothing cached fails the cycle before the NOMADS pull."""
    order: list[str] = []

    class Gfs:
        def fetch_series(self, coords):
            order.append("gfs")
            raise RuntimeError("stop after the order is known")

    def weather(coords):
        order.append("weather")
        return [{"hourly": {"time": []}} for _ in coords]

    from rosa_pipeline.blend import BlendedSource

    with pytest.raises(RuntimeError):
        BlendedSource(gfs=Gfs(), weather=weather).fetch_many([(1.0, 1.0)])
    assert order == ["weather", "gfs"]


def test_refused_weather_without_a_cache_dir_still_raises(monkeypatch):
    import httpx

    from rosa_pipeline import blend as blend_mod

    _weather_transport(monkeypatch, lambda request: httpx.Response(429, json=_DAILY_429))
    with pytest.raises(httpx.HTTPStatusError):
        blend_mod.fetch_weather_many([(1.0, 1.0)])


def test_refused_weather_with_nothing_cached_still_raises(monkeypatch, tmp_path):
    """Nothing fresh and nothing cached must stay a failed cycle, not a silent empty one."""
    import httpx

    from rosa_pipeline import blend as blend_mod

    _weather_transport(monkeypatch, lambda request: httpx.Response(429, json=_DAILY_429))
    with pytest.raises(httpx.HTTPStatusError):
        blend_mod.fetch_weather_many([(1.0, 1.0), (2.0, 2.0)], cache_dir=tmp_path)


def test_weather_cache_older_than_the_limit_is_not_used(monkeypatch, tmp_path):
    import json
    import os
    import time

    import httpx

    from rosa_pipeline import blend as blend_mod

    fresh, old = tmp_path / "weather_1_1.json", tmp_path / "weather_2_2.json"
    fresh.write_text(json.dumps(_weather_body(1.0)))
    old.write_text(json.dumps(_weather_body(2.0)))
    too_old = time.time() - (blend_mod.WEATHER_CACHE_MAX_AGE_H + 1) * 3600
    os.utime(old, (too_old, too_old))
    _weather_transport(monkeypatch, lambda request: httpx.Response(429, json=_DAILY_429))
    got = blend_mod.fetch_weather_many([(1.0, 1.0), (2.0, 2.0)], cache_dir=tmp_path)
    assert got[0]["hourly"]["wind_speed_10m"] == [1.0]
    assert got[1]["hourly"]["time"] == []


# --- weather leg: the self-hosted Open-Meteo, off unless ROSA_WEATHER_URL (2026-10-07) ---


def test_self_hosted_weather_is_asked_first_when_configured(monkeypatch, tmp_path):
    import httpx

    from rosa_pipeline import blend as blend_mod

    monkeypatch.setattr(blend_mod, "AUX_BATCH_SIZE", 2)
    monkeypatch.setenv(blend_mod.WEATHER_URL_ENV, "http://127.0.0.1:8080/v1/forecast")
    hosts: list[str] = []

    def handler(request):
        hosts.append(request.url.host)
        lats = [float(x) for x in request.url.params["latitude"].split(",")]
        bodies = [_weather_body(lat) for lat in lats]
        return httpx.Response(200, json=bodies if len(bodies) > 1 else bodies[0])

    _weather_transport(monkeypatch, handler)
    got = blend_mod.fetch_weather_many([(1.0, 1.0), (2.0, 2.0), (3.0, 3.0)], cache_dir=tmp_path)
    assert [w["hourly"]["wind_speed_10m"] for w in got] == [[1.0], [2.0], [3.0]]
    assert hosts == ["127.0.0.1", "127.0.0.1"]  # the public API is never asked


def test_self_hosted_weather_failure_falls_back_to_the_api_for_the_rest(
    monkeypatch, tmp_path, capsys
):
    """Turning it on must never cost a cycle: one failed batch there, and that batch and
    every later one go to api.open-meteo.com."""
    import httpx

    from rosa_pipeline import blend as blend_mod

    monkeypatch.setattr(blend_mod, "AUX_BATCH_SIZE", 2)
    monkeypatch.setenv(blend_mod.WEATHER_URL_ENV, "http://127.0.0.1:8080/v1/forecast")
    hosts: list[str] = []

    def handler(request):
        hosts.append(request.url.host)
        lats = [float(x) for x in request.url.params["latitude"].split(",")]
        if request.url.host == "127.0.0.1" and len(hosts) > 1:
            return httpx.Response(500, text="down")
        bodies = [_weather_body(lat) for lat in lats]
        return httpx.Response(200, json=bodies if len(bodies) > 1 else bodies[0])

    _weather_transport(monkeypatch, handler)
    coords = [(1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0), (5.0, 5.0)]
    got = blend_mod.fetch_weather_many(coords, cache_dir=tmp_path)
    assert [w["hourly"]["wind_speed_10m"] for w in got] == [[1.0], [2.0], [3.0], [4.0], [5.0]]
    assert hosts == ["127.0.0.1", "127.0.0.1", "api.open-meteo.com", "api.open-meteo.com"]
    assert "self-hosted weather failed at point 2 of 5" in capsys.readouterr().err


def test_weather_ignores_the_self_hosted_path_when_unset(monkeypatch):
    import httpx

    from rosa_pipeline import blend as blend_mod

    monkeypatch.delenv(blend_mod.WEATHER_URL_ENV, raising=False)
    hosts: list[str] = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(200, json=_weather_body(1.0))

    _weather_transport(monkeypatch, handler)
    blend_mod.fetch_weather_many([(1.0, 1.0)])
    assert hosts == ["api.open-meteo.com"]


def test_blend_archive_rows_publish_gfs_alone_past_the_ecmwf_horizon() -> None:
    """OPEN-ITEMS 37a: skill.json is written from this card, and past ECMWF's last step
    compose_raw publishes GFS-Wave alone - so the rebuild scores those hours as GFS alone
    (the 9d+ ceiling), while holds BETWEEN ECMWF steps stay unscored, and a run whose
    ECMWF member stopped short (a failed fetch, not the horizon) gets no tail."""
    from rosa_pipeline.blend import JOIN_TOL_H, blend_archive_rows

    run = "2026-10-01T02:20:00+00:00"
    t0 = datetime.fromisoformat(run)

    def at(h: float) -> str:
        return (t0 + timedelta(hours=h)).isoformat()

    last = 225.0  # a full ECMWF member: 240 h from its 12z cycle, archived 14 h later
    gfs = [
        {"run": run, "valid": at(222), "hs": 1.0, "tp": 9.0, "dir": 300.0},  # ECMWF hold
        {"run": run, "valid": at(225), "hs": 1.0, "tp": 9.0, "dir": 300.0},  # joined
        {"run": run, "valid": at(last + JOIN_TOL_H), "hs": 1.1, "tp": 9.0, "dir": 300.0},
        {"run": run, "valid": at(240), "hs": 1.4, "tp": 12.0, "dir": 280.0},  # GFS alone
    ]
    ecmwf = [
        {"run": run, "valid": at(219), "hs": 2.0, "tp": 10.0, "dir": 310.0},
        {"run": run, "valid": at(last), "hs": 2.0, "tp": 10.0, "dir": 310.0},
    ]
    rows = blend_archive_rows(gfs, ecmwf)
    assert [r["valid"] for r in rows] == [at(225), at(240)]
    assert rows[1] == {"run": run, "valid": at(240), "hs": 1.4, "tp": 12.0, "dir": 280.0}

    short = [{"run": run, "valid": at(30), "hs": 2.0, "tp": 10.0, "dir": 310.0}]
    assert blend_archive_rows(gfs, short) == []  # stopped at 30 h: no tail invented
