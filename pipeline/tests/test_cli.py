"""CLI: run --all publishes every spot with one fetch per unique offshore point."""

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rosa_pipeline.cli import _implausible_break_hours, group_by_point, main
from rosa_pipeline.models import HourForecast, Spot, SwellPartition
from rosa_pipeline.score import score_hour
from rosa_pipeline.spots import load_spots
from rosa_pipeline.transform import in_window, spread_exposure

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
            "--wave-source",
            "om",
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
            "--wave-source",
            "om",
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
    still exit 1 so publish.sh's trap sees a failed cycle.

    1 of 2 is a 50% fleet-failure share, far above PARTIAL_FAILURE_MAX_SHARE, so this is
    the hard-failure side of that rule (2026-08-28) - the shape a schema break has, which
    must never reach the CDN."""
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
            "--wave-source",
            "om",
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


def test_a_small_share_of_failures_still_publishes(tmp_path, monkeypatch, capsys):
    """2026-08-28: three shallow-profile spots raised the same ValueError, `run --all`
    returned 1, publish.sh's trap killed the cycle - and 621 healthy spots plus six freshly
    seeded regions sat off the CDN for a day. Withholding the whole forecast over a handful
    of spots is the more expensive failure, so under the share threshold the run exits
    EXIT_PARTIAL: publish.sh deploys on it and alerts instead of aborting.

    The share is patched rather than fabricating 20 spots - the rule under test is the
    comparison, not the constant."""
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
    monkeypatch.setattr(cli_mod, "PARTIAL_FAILURE_MAX_SHARE", 0.5)  # 1 of 2 now counts
    rc = main(
        [
            "run",
            "--wave-source",
            "om",
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
    assert rc == cli_mod.EXIT_PARTIAL
    assert rc != 0  # still not a clean cycle - the alert must fire
    assert (out / "spots" / "spot-a.json").exists()
    assert "1 of 2 spot(s) failed" in err  # the failure is still reported in full
    assert "publishing the other 1 spot(s) anyway" in err


def test_nothing_published_is_a_hard_failure_whatever_the_share(tmp_path, monkeypatch):
    """The share is meaningless at zero published, and an empty deploy is the one outcome
    that must never reach the CDN. Guarded before the share is ever computed."""
    import rosa_pipeline.cli as cli_mod

    spots_dir = tmp_path / "spots"
    spots_dir.mkdir()
    (spots_dir / "test.yaml").write_text(SPOTS_YAML, encoding="utf-8")

    def sabotaged(spot_id, bathy_dir):
        raise ValueError("boom")

    monkeypatch.setattr(cli_mod, "load_profile", sabotaged)
    monkeypatch.setattr(cli_mod, "PARTIAL_FAILURE_MAX_SHARE", 1.0)  # would allow anything
    rc = main(
        [
            "run",
            "--wave-source",
            "om",
            "--all",
            "--spots-dir",
            str(spots_dir),
            "--out",
            str(tmp_path / "out"),
            "--fixtures",
            str(FIXTURES),
        ]
    )
    assert rc == 1


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


def test_verify_skill_write_is_opt_in():
    """2026-08-07 review: skill.json is fleet-wide state (run --all feeds it to every
    spot's confidence ceiling), so the documented single-buoy spot check must not
    write it as a side effect - persisting requires an explicit --write-skill."""
    from rosa_pipeline.cli import _build_parser

    args = _build_parser().parse_args(["verify", "--buoy", "46042", "--archive"])
    assert args.write_skill is False
    args = _build_parser().parse_args(["verify", "--buoy", "46042", "--archive", "--write-skill"])
    assert args.write_skill is True


def test_verify_all_buoys_fleet_pass(tmp_path, monkeypatch, capsys):
    """The scheduled fleet pass (verify --all-buoys --archive --write-skill): skips
    ISRAMAR buoys (legal red line), survives one failing buoy per-buoy like run --all
    survives one failing spot, and writes skill.json naming only the buoys that
    actually contributed."""
    import rosa_pipeline.cli as cli

    root = Path(__file__).resolve().parents[2]
    failed = []

    def fake_obs(buoy, args):
        if not failed:
            failed.append(buoy.id)
            raise RuntimeError("obs outage")
        return []

    monkeypatch.setattr(cli, "_obs_for", fake_obs)
    monkeypatch.setattr(cli, "_with_measured_energy_period", lambda b, o, a, v: (o, v))
    rc = main(
        [
            "verify",
            "--all-buoys",
            "--archive",
            "--write-skill",
            "--buoys-dir",
            str(root / "data" / "buoys"),
            "--isramar-dir",
            str(tmp_path / "no-isramar"),
            "--archive-dir",
            str(tmp_path / "archive"),
        ]
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "left out of this skill pass" in err
    skill = json.loads((tmp_path / "skill.json").read_text())
    assert failed[0] not in skill["buoy_ids"]
    assert len(skill["buoy_ids"]) >= 2  # the rest of the fleet still contributed


BUOYS_YAML = """\
buoys:
  - {id: "11111", name: "B1", lat: 30.0, lon: -120.0, source: ndbc}
  - {id: "22222", name: "B2", lat: 31.0, lon: -121.0, source: ndbc}
  - {id: "33333", name: "B3", lat: 32.0, lon: -122.0, source: ndbc}
"""


def _marine_body() -> dict:
    hours = [f"2026-08-09T{h:02d}:00" for h in range(3)]
    return {
        "hourly": {
            "time": hours,
            "wave_height": [1.0, 1.1, 1.2],
            "wave_period": [8.0, 8.0, 8.0],
            "wave_direction": [270.0, 271.0, 272.0],
        }
    }


def _archive_argv(tmp_path: Path, buoys_dir: Path, extra: list[str] | None = None) -> list[str]:
    return [
        "archive",
        "--wave-source",
        "om",
        "--buoys-dir",
        str(buoys_dir),
        "--isramar-dir",
        str(tmp_path / "no-isramar"),
        "--archive-dir",
        str(tmp_path / "archive"),
        "--stations-dir",
        str(tmp_path / "no-stations"),  # keep the coastal-station arm offline
        *(extra or []),
    ]


STATIONS_YAML = """\
stations:
  - {id: "LLBG", name: "Ben Gurion", lat: 32.011, lon: 34.887, source: metar}
"""


def _wind_body(hours: list[str], speed: float = 4.0) -> dict:
    return {
        "hourly": {
            "time": hours,
            "wind_speed_10m": [speed for _ in hours],
            "wind_direction_10m": [270 for _ in hours],
        }
    }


def test_archive_station_arm_writes_wind_rows_and_never_raises(tmp_path, monkeypatch, capsys):
    """The coastal-station arm rides the buoy archive: one weather-host batch for the
    whole registry, wind-only rows per station under its own dir, and a batch failure
    is a warning - the buoy archive's exit code is untouched."""
    import rosa_pipeline.cli as cli

    buoys_dir = tmp_path / "buoys"
    buoys_dir.mkdir()
    (buoys_dir / "test.yaml").write_text(BUOYS_YAML, encoding="utf-8")
    stations_dir = tmp_path / "stations"
    stations_dir.mkdir()
    (stations_dir / "metar.yaml").write_text(STATIONS_YAML, encoding="utf-8")
    monkeypatch.setattr(
        cli, "fetch_marine_waves_many", lambda coords: [_marine_body() for _ in coords]
    )
    calls: list[tuple[list[tuple[float, float]], str]] = []

    def fake_wind(coords, *, model=cli.WEATHER_MODEL):
        calls.append((coords, model))
        speed = 4.0 if model == cli.WEATHER_MODEL else 2.0
        return [_wind_body(["2026-08-09T00:00", "2026-08-09T01:00"], speed) for _ in coords]

    monkeypatch.setattr(cli, "fetch_wind_many", fake_wind)
    argv = _archive_argv(tmp_path, buoys_dir)
    argv[argv.index("--stations-dir") + 1] = str(stations_dir)
    st_archive = tmp_path / "st-archive"
    rc = main([*argv, "--stations-archive-dir", str(st_archive)])
    assert rc == 0
    # the buoy fleet path's own wind join calls fetch_wind_many too; the station batches
    # are the ones carrying the station's coordinate - one per model, published + A/B
    assert ([(32.011, 34.887)], "gfs_seamless") in calls
    assert ([(32.011, 34.887)], "icon_seamless") in calls
    rows = [json.loads(line) for line in (st_archive / "LLBG.jsonl").read_text().splitlines()]
    assert len(rows) == 2 and rows[0]["ws"] == 4.0 and rows[0]["hs"] is None
    ab = [json.loads(line) for line in (st_archive / "LLBG.icon.jsonl").read_text().splitlines()]
    assert len(ab) == 2 and ab[0]["ws"] == 2.0

    def ab_boom(coords, *, model=cli.WEATHER_MODEL):
        if model != cli.WEATHER_MODEL:
            raise RuntimeError("icon leg down")
        return [_wind_body(["2026-08-09T00:00"], 4.0) for _ in coords]

    # losing the A/B member keeps the published model's rows
    monkeypatch.setattr(cli, "fetch_wind_many", ab_boom)
    st_archive_ab = tmp_path / "st-archive-ab"
    rc = main([*argv, "--stations-archive-dir", str(st_archive_ab)])
    assert rc == 0
    assert (st_archive_ab / "LLBG.jsonl").exists()
    assert not (st_archive_ab / "LLBG.icon.jsonl").exists()
    assert "A/B member skipped" in capsys.readouterr().err

    def boom(coords, *, model=cli.WEATHER_MODEL):
        raise RuntimeError("weather host down")

    monkeypatch.setattr(cli, "fetch_wind_many", boom)
    rc = main([*argv, "--stations-archive-dir", str(tmp_path / "st-archive-2")])
    assert rc == 0
    assert "station arm skipped" in capsys.readouterr().err


def test_verify_stations_scores_wind_by_lead_from_the_real_metar_capture(tmp_path, capsys):
    """verify --stations --archive: archived model wind vs the station's METARs, wind
    columns only, per-station card + pooled card; a station with no archive is skipped,
    not failed. Model rows are hand-written 1 m/s above a flat 4 m/s so the bias is known."""
    root = Path(__file__).resolve().parents[2]
    stations_dir = tmp_path / "stations"
    stations_dir.mkdir()
    (stations_dir / "metar.yaml").write_text(
        STATIONS_YAML + '  - {id: "NOPE", name: "no archive", lat: 0, lon: 0, source: metar}\n',
        encoding="utf-8",
    )
    st_archive = tmp_path / "st-archive"
    st_archive.mkdir()
    run = "2026-08-28T18:00:00+00:00"
    obs_start = datetime(2026, 8, 28, 19, tzinfo=UTC)
    for key, ws in (("LLBG", 99.0), ("LLBG.icon", 0.0)):
        with (st_archive / f"{key}.jsonl").open("w") as fh:
            for h in range(25):
                valid = (obs_start + __import__("datetime").timedelta(hours=h)).isoformat()
                fh.write(json.dumps({"run": run, "valid": valid, "ws": ws, "wdir": 260}) + "\n")
    argv = [
        "verify",
        "--stations",
        "--archive",
        "--stations-dir",
        str(stations_dir),
        "--stations-archive-dir",
        str(st_archive),
        "--obs-fixtures",
        str(root / "pipeline" / "tests" / "fixtures" / "verify"),
    ]
    rc = main(argv)
    out = capsys.readouterr().out
    assert rc == 0
    assert "wind model: gfs" in out
    assert "lead-time skill vs station LLBG" in out
    assert "NOPE: no archived gfs wind yet" in out
    assert "pooled coastal wind skill (gfs) - 1 of 2 station(s)" in out
    # 99 m/s against a ~4-7 m/s airport reads as a huge positive bias - sign is the point
    lines = [ln for ln in out.splitlines() if "Wind speed" in ln]
    assert lines and all("+9" in ln for ln in lines)
    assert "Sig. wave height" not in out

    # the A/B member is scored from its own key against the same METARs: 0 m/s model
    # rows read as a negative bias of the airport's own mean
    rc = main([*argv, "--wind-model", "icon"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "wind model: icon" in out and "pooled coastal wind skill (icon)" in out
    lines = [ln for ln in out.splitlines() if "Wind speed" in ln]
    assert lines and all("-" in ln.split("m/s")[0] for ln in lines)


def test_verify_stations_needs_archive(capsys):
    assert main(["verify", "--stations"]) == 2
    assert "add --archive" in capsys.readouterr().err


def test_archive_fleet_batches_om_into_one_request(tmp_path, monkeypatch):
    """The live fleet archive makes ONE comma-joined marine request, not one per buoy,
    while per-buoy capture filenames and archive rows stay exactly as before."""
    import rosa_pipeline.cli as cli

    buoys_dir = tmp_path / "buoys"
    buoys_dir.mkdir()
    (buoys_dir / "test.yaml").write_text(BUOYS_YAML, encoding="utf-8")
    calls: list[list[tuple[float, float]]] = []

    def fake_many(coords):
        calls.append(coords)
        return [_marine_body() for _ in coords]

    monkeypatch.setattr(cli, "fetch_marine_waves_many", fake_many)
    capture = tmp_path / "capture"
    rc = main(_archive_argv(tmp_path, buoys_dir, ["--capture", str(capture)]))
    assert rc == 0
    assert calls == [[(30.0, -120.0), (31.0, -121.0), (32.0, -122.0)]]
    for bid in ("11111", "22222", "33333"):
        assert (tmp_path / "archive" / f"{bid}.jsonl").exists()
        assert (capture / f"marine_{bid}.json").exists()


def test_archive_fleet_batch_failure_degrades_not_raises(tmp_path, monkeypatch, capsys):
    """One bad batch skips the om pass but must not raise (the gfswave/ecmwf members
    and the cron trap's exit-1 summary still run) - the semantics the per-buoy guard
    established, at batch granularity."""
    import rosa_pipeline.cli as cli

    buoys_dir = tmp_path / "buoys"
    buoys_dir.mkdir()
    (buoys_dir / "test.yaml").write_text(BUOYS_YAML, encoding="utf-8")

    def fake_many(coords):
        raise RuntimeError("marine host hiccup")

    monkeypatch.setattr(cli, "fetch_marine_waves_many", fake_many)
    rc = main(_archive_argv(tmp_path, buoys_dir))
    err = capsys.readouterr().err
    assert rc == 1
    assert "open-meteo batch failed" in err
    assert not (tmp_path / "archive").exists() or not list((tmp_path / "archive").glob("*.jsonl"))


class TestImplausibleBreakGuard:
    """The precompute-time sanity check on breaker MAGNITUDE.

    Nothing between ``breaker_height_from_profile`` and the CDN inspects how big
    ``h_break_mid`` is - correct by design, the transform is the authority. But Rosa
    serves static JSON with no request-time backend, so a bad number ships to every
    client for a whole cycle. This warns; it never clamps, so no rating can move.
    """

    SPOT = Spot(
        id="test",
        name="Test",
        lat=32.0,
        lon=34.8,
        timezone="Asia/Jerusalem",
        offshore_point=(32.2, 34.55),
        offshore_direction=90.0,
        shore_normal=270.0,
        swell_window=(250.0, 340.0),
        height_coeff=1.0,
        break_type="beach",
        ideal_wind_dir=(45.0, 135.0),
        ideal_size_m=(0.6, 1.5),
    )

    def _scored(self, h_break_mid: float, partitions):
        h = HourForecast(
            time=datetime(2026, 8, 15, 6, tzinfo=UTC),
            partitions=partitions,
            sst_c=25.0,
            wind_speed_kph=10.0,
            wind_dir_deg=90.0,
            wind_gusts_kph=None,
        )
        return dataclasses.replace(score_hour(self.SPOT, h), h_break_mid=h_break_mid)

    def test_plausible_height_is_silent(self):
        parts = (SwellPartition(height_m=2.0, period_s=10.0, direction_deg=290.0),)
        assert _implausible_break_hours(self.SPOT, [self._scored(2.6, parts)]) == []

    def test_long_period_groundswell_shoaling_is_not_an_alarm(self):
        """The regime the committed Med capture does not contain. A live fleet run put 19
        hours over 3x, every one a Pacific groundswell at Tp 14.9-17.9 s - real physics, not
        a defect. Live max is 3.25x, so the threshold must clear it. This is puerto-sandino
        2026-08-27T15:00 (1.30 m from a 0.40 m sea, Tp 17.5 s), the worst real case seen."""
        parts = (SwellPartition(height_m=0.40, period_s=15.8, direction_deg=290.0),)
        assert _implausible_break_hours(self.SPOT, [self._scored(1.30, parts)]) == []

    def test_implausible_height_is_reported(self):
        parts = (SwellPartition(height_m=3.0, period_s=8.0, direction_deg=290.0),)
        hits = _implausible_break_hours(self.SPOT, [self._scored(24.96, parts)])
        assert len(hits) == 1
        _iso, h_mid, sea = hits[0]
        assert (h_mid, sea) == (24.96, 3.0)

    def test_denominator_is_the_soft_window_not_the_hard_bearing_test(self):
        """The physics weights every partition by sqrt(spread_exposure), so a train whose
        fan only CLIPS the window still feeds the breaker. Measuring against the hard
        in_window() test instead undercounts the sea and fired on 42 sound fleet hours."""
        # 345 deg is outside (250, 340) but its directional fan still reaches the spot
        p = SwellPartition(height_m=3.0, period_s=12.0, direction_deg=345.0)
        assert not in_window(p.direction_deg, self.SPOT.swell_window)
        assert spread_exposure(p, self.SPOT.swell_window) > 0
        assert _implausible_break_hours(self.SPOT, [self._scored(4.0, (p,))]) == []

    def test_flat_sea_rounding_artefact_does_not_fire(self):
        """The fleet-wide max ratio on the committed capture is 2.012, at onjuku - 0.04 m
        from a 0.02 m sea. That is arithmetic at the flat end, not a physics failure, so
        the floor keeps it quiet; the defect this guards against produces tens of metres."""
        parts = (SwellPartition(height_m=0.02, period_s=4.0, direction_deg=290.0),)
        assert _implausible_break_hours(self.SPOT, [self._scored(0.04, parts)]) == []

    def test_no_in_window_sea_has_nothing_to_compare_against(self):
        parts = (SwellPartition(height_m=2.0, period_s=10.0, direction_deg=90.0),)
        assert _implausible_break_hours(self.SPOT, [self._scored(5.0, parts)]) == []
