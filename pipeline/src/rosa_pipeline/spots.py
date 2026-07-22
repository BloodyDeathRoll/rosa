"""Load the spot database (data/spots/*.yaml) into Spot models.

Two per-spot fields are derived when not given explicitly, so a straight coast of
40 beaches needn't hand-author 40 orientations/sample points:

* ``offshore_point`` — each spot samples deep water at its own coordinate pushed
  ~0.06° west, so neighbours that fall in different marine-grid cells get distinct
  forecasts (a shared point made them identical). Override with ``offshore_point``.
* ``offshore_direction`` — normally set explicitly per spot in the DB (derived from
  the OSM coastline shore-normal). When absent, falls back to the local tangent
  between the neighbouring spots (file order is N→S) minus 90° for this W-facing
  coast — a coarse proxy that misreads sharp bends, so prefer the explicit value.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

from .models import Spot

OFFSHORE_LON_OFFSET = 0.06  # deg west (~5.5 km) to a deep-water grid cell


def _pair(value: Any) -> tuple[float, float]:
    a, b = value
    return float(a), float(b)


def _bearing(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle initial bearing a→b in degrees (0=N, 90=E)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlon = lon2 - lon1
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _derive_offshore_direction(rows: list[dict], i: int) -> float:
    """Offshore-wind source direction from the local coast tangent. Uses the spots
    just north and south (file order is N→S); the seaward-facing coast puts the
    offshore normal 90 deg clockwise of the southward tangent -> tangent - 90."""
    n = len(rows)
    a = rows[max(0, i - 1)]
    b = rows[min(n - 1, i + 1)]
    if a is b:  # lone spot — fall back to due-east (W-facing default)
        return 90.0
    tangent = _bearing((float(a["lat"]), float(a["lon"])), (float(b["lat"]), float(b["lon"])))
    return round((tangent - 90.0) % 360.0, 1)


def _region_from_stem(stem: str) -> str:
    """Filename "sri-lanka" -> display region "Sri Lanka"."""
    return stem.replace("-", " ").title()


def load_spots_file(path: Path) -> list[Spot]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    rows: list[dict] = data["spots"]
    region = data.get("region") or _region_from_stem(path.stem)
    spots: list[Spot] = []
    for i, raw in enumerate(rows):
        ideal = raw["ideal"]
        lat, lon = float(raw["lat"]), float(raw["lon"])
        offshore_point = (
            _pair(raw["offshore_point"])
            if "offshore_point" in raw
            else (round(lat, 4), round(lon - OFFSHORE_LON_OFFSET, 4))
        )
        offshore_direction = (
            float(raw["offshore_direction"])
            if "offshore_direction" in raw
            else _derive_offshore_direction(rows, i)
        )
        spots.append(
            Spot(
                id=raw["id"],
                name=raw["name"],
                lat=lat,
                lon=lon,
                timezone=raw["timezone"],
                offshore_point=offshore_point,
                offshore_direction=offshore_direction,
                swell_window=_pair(raw["swell_window"]),
                height_coeff=float(raw["height_coeff"]),
                break_type=raw["break_type"],
                ideal_wind_dir=_pair(ideal["wind_dir"]),
                ideal_size_m=_pair(ideal["size_m"]),
                region=region,
            )
        )
    return spots


def load_spots(spots_dir: Path) -> dict[str, Spot]:
    spots: dict[str, Spot] = {}
    for path in sorted(spots_dir.glob("*.yaml")):
        for spot in load_spots_file(path):
            if spot.id in spots:
                raise ValueError(f"duplicate spot id {spot.id!r} in {path}")
            spots[spot.id] = spot
    return spots
