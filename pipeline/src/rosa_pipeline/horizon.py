"""Derive a spot's swell window from coastline geometry instead of guessing it.

``swell_window`` is the arc of source directions whose energy can reach the break. Until now
every non-Israeli region carried a hand-set regional default (Costa Rica's Pacific spots all
share ``[190, 310]``) tagged "approx - TODO verify", and at Santa Teresa that default was
rotated roughly 20 deg clockwise off the coast it describes: it clipped the dominant 190 deg
swell at the window edge, costing 28% of its energy, while its upper 20 deg pointed at dry
land (2026-08-02, docs/CALIBRATION.md).

Method: fan rays out from the spot over all 360 deg and ask of each one "does it reach open
ocean?". Same GEBCO source and the same ``destination`` geometry the depth profiles use, so a
window and a profile can never disagree about where the sea is.

The subtlety is what counts as a blocker, and the first two attempts both got it wrong. A plain
``elevation >= 0`` test does not work: at Santa Teresa a submerged bar 1.5-3 km out reads 0 to
+2 m in GEBCO with 60-90 m of water beyond it, and a sign test reads that as a headland and
carves a false notch through the open ocean. So the test is an ORDERED pair of thresholds - the
ray is open when it reaches open water BEFORE it crosses land. That ordering is load-bearing:
it is what lets a ray shrug off the bar it has already sailed past.

The first fleet sweep (2026-08-02) then put 185 of 199 spots at odds with their YAML with 39
windows narrower than 90 deg, which no open beach is. Reading the rays back gave two mechanical
faults, both since fixed, and one real limit that remains:

1. **The nearshore sample decided everything.** ``HORIZON_DISTANCES_KM`` starts at 0.5 km, which
   is INSIDE one GEBCO cell of the spot itself, and on a shallow-shelving coast that cell
   straddles the waterline. At `miramar` bearings 225-275 sit on one identical shelf and the
   only thing separating "open" from "blocked" was whether that sample rounded to +3 or +4 m -
   a 10 deg window on an open Pacific beach. Fixed by ``HORIZON_MIN_BLOCKER_KM``: a blocker
   closer than the source can resolve is not a blocker, so the land test ignores it. This one
   change alone took the no-window count from 12 to 4 and the sub-90 deg count from 39 to 18.
2. **A -50 m "open water" bar is unreachable on a broad shelf.** `calicoan-abcd` never gets
   past -43 m in 40 km, so a wide-open ocean sector read blocked. ``HORIZON_DEEP_M`` is now
   -20 m, which is past the surf zone and still discriminating; -50 -> -20 removes every
   remaining sub-60 deg window. Beyond -20 the curve flattens and the test stops meaning much.
3. **STILL TRUE, and not fixable here: this measures ocean visibility at ~450 m, so it cannot
   see a headland that shelters the break at 50-200 m.** `arugam-bay` derives a window opening
   at 25 deg because the Indian Ocean genuinely IS open from the NNE; the point that blocks
   exactly that swell is smaller than a GEBCO cell. A derived window is therefore an upper
   bound on exposure - it can be too generous where a spot is sheltered by something small,
   and only local knowledge or a finer bathymetry source can tighten it.

With both faults fixed: no window is narrower than 60 deg, 10 sit under 90 deg, and 3 spots
return none at all - `pavones`, `panga-drops` and `miura`, which are genuinely inside gulfs
where the shore normal really does point at land 20 km across the water. Those, and anything
the CLI flags as narrow, still want a human. Santa Teresa is invariant under every threshold
setting tried, which is what a well-conditioned spot looks like.
"""

from __future__ import annotations

from dataclasses import dataclass

from .bathymetry import BathymetrySource, destination
from .models import Spot

# Sampled every 5 deg: finer buys nothing against GEBCO's ~450 m cells, and the whole fan is
# 72 rays x 8 distances = 576 points = 6 requests at the API's 100-per-request cap.
HORIZON_STEP_DEG = 5
HORIZON_DISTANCES_KM: tuple[float, ...] = (0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 20.0, 40.0)
# Above GEBCO's +-2 m noise band near a coast, below any real shoreline sample (module docstring).
HORIZON_LAND_M = 3.0
# "Open ocean" - past the surf zone, and still discriminating. Was -50 m until 2026-08-02, which
# a broad shallow shelf never reaches inside the scan radius: whole open-ocean sectors read
# blocked (calicoan-abcd tops out at -43 m in 40 km). -50 -> -20 removes every sub-60 deg window;
# past -20 the curve flattens and the test stops distinguishing sea from lagoon.
HORIZON_DEEP_M = -20.0
# Land nearer than this cannot block anything, because it cannot be resolved: GEBCO's cells are
# ~450 m and the spot sits ON the shoreline, so its own nearshore cell straddles the waterline by
# construction and reads as a few metres of land on any shallow-shelving coast. Ignoring it is
# the single biggest correctness fix this module has had - see fault 1 in the module docstring.
HORIZON_MIN_BLOCKER_KM = 1.0
# A beach cannot receive energy from behind its own shoreline, so the geometric arc is clipped
# here. The transform's GRAZING_INCIDENCE_DEG honours the last few degrees of that arc; letting
# the window run past +-90 would hand it swell travelling parallel to the beach.
MAX_INCIDENCE_DEG = 90.0


