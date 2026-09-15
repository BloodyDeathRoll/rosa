"""Load the spot database (data/spots/*.yaml) into Spot models.

A spot's ``lat``/``lon`` is the SINGLE place its location is written down. Everything
else positional is derived from it, so correcting a pin never means hunting for copies
of the same coordinate - the deep-water sample follows the spot, and a stale bathymetry
profile is detected (see ``DepthProfile.matches_spot``) rather than silently believed.

Fields derived when not given explicitly, so a straight coast of 40 beaches needn't
hand-author 40 orientations/sample points:

* ``offshore_point`` - never stored. Each spot samples deep water at its own coordinate
  pushed ~0.06° west, so neighbours in different marine-grid cells get distinct forecasts
  (a shared point made them identical). Aim it elsewhere with ``offshore_km`` (+ optional
  ``offshore_bearing``, default = the seaward normal), which is relative to the pin -
  a coast that doesn't face west needs this.
* ``offshore_direction`` - normally set explicitly per spot in the DB (derived from
  the OSM coastline shore-normal). When absent, falls back to the local tangent
  between the neighbouring spots (file order is N→S) minus 90° for this W-facing
  coast - a coarse proxy that misreads sharp bends, so prefer the explicit value.
* ``shore_normal`` - seaward-facing azimuth for wave geometry (bathymetry ray,
  refraction). Defaults to ``offshore_direction + 180`` (the seaward normal for a spot
  whose best wind is straight offshore); override where they diverge (point breaks).
"""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import yaml

from .bathymetry import destination  # great-circle geodesy, shared rather than re-derived
from .models import Spot, SpotCam

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
    if a is b:  # lone spot - fall back to due-east (W-facing default)
        return 90.0
    tangent = _bearing((float(a["lat"]), float(a["lon"])), (float(b["lat"]), float(b["lon"])))
    return round((tangent - 90.0) % 360.0, 1)


def _offshore_point(lat: float, lon: float, raw: dict, shore_normal: float) -> tuple[float, float]:
    """Deep-water sample point, always expressed RELATIVE to the spot's own pin.

    ``offshore_km`` (with ``offshore_bearing``, defaulting to the seaward normal) casts a
    ray out from the spot; without it the spot falls back to the plain westward push, which
    only suits a west-facing coast. Deliberately never an absolute coordinate: a spot's
    lat/lon is the single place its location is written down, so correcting a pin carries
    the deep-water sample with it instead of leaving the forecast read from where the spot
    used to be.
    """
    if "offshore_km" in raw:
        bearing = float(raw.get("offshore_bearing", shore_normal))
        out_lat, out_lon = destination(lat, lon, bearing, float(raw["offshore_km"]))
        return round(out_lat, 4), round(out_lon, 4)
    return round(lat, 4), round(lon - OFFSHORE_LON_OFFSET, 4)


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
        if "offshore_point" in raw:
            raise ValueError(
                f"{raw['id']}: offshore_point was removed - it duplicated the spot's "
                "coordinates and went stale whenever a pin moved. Use offshore_km "
                "(+ offshore_bearing) so the sample point follows the pin."
            )
        offshore_direction = (
            float(raw["offshore_direction"])
            if "offshore_direction" in raw
            else _derive_offshore_direction(rows, i)
        )
        # Seaward normal for wave geometry (bathymetry ray, refraction). Defaults to the
        # opposite of the offshore wind direction; override where the two diverge (point
        # breaks whose best wind isn't simply opposite the coast, e.g. Arugam Bay).
        shore_normal = (
            float(raw["shore_normal"])
            if "shore_normal" in raw
            else (offshore_direction + 180.0) % 360.0
        )
        offshore_point = _offshore_point(lat, lon, raw, shore_normal)
        tide_best = raw.get("tide_best")
        if tide_best is not None and tide_best not in ("low", "mid", "high"):
            raise ValueError(f"{raw['id']}: tide_best must be low|mid|high, got {tide_best!r}")
        if "cam" in raw and "cams" in raw:
            raise ValueError(f"{raw['id']}: use either cam: or cams:, not both")
        raw_cams = raw.get("cams") or ([raw["cam"]] if raw.get("cam") else [])
        cams = []
        for raw_cam in raw_cams:
            missing = {"yt", "by", "by_url", "ch", "title"} - set(raw_cam)
            if missing:
                # a cam without its credit is exactly what we are not allowed to ship, and
                # one without ch + title goes dark at its stream's next restart
                raise ValueError(f"{raw['id']}: cam is missing {sorted(missing)}")
            if not re.fullmatch(r"UC[\w-]{22}", str(raw_cam["ch"])):
                raise ValueError(f"{raw['id']}: cam ch must be a UC... channel id")
            cams.append(
                SpotCam(
                    youtube_id=raw_cam["yt"],
                    by=raw_cam["by"],
                    by_url=raw_cam["by_url"],
                    channel_id=raw_cam["ch"],
                    title=str(raw_cam["title"]),
                    note=raw_cam.get("note"),
                    label=raw_cam.get("label"),
                )
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
                shore_normal=shore_normal,
                swell_window=_pair(raw["swell_window"]),
                height_coeff=float(raw["height_coeff"]),
                break_type=raw["break_type"],
                ideal_wind_dir=_pair(ideal["wind_dir"]),
                ideal_size_m=_pair(ideal["size_m"]),
                region=region,
                town=(raw.get("town") or None),
                tide_best=tide_best,
                cams=tuple(cams),
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
