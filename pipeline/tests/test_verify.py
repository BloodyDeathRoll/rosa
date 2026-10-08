"""Skill metrics, model/obs pairing, and the end-to-end scorecard on real fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rosa_pipeline.buoys import Buoy
from rosa_pipeline.observe import BuoyObs, NDBCFixtureSource
from rosa_pipeline.spectra import SpectrumMeasures
from rosa_pipeline.verify import (
    APD_FALLBACK_LABEL,
    ENERGY_PERIOD_VARIABLES,
    VARIABLES,
    VarScore,
    WavePoint,
    ang_diff,
    build_scorecard,
    lead_time_scorecard,
    pair_series,
    parse_marine_waves,
    render_lead_scorecard,
    render_scorecard,
    with_energy_period,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "verify"


def test_ang_diff_wraps() -> None:
    assert ang_diff(10, 350) == 20  # across 0, not -340
    assert ang_diff(350, 10) == -20
    assert ang_diff(90, 90) == 0


def _obs(t: datetime, **kw) -> BuoyObs:
    base = dict(hs_m=None, dpd_s=None, apd_s=None, mwd_deg=None, wtmp_c=None)
    base.update(kw)
    return BuoyObs(station="x", time=t, **base)


def test_pairing_matches_nearest_within_tolerance() -> None:
    t0 = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.5, tp=10.0, dir=250.0)]
    obs = [
        _obs(t0 + timedelta(minutes=10), hs_m=1.2, apd_s=8.0, mwd_deg=245.0),  # in tol
        _obs(t0 + timedelta(minutes=90), hs_m=9.9, apd_s=9.9, mwd_deg=9.9),  # out of tol
    ]
    pairs = pair_series(model, obs, tol_min=30)
    assert pairs["hs"] == [(1.5, 1.2)]
    assert pairs["tp"] == [(10.0, 8.0)]  # model MEAN period vs obs APD
    assert pairs["dir"] == [(250.0, 245.0)]


def test_missing_values_drop_from_that_variable_only() -> None:
    t0 = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.5, tp=10.0, dir=250.0)]
    obs = [_obs(t0, hs_m=1.2, apd_s=None, mwd_deg=245.0)]  # no period
    pairs = pair_series(model, obs, tol_min=30)
    assert pairs["hs"] and pairs["dir"]
    assert pairs["tp"] == []


def test_equidistant_obs_resolve_to_the_later_one() -> None:
    """Dream review 2026-08-05: the old linear scan's `gap <= best_gap` kept the LAST
    equal-gap observation in (oldest-first) list order, i.e. the later one. The bisect
    rewrite must preserve that exactly - verification history is compared run over run."""
    t0 = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.5, tp=None, dir=None)]
    obs = [
        _obs(t0 - timedelta(minutes=10), hs_m=1.0),
        _obs(t0 + timedelta(minutes=10), hs_m=2.0),
    ]
    assert pair_series(model, obs, tol_min=30)["hs"] == [(1.5, 2.0)]


def test_duplicate_timestamps_resolve_to_the_last_in_input_order() -> None:
    """Buoy files do repeat timestamps; the old scan kept the run's last row and the sort
    in _obs_index is stable, so the bisect must land on it too."""
    t0 = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.5, tp=None, dir=None)]
    obs = [
        _obs(t0 + timedelta(minutes=10), hs_m=1.0),
        _obs(t0 + timedelta(minutes=10), hs_m=2.0),
    ]
    assert pair_series(model, obs, tol_min=30)["hs"] == [(1.5, 2.0)]


def test_unsorted_observations_still_pair_with_the_nearest() -> None:
    """The parsers all return oldest-first, but that was an informal invariant; _obs_index
    sorts so a bisect over an unsorted source cannot silently pick the wrong neighbour."""
    t0 = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.5, tp=None, dir=None)]
    obs = [  # newest first
        _obs(t0 + timedelta(minutes=25), hs_m=3.0),
        _obs(t0 + timedelta(minutes=5), hs_m=1.0),
    ]
    assert pair_series(model, obs, tol_min=30)["hs"] == [(1.5, 1.0)]


def test_scorecard_metrics_math() -> None:
    t = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    # two hours; model hs over-predicts by +0.2 then +0.4 → bias +0.3, rmse sqrt(0.1)
    model = [
        WavePoint(time=t, hs=1.2, tp=None, dir=None),
        WavePoint(time=t + timedelta(hours=1), hs=1.4, tp=None, dir=None),
    ]
    obs = [_obs(t, hs_m=1.0), _obs(t + timedelta(hours=1), hs_m=1.0)]
    hs = build_scorecard(model, obs, tol_min=30)["hs"]
    assert hs.n == 2
    assert abs(hs.bias - 0.3) < 1e-9
    assert abs(hs.mae - 0.3) < 1e-9
    assert abs(hs.rmse - (0.1**0.5)) < 1e-9
    assert hs.scatter_index is not None and abs(hs.scatter_index - (0.1**0.5)) < 1e-9


def test_empty_scorecard_is_safe() -> None:
    scores = build_scorecard([], [], tol_min=30)
    assert all(s.n == 0 for s in scores.values())
    assert scores["dir"].scatter_index is None


def test_end_to_end_on_real_fixtures() -> None:
    marine = json.loads((FIX / "marine_46042.json").read_text(encoding="utf-8"))
    model = parse_marine_waves(marine)
    buoy = Buoy(id="46042", name="Monterey", lat=36.785, lon=-122.408, source="ndbc")
    obs = NDBCFixtureSource(FIX).fetch(buoy)
    scores = build_scorecard(model, obs, tol_min=30)
    # the captured forecast and buoy obs overlap on 2026-07-21 morning → real pairs exist
    assert scores["hs"].n > 0
    assert scores["hs"].rmse >= 0
    # Monterey summer swell ~1-2 m; a sane model shouldn't be off by more than a metre RMS
    assert scores["hs"].rmse < 1.0


def _measures(t: datetime, tm_m10_s: float) -> SpectrumMeasures:
    return SpectrumMeasures(
        time=t,
        hs_m=1.0,
        tp_s=12.0,
        tm_m10_s=tm_m10_s,
        tm02_s=tm_m10_s - 2.0,
        qp=2.0,
        consistency=70,
        sigma_peak_deg=20.0,
        windsea=False,
    )


def test_energy_period_attached_from_nearest_spectrum() -> None:
    t0 = datetime(2026, 7, 29, 6, 0, tzinfo=UTC)
    obs = [_obs(t0, hs_m=1.0, apd_s=7.0)]
    out = with_energy_period(obs, [_measures(t0 + timedelta(minutes=10), 9.2)], tol_min=30)
    assert out[0].tm_m10_s == 9.2
    assert out[0].apd_s == 7.0  # the met fields are untouched


def test_energy_period_never_falls_back_to_apd_when_no_spectrum_is_near() -> None:
    """A spectrum outside tolerance must leave the hour unscorable, not silently APD-paired."""
    t0 = datetime(2026, 7, 29, 6, 0, tzinfo=UTC)
    obs = [_obs(t0, hs_m=1.0, apd_s=7.0)]
    out = with_energy_period(obs, [_measures(t0 + timedelta(hours=3), 9.2)], tol_min=30)
    assert out[0].tm_m10_s is None

    model = [WavePoint(time=t0, hs=1.0, tp=9.3, dir=None)]
    assert pair_series(model, out, variables=ENERGY_PERIOD_VARIABLES)["tp"] == []


def test_apd_pairing_manufactures_the_definitional_period_bias() -> None:
    """The regression this fix exists to prevent (CALIBRATION.md 2026-07-29).

    Same model hour, same buoy hour: pairing Tm-1,0 against APD (Tm02) invents ~+2 s of
    'model error' that pairing against the measured energy period does not."""
    t0 = datetime(2026, 7, 29, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.0, tp=9.3, dir=None)]
    obs = with_energy_period([_obs(t0, hs_m=1.0, apd_s=7.2)], [_measures(t0, 9.2)], tol_min=30)

    apd = build_scorecard(model, obs, variables=VARIABLES)["tp"]
    energy = build_scorecard(model, obs, variables=ENERGY_PERIOD_VARIABLES)["tp"]
    assert abs(apd.bias - 2.1) < 1e-9
    assert abs(energy.bias - 0.1) < 1e-9
    assert apd.label == APD_FALLBACK_LABEL  # and so carries the renderer's warning


def test_apd_footnote_rides_along_with_the_fallback_only() -> None:
    buoy = Buoy(id="46042", name="Monterey", lat=36.8, lon=-122.4, source="ndbc")
    t0 = datetime(2026, 7, 29, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.0, tp=9.3, dir=None)]
    obs = with_energy_period([_obs(t0, hs_m=1.0, apd_s=7.2)], [_measures(t0, 9.2)], tol_min=30)

    fallback = render_scorecard(buoy, None, build_scorecard(model, obs, variables=VARIABLES))
    preferred = render_scorecard(
        buoy, None, build_scorecard(model, obs, variables=ENERGY_PERIOD_VARIABLES)
    )
    assert "never calibrate against it" in fallback
    assert "never calibrate against it" not in preferred


def test_lead_scorecard_reports_bias_not_just_rmse() -> None:
    """Guards the fault that hid the period bug for six days (CALIBRATION.md 2026-07-29).

    rmse is unsigned, so a systematic offset and random scatter render identically. A model
    running consistently hot must be visibly *hot* on the lead card, not merely 'wrong by
    0.30'."""
    buoy = Buoy(id="46042", name="Monterey", lat=36.8, lon=-122.4, source="ndbc")
    run = datetime(2026, 7, 29, 0, 0, tzinfo=UTC)
    rows, obs = [], []
    for h in range(6):  # model reads +0.30 m hot every hour
        valid = run + timedelta(hours=h)
        rows.append({"run": run.isoformat(), "valid": valid.isoformat(), "hs": 1.3})
        obs.append(_obs(valid, hs_m=1.0))

    out = render_lead_scorecard(buoy, lead_time_scorecard(rows, obs))
    assert "+0.30m" in out  # signed bias, with its sign
    assert "bias" in out
    line = next(ln for ln in out.splitlines() if "Sig. wave height" in ln)
    assert line.index("+0.30") < line.index("0.30m", line.index("+0.30") + 1)  # bias before rmse