@dataclass(frozen=True, slots=True)
class HorizonScan:
    spot: str
    shore_normal: float
    open_bearings: tuple[int, ...]
    window: tuple[float, float]


def ray_reaches_open_ocean(
    elevations: list[float | None],
    distances: tuple[float, ...] = HORIZON_DISTANCES_KM,
    *,
    land_m: float = HORIZON_LAND_M,
    deep_m: float = HORIZON_DEEP_M,
    min_blocker_km: float = HORIZON_MIN_BLOCKER_KM,
) -> bool:
    """True when this ray hits open water before it hits land (and hits open water at all).

    Ordering matters, not mere presence: a ray that runs out to the open Pacific and only then
    clips a far shore is open; one that crosses a headland first is not. It is also what lets a
    ray shrug off a submerged bar it has already sailed past.

    Land inside ``min_blocker_km`` is ignored - at GEBCO's resolution that is the spot's own
    shoreline cell, not an obstruction."""
    land = next(
        (
            d
            for d, e in zip(distances, elevations, strict=False)
            if e is not None and e > land_m and d >= min_blocker_km
        ),
        None,
    )
    deep = next(
        (d for d, e in zip(distances, elevations, strict=False) if e is not None and e < deep_m),
        None,
    )
    if deep is None:
        return False
    return land is None or land > deep


def window_from_open_bearings(
    open_bearings: set[int],
    shore_normal: float,
    *,
    step_deg: int = HORIZON_STEP_DEG,
    max_incidence_deg: float = MAX_INCIDENCE_DEG,
) -> tuple[float, float] | None:
    """The contiguous run of open bearings containing the shore normal, clipped to +-90 deg.

    Contiguity is what makes this a *window* rather than a mask: an island offshore splits the
    fan into two open arcs, and only the one the beach actually faces belongs in the window.
    Returns None when the shore normal itself is blocked, which means the spot's geometry is
    wrong (a ray marched up a hillside) rather than that it has no window - the caller should
    say so loudly instead of writing an empty arc into the spot DB."""
    anchor = int(shore_normal) - int(shore_normal) % step_deg
    if anchor % 360 not in open_bearings:
        return None
    lo = hi = anchor
    while (lo - step_deg) % 360 in open_bearings and hi - (lo - step_deg) < 360 - step_deg:
        lo -= step_deg
    while (hi + step_deg) % 360 in open_bearings and (hi + step_deg) - lo < 360 - step_deg:
        hi += step_deg
    lo = max(lo, shore_normal - max_incidence_deg)
    hi = min(hi, shore_normal + max_incidence_deg)
    return lo % 360, hi % 360


def scan_horizon(
    source: BathymetrySource,
    spot: Spot,
    *,
    step_deg: int = HORIZON_STEP_DEG,
    distances: tuple[float, ...] = HORIZON_DISTANCES_KM,
) -> HorizonScan:
    """Fan the rays, sample them, and reduce to a window. Never writes to the spot DB - the
    coordinate authority ladder in CLAUDE.md puts derived geometry below a human's eyes, so
    this reports and a person edits the YAML."""
    bearings = list(range(0, 360, step_deg))
    points = [destination(spot.lat, spot.lon, b, d) for b in bearings for d in distances]
    elevations: list[float | None] = []
    for i in range(0, len(points), 100):  # OpenTopoData caps a request at 100 locations
        elevations.extend(source.elevations(points[i : i + 100]))

    per_ray = len(distances)
    open_bearings = {
        b
        for j, b in enumerate(bearings)
        if ray_reaches_open_ocean(elevations[j * per_ray : (j + 1) * per_ray], distances)
    }
    normal = spot.shore_normal if spot.shore_normal is not None else spot.offshore_direction + 180.0
    window = window_from_open_bearings(open_bearings, normal % 360, step_deg=step_deg)
    if window is None:
        raise ValueError(
            f"{spot.id}: shore normal {normal % 360:.0f} deg is blocked by land within "
            f"{distances[-1]:g} km - the spot's geometry is wrong, not its window"
        )
    return HorizonScan(spot.id, normal % 360, tuple(sorted(open_bearings)), window)
