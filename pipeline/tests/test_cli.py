"""CLI: run --all publishes every spot with one fetch per unique offshore point."""

import json
from pathlib import Path

import pytest

from rosa_pipeline.cli import group_by_point, main
from rosa_pipeline.models import Spot
from rosa_pipeline.spots import load_spots

FIXTURES = Path(__file__).parent / "fixtures"

# both spots pinned to the same explicit offshore_point → one group, served by the
# single captured fixture (fixture_key 32.3817_34.8035)
SPOTS_YAML = """\
defaults: &d
  timezone: Asia/Jerusalem
  swell_window: [250, 340]
  height_coeff: 1.0
  break_type: beach
  ideal:
    wind_dir: [45, 135]
    size_m: [0.6, 1.5]

spots:
  - { id: spot-a, name: Spot A, lat: 32.39, lon: 34.86, offshore_point: [32.3817, 34.8035], <<: *d }
  - { id: spot-b, name: Spot B, lat: 32.43, lon: 34.87, offshore_point: [32.3817, 34.8035], <<: *d }
"""


def make_spot(spot_id: str, point: tuple[float, float]) -> Spot:
    return Spot(
        id=spot_id,
        name=spot_id,
        lat=32.0,
        lon=34.8,
        timezone="Asia/Jerusalem",
        offshore_point=point,
        offshore_direction=90.0,
        swell_window=(250.0, 340.0),
        height_coeff=1.0,
        break_type="beach",
        ideal_wind_dir=(45.0, 135.0),
        ideal_size_m=(0.6, 1.5),
    )


def test_group_by_point():
    a, b = make_spot("a", (32.2, 34.55)), make_spot("b", (32.2, 34.55))
    c = make_spot("c", (32.9, 34.85))
    groups = group_by_point([a, b, c])
    assert len(groups) == 2
    assert groups[(32.2, 34.55)] == [a, b]
    assert groups[(32.9, 34.85)] == [c]


def test_run_all_from_fixtures(tmp_path, capsys):
    spots_dir = tmp_path / "spots"
    spots_dir.mkdir()
    (spots_dir / "test.yaml").write_text(SPOTS_YAML, encoding="utf-8")
    out = tmp_path / "out"

    rc = main(
        [
            "run",
            "--all",
            "--spots-dir",
            str(spots_dir),
            "--out",
            str(out),
            "--fixtures",
            str(FIXTURES),
        ]
    )
    assert rc == 0
    assert (out / "spots" / "spot-a.json").exists()
    assert (out / "spots" / "spot-b.json").exists()
    index = json.loads((out / "index.json").read_text())
    assert set(index["spots"]) == {"spot-a", "spot-b"}
    assert len(capsys.readouterr().out.strip().splitlines()) == 2


def test_run_unknown_spot(tmp_path):
    rc = main(
        [
            "run",
            "--spot",
            "nope",
            "--spots-dir",
            "data/spots",
            "--out",
            str(tmp_path),
            "--fixtures",
            str(FIXTURES),
        ]
    )
    assert rc == 2


def test_spot_and_all_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        main(["run", "--spot", "beit-yanai", "--all"])
    with pytest.raises(SystemExit):
        main(["run"])


def test_real_db_loads_for_all():
    # each spot now samples its own offshore point → ~one group per spot (was 3 shared)
    spots = list(load_spots(Path(__file__).resolve().parents[2] / "data" / "spots").values())
    assert len(group_by_point(spots)) == len(spots)