def test_lead_scorecard_distinguishes_hot_from_cold() -> None:
    """The signed half: same magnitude of error, opposite direction, must read differently."""
    buoy = Buoy(id="46042", name="Monterey", lat=36.8, lon=-122.4, source="ndbc")
    run = datetime(2026, 7, 29, 0, 0, tzinfo=UTC)

    def card(model_hs: float) -> str:
        rows = [
            {
                "run": run.isoformat(),
                "valid": (run + timedelta(hours=h)).isoformat(),
                "hs": model_hs,
            }
            for h in range(4)
        ]
        obs = [_obs(run + timedelta(hours=h), hs_m=1.0) for h in range(4)]
        return render_lead_scorecard(buoy, lead_time_scorecard(rows, obs))

    assert "+0.30m" in card(1.3)
    assert "-0.30m" in card(0.7)


def test_lead_scorecard_scores_each_run_not_the_mean_of_the_runs() -> None:
    """Dream review 2026-09-18: several archived runs cover one valid hour in a bucket, and
    the card graded their MEAN - two runs 1 m low and 1 m high scored as a perfect forecast,
    and that scatter index prices the published confidence ceiling. n still counts the hour
    once (the 2026-08-07 rule); the hour's error is the mean of its runs' errors."""
    valid = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    rows = [
        {"run": (valid - timedelta(hours=30)).isoformat(), "valid": valid.isoformat(), "hs": 1.0},
        {"run": (valid - timedelta(hours=36)).isoformat(), "valid": valid.isoformat(), "hs": 3.0},
    ]
    hs = lead_time_scorecard(rows, [_obs(valid, hs_m=2.0)])["1-3d"]["hs"]
    assert hs.n == 1
    assert hs.bias == 0.0
    assert hs.mae == 1.0
    assert hs.rmse == 1.0
    assert hs.scatter_index == 0.5


