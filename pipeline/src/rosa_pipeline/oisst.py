"""NOAA OISST daily sea-surface temperature (fetch-plane plan C2).

One 0.25-deg global netCDF per day (~1.5 MB), public domain, sampled at every spot from
the same download - O(1) in spot count, the fetch-plane property. Recent days publish as
``*_preliminary.nc`` (the final file replaces it ~2 weeks later); the fetcher tries
final-then-preliminary, walking back up to MAX_LAG_DAYS.

Consumed by the BLEND arm only: `blend.compose_raw` fills the payload's SST column with
the daily value (SST varies ~0.1 C intra-day - far below the model's own error). When the
fetch fails the column is blank for the cycle: since 2026-09-12 the blend arm makes no
marine-host request, so there is no OM value to fall back on. The OM arm is untouched.
SST is display + tail carry (extract's ``last_sst``), never rating physics, so this is
not pb_0049-gated - the promotion A/B still reports it.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from .geo import dlon180

BASE_URL = (
    "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr"
)
# yesterday's preliminary file usually lands during the day, but NOAA can stall for a
# week (2026-11: newest file 7 days old, 4 days left every spot blank); walk back this far
MAX_LAG_DAYS = 14
NEAREST_MAX_DEG = 1.0  # OISST is a smooth field; a coastal cell one degree out is fine
FILL = -999


def day_urls(day: datetime) -> list[str]:
    """Final first, then preliminary - the final file silently replaces it later."""
    stem = f"{BASE_URL}/{day:%Y%m}/oisst-avhrr-v02r01.{day:%Y%m%d}"
    return [f"{stem}.nc", f"{stem}_preliminary.nc"]


def parse_points(nc_bytes: bytes, points: list[tuple[float, float]]) -> list[float | None]:
    """SST in Celsius at each point's nearest wet cell (None when none in reach)."""
    import h5py
    import numpy as np

    with tempfile.NamedTemporaryFile(suffix=".nc") as tf:
        tf.write(nc_bytes)
        tf.flush()
        with h5py.File(tf.name, "r") as f:
            sst = f["sst"][0, 0, :, :].astype(float)  # int16 x scale
            scale = float(f["sst"].attrs.get("scale_factor", [0.01])[0])
            lats = f["lat"][:].astype(float)
            lons = f["lon"][:].astype(float)  # 0..360
    out: list[float | None] = []
    for lat, lon in points:
        lon360 = lon % 360.0
        i = int(np.argmin(np.abs(lats - lat)))
        j = int(np.argmin(np.abs(dlon180(lons, lon360))))
        # spiral out over the local window for a wet cell; the field is 0.25 deg so
        # NEAREST_MAX_DEG is a 4-cell reach each way. The lon axis is periodic, so the
        # window is taken by WRAPPED column index - clipping it at 0 would hide the
        # cells just west of Greenwich from a spot just east of it (see geo.dlon180).
        reach = int(NEAREST_MAX_DEG / 0.25)
        cols = np.mod(np.arange(j - reach, j + reach + 1), len(lons))
        rows = slice(max(0, i - reach), i + reach + 1)  # lat is NOT periodic
        win = sst[rows, :][:, cols]
        wlat = lats[rows]
        wlon = lons[cols]
        wet = np.argwhere(win != FILL)
        if len(wet) == 0:
            out.append(None)
            continue
        d2 = (wlat[wet[:, 0]] - lat) ** 2 + (
            np.cos(np.radians(lat)) * dlon180(wlon[wet[:, 1]], lon360)
        ) ** 2
        k = int(np.argmin(d2))
        out.append(round(float(win[wet[k, 0], wet[k, 1]]) * scale, 2))
    return out


class SstSource(Protocol):
    def fetch(self, points: list[tuple[float, float]]) -> list[float | None]: ...


class OisstSource:
    """Live NCEI fetch: newest available daily file, all points from one download."""

    def __init__(self, capture_dir: Path | None = None, timeout_s: float = 60.0) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s

    def fetch(self, points: list[tuple[float, float]]) -> list[float | None]:
        if not points:
            return []
        data = self._latest_bytes()
        if data is None:
            return [None] * len(points)
        if self.capture_dir is not None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            (self.capture_dir / "oisst.nc").write_bytes(data)
        return parse_points(data, points)

    def _latest_bytes(self) -> bytes | None:
        today = datetime.now(UTC)
        with httpx.Client(timeout=self.timeout_s) as client:
            for back in range(1, MAX_LAG_DAYS + 1):
                for url in day_urls(today - timedelta(days=back)):
                    try:
                        resp = client.get(url)
                    except httpx.HTTPError:
                        continue
                    if resp.status_code == 200 and resp.content[:4] == b"\x89HDF":
                        return resp.content
        return None


class OisstFixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, points: list[tuple[float, float]]) -> list[float | None]:
        path = self.fixtures_dir / "oisst.nc"
        if not path.exists():
            return [None] * len(points)
        return parse_points(path.read_bytes(), points)
