"""CMEMS Global Coastal SDB - satellite-derived bathymetry for the nearshore ray points.

Why this exists (docs/OPEN-ITEMS.md item 23, measured 2026-08-27). On coral atolls the
committed profiles start in deep water: the pipeline's ``gebco2020`` API reads 84-280 m at
0.25 km off a Maldivian reef where the local ``GEBCO_2024.nc`` grid reads 1-36 m, and the
two disagree by more than 50 m at 33 of 69 nearshore points there. The physics then marches
the swell from a depth it has long since passed, so a reef-pass ``h_break`` is essentially
deep-water swell with no shoaling gain.

This module adds a THIRD, independent measurement of the same nearshore band:
``BATHYMETRY_GLO_PHY_COASTAL_L4_MY_016_001`` (DOI 10.48670/mds-00364, released 2025-11),
100 m global Sentinel-2 SDB. It is a measurement, not a model - patching a ray point with
it is a source swap, NOT the "append invented shallow samples" that docs/ALGORITHM.md
forbids. Nothing is fabricated: where SDB has no reading, the GEBCO sample stands.

**It is not the default and must not become one without an A/B.** Merging moves published
heights, so CLAUDE.md's tuning rule applies: same-input A/B on the shipped harness plus a
docs/CALIBRATION.md entry, in the same change. Until then ``sdb --apply`` is an operator
action and ``bathy`` is untouched. Validate against ICESat-2 lidar first - see atl24.py.

Licence (legal section of CLAUDE.md): Copernicus Marine Service Licence - worldwide,
non-exclusive, royalty-free, perpetual right to create and distribute derived work for any
purpose, commercial included. Attribution is REQUIRED and reads "Generated using E.U.
Copernicus Marine Service Information; https://doi.org/10.48670/mds-00364". Free of charge
is guaranteed only to 2028-06-30 - re-verify before then.

Access: the store is Zarr v2 on CloudFerro S3 and reads anonymously over plain HTTP, which
is why this needs no account and no toolbox. The DOCUMENTED route is the ``copernicusmarine``
toolbox with a free account, so treat the open bucket as convenient rather than guaranteed;
if it ever closes, the fix is a fetch adapter, not a new algorithm.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .bathymetry import DepthProfile

SDB_ZARR_URL = (
    "https://s3.waw3-1.cloudferro.com/mdl-arco-time-003/arco/"
    "BATHYMETRY_GLO_PHY_COASTAL_L4_MY_016_001/"
    "cmems_obs-sdb_glo_phy_comp_my_100m-l4-s2_static_202511/static.zarr"
)
ATTRIBUTION = (
    "Generated using E.U. Copernicus Marine Service Information; https://doi.org/10.48670/mds-00364"
)

# Grid geometry, read off the store's own .zmetadata 2026-08-27 and pinned here so a
# sample can be located without fetching metadata on every call. Pixel-CENTRE convention:
# the first row/column sits half a step inside the -90 / -180 corner.
GRID_STEP_DEG = 1.0 / 960.0  # = 116.0 m at the equator
GRID_LAT0 = -90.0 + GRID_STEP_DEG / 2.0
GRID_LON0 = -180.0 + GRID_STEP_DEG / 2.0
GRID_SHAPE = (172800, 345600)
CHUNK_SHAPE = (1024, 1024)

# Quality_indicator flag_values: 0 Highly_reliable, 1 Reliable, 2 Moderately_reliable,
# 3 High_uncertainties, 4 Unknown_uncertainties. Default gate keeps 0-2: below that the
# product itself declines to vouch for the number, and a wrong shallow depth is worse than
# no shallow depth - it would make the physics shoal a wave onto seabed that isn't there.
MAX_QUALITY_FLAG = 2

# Half-width of the sampling window in pixels. SDB is patchy at pixel resolution - a single
# cloud, a boat wake or a breaking wave leaves a hole - so a point sample misses about 60%
# of the fleet while a 5x5 median finds a reading at 23 of 23 Maldivian spots at 0.25 km
# (measured 2026-08-27). The median, not the mean, so one bad pixel cannot drag the value.
WINDOW_RADIUS_PX = 2

# The product's own stated ceiling; deeper than this it has no signal and returns NaN.
# Recorded so a reader knows an empty result past ~35 m is the instrument, not a bug.
MAX_SDB_DEPTH_M = 35.0


def _round_key(lat: float, lon: float) -> str:
    return f"{lat:.5f},{lon:.5f}"


@dataclass(frozen=True, slots=True)
class SdbReading:
    """One gated SDB sample. ``depth_m`` is positive down, matching DepthSample."""

    depth_m: float
    quality: int
    n_pixels: int  # how many of the window's pixels carried a value


class CmemsSdbSource:
    """Reads the CMEMS SDB Zarr store over HTTP, one 1024x1024 chunk at a time.

    Chunks are cached in memory for the life of the object and, optionally, on disk - a
    ``--all`` sweep over a region re-reads the same handful of chunks for every spot.
    """

    dataset = "cmems-sdb-100m"

    def __init__(
        self,
        base_url: str = SDB_ZARR_URL,
        cache_dir: Path | None = None,
        max_quality: int = MAX_QUALITY_FLAG,
        window_radius_px: int = WINDOW_RADIUS_PX,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.max_quality = max_quality
        self.window_radius_px = window_radius_px
        self.timeout_s = timeout_s
        self._transport = transport  # injectable for offline tests
        self._chunks: dict[tuple[str, int, int], object] = {}
        self._client: httpx.Client | None = None

    # -- chunk plumbing ----------------------------------------------------------------

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_s, transport=self._transport)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _raw_chunk(self, var: str, by: int, bx: int) -> bytes | None:
        """Compressed chunk bytes, or None where the store has no chunk (all-fill area)."""
        rel = f"{var}/{by}.{bx}"
        if self.cache_dir is not None:
            cached = self.cache_dir / var / f"{by}.{bx}.blosc"
            if cached.exists():
                data = cached.read_bytes()
                return None if data == b"" else data
        resp = self._http().get(f"{self.base_url}/{rel}")
        if resp.status_code == 404:
            data = b""  # a missing chunk is "no data here", not an error
        else:
            resp.raise_for_status()
            data = resp.content
        if self.cache_dir is not None:
            cached = self.cache_dir / var / f"{by}.{bx}.blosc"
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)
        return None if data == b"" else data

    def _chunk(self, var: str, by: int, bx: int, dtype: str):
        key = (var, by, bx)
        if key not in self._chunks:
            import numcodecs
            import numpy as np

            raw = self._raw_chunk(var, by, bx)
            if raw is None:
                self._chunks[key] = None
            else:
                codec = numcodecs.Blosc()
                buf = codec.decode(raw)
                self._chunks[key] = np.frombuffer(buf, dtype=dtype).reshape(CHUNK_SHAPE)
        return self._chunks[key]

    # -- sampling ----------------------------------------------------------------------

    def _pixel(self, lat: float, lon: float) -> tuple[int, int]:
        i = round((lat - GRID_LAT0) / GRID_STEP_DEG)
        j = round((lon - GRID_LON0) / GRID_STEP_DEG)
        return i, j

    def reading(self, lat: float, lon: float) -> SdbReading | None:
        """Median depth over the window, gated on Quality_indicator. None if nothing passes."""
        import numpy as np

        ci, cj = self._pixel(lat, lon)
        r = self.window_radius_px
        depths: list[float] = []
        quals: list[int] = []
        for i in range(ci - r, ci + r + 1):
            if not 0 <= i < GRID_SHAPE[0]:
                continue
            for j in range(cj - r, cj + r + 1):
                if not 0 <= j < GRID_SHAPE[1]:
                    continue
                h = self._chunk("height", i // CHUNK_SHAPE[0], j // CHUNK_SHAPE[1], "<f4")
                if h is None:
                    continue
                value = float(h[i % CHUNK_SHAPE[0], j % CHUNK_SHAPE[1]])
                if not math.isfinite(value):
                    continue
                q = self._chunk(
                    "Quality_indicator", i // CHUNK_SHAPE[0], j // CHUNK_SHAPE[1], "|i1"
                )
                flag = int(q[i % CHUNK_SHAPE[0], j % CHUNK_SHAPE[1]]) if q is not None else 4
                if flag > self.max_quality:
                    continue
                # the store's `height` is elevation (negative down); depth is positive down
                depths.append(-value)
                quals.append(flag)
        if not depths:
            return None
        return SdbReading(
            depth_m=float(np.median(depths)),
            quality=int(max(quals)),  # worst flag that survived the gate, not the best
            n_pixels=len(depths),
        )

    def readings(self, points: list[tuple[float, float]]) -> list[SdbReading | None]:
        return [self.reading(lat, lon) for lat, lon in points]

    def elevations(self, points: list[tuple[float, float]]) -> list[float | None]:
        """``BathymetrySource`` shape, so this can stand in for GEBCO where it has data."""
        return [None if r is None else -r.depth_m for r in self.readings(points)]

    def capture(self, points: list[tuple[float, float]], path: Path) -> None:
        """Write a {("lat,lon"): [depth_m, quality, n_pixels] | null} fixture, so tests and
        reproducible builds never touch the network - mirrors OpenTopoDataSource._capture."""
        store: dict[str, list[float] | None] = {}
        if path.exists():
            store = json.loads(path.read_text(encoding="utf-8"))
        for (lat, lon), r in zip(points, self.readings(points), strict=True):
            store[_round_key(lat, lon)] = (
                None
                if r is None
                else [
                    round(r.depth_m, 2),
                    r.quality,
                    r.n_pixels,
                ]
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, separators=(",", ":"), sort_keys=True), encoding="utf-8")


class FixtureSdbSource:
    """Replays a captured SDB map - offline tests and reproducible builds."""

    dataset = "cmems-sdb-100m"

    def __init__(self, mapping: dict[str, list[float] | None]) -> None:
        self.mapping = mapping

    @classmethod
    def from_file(cls, path: Path) -> FixtureSdbSource:
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def reading(self, lat: float, lon: float) -> SdbReading | None:
        key = _round_key(lat, lon)
        if key not in self.mapping:
            raise KeyError(f"no captured SDB reading for {key}")
        row = self.mapping[key]
        return None if row is None else SdbReading(float(row[0]), int(row[1]), int(row[2]))

    def readings(self, points: list[tuple[float, float]]) -> list[SdbReading | None]:
        return [self.reading(lat, lon) for lat, lon in points]

    def elevations(self, points: list[tuple[float, float]]) -> list[float | None]:
        return [None if r is None else -r.depth_m for r in self.readings(points)]


# -- merge ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PatchedSample:
    dist_km: float
    was_m: float | None  # None where GEBCO had no reading at all
    now_m: float
    quality: int


def merge_profile(
    profile: DepthProfile,
    readings: list[SdbReading | None],
    min_delta_m: float = 1.0,
) -> tuple[DepthProfile, list[PatchedSample]]:
    """Replace ray points where SDB measured the seabed and GEBCO did not see it.

    The rule is deliberately narrow, and each clause is there to keep this a source swap
    rather than a fabrication:

    * SDB must HAVE a gated reading at that exact ray point. No interpolation along the
      ray, no extrapolation past its ~35 m ceiling, no filling of a point it missed.
    * A GEBCO sample that is missing (NaN) is filled, because "no data" loses to data.
    * Otherwise SDB must disagree by more than ``min_delta_m``, so the two agreeing
      within a metre leaves the committed profile bit-identical.

    Note what is NOT here: no requirement that SDB be shallower. It usually is, but
    encoding that would make this a one-way correction and quietly bias the fleet.

    Returns the new profile and the list of points it changed - the caller reports them.
    """
    from .bathymetry import DepthProfile, DepthSample

    if len(readings) != len(profile.samples):
        raise ValueError(
            f"{profile.spot_id}: {len(readings)} SDB readings for {len(profile.samples)} ray points"
        )
    patched: list[PatchedSample] = []
    samples: list[DepthSample] = []
    for sample, r in zip(profile.samples, readings, strict=True):
        if r is None:
            samples.append(sample)
            continue
        had = math.isfinite(sample.depth_m)
        if had and abs(sample.depth_m - r.depth_m) <= min_delta_m:
            samples.append(sample)
            continue
        patched.append(
            PatchedSample(
                dist_km=sample.dist_km,
                was_m=sample.depth_m if had else None,
                now_m=r.depth_m,
                quality=r.quality,
            )
        )
        samples.append(
            DepthSample(dist_km=sample.dist_km, lat=sample.lat, lon=sample.lon, depth_m=r.depth_m)
        )
    merged = DepthProfile(
        spot_id=profile.spot_id,
        bearing_seaward_deg=profile.bearing_seaward_deg,
        samples=tuple(samples),
        origin_lat=profile.origin_lat,
        origin_lon=profile.origin_lon,
        # provenance travels with the profile: to_dict names both grids in `source`
        sdb_patched_km=tuple(p.dist_km for p in patched),
    )
    return merged, patched