def test_renderers_show_every_variable_handed_in() -> None:
    """Dream review 2026-08-05: both renderers iterated the module-level VARIABLES tuple,
    which worked only because all four *_VARIABLES tuples happen to share the same three
    keys. A source with a fourth variable would have printed three rows and silently
    dropped it - render the card that was handed in."""
    buoy = Buoy(id="46042", name="Monterey", lat=36.8, lon=-122.4, source="ndbc")
    scores = {
        key: VarScore(
            key=key,
            label=f"var {key}",
            unit="m",
            n=1,
            bias=0.1,
            mae=0.1,
            rmse=0.1,
            scatter_index=None,
        )
        for key in ("hs", "tp", "dir", "extra")
    }
    assert "var extra" in render_scorecard(buoy, None, scores)
    assert "var extra" in render_lead_scorecard(buoy, {"h024": scores})


def test_join_wind_attaches_by_timestamp() -> None:
    # plan C3 evidence: OM wind joins the wave points by exact hour; a missing hour
    # keeps None rather than borrowing a neighbour
    t0 = datetime(2026, 8, 14, 6, 0, tzinfo=UTC)
    from rosa_pipeline.verify import join_wind

    model = [
        WavePoint(time=t0, hs=1.0, tp=8.0, dir=250.0),
        WavePoint(time=t0 + timedelta(hours=1), hs=1.1, tp=8.0, dir=250.0),
    ]
    weather = {
        "hourly": {
            "time": [t0.strftime("%Y-%m-%dT%H:%M")],
            "wind_speed_10m": [5.2],
            "wind_direction_10m": [310.0],
        }
    }
    joined = join_wind(model, weather)
    assert (joined[0].ws, joined[0].wdir) == (5.2, 310.0)
    assert (joined[1].ws, joined[1].wdir) == (None, None)  # no matching hour
    assert joined[0].hs == 1.0  # wave fields untouched


