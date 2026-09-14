"""swan.py - boundary spectra rebuilt from GFS-Wave partitions, SWAN file writers."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from rosa_pipeline import swan

FIXTURES = Path(__file__).parent / "fixtures"
WAVE_GRIB = FIXTURES / "gfswave" / "med_f000.grib2"
WIND_GRIB = FIXTURES / "gfsatmos" / "gfsatmos_f000_31.011_33.809_33.887_36.043.grib2"


def test_jonswap_returns_the_height_and_mean_period_it_was_given():
    """The shape is normalized on the grid, so Hs comes back exactly; the peak picked for
    a mean period gives that mean period back (a property of the shape, not a guess)."""
    freqs = swan.frequency_grid()
    for hs, tm in ((0.5, 5.0), (2.0, 9.0), (1.2, 14.0)):
        tp = swan.peak_period_for_mean(tm, freqs)
        s = swan.jonswap(freqs, hs, tp)
        assert 4.0 * math.sqrt(np.trapezoid(s, freqs)) == pytest.approx(hs, rel=1e-9)
        assert swan._tm01(freqs, s) == pytest.approx(tm, rel=0.03)
        assert tp > tm  # JONSWAP's peak is always longer than its mean


def test_spread_power_matches_the_payload_spread_classes():
    """sigma^2 = 2/(m+1): 35 deg wind sea is a broad m~4, 20 deg mid swell m~15."""
    assert swan.spread_power(35.0) == pytest.approx(4.36, abs=0.05)
    assert swan.spread_power(20.0) == pytest.approx(15.4, abs=0.1)
    assert swan.spread_deg("wind", 5.0) == 35.0
    assert swan.spread_deg("swell", 8.0) == 25.0
    assert swan.spread_deg("swell", 12.0) == 20.0
    assert swan.spread_deg("swell", 16.0) == 24.0


def test_synth_spectrum_adds_partitions_in_energy_and_points_where_they_came_from():
    freqs, dirs = swan.frequency_grid(), swan.direction_grid()
    parts = [swan.Partition("wind", 1.0, 5.0, 300.0), swan.Partition("swell", 1.5, 14.0, 195.0)]
    e = swan.synth_spectrum(parts, freqs, dirs)
    assert swan.significant_height(e, freqs, dirs) == pytest.approx(math.hypot(1.0, 1.5), rel=0.01)
    # the 14 s swell's energy sits in the low bins and on its 15 deg bin (195)
    low = e[freqs < 0.1].sum(axis=0)
    assert dirs[int(np.argmax(low))] == 195.0
    high = e[freqs > 0.15].sum(axis=0)
    assert dirs[int(np.argmax(high))] == 300.0
    # noise partitions and land nodes add nothing
    assert not np.any(
        swan.synth_spectrum([swan.Partition("swell", 0.01, 12.0, 90.0)], freqs, dirs) > 0
    )


def test_parse_gfs_grid_gives_ascending_axes_and_land_as_nan():
    g = swan.parse_gfs_grid(WAVE_GRIB.read_bytes())
    assert np.all(np.diff(g.lats) > 0) and np.all(np.diff(g.lons) > 0)
    assert {"swh", "shww", "mpww", "wvdir", "swell1_h", "swell1_p", "swell1_d", "swell3_d"} <= set(
        g.fields
    )
    assert np.isnan(g.fields["swh"]).any()  # the Med box holds land
    wet = np.argwhere(~np.isnan(g.fields["swh"]))
    i, j = map(int, wet[0])
    parts = swan.node_partitions(g, i, j)
    assert parts and all(p.hs >= 0 and p.tm01 > 0 for p in parts)


def _outer_inside_med_fixture() -> dict:
    # a 1 x 1 deg outer grid off the Egyptian coast, edges on the 0.25 lattice, all wet
    return {"lon0": 31.0, "lat0": 32.0, "nx": 101, "ny": 101, "dlon": 0.01, "dlat": 0.01}


def test_boundary_nodes_follow_the_open_sides_in_segment_order():
    g = swan.parse_gfs_grid(WAVE_GRIB.read_bytes())
    outer = {"west": 31.0, "south": 32.0, "east": 32.0, "north": 33.0}
    nodes = swan.boundary_nodes(g, outer)
    by_side = {s: [n for n in nodes if n.side == s] for s in ("W", "S", "N")}
    assert [n.lat for n in by_side["W"]] == [32.0, 32.25, 32.5, 32.75, 33.0]
    assert [n.along_deg for n in by_side["W"]] == [0.0, 0.25, 0.5, 0.75, 1.0]
    assert [n.lon for n in by_side["S"]] == [31.0, 31.25, 31.5, 31.75, 32.0]
    assert [n.along_deg for n in by_side["N"]] == [0.0, 0.25, 0.5, 0.75, 1.0]
    with pytest.raises(ValueError, match="not on the GFS lattice"):
        swan.boundary_nodes(g, {**outer, "west": 31.1})


def _read_sp2(path: Path) -> tuple[list[tuple[float, float]], np.ndarray, np.ndarray, list]:
    lines = path.read_text(encoding="utf-8").splitlines()
    k = lines.index(next(line for line in lines if line.startswith("LONLAT")))
    n = int(lines[k + 1].split()[0])
    locs = [tuple(map(float, lines[k + 2 + i].split())) for i in range(n)]
    k = lines.index(next(line for line in lines if line.startswith("AFREQ")))
    nf = int(lines[k + 1].split()[0])
    freqs = np.array([float(lines[k + 2 + i]) for i in range(nf)])
    k = lines.index(next(line for line in lines if line.startswith("NDIR")))
    nd = int(lines[k + 1].split()[0])
    dirs = np.array([float(lines[k + 2 + i]) for i in range(nd)])
    k = lines.index("QUANT") + 5
    blocks = []
    while k < len(lines):
        if lines[k] in ("NODATA", "ZERO"):
            blocks.append(None)
            k += 1
            continue
        assert lines[k] == "FACTOR"
        factor = float(lines[k + 1])
        rows = [np.array(lines[k + 2 + r].split(), dtype=float) for r in range(nf)]
        blocks.append(np.array(rows) * factor)
        k += 2 + nf
    return locs, freqs, dirs, blocks


def test_sp2_round_trips_through_swans_factor_encoding(tmp_path):
    freqs, dirs = swan.frequency_grid(), swan.direction_grid()
    e = swan.synth_spectrum([swan.Partition("swell", 2.0, 12.0, 250.0)], freqs, dirs)
    path = tmp_path / "b.sp2"
    swan.write_sp2(path, [(32.0, -121.0), (32.25, -121.0)], freqs, dirs, [e, None])
    text = path.read_text(encoding="utf-8")
    assert text.startswith("SWAN   1") and "TIME" not in text  # stationary: no TIME block
    locs, f2, d2, blocks = _read_sp2(path)
    assert locs == [(-121.0, 32.0), (-121.0, 32.25)]  # lon lat, SWAN's order
    assert np.allclose(f2, freqs, rtol=1e-5) and np.allclose(d2, dirs)
    assert blocks[1] is None
    assert swan.significant_height(blocks[0], f2, d2) == pytest.approx(2.0, rel=1e-3)


def test_boundspec_lines_number_the_locations_per_side():
    g = swan.parse_gfs_grid(WAVE_GRIB.read_bytes())
    outer = {"west": 31.0, "south": 32.0, "east": 32.0, "north": 33.0}
    nodes = swan.boundary_nodes(g, outer)
    lines = swan.boundspec_lines(nodes, outer, "f000")
    assert len(lines) == 3
    # one file per node, each name used once (SWAN refuses a repeated or missing name)
    assert lines[0] == (
        "BOUNDSPEC SEGMENT XY 31 32 31 33 VARIABLE FILE 0.0000 'bnd_f000_W0000.sp2' 1 "
        "0.2500 'bnd_f000_W0025.sp2' 1 0.5000 'bnd_f000_W0050.sp2' 1 "
        "0.7500 'bnd_f000_W0075.sp2' 1 1.0000 'bnd_f000_W0100.sp2' 1"
    )
    assert lines[1].startswith(
        "BOUNDSPEC SEGMENT XY 31 32 32 32 VARIABLE FILE 0.0000 'bnd_f000_S0000.sp2' 1 "
    )
    assert lines[2].startswith(
        "BOUNDSPEC SEGMENT XY 31 33 32 33 VARIABLE FILE 0.0000 'bnd_f000_N0000.sp2' 1 "
    )
    names = [p for line in lines for p in line.split("'")[1::2]]
    assert len(names) == len(set(names)) == 15


def test_write_step_produces_a_complete_stationary_run(tmp_path):
    outer = _outer_inside_med_fixture()
    files = swan.write_step(
        tmp_path / "run",
        step=0,
        valid=swan.valid_time(swan.datetime(2026, 9, 14, 6), 0),
        outer_meta=outer,
        wave_grib=WAVE_GRIB.read_bytes(),
        wind_grib=WIND_GRIB.read_bytes(),
        bottom_rel="../outer/bot.grd",
        points_rel="../points.loc",
    )
    assert files.nodes == 15 and files.hs_boundary_max > 0
    text = files.input_path.read_text(encoding="utf-8")
    assert "MODE STATIONARY TWODIMENSIONAL" in text
    assert "CGRID REGULAR 31 32 0. 1 1 100 100 CIRCLE 24 0.035 0.5 25" in text
    assert "READINP BOTTOM 1. '../outer/bot.grd' 3 0 FREE" in text
    assert "INPGRID WIND REGULAR 34 31.25 0. 8 10 0.25 0.25" in text
    assert "READINP WIND 1. 'wind_f000.dat' 3 0 FREE" in text
    assert text.count("BOUNDSPEC SEGMENT") == 3
    assert len(list((tmp_path / "run").glob("bnd_f000_*.sp2"))) == 15
    assert "TABLE 'SPOTS' HEAD 'spots_f000.tab' XP YP DEP HSIGN TPS DIR DSPR" in text
    wind_rows = (tmp_path / "run" / "wind_f000.dat").read_text().splitlines()
    assert len(wind_rows) == 2 * 11 and len(wind_rows[0].split()) == 9


def test_swan_command_replays_fixtures_offline(tmp_path):
    from rosa_pipeline.cli import main

    region = tmp_path / "data" / "swan" / "medtest"
    (region / "outer").mkdir(parents=True)
    (region / "outer" / "meta.json").write_text(json.dumps(_outer_inside_med_fixture()))
    fx = tmp_path / "fx"
    fx.mkdir()
    (fx / "swan_wave_f000.grib2").write_bytes(WAVE_GRIB.read_bytes())
    (fx / "swan_wind_f000.grib2").write_bytes(WIND_GRIB.read_bytes())
    import os

    cwd = os.getcwd()
    os.chdir(tmp_path)
    try:
        rc = main(
            [
                "swan",
                "--region",
                "medtest",
                "--steps",
                "0-3",
                "--fixtures",
                str(fx),
                "--cycle",
                "2026-09-14T06:00",
            ]
        )
    finally:
        os.chdir(cwd)
    assert rc == 0
    run = region / "run"
    assert (run / "INPUT_f000").exists() and (run / "bnd_f000_W0000.sp2").exists()
    assert not (run / "INPUT_f003").exists()  # no fixture for f003 -> skipped, not invented
    assert json.loads((run / "cycle.json").read_text())["written"] == 1
