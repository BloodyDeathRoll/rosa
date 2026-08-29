"""Coastal wind-station registry: loading, the committed METAR file, nearest lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from rosa_pipeline.stations import Station, load_stations, nearest_station

ROOT = Path(__file__).resolve().parents[2]


def test_committed_metar_registry_loads_with_unique_ids() -> None:
    stations = load_stations(ROOT / "data" / "stations")
    assert len(stations) >= 80  # 90 on 2026-08-29; regenerated after spot-DB changes
    assert all(s.source in ("metar", "ims") for s in stations.values())
    assert stations["LLBG"].lat == pytest.approx(32.011, abs=1e-3)


def test_missing_dir_is_no_stations(tmp_path: Path) -> None:
    assert load_stations(tmp_path / "nope") == {}


def test_duplicate_id_across_files_raises(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        'stations:\n  - {id: "X", name: "a", lat: 1, lon: 2, source: metar}\n'
    )
    (tmp_path / "b.yaml").write_text(
        'stations:\n  - {id: "X", name: "b", lat: 1, lon: 2, source: ims}\n'
    )
    with pytest.raises(ValueError, match="duplicate station id"):
        load_stations(tmp_path)


def test_nearest_station_respects_radius() -> None:
    stations = {
        "A": Station("A", "a", 32.0, 34.8, "metar"),
        "B": Station("B", "b", 32.1, 34.8, "metar"),
    }
    hit = nearest_station(32.09, 34.8, stations, radius_km=25)
    assert hit is not None and hit[0].id == "B" and hit[1] < 2
    assert nearest_station(40.0, 34.8, stations, radius_km=25) is None
