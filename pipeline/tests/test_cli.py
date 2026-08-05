"""CLI: run --all publishes every spot with one fetch per unique offshore point."""

import json
from pathlib import Path

import pytest

from rosa_pipeline.cli import group_by_point, main
from rosa_pipeline.models import Spot
from rosa_pipeline.spots import load_spots

FIXTURES = Path(__file__).parent / "fixtures"

# both spots resolve to the SAME deep-water point - different pins, with bearings and
# distances chosen to converge → one group, served by the single captured fixture
# (fixture_key 32.3817_34.8035)
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
  - { id: spot-a, name: Spot A, lat: 32.39, lon: 34.86,
      offshore_bearing: 260.1, offshore_km: 5.39, <<: *d }
  - { id: spot-b, name: Spot B, lat: 32.43, lon: 34.87,
      offshore_bearing: 229.3, offshore_km: 8.24, <<: *d }
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
        shore_normal=270.0,
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


def test_run_all_survives_one_failing_spot(tmp_path, monkeypatch, capsys):
    """Dream review 2026-08-05: this loop ran bare while every other step in _cmd_run was
    guarded, so one raising spot stranded every spot after it AND skipped prune_index -
    the ghost-card failure mode. The rest of the batch must publish, and the cycle must
    still exit 1 so publish.sh's trap sees a failed cycle."""
    import rosa_pipeline.cli as cli_mod

    spots_dir = tmp_path / "spots"
    spots_dir.mkdir()
    (spots_dir / "test.yaml").write_text(SPOTS_YAML, encoding="utf-8")
    out = tmp_path / "out"

    real = cli_mod.load_profile

    def sabotaged(spot_id, bathy_dir):
        if spot_id == "spot-b":
            raise ValueError("boom")
        return real(spot_id, bathy_dir)

    monkeypatch.setattr(cli_mod, "load_profile", sabotaged)
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
    err = capsys.readouterr().err
    assert rc == 1  # a failed spot is still a failed cycle
    assert (out / "spots" / "spot-a.json").exists()  # the batch went on without spot-b
    assert not (out / "spots" / "spot-b.json").exists()
    assert set(json.loads((out / "index.json").read_text())["spots"]) == {"spot-a"}
    assert "error: spot-b: ValueError('boom')" in err  # repr - the type is the signal
    assert "1 of 2 spot(s) failed (ValueError): spot-b" in err


def test_swellmap_world_only_with_basin_is_a_usage_error(capsys):
    """Dream review 2026-08-05: --world-only skips the basin layer and --basin narrows it,
    so together they select nothing. This fell through both branches and returned 1, which
    publish.sh's trap reads as a broken cycle, not a typo."""
    rc = main(["swellmap", "--world-only", "--basin", "east-med"])
    assert rc == 2
    assert "drop --basin" in capsys.readouterr().err


def test_swellmap_layer_flags_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        main(["swellmap", "--skip-world", "--world-only"])


def test_real_db_loads_for_all():
    # each spot now samples its own offshore point → ~one group per spot (was 3 shared)
    spots = list(load_spots(Path(__file__).resolve().parents[2] / "data" / "spots").values())
    assert len(group_by_point(spots)) == len(spots)
