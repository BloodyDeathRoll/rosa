"""Longitude arithmetic shared by every nearest-cell sampler.

Every grid Rosa samples (EOT20 tides, OISST, GFS-Wave gridded) stores longitude in
0-360, and a plain `a - b` in that frame is correct only while nothing sits near the
0/360 seam. Today nothing does - the closest committed spot is Portugal at ~347 deg -
so the unwrapped form was a correct simplification, not a bug. It stops being correct
the first time a region lands on the Greenwich meridian (Ghana/Togo at ~0 deg, or a
Biscay spot at -1.5 deg with a 0.5-1.0 deg search ring): the tide sampler would refuse
or pick the wrong wet cell, OISST would return None or a far cell, and the GFS samplers
would measure ~360 deg to a cell one step away - all silently, all in published numbers.

These two functions are the whole fix, and they agree with the unwrapped form
everywhere further than the search radius from the seam, so the current fleet's numbers
do not move.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Floor on the cos(lat) scale below, so a sampler near a pole cannot widen its search
# window without bound. cos = 0.05 is lat 87 deg; the spot DB's northern edge is
# brims-ness at 58.67 (cos 0.52), so nothing today comes near this.
_MIN_LON_SCALE = 0.05

# How far behind the pin's shoreline plane a wet node may sit and still count as this
# spot's own water: 0.05 deg (~5.5 km) of ground distance. The nearest coastal cell of a
# 0.25 deg grid naturally has its centre a few km behind the pin's plane - it is the cell
# the coast runs through - and the strict half-plane (tolerance 0) was measured on
# 2026-09-11 to move 175 / 250 spots (GFS / ECMWF), 3 in 4 of them that coast-hugging
# cell traded for the next one out, median +0.13 / +0.20 m: a fleet-wide tune, not the
# bay fix. A node clearly behind the plane is on the other side of land (Port Phillip Bay
# -0.09, Peconic -0.07, Bocas lagoon -0.06 deg).
SEAWARD_TOL_DEG = 0.05


def lon_scale(lat: float) -> float:
    """Ground length of one longitude degree at ``lat``, as a fraction of a latitude one.

    Every nearest-cell sampler scores candidates with a squared distance built from a lat
    offset and a lon offset. Those two are only interchangeable at the equator: a degree
    of longitude spans cos(lat) of a degree of latitude, so an unscaled ``dlon**2`` term
    both ranks a lon-offset node too far (the sampler then returns a node that is
    genuinely further away) and shortens the effective ``NEAREST_MAX_DEG`` reach in lon by
    the same factor (so a wet node inside the intended radius is refused outright). At the
    spot DB's northern edge the factor is 0.52 - a lon degree is barely half a lat one.

    ``oisst``, ``gwam`` and ``tide`` have always applied this inline; it lives here so the
    GRIB wave samplers share one definition of what ``NEAREST_MAX_DEG`` measures.
    """
    return max(math.cos(math.radians(lat)), _MIN_LON_SCALE)


@dataclass(frozen=True, slots=True)
class Seaward:
    """The shore a sample point belongs to: the spot's pin and its seaward azimuth
    (``Spot.shore_normal``, compass degrees). ``nearest_wet`` keeps to the half-plane on
    the sea side of the PIN - not of the offshore sample point, which sits a few km out
    along the same azimuth: a wet node between the pin and the sample point is sea and
    must stay eligible."""

    lat: float
    lon: float
    azimuth: float


def nearest_wet(
    vals, lats, lons, lat: float, lon: float, max_deg: float, aim: Seaward | None = None
):
    """Index of the wet node to sample for ``(lat, lon)``, or None if none is in reach.

    The one metric behind the three GRIB wave samplers (``ecmwf``, ``gfswave``, ``blend``):
    ground distance (lon scaled by ``lon_scale``), masked nodes out, ``max_deg`` a radius.

    With ``aim``, a node clearly BEHIND the spot's pin - more than ``SEAWARD_TOL_DEG``
    landward of the shoreline plane through the pin - is on the other side of land, and
    the nearest node that is not wins if one is in reach; only when none is does the plain
    nearest one stand in. Distance alone is the wrong question at a 0.25 deg grid on a
    broken coast - the 2026-09-11 fleet A/B found point-lonsdale and ocean-grove's truly
    nearest node 12 km inside Port Phillip Bay (0.6-0.75 m) while the spots face Bass
    Strait (1.7-2.9 m), and ilot-sancho's on the west coast of Mauritius while it faces
    south. ``aim`` is None for a buoy (the archive arm) - a buoy has no shore.
    """
    import numpy as np

    scale = lon_scale(lat)
    d2 = (lats - lat) ** 2 + (scale * dlon180(lons, lon)) ** 2
    if hasattr(vals, "mask") and vals.mask is not np.ma.nomask:
        d2 = np.where(vals.mask, np.inf, d2)
    reach2 = max_deg**2
    if aim is not None:
        a = math.radians(aim.azimuth)
        behind = (lats - aim.lat) * math.cos(a) + scale * dlon180(lons, aim.lon) * math.sin(a)
        seaward = behind >= -SEAWARD_TOL_DEG
        d2_sea = np.where(seaward, d2, np.inf)
        idx = np.unravel_index(np.argmin(d2_sea), d2.shape)
        if d2_sea[idx] <= reach2:
            return idx
    idx = np.unravel_index(np.argmin(d2), d2.shape)
    return idx if d2[idx] <= reach2 else None


def lon360(lon: float) -> float:
    """Longitude in the 0-360 frame every gridded source stores."""
    return lon % 360.0


def dlon180(a, b):
    """Signed shortest angular distance a - b, in [-180, 180).

    Works elementwise on numpy arrays as well as scalars, which is what the samplers
    need: they build a squared-distance field over a whole window at once.

    An exact half turn comes back as -180; every caller squares this, so the sign
    there does not matter, and no sampler has a search radius near 180 deg anyway.
    """
    return ((a - b + 180.0) % 360.0) - 180.0
