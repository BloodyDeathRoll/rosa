#!/usr/bin/env python3
"""Local GEBCO sampler - reads seabed elevation from the GEBCO_2024 grid on disk
instead of the rate-capped OpenTopoData API. Download once (data/bathy/GEBCO_2024.nc,
~7.5 GB, gitignored), then bathy sampling is free, offline, and unlimited - which is
what lets the spot-seed pipeline scale worldwide.

elevations(points) returns GEBCO elevation in metres (negative = underwater), the
same convention as bathy_gate.gebco_elevations, so it's a drop-in swap.

Requires netCDF4 + numpy (tools/spot-seed/.venv). Run seed.py under that venv to use it.
"""

from __future__ import annotations
from pathlib import Path

DEFAULT_GRID = Path(__file__).resolve().parents[2] / "data" / "bathy" / "GEBCO_2024.nc"


class LocalGebco:
    def __init__(self, path=DEFAULT_GRID):
        import numpy as np
        from netCDF4 import Dataset

        self.np = np
        self.ds = Dataset(str(path))
        v = self.ds.variables
        latn = "lat" if "lat" in v else "latitude"
        lonn = "lon" if "lon" in v else "longitude"
        self.lat = np.asarray(v[latn][:], dtype="float64")
        self.lon = np.asarray(v[lonn][:], dtype="float64")
        dn = next(
            (n for n in ("elevation", "z") if n in v),
            next((k for k, var in v.items() if var.ndim == 2), None),
        )
        if dn is None:
            raise ValueError("no 2-D elevation variable found in grid")
        self.elev = v[dn]  # lazy [lat, lon]
        self.lat0, self.dlat = float(self.lat[0]), float(self.lat[1] - self.lat[0])
        self.lon0, self.dlon = float(self.lon[0]), float(self.lon[1] - self.lon[0])
        self.nlat, self.nlon = self.lat.size, self.lon.size

    def elevations(self, points):
        """points: list[(lat, lon)] -> list[float] elevation (neg = underwater)."""
        if not points:
            return []
        np = self.np
        la = np.array([p[0] for p in points], dtype="float64")
        lo = np.array([p[1] for p in points], dtype="float64")
        ii = np.clip(np.round((la - self.lat0) / self.dlat).astype(int), 0, self.nlat - 1)
        jj = np.clip(np.round((lo - self.lon0) / self.dlon).astype(int), 0, self.nlon - 1)
        # one bounding-box read, then local indexing - far faster than per-point disk hits
        i0, i1 = int(ii.min()), int(ii.max())
        j0, j1 = int(jj.min()), int(jj.max())
        sub = np.asarray(self.elev[i0 : i1 + 1, j0 : j1 + 1], dtype="float64")
        return [float(sub[i - i0, j - j0]) for i, j in zip(ii, jj)]


if __name__ == "__main__":
    import sys

    g = LocalGebco()
    print(
        f"grid: {g.nlat}x{g.nlon}  lat[{g.lat0:.4f}..{float(g.lat[-1]):.4f}] "
        f"lon[{g.lon0:.4f}..{float(g.lon[-1]):.4f}]  dlat={g.dlat:.6f}"
    )
    # smoke: a known-deep point + a land point
    pts = [(5.90, 80.40), (32.0, 34.6), (0.0, 0.0)]
    for p, e in zip(pts, g.elevations(pts)):
        print(f"  {p} -> {e:.0f} m")
