"""The rosa-backup staleness watchdog's decision logic (deploy/backup/freshness-watch.py).

This runs off-repo on rosa-backup and is the *second* eye on publishing - the publish VM's
own ERR trap cannot fire when the VM is down or cron never runs. A bug here is silent by
construction: it does not break a forecast, it just means nobody gets paged. Hence tests.

Loaded by path because the watchdog is a standalone script (stdlib only at import time,
pywebpush imported lazily inside push()), not part of the rosa_pipeline package.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "backup" / "freshness-watch.py"
_spec = importlib.util.spec_from_file_location("freshness_watch", SCRIPT)
assert _spec and _spec.loader
watch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(watch)

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def test_fresh_data_is_silent() -> None:
    """A cycle that landed within the window must not page anyone."""
    assert watch.stale_message(NOW - timedelta(hours=3), NOW) is None


def test_stale_data_pages_with_the_age_in_the_message() -> None:
    msg = watch.stale_message(NOW - timedelta(hours=9), NOW)
    assert msg is not None
    assert "9.0 h ago" in msg  # the age is the whole point of the page
    assert "publish.log" in msg  # and it says where to look


def test_boundary_is_inclusive_so_a_cycle_exactly_at_the_limit_is_still_ok() -> None:
    """MAX_AGE_H is 'cycles run every 6 h + slack' - at exactly the limit, nothing is wrong."""
    at_limit = NOW - timedelta(hours=watch.MAX_AGE_H)
    assert watch.stale_message(at_limit, NOW) is None
    just_over = NOW - timedelta(hours=watch.MAX_AGE_H, minutes=1)
    assert watch.stale_message(just_over, NOW) is not None


def test_first_problem_alerts_immediately() -> None:
    assert watch.alert_is_due({}, NOW) is True
    assert watch.alert_is_due({"last_alert": None}, NOW) is True


def test_recent_alert_suppresses_the_hourly_nag() -> None:
    """The watchdog runs hourly; a still-broken system must not page every hour."""
    recent = (NOW - timedelta(hours=2)).isoformat()
    assert watch.alert_is_due({"last_alert": recent}, NOW) is False


def test_alert_repeats_once_the_realert_window_has_passed() -> None:
    """Still broken after REALERT_H means page again - silence must not be permanent."""
    old = (NOW - timedelta(hours=watch.REALERT_H)).isoformat()
    assert watch.alert_is_due({"last_alert": old}, NOW) is True