def test_wind_scorecard_pairs_with_the_anemometer() -> None:
    t0 = datetime(2026, 8, 14, 6, 0, tzinfo=UTC)
    model = [WavePoint(time=t0, hs=1.0, tp=8.0, dir=250.0, ws=6.0, wdir=300.0)]
    obs = [_obs(t0, hs_m=1.0, wspd_ms=5.0, wdir_deg=290.0)]
    scores = build_scorecard(model, obs)
    assert scores["ws"].n == 1 and abs(scores["ws"].bias - 1.0) < 1e-9
    assert scores["wdir"].n == 1 and abs(scores["wdir"].bias - 10.0) < 1e-9


def test_windless_history_scores_empty_not_crashing() -> None:
    # every pre-2026-08-14 archive row lacks ws/wdir - history must score as before
    t0 = datetime(2026, 8, 14, 6, 0, tzinfo=UTC)
    scores = build_scorecard(
        [WavePoint(time=t0, hs=1.0, tp=8.0, dir=250.0)], [_obs(t0, hs_m=1.0, wspd_ms=5.0)]
    )
    assert scores["ws"].n == 0
    assert scores["hs"].n == 1


# --- coastal wind stations (2026-08-29) -------------------------------------------------


def test_wind_points_shape_a_weather_body_as_wind_only_rows() -> None:
    from rosa_pipeline.verify import wind_points

    body = {
        "hourly": {
            "time": ["2026-08-29T00:00", "2026-08-29T01:00"],
            "wind_speed_10m": [3.1, None],
            "wind_direction_10m": [280, 285],
        }
    }
    pts = wind_points(body)
    assert [p.time for p in pts] == [
        datetime(2026, 8, 29, 0, tzinfo=UTC),
        datetime(2026, 8, 29, 1, tzinfo=UTC),
    ]
    assert pts[0].ws == 3.1 and pts[0].wdir == 280 and pts[0].hs is None
    assert pts[1].ws is None and pts[1].wdir == 285


def test_pooled_lead_card_merges_n_weighted() -> None:
    from rosa_pipeline.verify import STATION_VARIABLES, render_pooled_lead

    def card(bias: float, n: int) -> dict:
        return {
            "0-1d": {
                "ws": VarScore("ws", "Wind speed", "m/s", n, bias, abs(bias), abs(bias), None),
                "wdir": VarScore("wdir", "Wind direction", "°", 0, 0.0, 0.0, 0.0, None),
            }
        }

    out = render_pooled_lead([card(1.0, 10), card(-1.0, 30)], "pooled")
    # (1.0*10 + -1.0*30) / 40 = -0.5
    assert "0-1d  Wind speed            40    -0.50m/s" in out
    assert "Wind direction" not in out  # n=0 rows are not printed
    assert render_pooled_lead([], "pooled").endswith("(nothing scored)")
    assert STATION_VARIABLES[0][0] == "ws"


