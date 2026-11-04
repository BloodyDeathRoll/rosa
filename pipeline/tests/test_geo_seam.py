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


def test_cluster_boxes_splits_a_seam_crossing_cluster_in_two(capsys):
    """A cluster at 359.8 / 0.2 used to produce left=~-0.2 or a 359-wide box.

    grib-filter cannot express a wrapping box, and clamping would drop every cell on the
    far side of the seam - which is where half the members are. So the cluster is split
    and each side fetched: every member is still covered exactly once, each box is valid
    in 0-360, and neither is near-global."""
    pts = [(5.0, -0.2), (5.1, 0.2), (5.2, -0.4)]
    boxes = cluster_boxes(pts)
    assert len(boxes) == 2
    assert sorted(i for _, m in boxes for i in m) == [0, 1, 2]
    for box, members in boxes:
        assert members  # no empty side
        assert 0.0 <= box.left <= box.right <= 360.0
        assert box.right - box.left < 5.0
        # every member of a side really sits inside that side's box
        for i in members:
            assert box.left <= lon360(pts[i][1]) <= box.right
    assert "seam" not in capsys.readouterr().out  # splitting is the fix, not a warning


def test_cluster_boxes_is_unchanged_for_a_normal_cluster(capsys):
    pts = [(32.0, 34.8), (32.1, 34.9)]
    ((box, members),) = cluster_boxes(pts)
    assert sorted(members) == [0, 1]
    assert 0.0 <= box.left < box.right <= 360.0
    assert "seam" not in capsys.readouterr().out


def test_cluster_boxes_clamps_padding_silently_when_no_member_crosses(capsys):
    """Cornwall to Scarborough spans 354-359.6 deg: the members are inside the file and
    only the 1-degree pad would cross, so the box is clamped at 360 without a warning."""
    pts = [(50.1, -5.7), (54.3, -0.4)]
    ((box, members),) = cluster_boxes(pts)
    assert sorted(members) == [0, 1]
    assert box.right == 360.0 and box.left > 350.0
    assert "seam" not in capsys.readouterr().out


