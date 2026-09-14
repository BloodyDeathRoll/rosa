"""swan.py - nest INPUTs, hot-start chains and the run script (plan 4.3)."""

from __future__ import annotations

import json
from pathlib import Path

from rosa_pipeline import swan

FIXTURES = Path(__file__).parent / "fixtures"
WAVE_GRIB = FIXTURES / "gfswave" / "med_f000.grib2"

OUTER = {"lon0": 31.0, "lat0": 32.0, "nx": 101, "ny": 101, "dlon": 0.01, "dlat": 0.01}
NEST = {"lon0": 31.3, "lat0": 32.3, "nx": 101, "ny": 51, "dlon": 0.002, "dlat": 0.002}


def test_outer_writes_nest_boundaries_and_nest_input_reads_them(tmp_path):
    files = swan.write_step(
        tmp_path / "run",
        step=3,
        valid=swan.valid_time(swan.datetime(2026, 9, 14, 6), 3),
        outer_meta=OUTER,
        wave_grib=WAVE_GRIB.read_bytes(),
        wind_grib=None,
        bottom_rel="../outer/bot.grd",
        points_rel="../points.loc",
        nests={"cove": NEST},
        nest_points_rel={"cove": "points_cove.loc"},
        hotstart_tag="f000",
    )
    outer = files.input_path.read_text(encoding="utf-8")
    assert "NGRID 'cove' 31.3 32.3 0. 0.2 0.1 100 50" in outer
    assert "NESTOUT 'cove' 'nest_cove_f003.sp2'" in outer
    assert "INITIAL HOTSTART 'hot_outer_f000' UNFORMATTED" in outer
    assert outer.rstrip().endswith("COMPUTE\nHOTFILE 'hot_outer_f003' UNFORMATTED\nSTOP")
    # output requests precede COMPUTE; the hot file follows it (SWAN's required order)
    assert outer.index("NESTOUT") < outer.index("COMPUTE") < outer.index("HOTFILE")
    nest = (tmp_path / "run" / "INPUT_f003_cove").read_text(encoding="utf-8")
    assert "CGRID REGULAR 31.3 32.3 0. 0.2 0.1 100 50 CIRCLE 24" in nest
    assert "READINP BOTTOM 1. '../cove/bot.grd' 3 0 FREE" in nest
    assert "BOUNDNEST1 NEST 'nest_cove_f003.sp2' CLOSED" in nest
    assert "BOUNDSPEC" not in nest
    assert (
        "INITIAL HOTSTART 'hot_cove_f000' UNFORMATTED" in nest
        and "HOTFILE 'hot_cove_f003' UNFORMATTED" in nest
    )
    assert "POINTS 'SPOTS' FILE 'points_cove.loc'" in nest
    assert "TABLE 'SPOTS' HEAD 'spots_f003_cove.tab'" in nest


def test_first_step_of_a_chain_has_no_hotstart_but_writes_one(tmp_path):
    files = swan.write_step(
        tmp_path / "run",
        step=0,
        valid=swan.valid_time(swan.datetime(2026, 9, 14, 6), 0),
        outer_meta=OUTER,
        wave_grib=WAVE_GRIB.read_bytes(),
        wind_grib=None,
        bottom_rel="../outer/bot.grd",
        points_rel="../points.loc",
        nests={"cove": NEST},
    )
    text = files.input_path.read_text(encoding="utf-8")
    assert "INITIAL HOTSTART" not in text and "HOTFILE 'hot_outer_f000' UNFORMATTED" in text


def test_region_grids_reads_every_built_grid(tmp_path):
    region = tmp_path / "socal"
    for name, meta in (("outer", OUTER), ("cove", NEST), ("bay", NEST)):
        (region / name).mkdir(parents=True)
        (region / name / "meta.json").write_text(json.dumps(meta))
    (region / "src").mkdir()  # the gitignored source cache holds no meta.json
    outer, nests = swan.region_grids(region)
    assert outer == OUTER and sorted(nests) == ["bay", "cove"]


def test_run_script_runs_outer_then_nests_per_step():
    text = swan.run_script([0, 3], ["cove", "bay"])
    order = [line for line in text.splitlines() if line.startswith("run f")]
    assert order == [
        "run f000",
        "run f000_cove",
        "run f000_bay",
        "run f003",
        "run f003_cove",
        "run f003_bay",
    ]
    assert 'cp "INPUT_$1" INPUT' in text and "OMP_NUM_THREADS" in text
