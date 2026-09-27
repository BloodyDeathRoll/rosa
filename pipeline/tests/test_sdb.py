"""CMEMS coastal SDB source + merge policy. All offline: the network shape is a fixture."""

import json
import math

import pytest

from rosa_pipeline.bathymetry import DepthProfile, DepthSample
from rosa_pipeline.sdb import (
    GRID_LAT0,
    GRID_LON0,
    GRID_STEP_DEG,
    FixtureSdbSource,
    SdbReading,
    merge_profile,
)


def _profile(depths, spot_id="reef", dists=(0.25, 0.5, 1.0)):
    return DepthProfile(
        spot_id=spot_id,
        bearing_seaward_deg=90.0,
        samples=tuple(
            DepthSample(dist_km=d, lat=1.0 + i / 1000, lon=73.0, depth_m=z)
            for i, (d, z) in enumerate(zip(dists, depths, strict=True))
        ),
        origin_lat=1.0,
        origin_lon=73.0,
    )


def _readings(*rows):
    return [None if r is None else SdbReading(r, 1, 25) for r in rows]


def test_grid_origin_is_pixel_centre():
    """Half a step inside the corner. Off-by-half-a-cell is 58 m, which on a reef pass is
    the difference between the take-off and dry land."""
    assert GRID_LAT0 == pytest.approx(-90.0 + GRID_STEP_DEG / 2)  # noqa: SIM300
    assert GRID_LON0 == pytest.approx(-180.0 + GRID_STEP_DEG / 2)  # noqa: SIM300
    assert GRID_STEP_DEG * 111320 == pytest.approx(116.0, abs=0.5)  # noqa: SIM300


def test_fixture_source_signs_are_depth_positive_down():
    """The store holds `height` (negative under water); DepthSample holds depth (positive
    down). A sign slip here would shoal every wave onto a mountain."""
    src = FixtureSdbSource({"1.00000,73.00000": [5.2, 1, 25]})
    assert src.reading(1.0, 73.0).depth_m == 5.2
    assert src.elevations([(1.0, 73.0)]) == [-5.2]


def test_fixture_source_raises_on_an_uncaptured_point():
    src = FixtureSdbSource({})
    with pytest.raises(KeyError):
        src.reading(1.0, 73.0)


def test_merge_replaces_only_where_sdb_measured():
    """The narrow rule: SDB wins where it has a gated reading, GEBCO stands everywhere else.
    No interpolation along the ray, so a gap stays a gap."""
    profile = _profile([280.0, 359.0, 509.0])
    merged, patched = merge_profile(profile, _readings(5.2, None, 12.0))
    assert [round(s.depth_m, 1) for s in merged.samples] == [5.2, 359.0, 12.0]
    assert [p.dist_km for p in patched] == [0.25, 1.0]
    assert merged.sdb_patched_km == (0.25, 1.0)


def test_merge_leaves_an_agreeing_profile_untouched():
    """Within min_delta the committed profile must come back bit-identical, so running this
    over a fleet that already agrees is a no-op rather than a diff."""
    profile = _profile([5.0, 8.0, 12.0])
    merged, patched = merge_profile(profile, _readings(5.4, 8.0, 12.5), min_delta_m=1.0)
    assert patched == []
    assert merged.sdb_patched_km == ()
    assert merged.to_dict() == profile.to_dict()


def test_merge_fills_a_missing_gebco_sample():
    """A hole loses to a measurement: NaN is not data, so any SDB reading beats it."""
    profile = _profile([float("nan"), 20.0, 40.0])
    merged, patched = merge_profile(profile, _readings(3.0, None, None))
    assert merged.samples[0].depth_m == 3.0
    assert patched[0].was_m is None


def test_merge_is_not_a_one_way_shallowing():
    """SDB is usually shallower, but encoding that would bias the fleet. A deeper SDB
    reading must win too, or this stops being a source swap and becomes a thumb on the
    scale."""
    profile = _profile([2.0, 8.0, 12.0])
    merged, patched = merge_profile(profile, _readings(9.0, None, None))
    assert merged.samples[0].depth_m == 9.0
    assert patched[0].was_m == 2.0 and patched[0].now_m == 9.0


def test_merge_never_invents_a_sample():
    """docs/ALGORITHM.md standing prohibition. The ray keeps its length and its geometry;
    only depths at points SDB actually measured can change."""
    profile = _profile([280.0, 359.0, 509.0])
    merged, _ = merge_profile(profile, _readings(5.2, None, None))
    assert len(merged.samples) == len(profile.samples)
    for before, after in zip(profile.samples, merged.samples, strict=True):
        assert (before.dist_km, before.lat, before.lon) == (after.dist_km, after.lat, after.lon)


def test_merge_rejects_a_reading_count_mismatch():
    with pytest.raises(ValueError, match="SDB readings"):
        merge_profile(_profile([1.0, 2.0, 3.0]), _readings(1.0))


def test_patched_profile_names_both_grids_in_its_source():
    """Provenance travels with the profile: a reader must be able to tell a patched profile
    from a pure GEBCO cut, or two spots shoaling differently is inexplicable."""
    merged, _ = merge_profile(_profile([280.0, 359.0, 509.0]), _readings(5.2, None, None))
    d = merged.to_dict()
    assert "gebco2020" in d["source"] and "SDB" in d["source"]
    assert d["sdb_patched_km"] == [0.25]
    assert "sdb_patched_km" not in _profile([1.0, 2.0, 3.0]).to_dict()


def test_patched_profile_round_trips():
    merged, _ = merge_profile(_profile([280.0, 359.0, 509.0]), _readings(5.2, None, 12.0))
    back = DepthProfile.from_dict(json.loads(json.dumps(merged.to_dict())))
    assert back.sdb_patched_km == (0.25, 1.0)
    assert [round(s.depth_m, 1) for s in back.samples] == [5.2, 359.0, 12.0]


def test_patching_changes_the_shoaling_reference():
    """Why any of this matters: the physics marches inward from the nearshore sample, so a
    280 m start and a 5 m start are different waves. Pins the effect, not a constant."""
    profile = _profile([280.0, 359.0, 509.0])
    merged, _ = merge_profile(profile, _readings(5.2, 7.5, None))
    assert profile.nearshore_depth_m == 280.0
    assert merged.nearshore_depth_m == 5.2
    assert math.isfinite(merged.mean_slope_m_per_km)


def test_sdb_all_sweep_survives_one_failed_read(tmp_path, monkeypatch, capsys):
    """One CMEMS blip must not end an `sdb --all` sweep: the failed spot is named, the
    rest are read, and the exit code says something failed (Dream 2026-09-27)."""
    from pathlib import Path

    import rosa_pipeline.cli as cli

    repo = Path(__file__).resolve().parents[2]
    spots = tmp_path / "spots"
    spots.mkdir()
    (spots / "t.yaml").write_text(
        (repo / "data/spots/portugal.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    calls = []

    class Flaky:
        def readings(self, points):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("503")
            return [None] * len(points)

    monkeypatch.setattr(cli, "_sdb_source", lambda args: Flaky())
    rc = cli.main(
        [
            "sdb",
            "--all",
            "--spots-dir",
            str(spots),
            "--bathy-dir",
            str(repo / "data/spots/derived/bathy"),
        ]
    )
    assert rc == 1
    assert len(calls) > 2
    assert "SDB read failed" in capsys.readouterr().err


def test_atl24_label_names_the_graded_grid():
    from rosa_pipeline.cli import profile_source_label

    assert profile_source_label({"gebco2024 via local grid"}) == (
        "committed profile (gebco2024 via local grid)"
    )
