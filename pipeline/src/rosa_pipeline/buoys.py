"""Buoy registry + nearest-buoy matching for the verification harness (roadmap Stage 0).

A ``Buoy`` is a validation ground-truth point: the harness samples the offshore model at
its coordinate and scores the forecast against the buoy's observations. Registry lives in
``data/buoys/*.yaml`` (NOAA/NDBC is public domain). Sparse by design - the eastern Med has
no NDBC coverage, so Israel is validated locally via ISRAMAR, not from this registry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

EARTH_R_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class Buoy:
    id: str
    name: str
    lat: float
    lon: float
    source: str  # "ndbc", later "cdip", "isramar" (local-only), ...


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(a))


def load_buoys(buoys_dir: Path) -> dict[str, Buoy]:
    buoys: dict[str, Buoy] = {}
    for path in sorted(buoys_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for raw in data["buoys"]:
            buoy = Buoy(
                id=str(raw["id"]),
                name=raw["name"],
                lat=float(raw["lat"]),
                lon=float(raw["lon"]),
                source=raw.get("source", "ndbc"),
            )
            if buoy.id in buoys:
                raise ValueError(f"duplicate buoy id {buoy.id!r} in {path}")
            buoys[buoy.id] = buoy
    return buoys


def load_all_buoys(buoys_dir: Path, isramar_dir: Path | None = None) -> dict[str, Buoy]:
    """Committed NDBC registry, plus the LOCAL-only ISRAMAR stations if present.

    ISRAMAR stations live under the gitignored ``data/verify/isramar/`` (never committed) so
    the eastern Med gets validation truth without shipping ISRAMAR's all-rights-reserved data.
    Its ``stations.yaml`` is loaded the same way; obs come from ISRAMARLocalSource (manual csv)."""
    buoys = load_buoys(buoys_dir)
    if isramar_dir is not None and isramar_dir.exists() and any(isramar_dir.glob("*.yaml")):
        for bid, buoy in load_buoys(isramar_dir).items():
            buoys[bid] = buoy
    return buoys


def nearest_buoys(
    lat: float, lon: float, buoys: dict[str, Buoy], *, radius_km: float, limit: int = 3
) -> list[tuple[Buoy, float]]:
    """Buoys within ``radius_km`` of (lat, lon), closest first, capped at ``limit``.
    Empty when nothing is in range - the honest answer for a spot with no nearby truth."""
    hits = [(b, haversine_km(lat, lon, b.lat, b.lon)) for b in buoys.values()]
    hits = [(b, d) for b, d in hits if d <= radius_km]
    hits.sort(key=lambda bd: bd[1])
    return hits[:limit]
