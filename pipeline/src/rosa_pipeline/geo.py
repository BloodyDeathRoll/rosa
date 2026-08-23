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
