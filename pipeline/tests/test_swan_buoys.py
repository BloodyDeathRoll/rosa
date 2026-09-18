"""The Stage-4 buoy arm: SWAN tabled at the registered buoys, archived as the `swan` member."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rosa_pipeline import nearshore, swan
from rosa_pipeline.archive import FileArchiveStore
from rosa_pipeline.cli import SOURCE_KEY_SUFFIX, SOURCE_VARIABLES, main

FIXTURES = Path(__file__).parent / "fixtures"
WAVE_GRIB = FIXTURES / "gfswave" / "med_f000.grib2"
T0 = datetime(2026, 9, 14, 0, tzinfo=UTC)
OUTER = {"lon0": 31.0, "lat0": 32.0, "nx": 101, "ny": 101, "dlon": 0.01, "dlat": 0.01}
NEST = {"lon0": 31.3, "lat0": 32.3, "nx": 101, "ny": 51, "dlon": 0.002, "dlat": 0.002}


def test_assign_buoys_picks_the_finest_grid_and_drops_outsiders():
    buoys = [("in-nest", 32.35, 31.4), ("outer-only", 32.9, 31.9), ("far", 40.0, 20.0)]
    got = swan.assign_buoys(buoys, OUTER, {"cove": NEST})
    assert got == {"cove": [("in-nest", 32.35, 31.4)], "outer": [("outer-only", 32.9, 31.9)]}


def test_write_step_tables_buoys_per_grid(tmp_path):
    files = swan.write_step(
        tmp_path / "run",
        step=0,
        valid=T0,
        outer_meta=OUTER,
        wave_grib=WAVE_GRIB.read_bytes(),
        wind_grib=None,
        bottom_rel="../outer/bot.grd",
        points_rel="../points.loc",
        nests={"cove": NEST},
        buoy_points_rel={"outer": "buoys_outer.loc", "cove": "buoys_cove.loc"},
    )
    outer = files.input_path.read_text(encoding="utf-8")
    assert "POINTS 'BUOYS' FILE 'buoys_outer.loc'" in outer
    assert "TABLE 'BUOYS' HEAD 'buoys_f000.tab' XP YP DEP HSIGN TPS DIR DSPR TM01" in outer
    nest = (tmp_path / "run" / "INPUT_f000_cove").read_text(encoding="utf-8")
    assert "TABLE 'BUOYS' HEAD 'buoys_f000_cove.tab'" in nest
    # output requests stay ahead of COMPUTE
    assert outer.index("TABLE 'BUOYS'") < outer.index("COMPUTE")


def test_write_step_without_buoys_has_no_buoy_table(tmp_path):
    files = swan.write_step(
        tmp_path / "run",
        step=0,
        valid=T0,
        outer_meta=OUTER,
        wave_grib=WAVE_GRIB.read_bytes(),
        wind_grib=None,
        bottom_rel="../outer/bot.grd",
        points_rel="../points.loc",
    )
    assert "BUOYS" not in files.input_path.read_text(encoding="utf-8")


HEAD = (
    "%\n%\n% Run:f000  Table:BUOYS\n%\n"
    "%    Xp        Yp        Depth     Hsig      TPsmoo    Dir       Dspr      Tm01\n"
    "%    [degr]    [degr]    [m]       [m]       [sec]     [degr]    [degr]    [sec]\n%\n"
)


def _buoy_run(tmp_path: Path) -> Path:
    run = tmp_path / "run"
    run.mkdir()
    (run / "cycle.json").write_text(json.dumps({"cycle": T0.isoformat(), "steps": [0, 3]}))
    (run / "buoys.json").write_text(json.dumps({"cove": ["46254"], "outer": ["46225", "46254"]}))
    for step in (0, 3):
        tag = f"f{step:03d}"
        # the nest tables the nearshore buoy; the outer tables both, and its row for the
        # nearshore buoy must lose to the nest's
        (run / f"buoys_{tag}_cove.tab").write_text(
            HEAD + f" -117.267 32.868 38.0 {1.0 + step / 10:.2f} 12.0 250.0 25.0 8.0\n"
        )
        (run / f"buoys_{tag}.tab").write_text(
            HEAD
            + f" -117.391 32.933 550.0 {1.5 + step / 10:.2f} 13.0 255.0 24.0 9.0\n"
            + " -117.267 32.868 40.0 9.99 9.0 9.0 9.0 9.0\n"
        )
    return run


def test_load_buoys_and_archive_rows(tmp_path):
    run = _buoy_run(tmp_path)
    series = nearshore.load_buoys(run)
    assert sorted(series) == ["46225", "46254"]
    assert [s.hs for s in series["46254"]] == pytest.approx([1.0, 1.3])  # the nest's rows
    assert series["46254"][0].handoff_m == 0.0 and series["46254"][0].depth_m == 38.0
    rows = nearshore.archive_rows(series["46225"], T0)
    assert rows[1] == {
        "run": T0.isoformat(timespec="seconds"),
        "valid": (T0 + timedelta(hours=3)).isoformat(timespec="seconds"),
        "hs": 1.8,
        "tp": 13.0,
        "dir": 255.0,
        "tm01": 9.0,
        "dspr": 24.0,
    }
    # the archive command stamps its invocation time, like every member the swan card is
    # read against per lead bucket; the model cycle rides along (Dream 2026-09-18)
    now = T0 + timedelta(hours=5)
    stamped = nearshore.archive_rows(series["46225"], T0, run_time=now)
    assert stamped[1]["run"] == now.isoformat(timespec="seconds")
    assert stamped[1]["cycle"] == T0.isoformat(timespec="seconds")
    assert stamped[1]["valid"] == rows[1]["valid"]
    assert nearshore.load_buoys(tmp_path) == {}  # no buoys.json -> nothing, not an error


def test_swan_archive_command_appends_the_swan_member(tmp_path):
    run = _buoy_run(tmp_path)
    archive = tmp_path / "archive"
    assert main(["swan-archive", "--run", str(run), "--archive-dir", str(archive)]) == 0
    store = FileArchiveStore(archive)
    rows = store.read("46254" + SOURCE_KEY_SUFFIX["swan"])
    assert [r["hs"] for r in rows] == pytest.approx([1.0, 1.3])
    assert (archive / "46225.swan.jsonl").exists()
    # append-only: a second call adds the same cycle again, like the other members
    main(["swan-archive", "--run", str(run), "--archive-dir", str(archive)])
    assert len(store.read("46254.swan")) == 4


def test_swan_source_scores_peak_period_against_dpd_without_wind():
    variables = SOURCE_VARIABLES["swan"]
    assert [v[0] for v in variables] == ["hs", "tp", "dir"]
    assert dict((v[0], v[4]) for v in variables)["tp"] == "dpd_s"


def test_run_script_summarises_and_fails_on_a_failed_run():
    text = swan.run_script([0], ["cove"])
    assert 'echo "$line" >> run.log' in text
    assert "swan FAILED" in text and '[ "$FAILED" -eq 0 ]' in text.splitlines()[-1]
