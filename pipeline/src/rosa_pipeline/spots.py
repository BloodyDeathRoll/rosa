"""Load the spot database (data/spots/*.yaml) into Spot models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Spot


def _pair(value: Any) -> tuple[float, float]:
    a, b = value
    return float(a), float(b)


def load_spots_file(path: Path) -> list[Spot]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    points: dict[str, Any] = data.get("offshore_points", {})
    spots: list[Spot] = []
    for raw in data["spots"]:
        ideal = raw["ideal"]
        spots.append(
            Spot(
                id=raw["id"],
                name=raw["name"],
                lat=float(raw["lat"]),
                lon=float(raw["lon"]),
                timezone=raw["timezone"],
                offshore_point=_pair(points[raw["point"]]),
                offshore_direction=float(raw["offshore_direction"]),
                swell_window=_pair(raw["swell_window"]),
                height_coeff=float(raw["height_coeff"]),
                break_type=raw["break_type"],
                ideal_wind_dir=_pair(ideal["wind_dir"]),
                ideal_size_m=_pair(ideal["size_m"]),
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
