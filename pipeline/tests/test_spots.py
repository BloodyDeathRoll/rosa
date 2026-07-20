from pathlib import Path

from rosa_pipeline.spots import load_spots, load_spots_file

SPOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "spots"


def test_loads_israel_seed():
    spots = load_spots_file(SPOTS_DIR / "israel.yaml")
    assert len(spots) == 40


def test_beit_yanai_fields():
    spots = load_spots(SPOTS_DIR)
    by = spots["beit-yanai"]
    assert by.name == "Beit Yanai"
    # offshore_direction derived from the local coast tangent (W-facing coast → ~90-120)
    assert 90 <= by.offshore_direction <= 120
    assert by.swell_window == (250, 340)
    assert by.height_coeff == 1.0
    # sampled at its own coord pushed ~0.06° west, not a shared regional point
    assert by.offshore_point == (32.3817, 34.8035)
    assert by.timezone == "Asia/Jerusalem"
    assert by.ideal_size_m == (0.6, 1.5)


def test_per_spot_override_survives_merge():
    spots = load_spots(SPOTS_DIR)
    assert spots["bat-galim"].swell_window == (270, 360)  # bay orientation override


def test_per_spot_points_are_distinct():
    # neighbours no longer collapse onto one shared sample point (the identical-forecast bug)
    spots = load_spots(SPOTS_DIR)
    assert spots["hilton"].offshore_point != spots["kontiki"].offshore_point


def test_derived_directions_vary():
    spots = load_spots(SPOTS_DIR)
    dirs = {round(s.offshore_direction) for s in spots.values()}
    assert len(dirs) > 5  # not all pinned to a single default angle