def test_committed_spots_are_each_in_exactly_one_fetch_box():
    """Splitting a seam-crossing cluster must not lose or duplicate a spot.

    Ghana (358-360 deg) clusters with Angola (13 deg) - 15 deg apart, inside
    CLUSTER_SPAN_DEG - so the group straddles the seam and is split. Every committed spot
    must still appear exactly once, inside a box that really contains it."""
    from pathlib import Path

    from rosa_pipeline.spots import load_spots

    spots = load_spots(Path(__file__).resolve().parents[2] / "data" / "spots")
    pts = [(s.lat, s.lon) for s in spots.values()]
    boxes = cluster_boxes(pts)
    seen = sorted(i for _, m in boxes for i in m)
    assert seen == list(range(len(pts))), "a spot was dropped or double-counted"
    for box, members in boxes:
        assert 0.0 <= box.left <= box.right <= 360.0
        for i in members:
            lat, lon = pts[i]
            assert box.bottom <= lat <= box.top
            assert box.left <= lon360(lon) <= box.right


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

    For every spot FARTHER than the search radius from the 0/360 seam the wrapped window
    and the old clipped one select the same cells, so no published SST - and nothing
    downstream of it - moves. Spots inside that radius are the reason the wrap exists:
    since 2026-09-03 the Yorkshire coast (Saltburn to Cayton Bay, 0.97 W to 0.36 W) and
    Ghana's Accra pair (Kokrobite and Labadi, 0.36 W to 0.14 W) sit inside it, since
    2026-09-11 Algeria's Oran pair (Ain El Turk 0.79 W, Cap Ivi 0.22 E) and since 2026-10-29
    the Valencian and Murcian coasts (Castellon to Cartagena) too, and the old
    code clipped those windows at column 0 and lost the cells across the seam. They are
    asserted separately: same centre cell, full-width window, and it must actually wrap.
    """
    from pathlib import Path

    from rosa_pipeline.oisst import NEAREST_MAX_DEG
    from rosa_pipeline.spots import load_spots

    lons = np.arange(0.125, 360.0, 0.25)
    reach = int(NEAREST_MAX_DEG / 0.25)
    spots = load_spots(Path(__file__).resolve().parents[2] / "data" / "spots")
    assert len(spots) == 3613

    near_seam = []
    for s in spots.values():
        lon360_v = s.lon % 360.0
        j_old = int(np.argmin(np.abs(lons - lon360_v)))
        j_new = int(np.argmin(np.abs(dlon180(lons, lon360_v))))
        assert j_old == j_new, f"{s.id}: centre cell moved"
        cols_new = np.mod(np.arange(j_new - reach, j_new + reach + 1), len(lons))
        if j_new - reach < 0 or j_new + reach >= len(lons):
            near_seam.append((s, cols_new))
            continue
        cols_old = np.arange(j_old - reach, j_old + reach + 1)
        assert list(cols_new) == list(cols_old), f"{s.id}: window moved"
        # and the cos-weighted distance is identical over that window
        old_d = np.cos(np.radians(s.lat)) * (lons[cols_old] - lon360_v)
        new_d = np.cos(np.radians(s.lat)) * dlon180(lons[cols_new], lon360_v)
        assert np.allclose(old_d, new_d), f"{s.id}: distance moved"

    # the seam spots the wrap exists for: a full-width window that really wraps, and
    # every column within the search radius by the signed distance
    assert sorted(s.id for s, _ in near_seam) == [
        "aiguaoliva",
        "ain-el-turk",
        "bexhill",
        "birling-gap",
        "brighton",
        "cala-cantalar",
        "cala-finestrat",
        "calblanque",
        "camber-sands",
        "cap-ivi",
        "cayton-bay",
        "courseulles-sur-mer",
        "deauville",
        "derecha-de-la-cala",
        "east-wittering",
        "el-arenal",
        "el-cantal-roig",
        "el-jucar",
        "el-perello",
        "el-puerto",
        "el-saler",
        "etretat",
        "fairlight",
        "fecamp",
        "hastings",
        "hayling-island",
        "hot-pipe",
        "kokrobite",
        "la-calita",
        "la-manga",
        "la-mata",
        "la-placa",
        "la-siesta",
        "la-zenia",
        "labadi",
        "le-havre",
        "les-petites-dalles",
        "les-rotes",
        "littlehampton",
        "luc-sur-mer",
        "malva-rosa",
        "miami-platja",
        "oliva-beach",
        "pico-madrid",
        "platja-de-lampolla",
        "platja-de-lauir",
        "platja-de-miramar",
        "platja-de-xeraco",
        "playa-de-bellreguard",
        "playa-de-entremares",
        "playa-de-la-albufereta",
        "playa-de-las-arenas",
        "playa-de-san-juan",
        "playa-del-bol",
        "playa-del-cura",
        "playa-del-descargador",
        "playa-del-dosel",
        "playa-del-gorguel",
        "playa-del-postiguet",
        "playa-del-saladar",
        "playa-del-torres",
        "playa-muchavista",
        "playa-poniente",
        "port-saplaya",
        "portman",
        "puerto-benidorm",
        "punta-prima",
        "rio-algar",
        "runswick-bay",
        "sagunto",
        "sainte-adresse",
        "saltburn",
        "sandsend",
        "scarborough-north-bay",
        "shoreham",
        "sierra-de-irta",
        "south-lancing",
        "stamco",
        "vaucottes",
        "veules-les-roses",
        "voramar",
        "west-wittering",
        "whitby",
        "yport",
    ], "seam-spot set changed"
    for s, cols in near_seam:
        assert len(cols) == 2 * reach + 1, f"{s.id}: window truncated at the seam"
        assert len(set(cols.tolist())) == len(cols), f"{s.id}: window repeats a column"
        assert cols.max() - cols.min() > reach, f"{s.id}: window did not wrap"
        d = np.abs(dlon180(lons[cols], s.lon % 360.0))
        assert d.max() <= NEAREST_MAX_DEG + 0.25, f"{s.id}: window reaches too far"
