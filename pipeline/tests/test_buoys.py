"""Buoy registry loading + nearest-buoy matching."""

from __future__ import annotations

from pathlib import Path

from rosa_pipeline.buoys import Buoy, haversine_km, load_buoys, nearest_buoys

BUOYS_DIR = Path(__file__).resolve().parents[2] / "data" / "buoys"


def _registry() -> dict[str, Buoy]:
    return load_buoys(BUOYS_DIR)


def test_registry_loads_and_is_unique() -> None:
    buoys = _registry()
    assert "46042" in buoys
    assert buoys["46042"].source == "ndbc"
    # ids are strings even though the yaml value looks numeric
    assert all(isinstance(b.id, str) for b in buoys.values())


def test_haversine_known_distance() -> None:
    # ~1 degree of latitude ≈ 111 km
    assert 110 < haversine_km(36.0, -122.0, 37.0, -122.0) < 112


def test_nearest_orders_by_distance_and_caps() -> None:
    buoys = _registry()
    # near buoy 46042 (Monterey): 46026 (SF) is the next closest CA buoy
    hits = nearest_buoys(36.785, -122.408, buoys, radius_km=300, limit=2)
    assert [b.id for b, _ in hits] == ["46042", "46026"]
    assert hits[0][1] < hits[1][1]  # sorted ascending by distance


def test_nearest_empty_when_out_of_range() -> None:
    buoys = _registry()
    # Israel — no NDBC buoy within 150 km (the honest coverage gap)
    assert nearest_buoys(32.38, 34.80, buoys, radius_km=150) == []
