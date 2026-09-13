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


def test_discover_metar_keeps_a_registered_station_missing_from_the_snapshot(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """The METAR cache lists only airfields that reported in the last few hours, so a field
    closed at that hour is absent from it. Rediscovery must keep a registered station while
    a spot is in reach (dropping it ends its archive) and still drop one no spot is near."""
    import gzip
    import re

    import httpx

    from rosa_pipeline import cli
    from rosa_pipeline.spots import load_spots

    spot = next(iter(load_spots(ROOT / "data" / "spots").values()))
    reg = tmp_path / "stations"
    reg.mkdir()
    (reg / "metar.yaml").write_text(
        "stations:\n"
        f'  - {{id: "QUIET", name: "Closed tonight", lat: {spot.lat}, lon: {spot.lon}, '
        "source: metar}\n"
        '  - {id: "GONE", name: "No spot near", lat: 0.0, lon: -150.0, source: metar}\n'
    )
    csv = (
        "raw_text,station_id,observation_time,latitude,longitude\n"
        f"X,LIVE,t,{spot.lat + 0.01},{spot.lon}\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".csv.gz"):
            return httpx.Response(200, content=gzip.compress(csv.encode()))
        return httpx.Response(200, json=[{"icaoId": "LIVE", "name": "Live Field"}])

    real_client = httpx.Client
    monkeypatch.setattr(
        cli.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    rc = cli.main(
        [
            "stations",
            "--discover",
            "metar",
            "--spots-dir",
            str(ROOT / "data" / "spots"),
            "--stations-dir",
            str(reg),
        ]
    )
    out, err = capsys.readouterr()
    assert rc == 0
    assert re.findall(r'id: "([A-Z]+)"', out) == ["LIVE", "QUIET"]
    assert "kept 1 registered station" in err
