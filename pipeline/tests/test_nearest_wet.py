"""geo.nearest_wet - the one metric behind the three GRIB wave samplers.

Ground distance (lon scaled by cos lat), NEAREST_MAX_DEG as a radius, and the seaward
preference from the spot's pin + shore_normal. Cases 1-4 are the 2026-09-05 Dream
finding's, driven through the real ecmwf._nearest_wet (window + metric); the seaward
cases are the 2026-09-11 A/B's point-lonsdale shape on a synthetic grid."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from rosa_pipeline import geo
from rosa_pipeline.ecmwf import GRID_STEP_DEG, NEAREST_MAX_DEG, _nearest_wet, parse_grib_points
from rosa_pipeline.geo import Seaward, lon_scale, nearest_wet

ECMWF_GRIB = Path(__file__).parent / "fixtures" / "ecmwf" / "ecmwf_f000.grib2"
SEA_POINT = (32.2, 34.55)  # open water off the Israeli coast (test_ecmwf.py)


def _grid(centre_lat: float, centre_lon: float, half: int = 12):
    lats1d = centre_lat + GRID_STEP_DEG * np.arange(-half, half + 1)
    lons1d = centre_lon + GRID_STEP_DEG * np.arange(-half, half + 1)
    lons2d, lats2d = np.meshgrid(lons1d, lats1d)
    return lats1d, lons1d, lats2d, lons2d


def _field(lats1d, lons1d, wet: dict[tuple[float, float], float]):
    """All-dry masked array with the given (lat, lon) -> value wet nodes."""
    data = np.zeros((len(lats1d), len(lons1d)))
    mask = np.ones_like(data, dtype=bool)
    for (wlat, wlon), v in wet.items():
        i = int(np.argmin(np.abs(lats1d - wlat)))
        j = int(np.argmin(np.abs(lons1d - wlon)))
        assert abs(lats1d[i] - wlat) < 1e-9 and abs(lons1d[j] - wlon) < 1e-9, "node off-grid"
        data[i, j] = v
        mask[i, j] = False
    return np.ma.array(data, mask=mask)


def test_lon_scale_is_cos_lat_with_a_polar_floor() -> None:
    assert lon_scale(0.0) == 1.0
    assert lon_scale(58.5) == pytest.approx(math.cos(math.radians(58.5)))
    assert lon_scale(89.9) == geo._MIN_LON_SCALE


def test_case1_lon_offset_node_that_is_closer_on_the_ground_wins() -> None:
    # Thurso-ish, lat 58.5: 0.50 deg north (55.7 km) vs 0.75 deg east (43.6 km). Raw
    # degrees score the east node 0.5625 against 0.25 and take the north one.
    lat, lon = 58.5, -4.0
    lats1d, lons1d, lats2d, lons2d = _grid(lat, lon)
    vals = _field(lats1d, lons1d, {(lat + 0.50, lon): 11.0, (lat, lon + 0.75): 22.0})
    assert _nearest_wet(vals, lats2d, lons2d, lat, lon) == 22.0


def test_case2_reach_is_a_ground_distance_in_lon_too() -> None:
    # the only wet node is 1.00 deg east = 58.2 km, inside the 0.6 deg (66.8 km) reach;
    # both the window and the metric have to widen by cos(lat) to see it
    lat, lon = 58.5, -4.0
    lats1d, lons1d, lats2d, lons2d = _grid(lat, lon)
    vals = _field(lats1d, lons1d, {(lat, lon + 1.00): 33.0})
    assert _nearest_wet(vals, lats2d, lons2d, lat, lon) == 33.0


def test_case3_equator_control_does_not_move() -> None:
    lat, lon = 0.0, -4.0
    lats1d, lons1d, lats2d, lons2d = _grid(lat, lon)
    vals = _field(lats1d, lons1d, {(lat + 0.50, lon): 11.0, (lat, lon + 0.75): 22.0})
    assert _nearest_wet(vals, lats2d, lons2d, lat, lon) == 11.0


def test_case4_a_node_two_degrees_out_is_still_refused() -> None:
    lat, lon = 58.5, -4.0
    lats1d, lons1d, lats2d, lons2d = _grid(lat, lon)
    vals = _field(lats1d, lons1d, {(lat, lon + 2.0): 44.0})
    assert _nearest_wet(vals, lats2d, lons2d, lat, lon) is None


# --- the seaward preference ------------------------------------------------------------

# point-lonsdale's shape: the pin faces SW (216) into Bass Strait, the sample point sits
# ~5 km out along that azimuth, the truly nearest wet node is NE inside Port Phillip Bay
# and a farther one lies SSW in open water
PIN = Seaward(-38.290, 144.608, 216.0)
LAT, LON = -38.327, 144.574  # the offshore sample point
BAY = (-38.25, 144.75)  # ~18 km from the sample point, landward of the pin
STRAIT = (-38.50, 144.50)  # ~20 km, seaward


def _bay_and_strait():
    lats1d, lons1d, lats2d, lons2d = _grid(-38.25, 144.50)
    vals = _field(lats1d, lons1d, {BAY: 0.7, STRAIT: 1.7})
    return vals, lats2d, lons2d


def test_seaward_node_beats_a_nearer_one_behind_the_pin() -> None:
    vals, lats2d, lons2d = _bay_and_strait()
    assert _nearest_wet(vals, lats2d, lons2d, LAT, LON, aim=PIN) == 1.7


def test_without_a_shore_plain_nearest_stands() -> None:
    # a buoy (the archive arm) has no shore: distance alone decides
    vals, lats2d, lons2d = _bay_and_strait()
    assert _nearest_wet(vals, lats2d, lons2d, LAT, LON) == 0.7


def test_no_seaward_node_in_reach_falls_back_to_plain_nearest() -> None:
    lats1d, lons1d, lats2d, lons2d = _grid(-38.25, 144.50)
    vals = _field(lats1d, lons1d, {BAY: 0.7})
    assert _nearest_wet(vals, lats2d, lons2d, LAT, LON, aim=PIN) == 0.7


def test_a_node_between_the_pin_and_the_sample_point_is_still_sea() -> None:
    # the half-plane is drawn at the PIN, not at the sample point: a wet node on the
    # pin's own cell is landward of a sample point 0.2 deg out, yet it is the coast's
    # own water and must beat a node farther out to sea
    pin = Seaward(-38.25, 144.50, 216.0)
    sample = (-38.41, 144.35)  # 0.2 deg out along 216
    far_out = (-38.75, 144.25)  # seaward too, but 0.35 deg from the sample point
    lats1d, lons1d, lats2d, lons2d = _grid(-38.25, 144.50)
    vals = _field(lats1d, lons1d, {(pin.lat, pin.lon): 1.2, far_out: 2.0})
    assert _nearest_wet(vals, lats2d, lons2d, *sample, aim=pin) == 1.2


def test_the_coast_cell_a_few_km_behind_the_plane_is_still_this_spots_water() -> None:
    # coogee's shape: the nearest cell's centre is 0.01 deg behind the pin's plane (the
    # coast runs through it); it stays, the next cell out does not replace it
    pin = Seaward(-33.920, 151.258, 88.0)
    coast = (-34.00, 151.25)  # dot -0.010 from the pin
    out = (-34.00, 151.50)
    lats1d, lons1d, lats2d, lons2d = _grid(-34.00, 151.25)
    vals = _field(lats1d, lons1d, {coast: 1.64, out: 2.92})
    assert _nearest_wet(vals, lats2d, lons2d, -33.919, 151.312, aim=pin) == 1.64
    assert geo.SEAWARD_TOL_DEG == 0.05


def test_shared_metric_returns_the_index_the_samplers_read() -> None:
    vals, lats2d, lons2d = _bay_and_strait()
    idx = nearest_wet(vals, lats2d, lons2d, LAT, LON, NEAREST_MAX_DEG, PIN)
    assert idx is not None and float(vals[idx]) == 1.7
    assert nearest_wet(vals, lats2d, lons2d, LAT + 5.0, LON, NEAREST_MAX_DEG, PIN) is None


def test_ecmwf_parse_honours_a_shore_on_the_real_field() -> None:
    valid = datetime(2026, 7, 22, 0, tzinfo=UTC)
    data = ECMWF_GRIB.read_bytes()
    shore = {SEA_POINT: Seaward(32.2, 34.61, 270.0)}
    plain = parse_grib_points(data, [SEA_POINT], valid, params=("swh",))[0]
    aimed = parse_grib_points(data, [SEA_POINT], valid, params=("swh",), aims=shore)[0]
    # open water off Israel: the point's own cell is wet, so the shore changes nothing
    assert plain is not None and aimed is not None and aimed.swh == plain.swh
