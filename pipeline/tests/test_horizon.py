"""Swell windows derived from coastline geometry (2026-08-02).

The numbers in the fixtures are the shape of the real Santa Teresa scan, which is what makes
the shoal test worth having: a submerged bar 1.5-3 km offshore reads 0 to +2 m in GEBCO with
60-90 m of water past it, and a plain sign test cuts a false notch through the open ocean.
"""

from __future__ import annotations

import pytest

from rosa_pipeline.horizon import (
    HORIZON_DISTANCES_KM,
    ray_reaches_open_ocean,
    scan_horizon,
    window_from_open_bearings,
)
from rosa_pipeline.models import Spot

DIST = HORIZON_DISTANCES_KM  # (0.5, 1, 2, 3, 5, 10, 20, 40) km


def make_spot(**kw) -> Spot:
    base = dict(
        id="fake",
        name="Fake",
        lat=9.64,
        lon=-85.17,
        timezone="UTC",
        offshore_point=(9.64, -85.23),
        offshore_direction=70.0,
        shore_normal=250.0,
        swell_window=(190.0, 310.0),
        height_coeff=1.0,
        break_type="beach",
        ideal_wind_dir=(30.0, 120.0),
        ideal_size_m=(0.8, 2.5),
    )
    base.update(kw)
    return Spot(**base)


def test_open_ocean_ray_is_open() -> None:
    assert ray_reaches_open_ocean([-21, -11, -3, -9, -64, -89, -566, -1640], DIST)


def test_ray_over_land_is_blocked() -> None:
    assert not ray_reaches_open_ocean([36, 91, 128, 116, 74, 58, 101, 12], DIST)


def test_submerged_bar_is_not_a_headland() -> None:
    """The bug this module exists to avoid: 0 to +2 m at 2 km, deep water beyond."""
    assert ray_reaches_open_ocean([-30, -22, 1, -4, -65, -84, -501, -1310], DIST)


def test_land_before_deep_water_blocks_but_land_after_it_does_not() -> None:
    """Ordering, not presence - a ray can cross the whole ocean and clip a far shore.
    The blocker sits at 2 km so it is outside HORIZON_MIN_BLOCKER_KM and really does block."""
    assert not ray_reaches_open_ocean([-5, -8, 50, -80, -90, -95, -99, -120], DIST)
    assert ray_reaches_open_ocean([-60, -70, -80, -90, -95, -99, -120, 50], DIST)


def test_ray_that_never_reaches_open_water_is_blocked() -> None:
    """A shelf that stays inside the surf zone for 40 km is shadowed, not open."""
    assert not ray_reaches_open_ocean([-2, -3, -4, -5, -6, -8, -10, -12], DIST)


def test_shallow_shelf_past_the_surf_zone_is_open() -> None:
    """calicoan-abcd: tops out at -43 m in 40 km. Under the old -50 m bar a wide-open ocean
    sector read blocked, which collapsed its window to 10 deg (2026-08-02)."""
    assert ray_reaches_open_ocean([-1, -2, -6, -7, -8, -10, -31, -43], DIST)


def test_the_spots_own_shoreline_cell_is_not_a_blocker() -> None:
    """miramar: on a shallow-shelving coast the 0.5 km sample straddles the waterline, and
    whether it rounded to +3 or +4 m was deciding the entire window."""
    assert ray_reaches_open_ocean([4, 0, -9, -16, -23, -33, -61, -105], DIST)
    assert ray_reaches_open_ocean([3, 0, -9, -15, -22, -32, -65, -102], DIST)


def test_real_land_just_beyond_the_resolution_limit_still_blocks() -> None:
    """The exemption is only for what GEBCO cannot resolve - 1 km out it counts again."""
    assert not ray_reaches_open_ocean([0, 40, 60, -80, -90, -95, -99, -120], DIST)


def test_window_is_the_contiguous_arc_around_the_shore_normal() -> None:
    open_b = set(range(135, 300, 5))
    assert window_from_open_bearings(open_b, 250.0) == (160.0, 295.0)  # clipped at normal-90


def test_window_stops_at_an_island_instead_of_jumping_it() -> None:
    """Two open arcs split by an obstruction: only the one the beach faces is the window."""
    open_b = set(range(100, 150, 5)) | set(range(200, 290, 5))
    assert window_from_open_bearings(open_b, 250.0) == (200.0, 285.0)


def test_blocked_shore_normal_reports_none_rather_than_an_empty_arc() -> None:
    assert window_from_open_bearings({10, 15, 20}, 250.0) is None


def test_fully_open_fan_spans_the_whole_clip_not_half() -> None:
    """Dream review 2026-08-05: the two expansion loops shared one budget, so `lo` could
    spend the whole circle before `hi` moved a step. A fully open fan came back as
    [normal-90, normal] - half the arc, and exactly 90 deg wide, which is one degree too
    wide for the CLI's NARROW (<90) warning to catch."""
    open_b = set(range(0, 360, 5))
    assert window_from_open_bearings(open_b, 250.0) == (160.0, 340.0)


class _FakeSource:
    """Sea everywhere except a headland from 300 deg round to 130 deg.

    Stateful because scan_horizon chunks the fan into 100-point requests and 100 is not a
    multiple of the 8 samples per ray, so a chunk starts mid-ray."""

    def __init__(self) -> None:
        self.seen = 0

    def elevations(self, points: list[tuple[float, float]]) -> list[float | None]:
        out = [self._elev(self.seen + i) for i in range(len(points))]
        self.seen += len(points)
        return out

    @staticmethod
    def _elev(i: int) -> float:
        bearing = (i // len(DIST)) * 5
        landward = bearing >= 300 or bearing <= 130
        return 40.0 if landward else -80.0


def test_scan_horizon_end_to_end() -> None:
    scan = scan_horizon(_FakeSource(), make_spot())
    assert scan.window == (160.0, 295.0)
    assert 250 in scan.open_bearings and 0 not in scan.open_bearings


def test_scan_horizon_refuses_a_short_elevation_batch() -> None:
    """Rays are sliced out of the pooled elevation list by position, so a batch that
    comes back one sample short would shift every later ray onto its neighbour's samples
    and yield a plausible, wrong window. Loud failure instead."""

    class _ShortSource(_FakeSource):
        def elevations(self, points: list[tuple[float, float]]) -> list[float | None]:
            return super().elevations(points)[:-1]

    with pytest.raises(ValueError, match="refusing to slice the fan by position"):
        scan_horizon(_ShortSource(), make_spot())


def test_scan_horizon_raises_when_the_shore_normal_faces_land() -> None:
    """A spot whose ray marches up a hillside has a geometry fault, not a narrow window -
    the same failure the 2026-07-29 shore_normal audit found at fishermen."""
    # shore_normal points into the headland the fake source puts there
    spot = make_spot(id="inland", offshore_direction=250.0, shore_normal=70.0)
    with pytest.raises(ValueError, match="blocked by land"):
        scan_horizon(_FakeSource(), spot)
