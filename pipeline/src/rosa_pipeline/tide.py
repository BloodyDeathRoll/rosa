"""EOT20 tide - per-spot harmonic constants, evaluated locally (fetch-plane plan C1).

Two halves, deliberately asymmetric:

* **Extraction** (`extract_constants`, the ``tide`` CLI) runs ONCE per spot on a machine
  holding the EOT20 constituent grids (`data/tide-src/ocean_tides/`, 2.1 GB, gitignored -
  redownload: SEANOE 10.17882/79489). It samples the 17 constituents at the spot's derived
  offshore point and writes a ~1 KB JSON to `data/spots/derived/tide/{spot}.json`, which IS
  committed - the bathy-profile pattern exactly.
* **Synthesis** (`predict`) runs every cycle anywhere from the committed constants alone:
  h(t) = Σ f_k(t) · (re_k·cos θ_k(t) + im_k·sin θ_k(t)), with nodal factors f, u and
  astronomical argument G from pyTMD (FES corrections - EOT20 is FES-formatted). No grid,
  no network, no quota. This is what replaces Open-Meteo's ``sea_level_height_msl``.

Verification before any switch (plan C1 acceptance): amplitude AND phase against the OM
series at the published fleet - see CALIBRATION.md 2026-08-14. Until that entry records a
pass, nothing in extract/publish consumes this module; the CLI is report-and-write only.

Conventions, verified against the M2 grid directly (2026-08-14):
units cm; phase degrees; ``real`` = A·cosφ, ``imag`` = A·sinφ; land cells carry the
_FillValue 0.0 in every field, so a cell with amplitude exactly 0 in ALL constituents is
land, not calm water. Constants are stored in METERS.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from .buoys import haversine_km
from .geo import dlon180
from .models import Spot

# EOT20's 17 constituents, named as pyTMD knows them; filename stems are upper-case.
CONSTITUENTS: tuple[str, ...] = (
    "2n2",
    "j1",
    "k1",
    "k2",
    "m2",
    "m4",
    "mf",
    "mm",
    "n2",
    "o1",
    "p1",
    "q1",
    "s1",
    "s2",
    "sa",
    "ssa",
    "t2",
)
# pyTMD's tide epoch: days are measured from 1992-01-01T00:00:00 UTC (MJD 48622)
_TIDE_EPOCH = datetime(1992, 1, 1, tzinfo=UTC)
_MJD_TIDE = 48622.0
# how far from the requested point a wet cell may be adopted (deg); the grid is 0.125 deg,
# so this allows a ~4-cell search ring for pins whose offshore point sits in a masked cell
NEAREST_MAX_DEG = 0.5
# how far the committed origin may sit from the spot's offshore point before the constants
# count as stale. Both are rounded to 4 dp (~11 m), so this is exact-match with slack for
# the rounding, matching bathymetry.ORIGIN_TOLERANCE_M.
ORIGIN_TOLERANCE_M = 10.0


@dataclass(frozen=True, slots=True)
class TideConstants:
    """Per-spot harmonic constants (meters), plus where they were actually sampled."""

    spot_id: str
    origin: tuple[float, float]  # the offshore point the extraction aimed for
    sample: tuple[float, float]  # the wet grid cell actually used
    method: str  # "bilinear" | "nearest"
    # constituent -> (re, im) in meters, EOT20 convention (re = A cos phi, im = A sin phi)
    coeffs: dict[str, tuple[float, float]]

    def matches_spot(self, spot: Spot, tol_m: float = ORIGIN_TOLERANCE_M) -> bool:
        """Were these constants sampled at the offshore point the spot casts NOW?

        Same rot the bathy profile has ``matches_spot`` for, and the same fix (re-run
        `tide --spot <id>`): a pin move or an ``offshore_direction`` re-aim moves
        ``offshore_point``, and the committed constants keep predicting the tide at
        where the spot used to be. Caught 2026-08-27 with 18 CA/OR/WA spots stale, one
        of them (`bandon`) 12 km off - nothing had been checking.

        Only the origin is checked, not the aim: unlike the bathy ray, the constants are
        a point sample, so the bearing only matters through the point it produced.
        """
        return haversine_km(self.origin[0], self.origin[1], *spot.offshore_point) * 1000.0 <= tol_m


# ---------------------------------------------------------------------------
# synthesis - runs every cycle, from the committed constants alone
# ---------------------------------------------------------------------------


def predict(constants: TideConstants, times: list[datetime]) -> list[float]:
    """Tide height (m, about mean sea level) at each aware datetime."""
    import numpy as np  # local: numpy rides with pygrib, keep import-time light
    import pyTMD.constituents

    cons = [c for c in CONSTITUENTS if c in constants.coeffs]
    mjd = np.array(
        [(t.astimezone(UTC) - _TIDE_EPOCH).total_seconds() / 86400.0 + _MJD_TIDE for t in times]
    )
    # nodal factor f, nodal angle u (radians), astronomical argument G (degrees)
    pu, pf, G = pyTMD.constituents.arguments(mjd, cons, corrections="FES")
    theta = np.radians(G) + pu
    re = np.array([constants.coeffs[c][0] for c in cons])
    im = np.array([constants.coeffs[c][1] for c in cons])
    heights = (pf * (re[None, :] * np.cos(theta) + im[None, :] * np.sin(theta))).sum(axis=1)
    return [float(h) for h in heights]


# ---------------------------------------------------------------------------
# extraction - one-time, needs the local EOT20 grids
# ---------------------------------------------------------------------------


def extract_constants(
    spot_id: str,
    point: tuple[float, float],
    grids_dir: Path,
) -> TideConstants:
    """Sample all 17 constituents at ``point`` (lat, lon) from the local EOT20 grids.

    Bilinear over the 4 surrounding cells when all are wet; otherwise the nearest wet
    cell within NEAREST_MAX_DEG (recorded, so a reader can judge the approximation).
    Raises if no wet cell is in range - a tide constant from dry land is worse than none.
    """
    import h5py  # local import: C extension, only the extraction machine needs it
    import numpy as np

    lat, lon = point
    lon360 = lon % 360.0
    # The wet/dry mask is the same coastline in every constituent file, so the sampling
    # decision (bilinear cell + weights, or one nearest wet cell) is made ONCE on M2 and
    # applied identically to all 17 - mixed per-constituent sampling would blend phases
    # from different water and is exactly the kind of quiet inconsistency this DB bans.
    with h5py.File(grids_dir / "M2_ocean_eot20.nc", "r") as f:
        lats, lons = f["lat"][:], f["lon"][:]
        i = max(0, min(int(np.searchsorted(lats, lat)) - 1, len(lats) - 2))
        j = max(0, min(int(np.searchsorted(lons, lon360)) - 1, len(lons) - 2))
        if (f["amplitude"][i : i + 2, j : j + 2] != 0.0).all():
            method = "bilinear"
            wy = (lat - lats[i]) / (lats[i + 1] - lats[i])
            wx = (lon360 - lons[j]) / (lons[j + 1] - lons[j])
            weights = np.array([[(1 - wy) * (1 - wx), (1 - wy) * wx], [wy * (1 - wx), wy * wx]])
            cells = (i, j)
            sample = (lat, lon)
        else:
            method = "nearest"
            weights = None
            cells = _nearest_wet(f, lats, lons, lat, lon360)
            ii, jj = cells
            sample = (float(lats[ii]), float(((lons[jj] + 180) % 360) - 180))

    coeffs: dict[str, tuple[float, float]] = {}
    for name in CONSTITUENTS:
        with h5py.File(grids_dir / f"{name.upper()}_ocean_eot20.nc", "r") as f:
            if method == "bilinear":
                i, j = cells
                re_v = float((f["real"][i : i + 2, j : j + 2] * weights).sum())
                im_v = float((f["imag"][i : i + 2, j : j + 2] * weights).sum())
            else:
                ii, jj = cells
                re_v = float(f["real"][ii, jj])
                im_v = float(f["imag"][ii, jj])
            coeffs[name] = (re_v / 100.0, im_v / 100.0)  # cm -> m
    return TideConstants(spot_id=spot_id, origin=point, sample=sample, method=method, coeffs=coeffs)


def _nearest_wet(f, lats, lons, lat: float, lon360: float) -> tuple[int, int]:
    import numpy as np

    span = NEAREST_MAX_DEG
    i0 = int(np.searchsorted(lats, lat - span))
    i1 = int(np.searchsorted(lats, lat + span)) + 1
    # The lon axis is periodic, so the window is taken by WRAPPED column index rather
    # than by slicing: a spot just east of Greenwich needs the columns near 359.x too,
    # and a plain searchsorted slice silently clips them (see geo.dlon180).
    step = float(lons[1] - lons[0])
    jc = int(np.argmin(np.abs(dlon180(lons, lon360))))
    reach = int(np.ceil(span / abs(step)))
    cols = np.mod(np.arange(jc - reach, jc + reach + 1), len(lons))
    amp = f["amplitude"][i0:i1, :][:, cols]
    wet = np.argwhere(amp != 0.0)
    if len(wet) == 0:
        raise ValueError(
            f"no wet EOT20 cell within {span} deg of ({lat:.4f}, {lon360:.4f}) - "
            "refusing to fabricate a tide constant on dry land"
        )
    cell_lat = lats[i0:i1][wet[:, 0]]
    cell_lon = lons[cols][wet[:, 1]]
    # planar closest is fine at this radius; cos-weight the lon axis
    d2 = (cell_lat - lat) ** 2 + (np.cos(np.radians(lat)) * dlon180(cell_lon, lon360)) ** 2
    k = int(np.argmin(d2))
    return i0 + int(wet[k, 0]), int(cols[wet[k, 1]])


# ---------------------------------------------------------------------------
# committed-constants store - the bathy-profile pattern
# ---------------------------------------------------------------------------


def constants_path(derived_dir: Path, spot_id: str) -> Path:
    return derived_dir / f"{spot_id}.json"


def save_constants(c: TideConstants, derived_dir: Path) -> Path:
    derived_dir.mkdir(parents=True, exist_ok=True)
    path = constants_path(derived_dir, c.spot_id)
    payload = {
        "spot": c.spot_id,
        "source": "EOT20 (SEANOE 10.17882/79489, CC-BY 4.0)",
        "origin": [round(c.origin[0], 6), round(c.origin[1], 6)],
        "sample": [round(c.sample[0], 6), round(c.sample[1], 6)],
        "method": c.method,
        "units": "m",
        "coeffs": {k: [round(re, 6), round(im, 6)] for k, (re, im) in c.coeffs.items()},
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def load_constants(derived_dir: Path, spot_id: str) -> TideConstants | None:
    path = constants_path(derived_dir, spot_id)
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return TideConstants(
        spot_id=raw["spot"],
        origin=(raw["origin"][0], raw["origin"][1]),
        sample=(raw["sample"][0], raw["sample"][1]),
        method=raw["method"],
        coeffs={k: (v[0], v[1]) for k, v in raw["coeffs"].items()},
    )


def amplitude_m(c: TideConstants) -> float:
    """Rough spring-range scale: sum of constituent amplitudes (m). For reports."""
    return sum(math.hypot(re, im) for re, im in c.coeffs.values())
