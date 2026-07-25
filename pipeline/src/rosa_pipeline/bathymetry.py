"""Bathymetry ingest - seabed depth profile per spot (accuracy roadmap Stage 2A).

The Stage-2 transform replaces the single per-spot ``height_coeff`` with real shoaling +
refraction + depth-limited breaking. To do that it needs the depth the swell crosses on its
way in. This module samples that: a ray along the spot's shore-normal, from the break out to
deep water, at GEBCO resolution.

Source is behind ``BathymetrySource`` so the build-time GEBCO point API (today, no data
download) and a local GEBCO 2024 / EMODnet grid (later) are the same code path - the same
interface discipline the forecast fetch layer uses.

Convention: ``depth_m`` is metres **positive down** (= ``-elevation``); land / above-MSL is
negative. The ray runs SEAWARD along the spot's ``shore_normal``, so ``samples[0]`` is the
nearshore/break end and ``samples[-1]`` is the deep-water reference.

Attribution (legal §8): GEBCO Compilation Group (open); served via OpenTopoData. When a local
grid replaces the API, add EMODnet attribution too.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from .models import Spot

EARTH_R_KM = 6371.0088
OPENTOPODATA_URL = "https://api.opentopodata.org/v1/gebco2020"
MAX_LOCATIONS_PER_REQ = 100

# Seaward ray sample distances (km from the spot along the shore-normal). Dense nearshore to
# catch the shoaling gradient GEBCO can resolve, out to ~18 km for a deep-water reference.
RAY_DISTANCES_KM: tuple[float, ...] = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0, 12.0, 18.0)


@dataclass(frozen=True, slots=True)
class DepthSample:
    dist_km: float
    lat: float
    lon: float
    depth_m: float  # positive down; <= 0 means land / above MSL


@dataclass(frozen=True, slots=True)
class DepthProfile:
    spot_id: str
    bearing_seaward_deg: float
    samples: tuple[DepthSample, ...]

    @property
    def nearshore_depth_m(self) -> float:
        return self.samples[0].depth_m

    @property
    def offshore_depth_m(self) -> float:
        return self.samples[-1].depth_m

    @property
    def land_samples(self) -> int:
        """Count of ray points on land - > 0 in the offshore half flags a bad shore-normal."""
        return sum(1 for s in self.samples if s.depth_m <= 0)

    @property
    def mean_slope_m_per_km(self) -> float:
        near, far = self.samples[0], self.samples[-1]
        span = far.dist_km - near.dist_km
        return (far.depth_m - near.depth_m) / span if span else 0.0

    def wet_depths_deep_to_shallow(self) -> list[float]:
        """Wet-sample depths ordered deep -> shallow, the input the physics shoaling march
        wants (samples are stored nearshore-first, so reverse and drop dry/land points)."""
        return [s.depth_m for s in reversed(self.samples) if s.depth_m > 0]

    @classmethod
    def from_dict(cls, d: dict) -> DepthProfile:
        samples = tuple(
            DepthSample(dist_km=s["dist_km"], lat=s["lat"], lon=s["lon"], depth_m=s["depth_m"])
            for s in d["samples"]
        )
        return cls(
            spot_id=d["spot"], bearing_seaward_deg=d["bearing_seaward_deg"], samples=samples
        )

    def to_dict(self) -> dict:
        return {
            "spot": self.spot_id,
            "source": "gebco2020 via opentopodata",
            "bearing_seaward_deg": round(self.bearing_seaward_deg, 1),
            "nearshore_depth_m": round(self.nearshore_depth_m, 1),
            "offshore_depth_m": round(self.offshore_depth_m, 1),
            "mean_slope_m_per_km": round(self.mean_slope_m_per_km, 2),
            "land_samples": self.land_samples,
            "samples": [
                {
                    "dist_km": s.dist_km,
                    "lat": round(s.lat, 5),
                    "lon": round(s.lon, 5),
                    "depth_m": round(s.depth_m, 1),
                }
                for s in self.samples
            ],
        }


def destination(lat: float, lon: float, bearing_deg: float, dist_km: float) -> tuple[float, float]:
    """Great-circle destination point from (lat, lon) along a bearing (spherical earth)."""
    ang = dist_km / EARTH_R_KM
    br = math.radians(bearing_deg)
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(br)
    )
    lon2 = lon1 + math.atan2(
        math.sin(br) * math.sin(ang) * math.cos(lat1),
        math.cos(ang) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), (math.degrees(lon2) + 540.0) % 360.0 - 180.0


def ray_points(
    origin_lat: float,
    origin_lon: float,
    seaward_bearing_deg: float,
    distances: tuple[float, ...] = RAY_DISTANCES_KM,
) -> list[tuple[float, float, float]]:
    """(lat, lon, dist_km) sample points marching seaward from the spot along the shore-normal."""
    return [
        (*destination(origin_lat, origin_lon, seaward_bearing_deg, d), d) for d in distances
    ]


def _round_key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


class BathymetrySource(Protocol):
    def elevations(self, points: list[tuple[float, float]]) -> list[float | None]: ...


class OpenTopoDataSource:
    """GEBCO 2020 via the OpenTopoData point API (<= 100 locations/request, ~1 req/s).

    Optionally captures the raw {("lat,lon"): elevation} map to a single JSON fixture so the
    build and its tests can run fully offline afterwards - mirrors ``fetch.py``'s capture flow.
    """

    dataset = "gebco2020"

    def __init__(
        self,
        capture_dir: Path | None = None,
        timeout_s: float = 30.0,
        max_retries: int = 4,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._transport = transport  # injectable for offline tests

    def elevations(self, points: list[tuple[float, float]]) -> list[float | None]:
        if len(points) > MAX_LOCATIONS_PER_REQ:
            raise ValueError(f"OpenTopoData caps a request at {MAX_LOCATIONS_PER_REQ} locations")
        locations = "|".join(f"{lat:.5f},{lon:.5f}" for lat, lon in points)
        with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
            data = self._get_with_backoff(client, locations)
        if data.get("status") != "OK":
            raise RuntimeError(f"OpenTopoData error: {data.get('error', data.get('status'))}")
        elevations = [r.get("elevation") for r in data["results"]]
        if self.capture_dir is not None:
            self._capture(points, elevations)
        return elevations

    def _get_with_backoff(self, client: httpx.Client, locations: str) -> dict:
        """The public API rate-limits to ~1 req/s → retry 429 with exponential backoff
        (honouring Retry-After) so a full ``bathy --all`` sweep doesn't die mid-run."""
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            resp = client.get(OPENTOPODATA_URL, params={"locations": locations})
            if resp.status_code == 429 and attempt < self.max_retries:
                wait = float(resp.headers.get("retry-after", delay))
                time.sleep(wait)
                delay = min(delay * 2, 30.0)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("OpenTopoData: retries exhausted on 429")  # pragma: no cover

    def _capture(self, points: list[tuple[float, float]], elevations: list[float | None]) -> None:
        self.capture_dir.mkdir(parents=True, exist_ok=True)
        path = self.capture_dir / "bathy_elevations.json"
        store: dict[str, float | None] = {}
        if path.exists():
            store = json.loads(path.read_text(encoding="utf-8"))
        for (lat, lon), elev in zip(points, elevations, strict=True):
            store[_round_key(lat, lon)] = elev
        path.write_text(json.dumps(store, separators=(",", ":"), sort_keys=True), encoding="utf-8")


