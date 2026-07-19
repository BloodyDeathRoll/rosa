from pathlib import Path

from rosa_pipeline.spots import load_spots, load_spots_file

SPOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "spots"


def test_loads_israel_seed():
    spots = load_spots_file(SPOTS_DIR / "israel.yaml")
    assert len(spots) == 38


def test_beit_yanai_fields():
    spots = load_spots(SPOTS_DIR)
    by = spots["beit-yanai"]
    assert by.name == "Beit Yanai"
    assert by.offshore_direction == 90
    assert by.swell_window == (250, 340)
    assert by.height_coeff == 1.0
    assert by.offshore_point == (32.2, 34.55)  # il_central
    assert by.timezone == "Asia/Jerusalem"
    assert by.ideal_size_m == (0.6, 1.5)


def test_per_spot_override_survives_merge():
    spots = load_spots(SPOTS_DIR)
    assert spots["bat-galim"].swell_window == (270, 360)  # bay orientation override
