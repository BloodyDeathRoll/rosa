"""ISRAMAR manual-import adapter (local-only) + merged registry.

All data here is SYNTHETIC — ISRAMAR's real data is all-rights-reserved and never committed.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from rosa_pipeline.buoys import Buoy, load_all_buoys
from rosa_pipeline.observe import ISRAMARLocalSource, parse_isramar_csv

BUOYS_DIR = Path(__file__).resolve().parents[2] / "data" / "buoys"

SAMPLE = """# ISRAMAR manual-import (synthetic test data)
# time_utc, hs_m, period_s, dir_deg, wtmp_c
2026-07-19T07:00, 0.5, 6.5, 270, 28.0
2026-07-19T06:00, 0.4, -, ,
bad line without commas
2026-07-19T08:00, , 7.0, 280
"""


def test_parse_handles_missing_blank_and_bad_lines() -> None:
    obs = parse_isramar_csv(SAMPLE, "hadera")
    assert [o.time.hour for o in obs] == [6, 7, 8]  # oldest-first, bad line dropped
    o6, o7, o8 = obs
    assert o6.hs_m == 0.4 and o6.apd_s is None and o6.mwd_deg is None and o6.wtmp_c is None
    assert o7.hs_m == 0.5 and o7.apd_s == 6.5 and o7.mwd_deg == 270.0 and o7.wtmp_c == 28.0
    assert o8.hs_m is None and o8.apd_s == 7.0 and o8.mwd_deg == 280.0


def test_parse_times_default_to_utc() -> None:
    obs = parse_isramar_csv(SAMPLE, "x")
    assert all(o.time.tzinfo is UTC for o in obs)
    assert all(o.station == "x" for o in obs)


def test_local_source_reads_file_and_missing_is_empty(tmp_path) -> None:
    buoy = Buoy(id="hadera", name="Hadera", lat=32.47, lon=34.88, source="isramar")
    assert ISRAMARLocalSource(tmp_path).fetch(buoy) == []  # no file yet → empty, not error
    (tmp_path / "hadera.csv").write_text(SAMPLE, encoding="utf-8")
    obs = ISRAMARLocalSource(tmp_path).fetch(buoy)
    assert [o.hs_m for o in obs] == [0.4, 0.5, None]


def test_load_all_buoys_merges_local_isramar(tmp_path) -> None:
    (tmp_path / "stations.yaml").write_text(
        "buoys:\n  - id: hadera\n    name: Hadera\n    lat: 32.47\n    lon: 34.88\n"
        "    source: isramar\n",
        encoding="utf-8",
    )
    merged = load_all_buoys(BUOYS_DIR, tmp_path)
    assert "46042" in merged and merged["hadera"].source == "isramar"
    # without a local dir, only the committed NDBC registry is present
    assert "hadera" not in load_all_buoys(BUOYS_DIR, None)


def test_isramar_station_now_found_near_israel_spot(tmp_path) -> None:
    from rosa_pipeline.buoys import nearest_buoys

    (tmp_path / "stations.yaml").write_text(
        "buoys:\n  - id: hadera\n    name: Hadera\n    lat: 32.47\n    lon: 34.88\n"
        "    source: isramar\n",
        encoding="utf-8",
    )
    merged = load_all_buoys(BUOYS_DIR, tmp_path)
    # Beit Yanai (32.38, 34.80) previously had NO buoy in range; Hadera now covers it
    hits = nearest_buoys(32.38, 34.80, merged, radius_km=50)
    assert hits and hits[0][0].id == "hadera"