class FixtureBathymetrySource:
    """Replays a captured {("lat,lon"): elevation} map - offline tests + reproducible builds."""

    def __init__(self, mapping: dict[str, float | None]) -> None:
        self.mapping = mapping

    @classmethod
    def from_file(cls, path: Path) -> FixtureBathymetrySource:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def elevations(self, points: list[tuple[float, float]]) -> list[float | None]:
        out: list[float | None] = []
        for lat, lon in points:
            key = _round_key(lat, lon)
            if key not in self.mapping:
                raise KeyError(f"no captured elevation for {key}")
            out.append(self.mapping[key])
        return out


def load_profile(spot_id: str, bathy_dir: Path) -> DepthProfile | None:
    """Read a committed per-spot depth profile back (Stage 2B). None if not yet generated."""
    path = bathy_dir / f"{spot_id}.json"
    if not path.exists():
        return None
    return DepthProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))


def build_profile(source: BathymetrySource, spot: Spot) -> DepthProfile:
    """Sample the seabed along the spot's shore-normal (seaward), deep-water end last."""
    seaward = spot.shore_normal % 360.0
    pts = ray_points(spot.lat, spot.lon, seaward)
    elevations = source.elevations([(lat, lon) for lat, lon, _ in pts])
    samples = tuple(
        DepthSample(
            dist_km=dist,
            lat=lat,
            lon=lon,
            depth_m=(-elev if elev is not None else float("nan")),
        )
        for (lat, lon, dist), elev in zip(pts, elevations, strict=True)
    )
    return DepthProfile(spot_id=spot.id, bearing_seaward_deg=seaward, samples=samples)
