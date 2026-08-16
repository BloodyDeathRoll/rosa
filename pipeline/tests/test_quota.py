"""The daily-quota guard (rosa_pipeline.quota) - the thing that was missing on 2026-08-15,
when an ad-hoc fleet run on top of the cron's four exhausted Open-Meteo's per-IP daily
allowance and took the cycle down with a mid-fleet 429."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rosa_pipeline import quota

SPOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "spots"


def test_marine_units_scale_with_the_point_count():
    # marine_units rounds to 0.1 - one point is the per-point weight itself
    assert quota.marine_units(1) == pytest.approx(round(quota.MARINE_UNITS_PER_POINT, 1))
    # a 265-spot fleet run against the default budget: the cron's four fit, a fifth does not.
    fleet = quota.marine_units(265)
    assert fleet == pytest.approx(2037.9)
    assert 4 * fleet < quota.DEFAULT_DAILY_BUDGET < 5 * fleet


def test_a_missing_ledger_is_a_fresh_day(tmp_path):
    led = quota.Ledger.load(tmp_path / "nope.json")
    assert led.spent == 0.0
    assert led.affords(quota.marine_units(265))


def test_spend_accumulates_and_survives_a_reload(tmp_path):
    path = tmp_path / "quota.json"
    led = quota.Ledger.load(path)
    led.record(quota.marine_units(265))
    led.record(quota.marine_units(265))
    again = quota.Ledger.load(path)
    assert again.spent == pytest.approx(2 * 2037.9)
    assert again.remaining == pytest.approx(quota.DEFAULT_DAILY_BUDGET - 2 * 2037.9)


def test_yesterdays_spend_does_not_count_against_today(tmp_path):
    """The cap resets at 00:00Z. A ledger that carried yesterday's total forward would
    refuse the first cycle of every day - the opposite failure, and a worse one."""
    path = tmp_path / "quota.json"
    yesterday = quota.Ledger.load(path, now=datetime(2026, 8, 15, 23, 0, tzinfo=UTC))
    yesterday.record(8_999.0)
    today = quota.Ledger.load(path, now=datetime(2026, 8, 16, 0, 5, tzinfo=UTC))
    assert today.spent == 0.0
    assert today.affords(quota.marine_units(265))


def test_a_corrupt_ledger_never_blocks_a_run(tmp_path):
    path = tmp_path / "quota.json"
    path.write_text("{not json at all")
    led = quota.Ledger.load(path)
    assert led.spent == 0.0
    assert led.affords(quota.marine_units(265))


def test_a_fifth_fleet_run_is_refused(tmp_path):
    led = quota.Ledger.load(tmp_path / "quota.json")
    fleet = quota.marine_units(265)
    for _ in range(4):
        assert led.affords(fleet)
        led.record(fleet)
    assert not led.affords(fleet)
    msg = led.refusal(fleet)
    assert "00:00Z" in msg and "--ignore-quota" in msg


def test_budget_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("ROSA_OM_DAILY_BUDGET", "100")
    assert quota.Ledger.load(tmp_path / "q.json").budget == 100.0
    monkeypatch.setenv("ROSA_OM_DAILY_BUDGET", "not-a-number")
    assert quota.Ledger.load(tmp_path / "q.json").budget == quota.DEFAULT_DAILY_BUDGET


def test_run_refuses_before_it_fetches(tmp_path, monkeypatch, capsys):
    """The guard has to sit in front of the network, not behind it: a run that fetches and
    then notices it is over budget has already spent the quota it was protecting."""
    from rosa_pipeline import cli

    monkeypatch.setenv("ROSA_OM_DAILY_BUDGET", "0")

    def explode(*a, **k):  # any live source construction is a failure of the guard
        raise AssertionError("fetched despite an exhausted quota")

    monkeypatch.setattr(cli, "OpenMeteoSource", explode)
    monkeypatch.setattr(cli, "EcmwfSource", explode)
    rc = cli.main(
        [
            "run",
            "--spot",
            "beit-yanai",
            "--spots-dir",
            str(SPOTS_DIR),
            "--quota-state",
            str(tmp_path / "quota.json"),
            "--out",
            str(tmp_path / "out"),
            "--skill",
            "/dev/null",
        ]
    )
    assert rc == quota.EXIT_QUOTA_EXHAUSTED
    assert "refusing to fetch" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_fixture_replay_is_exempt(tmp_path, monkeypatch):
    """An offline replay costs no quota, so a spent day must not stop the tests, the
    same-input A/B, or an operator debugging on a plane."""
    from rosa_pipeline import cli

    monkeypatch.setenv("ROSA_OM_DAILY_BUDGET", "0")
    rc = cli.main(
        [
            "run",
            "--spot",
            "beit-yanai",
            "--spots-dir",
            str(SPOTS_DIR),
            "--fixtures",
            str(Path(__file__).parent / "fixtures"),
            "--quota-state",
            str(tmp_path / "quota.json"),
            "--out",
            str(tmp_path / "out"),
            "--skill",
            "/dev/null",
        ]
    )
    assert rc == 0
    assert (tmp_path / "out" / "spots" / "beit-yanai.json").exists()
