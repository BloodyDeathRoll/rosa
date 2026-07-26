import json
import math

import httpx
import pytest

from rosa_pipeline.bathymetry import (
    RAY_DISTANCES_KM,
    DepthProfile,
    DepthSample,
    FixtureBathymetrySource,
    OpenTopoDataSource,
    _round_key,
    build_profile,
    destination,
    load_profile,
    ray_points,
)
from rosa_pipeline.models import Spot


def make_spot(**kw) -> Spot:
    base = dict(
        id="test",
        name="Test",
        lat=32.0,
        lon=34.8,
        timezone="UTC",
        offshore_point=(32.0, 34.74),
        offshore_direction=90.0,
        shore_normal=270.0,
        swell_window=(250.0, 340.0),
        height_coeff=1.0,
        break_type="beach",
        ideal_wind_dir=(45.0, 135.0),
        ideal_size_m=(0.6, 1.5),
    )
    base.update(kw)
    return Spot(**base)


class StubSource:
    """Returns canned elevations and records the points it was asked about."""

    def __init__(self, elevations: list[float | None]) -> None:
        self._elevations = elevations
        self.seen: list[tuple[float, float]] = []

    def elevations(self, points: list[tuple[float, float]]) -> list[float | None]:
        self.seen = points
        return self._elevations[: len(points)]


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    r = 6371.0088
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


class TestDestination:
    def test_north_moves_up_one_degree(self):
        lat, lon = destination(0.0, 0.0, 0.0, 111.195)  # ~1° of latitude
        assert lat == pytest.approx(1.0, abs=0.01)
        assert lon == pytest.approx(0.0, abs=1e-6)

    def test_east_moves_right_at_equator(self):
        lat, lon = destination(0.0, 0.0, 90.0, 111.195)
        assert lon == pytest.approx(1.0, abs=0.01)
        assert lat == pytest.approx(0.0, abs=0.01)

    def test_distance_is_preserved(self):
        origin = (32.0, 34.8)
        dest = destination(*origin, 250.0, 12.0)
        assert _haversine_km(origin, dest) == pytest.approx(12.0, abs=0.05)

    def test_longitude_wraps_to_180_range(self):
        _, lon = destination(0.0, 179.9, 90.0, 111.195)
        assert -180.0 <= lon <= 180.0


class TestRayPoints:
    def test_count_and_distances(self):
        pts = ray_points(32.0, 34.8, 270.0)
        assert len(pts) == len(RAY_DISTANCES_KM)
        assert [d for *_, d in pts] == list(RAY_DISTANCES_KM)

    def test_marches_monotonically_seaward(self):
        origin = (32.0, 34.8)
        pts = ray_points(*origin, 270.0)
        dists = [_haversine_km(origin, (lat, lon)) for lat, lon, _ in pts]
        assert dists == sorted(dists)
        assert dists[-1] == pytest.approx(RAY_DISTANCES_KM[-1], abs=0.1)


class TestFixtureSource:
    def test_lookup_by_rounded_key(self):
        src = FixtureBathymetrySource({"32.0000,34.7400": -50.0})
        assert src.elevations([(32.0, 34.74)]) == [-50.0]

    def test_missing_point_raises(self):
        src = FixtureBathymetrySource({})
        with pytest.raises(KeyError):
            src.elevations([(1.0, 2.0)])

    def test_passes_through_none(self):
        src = FixtureBathymetrySource({"0.0000,0.0000": None})
        assert src.elevations([(0.0, 0.0)]) == [None]


class TestBuildProfile:
    def test_seaward_bearing_is_shore_normal_not_offshore(self):
        # shore_normal drives the ray, decoupled from the offshore wind direction (point breaks)
        spot = make_spot(offshore_direction=245.0, shore_normal=115.0)
        profile = build_profile(StubSource([-10.0] * 9), spot)
        assert profile.bearing_seaward_deg == 115.0

    def test_depth_is_negative_elevation_deep_end_last(self):
        elevs = [-2.0, -5.0, -10.0, -20.0, -30.0, -50.0, -80.0, -120.0, -180.0]
        profile = build_profile(StubSource(elevs), make_spot())
        depths = [s.depth_m for s in profile.samples]
        assert depths == [2.0, 5.0, 10.0, 20.0, 30.0, 50.0, 80.0, 120.0, 180.0]
        assert profile.nearshore_depth_m == 2.0
        assert profile.offshore_depth_m == 180.0
        assert profile.land_samples == 0
        assert profile.mean_slope_m_per_km > 0

    def test_land_samples_counted(self):
        elevs = [5.0, 1.0, -3.0, -10.0, -20.0, -40.0, -60.0, -90.0, -140.0]
        profile = build_profile(StubSource(elevs), make_spot())
        assert profile.land_samples == 2  # the two positive-elevation (above-MSL) points

    def test_nan_for_missing_elevation(self):
        elevs = [None, -5.0, -10.0, -20.0, -30.0, -50.0, -80.0, -120.0, -180.0]
        profile = build_profile(StubSource(elevs), make_spot())
        assert math.isnan(profile.samples[0].depth_m)


class TestDepthProfileDict:
    def test_to_dict_shape(self):
        samples = tuple(
            DepthSample(dist_km=d, lat=32.0, lon=34.8 - d * 0.01, depth_m=d * 10)
            for d in RAY_DISTANCES_KM
        )
        profile = DepthProfile(spot_id="x", bearing_seaward_deg=270.0, samples=samples)
        d = profile.to_dict()
        assert d["spot"] == "x"
        assert d["source"] == "gebco2020 via opentopodata"
        assert d["bearing_seaward_deg"] == 270.0
        assert len(d["samples"]) == len(RAY_DISTANCES_KM)
        assert set(d["samples"][0]) == {"dist_km", "lat", "lon", "depth_m"}