def test_pooled_lead_card_carries_the_apd_footnote() -> None:
    """An APD-paired period row reaches a fleet card with the same warning the per-buoy
    cards print - the pooled renderer was the one of the three without it."""
    from rosa_pipeline.verify import APD_FALLBACK_LABEL, render_pooled_lead

    apd = {"0-1d": {"tp": VarScore("tp", APD_FALLBACK_LABEL, "s", 10, 2.7, 2.8, 3.0, 0.3)}}
    out = render_pooled_lead([apd, apd], "pooled")
    assert "never calibrate against it" in out
    wind = {"0-1d": {"ws": VarScore("ws", "Wind speed", "m/s", 10, 0.1, 0.2, 0.3, None)}}
    assert "never calibrate" not in render_pooled_lead([wind], "pooled")


def test_calm_hour_is_no_direction_truth_on_any_card() -> None:
    # the vane still logs a heading at 0 m/s (IMS, NDBC); that is not a truth to grade against
    from rosa_pipeline.verify import STATION_VARIABLES

    t0 = datetime(2026, 7, 21, 6, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=1)
    obs = [_obs(t0, wspd_ms=0.0, wdir_deg=0.0), _obs(t1, wspd_ms=4.0, wdir_deg=270.0)]
    model = [WavePoint(time=t, hs=1.0, tp=10.0, dir=250.0, ws=3.0, wdir=90.0) for t in (t0, t1)]
    pairs = pair_series(model, obs)
    assert pairs["wdir"] == [(90.0, 270.0)]  # the calm hour is gone, the windy one stays
    assert len(pairs["ws"]) == 2  # calm is still a wind SPEED truth
    run = (t0 - timedelta(hours=6)).isoformat()
    rows = [{"run": run, "valid": t.isoformat(), "ws": 3.0, "wdir": 90.0} for t in (t0, t1)]
    card = lead_time_scorecard(rows, obs, variables=STATION_VARIABLES)["0-1d"]
    assert card["wdir"].n == 1
    assert card["ws"].n == 2


# --- direction pairs like-for-like: the measured mean beside MWD (2026-10-08, 37b) ---


def test_with_energy_period_attaches_the_measured_mean_direction() -> None:
    t0 = datetime(2026, 10, 8, 11, 50, tzinfo=UTC)
    m = SpectrumMeasures(
        time=t0,
        hs_m=1.6,
        tp_s=11.4,
        tm_m10_s=8.0,
        tm02_s=6.4,
        qp=2.0,
        consistency=2,
        sigma_peak_deg=None,
        windsea=False,
        mean_dir_deg=297.0,
    )
    (o,) = with_energy_period([_obs(t0, hs_m=1.7, mwd_deg=270.0)], [m])
    assert o.mdir_deg == 297.0 and o.mwd_deg == 270.0 and o.tm_m10_s == 8.0


def test_mean_card_scores_dirm_against_the_mean_and_dir_against_mwd() -> None:
    """Both rows read the same archived row["dir"]: "dir" keeps the old MWD (peak)
    pairing, "dirm" pairs the measured mean - so the offset between them is visible."""
    run = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
    valid = run + timedelta(hours=12)
    rows = [{"run": run.isoformat(), "valid": valid.isoformat(), "hs": 1.5, "dir": 290.0}]
    obs = [_obs(valid, hs_m=1.6, mwd_deg=270.0, mdir_deg=296.0)]
    card = lead_time_scorecard(rows, obs, variables=ENERGY_PERIOD_VARIABLES)
    cell = next(c for c in card.values() if c["dir"].n)
    assert round(cell["dir"].bias, 6) == 20.0  # 290 vs MWD 270
    assert round(cell["dirm"].bias, 6) == -6.0  # 290 vs the measured mean 296
    assert cell["dirm"].label == "Wave dir. (mean)"


def test_gfswave_card_keeps_mwd_as_its_like_for_like_direction() -> None:
    from rosa_pipeline.verify import GFSWAVE_VARIABLES

    rows_attr = {v[0]: (v[1], v[4]) for v in GFSWAVE_VARIABLES}
    assert rows_attr["dir"] == ("Wave dir. (peak)", "mwd_deg")
    assert rows_attr["dirm"] == ("Wave dir. vs mean", "mdir_deg")
