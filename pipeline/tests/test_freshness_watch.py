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


def _index(ages_h: dict[str, float]) -> dict:
    return {
        "spots": {
            sid: {"generated_at": (NOW - timedelta(hours=h)).isoformat()}
            for sid, h in ages_h.items()
        }
    }


def test_a_spot_left_behind_by_a_partial_cycle_is_caught() -> None:
    """The hole exit 4 opened (2026-08-28). publish.sh now DEPLOYS a partial run, so a failing
    spot keeps serving its previous payload while beit-yanai - the only spot the single-payload
    check reads - refreshes on time. Without this sweep that spot rots invisibly forever."""
    rotting = watch.rotting_spots(_index({"fresh": 2.0, "rotten": 40.0}), NOW)
    assert rotting == [("rotten", 40.0)]
    msg = watch.rot_message(rotting, 2)
    assert msg is not None and "rotten 40 h" in msg and "1 of 2" in msg


def test_missing_one_cycle_does_not_page() -> None:
    """Cycles are 6 h apart, so a spot that missed one reads 6-12 h. That is the partial run
    working as designed - paging on it would make exit 4 useless."""
    assert watch.rotting_spots(_index({"a": 6.5, "b": 12.0, "c": 23.9}), NOW) == []
    assert watch.rot_message([], 3) is None


def test_the_worst_offenders_are_named_and_the_rest_counted() -> None:
    """A schema break rots all 624 spots; the push must stay readable and still say how bad."""
    ages = {f"spot-{i}": 30.0 + i for i in range(watch.MAX_SPOTS_NAMED + 3)}
    rotting = watch.rotting_spots(_index(ages), NOW)
    msg = watch.rot_message(rotting, 624)
    assert msg is not None
    assert msg.count(" h,") + 1 >= watch.MAX_SPOTS_NAMED  # oldest-first, capped
    assert "+3 more" in msg
    assert f"{len(ages)} of 624" in msg


def test_a_spot_without_a_timestamp_is_skipped_not_assumed_rotten() -> None:
    """A schema gap must not masquerade as rot - that turns one bug into a false page."""
    index = _index({"ok": 1.0})
    index["spots"]["no-stamp"] = {"name": "No Stamp"}
    assert watch.rotting_spots(index, NOW) == []


def test_a_whole_fleet_rotting_is_reported_as_no_cycle_not_a_partial_one() -> None:
    """Pointing at publish.log's "failing ids" when nothing ran sends the reader after a list
    that does not exist. All spots stale means no cycle landed - the 2026-08-27/28 outage."""
    all_rotten = _index({"a": 30.0, "b": 31.0})
    msg = watch.rot_message(watch.rotting_spots(all_rotten, NOW), 2)
    assert msg is not None and "No cycle has landed" in msg
    some = _index({"a": 2.0, "b": 31.0})
    msg = watch.rot_message(watch.rotting_spots(some, NOW), 2)
    assert msg is not None and "partial cycle" in msg