class TestProfileLoad:
    def test_from_dict_roundtrips(self):
        prof = DepthProfile(
            spot_id="x",
            bearing_seaward_deg=270.0,
            samples=(DepthSample(0.25, 32.0, 34.8, 15.0), DepthSample(1.0, 32.0, 34.7, 50.0)),
        )
        again = DepthProfile.from_dict(prof.to_dict())
        assert again.spot_id == "x"
        assert again.bearing_seaward_deg == 270.0
        assert [s.depth_m for s in again.samples] == [15.0, 50.0]

    def test_wet_depths_deep_to_shallow_reverses_and_drops_land(self):
        prof = DepthProfile(
            "x",
            270.0,
            (
                DepthSample(0.25, 0.0, 0.0, -3.0),  # land - dropped
                DepthSample(1.0, 0.0, 0.0, 15.0),
                DepthSample(2.0, 0.0, 0.0, 50.0),
            ),
        )
        assert prof.wet_depths_deep_to_shallow() == [50.0, 15.0]

    def test_load_profile_missing_returns_none(self, tmp_path):
        assert load_profile("nope", tmp_path) is None

    def test_load_profile_reads_committed_shape(self, tmp_path):
        prof = DepthProfile("beit", 282.0, (DepthSample(0.25, 32.0, 34.8, 15.0),))
        (tmp_path / "beit.json").write_text(json.dumps(prof.to_dict()), encoding="utf-8")
        loaded = load_profile("beit", tmp_path)
        assert loaded is not None
        assert loaded.spot_id == "beit"
        assert loaded.samples[0].depth_m == 15.0


class TestOpenTopoDataGuard:
    def test_rejects_over_100_locations_before_network(self):
        src = OpenTopoDataSource()
        with pytest.raises(ValueError, match="100 locations"):
            src.elevations([(0.0, float(i)) for i in range(101)])


class TestOpenTopoDataBackoff:
    def test_retries_on_429_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("rosa_pipeline.bathymetry.time.sleep", lambda *_: None)
        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] <= 2:
                return httpx.Response(429, headers={"retry-after": "0"})
            return httpx.Response(200, json={"status": "OK", "results": [{"elevation": -50.0}]})

        src = OpenTopoDataSource(transport=httpx.MockTransport(handler))
        assert src.elevations([(32.0, 34.8)]) == [-50.0]
        assert calls["n"] == 3

    def test_raises_after_exhausting_retries(self, monkeypatch):
        monkeypatch.setattr("rosa_pipeline.bathymetry.time.sleep", lambda *_: None)

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"retry-after": "0"})

        src = OpenTopoDataSource(max_retries=2, transport=httpx.MockTransport(handler))
        with pytest.raises(httpx.HTTPStatusError):
            src.elevations([(32.0, 34.8)])


def test_round_key_format():
    assert _round_key(32.38173, 34.80351) == "32.3817,34.8035"


class TestOriginProvenance:
    """A profile records the pin it was cast from, so a moved spot can't silently keep
    bathymetry sampled somewhere else (that used to be undetectable - it just fed the
    wrong depths into h_break)."""

    def test_build_stamps_the_spot_coords(self):
        spot = make_spot(lat=32.0887112, lon=34.7675748, shore_normal=270.0)
        src = FixtureBathymetrySource(
            {_round_key(lat, lon): -20.0 for lat, lon, _ in ray_points(spot.lat, spot.lon, 270.0)}
        )
        profile = build_profile(src, spot)
        assert (profile.origin_lat, profile.origin_lon) == (spot.lat, spot.lon)
        assert profile.to_dict()["origin"] == [spot.lat, spot.lon]

    def test_round_trips_through_json(self):
        profile = DepthProfile(
            spot_id="x",
            bearing_seaward_deg=270.0,
            samples=(DepthSample(0.25, 32.0, 34.0, 5.0),),
            origin_lat=32.0,
            origin_lon=34.1,
        )
        back = DepthProfile.from_dict(json.loads(json.dumps(profile.to_dict())))
        assert (back.origin_lat, back.origin_lon) == (32.0, 34.1)

    def test_pre_origin_profile_never_claims_to_match(self):
        legacy = DepthProfile.from_dict(
            {
                "spot": "x",
                "bearing_seaward_deg": 270.0,
                "samples": [{"dist_km": 0.25, "lat": 32.0, "lon": 34.0, "depth_m": 5.0}],
            }
        )
        assert legacy.origin_lat is None
        assert not legacy.matches_spot(make_spot(lat=32.0, lon=34.0))

    def test_matches_only_within_tolerance(self):
        profile = DepthProfile(
            spot_id="x",
            bearing_seaward_deg=270.0,
            samples=(DepthSample(0.25, 32.0, 34.0, 5.0),),
            origin_lat=32.0,
            origin_lon=34.0,
        )
        assert profile.matches_spot(make_spot(lat=32.0, lon=34.0))
        assert profile.matches_spot(make_spot(lat=32.00004, lon=34.0))  # ~4 m, rounding noise
        assert not profile.matches_spot(make_spot(lat=32.002, lon=34.0))  # ~220 m, a real move
