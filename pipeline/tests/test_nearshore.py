"""nearshore.py - the Stage-4 SWAN arm's reader and its seam into score_hour."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from rosa_pipeline import nearshore
from rosa_pipeline.models import HourForecast, Spot, SwellPartition
from rosa_pipeline.publish import _hour_entry
from rosa_pipeline.score import score_hour

T0 = datetime(2026, 9, 14, 0, tzinfo=UTC)

TABLE = """%
%
% Run:f003  Table:SPOTS             SWAN version:41.51AB
%
%    Xp        Yp        Depth     Hsig      TPsmoo    Dir       Dspr      Tm01
%    [degr]    [degr]    [m]       [m]       [sec]     [degr]    [degr]    [sec]
%
  -117.418   33.1964   15.6877   1.03769   8.1160    254.846   27.9575   6.8
  -120.071   34.4570   -99.0000  -9.00000  -9.0000   -999.000  -9.0000   -9.0
"""


def test_read_table_uses_swans_own_column_names(tmp_path):
    path = tmp_path / "t.tab"
    path.write_text(TABLE)
    rows = nearshore.read_table(path)
    assert len(rows) == 2
    assert rows[0]["Hsig"] == 1.03769 and rows[0]["Tm01"] == 6.8 and rows[0]["Dir"] == 254.846
    assert not nearshore._valid(rows[1])  # a dry cell's exception values


def _run_dir(tmp_path: Path, steps=(0, 3), missing=()) -> tuple[Path, Path]:
    region = tmp_path / "socal"
    run = region / "run"
    run.mkdir(parents=True)
    points = [
        {
            "spot": "oceanside-harbor",
            "lat": 33.1964,
            "lon": -117.418,
            "grid": "san-diego",
            "handoff_km": 1.2,
        },
        {
            "spot": "refugio",
            "lat": 34.457,
            "lon": -120.071,
            "grid": "santa-barbara",
            "handoff_km": 0.5,
        },
    ]
    (region / "points.json").write_text(json.dumps(points))
    (run / "cycle.json").write_text(json.dumps({"cycle": T0.isoformat(), "steps": list(steps)}))
    head = "\n".join(TABLE.splitlines()[:7]) + "\n"
    for step in steps:
        tag = f"f{step:03d}"
        if tag in missing:
            continue
        hs = 1.0 + 0.1 * step
        (run / f"spots_{tag}_san-diego.tab").write_text(
            head + f" -117.418 33.1964 15.7 {hs:.3f} 8.1 250.0 28.0 6.8\n"
        )
        (run / f"spots_{tag}_santa-barbara.tab").write_text(
            head + " -120.071 34.457 -99.0 -9.0 -9.0 -999.0 -9.0 -9.0\n"
        )
        # the outer table lists every point; its rows only count where no nest gave one
        (run / f"spots_{tag}.tab").write_text(
            head
            + f" -117.418 33.1964 20.0 {hs + 5:.3f} 9.0 270.0 30.0 7.0\n"
            + " -120.071 34.457 18.0 0.500 7.0 240.0 30.0 6.0\n"
        )
    return run, region / "points.json"


def test_load_run_prefers_the_nest_row_and_skips_dry_cells(tmp_path):
    run, points = _run_dir(tmp_path)
    series = nearshore.load_run(run, points)
    assert [s.hs for s in series["oceanside-harbor"]] == pytest.approx([1.0, 1.3])
    assert series["oceanside-harbor"][0].time == T0
    assert series["oceanside-harbor"][1].handoff_m == 1200.0
    # refugio's nest cell is dry, so the OUTER row stands in for it
    assert [s.hs for s in series["refugio"]] == pytest.approx([0.5, 0.5])
    assert series["refugio"][0].depth_m == 18.0


def test_load_run_leaves_a_missing_step_absent(tmp_path):
    run, points = _run_dir(tmp_path, steps=(0, 3, 6), missing=("f003",))
    series = nearshore.load_run(run, points)
    assert [s.time for s in series["oceanside-harbor"]] == [T0, T0 + timedelta(hours=6)]


def test_nearshore_at_interpolates_between_steps_and_gives_up_past_the_gap():
    a = nearshore.NearshoreSea(T0, 1.0, 6.0, 8.0, 350.0, 25.0, 15.0, 1000.0)
    b = nearshore.NearshoreSea(T0 + timedelta(hours=3), 2.0, 7.0, 9.0, 10.0, 27.0, 15.0, 1000.0)
    mid = nearshore.nearshore_at([a, b], T0 + timedelta(hours=1))
    assert mid.hs == pytest.approx(1.0 + 1.0 / 3) and mid.tm01 == pytest.approx(6.0 + 1.0 / 3)
    assert mid.direction == pytest.approx(356.667, abs=0.01)  # circular, through north
    assert nearshore.nearshore_at([a, b], T0) is a
    # past the last step: the nearest step carries up to MAX_GAP_H, then nothing
    assert nearshore.nearshore_at([a, b], T0 + timedelta(hours=5)).hs == 2.0
    assert nearshore.nearshore_at([a, b], T0 + timedelta(hours=7)) is None
    assert nearshore.nearshore_at(None, T0) is None
    assert nearshore.nearshore_at([], T0) is None


def test_inner_samples_start_at_the_handoff_point():
    wet = [
        (18000.0, 600.0),
        (5000.0, 60.0),
        (2000.0, 33.0),
        (1000.0, 22.0),
        (500.0, 18.0),
        (250.0, 14.0),
    ]
    sea = nearshore.NearshoreSea(T0, 1.0, 6.0, 8.0, 260.0, 25.0, 15.2, 1400.0)
    assert nearshore.inner_samples(wet, sea) == [
        (1400.0, 15.2),
        (1000.0, 22.0),
        (500.0, 18.0),
        (250.0, 14.0),
    ]


SPOT = Spot(
    id="blacks-beach",
    name="Blacks",
    lat=32.8935,
    lon=-117.2538,
    timezone="America/Los_Angeles",
    offshore_point=(32.89, -117.31),
    offshore_direction=89.0,
    shore_normal=269.0,
    swell_window=(204.0, 334.0),
    height_coeff=1.0,
    break_type="beach",
    ideal_wind_dir=(45.0, 135.0),
    ideal_size_m=(0.8, 2.5),
)
WET = [
    (18000.0, 615.0),
    (12000.0, 335.0),
    (5000.0, 66.0),
    (2000.0, 33.0),
    (1000.0, 22.0),
    (500.0, 19.0),
    (250.0, 19.0),
]


def _hour() -> HourForecast:
    return HourForecast(
        time=T0,
        partitions=(SwellPartition(2.0, 9.0, 280.0, "swell", 12.0),),
        sst_c=18.0,
        wind_speed_kph=8.0,
        wind_dir_deg=90.0,
        wind_gusts_kph=None,
    )


def test_score_hour_without_a_sea_is_the_shipping_path():
    a = score_hour(SPOT, _hour(), WET)
    b = score_hour(SPOT, _hour(), WET, nearshore=None)
    assert a == b and a.nearshore is None
    assert "nearshore" not in _hour_entry(SPOT, a, ZoneInfo(SPOT.timezone))


def test_score_hour_with_a_sea_marches_from_the_handoff_point_and_says_so():
    march = score_hour(SPOT, _hour(), WET)
    # the model says the sea at 900 m is smaller and turned toward the normal than the
    # offshore partition marched over the whole ray would make it
    sea = nearshore.NearshoreSea(T0, 1.0, 7.0, 9.0, 262.0, 24.0, 16.6, 900.0)
    swan = score_hour(SPOT, _hour(), WET, nearshore=sea)
    assert swan.nearshore == "swan"
    assert swan.h_break_mid < march.h_break_mid
    # everything but the height link is untouched: the displayed partitions, the period
    # and wind terms, the energy
    assert swan.hour == march.hour and swan.dominant == march.dominant
    assert swan.period_score == march.period_score and swan.energy == march.energy
    assert _hour_entry(SPOT, swan, ZoneInfo(SPOT.timezone))["nearshore"] == "swan"
    # the model's sea drives the height: a bigger sea at the handoff breaks bigger
    bigger = score_hour(
        SPOT,
        _hour(),
        WET,
        nearshore=nearshore.NearshoreSea(T0, 2.0, 7.0, 9.0, 262.0, 24.0, 16.6, 900.0),
    )
    assert bigger.h_break_mid > swan.h_break_mid


def test_score_hour_with_a_sea_but_no_profile_ignores_it():
    a = score_hour(SPOT, _hour(), None)
    sea = nearshore.NearshoreSea(T0, 1.0, 7.0, 9.0, 262.0, 24.0, 16.6, 900.0)
    b = score_hour(SPOT, _hour(), None, nearshore=sea)
    assert a == b and b.nearshore is None
