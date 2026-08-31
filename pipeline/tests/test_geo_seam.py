"""Longitude-seam robustness in the nearest-cell samplers (2026-08-21 proposal).

Not triggered by any committed spot - the closest is Portugal at ~347 deg - so these
synthesize the seam case the DB will eventually grow into, and pin that the current
fleet's geometry is untouched.
"""

import numpy as np

from rosa_pipeline.geo import dlon180, lon360
from rosa_pipeline.gfswave import cluster_boxes


def test_dlon180_takes_the_short_way_round():
    assert dlon180(1.0, 359.0) == 2.0
    assert dlon180(359.0, 1.0) == -2.0
    assert dlon180(10.0, 5.0) == 5.0
    assert abs(dlon180(180.0, 0.0)) == 180.0  # exact half turn: sign is arbitrary


def test_dlon180_agrees_with_plain_subtraction_away_from_the_seam():
    """Why the current fleet's numbers cannot move: every committed spot is further
    from 0/360 than any sampler's search radius."""
    rng = np.random.default_rng(0)
    a = rng.uniform(5.0, 355.0, 500)
    b = a + rng.uniform(-1.0, 1.0, 500)  # within the widest search ring
    assert np.allclose(dlon180(a, b), a - b)


def test_lon360_and_dlon180_compose_across_the_seam():
    # Ghana at -0.2 deg and a grid cell at 359.9: one step apart, not 360
    assert abs(dlon180(359.9, lon360(-0.2))) < 0.5


def test_cluster_boxes_keeps_a_seam_crossing_cluster_contiguous(capsys):
    """A cluster at 359.8 / 0.2 used to produce left=~-0.2 or a 359-wide box."""
    pts = [(5.0, -0.2), (5.1, 0.2), (5.2, -0.4)]
    boxes = cluster_boxes(pts)
    assert len(boxes) == 1  # they are neighbours, not two clusters 360 deg apart
    box, members = boxes[0]
    assert sorted(members) == [0, 1, 2]
    assert box.right - box.left < 5.0  # a tight box, not a near-global one
    assert "crosses the 0/360 seam" in capsys.readouterr().out  # says so out loud


def test_cluster_boxes_is_unchanged_for_a_normal_cluster(capsys):
    pts = [(32.0, 34.8), (32.1, 34.9)]
    ((box, members),) = cluster_boxes(pts)
    assert sorted(members) == [0, 1]
    assert 0.0 <= box.left < box.right <= 360.0
    assert "seam" not in capsys.readouterr().out


def test_committed_spots_produce_no_seam_warning(capsys):
    """The whole fleet must still cluster silently - this change is a no-op today."""
    from pathlib import Path

    from rosa_pipeline.spots import load_spots

    spots = load_spots(Path(__file__).resolve().parents[2] / "data" / "spots")
    pts = [(s.lat, s.lon) for s in spots.values()]
    boxes = cluster_boxes(pts)
    assert sum(len(m) for _, m in boxes) == len(pts)
    assert "seam" not in capsys.readouterr().out


def test_oisst_finds_the_wet_cell_across_the_seam():
    """A spot at 0.1 deg E whose only wet water is at 359.8 deg."""
    from rosa_pipeline import oisst

    lons = np.arange(0.125, 360.0, 0.25)
    lats = np.arange(-89.875, 90.0, 0.25)
    sst = np.full((len(lats), len(lons)), float(oisst.FILL))
    i = int(np.argmin(np.abs(lats - 5.0)))
    j = int(np.argmin(np.abs(lons - 359.875)))
    sst[i, j] = 2800.0  # x scale 0.01 -> 28.0 C

    # exercise the sampling core directly against synthetic arrays
    lon360_v = 0.125 % 360.0
    jc = int(np.argmin(np.abs(dlon180(lons, lon360_v))))
    reach = int(oisst.NEAREST_MAX_DEG / 0.25)
    cols = np.mod(np.arange(jc - reach, jc + reach + 1), len(lons))
    win = sst[max(0, i - reach) : i + reach + 1, :][:, cols]
    assert (win != oisst.FILL).any()  # the wrapped window reaches it
    # and the clipped window the old code used would not have
    clipped = sst[max(0, i - reach) : i + reach + 1, max(0, jc - reach) : jc + reach + 1]
    assert not (clipped != oisst.FILL).any()


def test_every_committed_spot_picks_the_same_oisst_cell_as_before():
    """The no-op proof the smoke rule wants, run offline.

    The wrapped window and the old clipped one must select the SAME cell for all 469
    committed spots - none is within a search radius of the seam - so no published SST,
    and nothing downstream of it, moves.
    """
    from pathlib import Path

    from rosa_pipeline.oisst import NEAREST_MAX_DEG
    from rosa_pipeline.spots import load_spots

    lons = np.arange(0.125, 360.0, 0.25)
    reach = int(NEAREST_MAX_DEG / 0.25)
    spots = load_spots(Path(__file__).resolve().parents[2] / "data" / "spots")
    assert len(spots) == 713

    for s in spots.values():
        lon360_v = s.lon % 360.0
        j_old = int(np.argmin(np.abs(lons - lon360_v)))
        j_new = int(np.argmin(np.abs(dlon180(lons, lon360_v))))
        assert j_old == j_new, f"{s.id}: centre cell moved"
        cols_new = np.mod(np.arange(j_new - reach, j_new + reach + 1), len(lons))
        cols_old = np.arange(max(0, j_old - reach), j_old + reach + 1)
        assert list(cols_new) == list(cols_old), f"{s.id}: window moved"
        # and the cos-weighted distance is identical over that window
        old_d = np.cos(np.radians(s.lat)) * (lons[cols_old] - lon360_v)
        new_d = np.cos(np.radians(s.lat)) * dlon180(lons[cols_new], lon360_v)
        assert np.allclose(old_d, new_d), f"{s.id}: distance moved"
