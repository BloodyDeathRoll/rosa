#!/usr/bin/env python3
"""Stale-forecast watchdog - runs on rosa-backup (NOT the publish VM), hourly cron.

The publish VM alerts when a cycle fails (publish.sh ERR trap), but can't alert
when it is down or cron never fires. This watchdog is the second, independent
eye: it reads a published spot payload's fetched_at from rosa-data and pushes an
admin alert when no fresh cycle has landed in MAX_AGE_H hours (or the CDN is
unreadable). Re-alerts at most every REALERT_H hours while the problem persists.

Standalone by design - stdlib + pywebpush only, no repo checkout needed:
  ~/rosa-watch/freshness-watch.py   this file
  ~/rosa-watch/admin-subs.json      admin device snapshot (same as publish VM)
  ~/rosa-watch/vapid_private.pem    VAPID private key
  ~/rosa-watch/venv/                python3 -m venv + pip install pywebpush
Cron: 17 * * * * ~/rosa-watch/venv/bin/python3 ~/rosa-watch/freshness-watch.py \
        >> ~/rosa-watch/watch.log 2>&1
"""

import json
import os
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

DATA_URL = "https://rosa-data-opal.vercel.app/data/spots/beit-yanai.json"
# Cycles run every 6 h, but `fetched_at` is stamped when a cycle STARTS and the data only
# reaches the CDN 60-90 min later, so served age peaks near 6.9 h just before each publish
# lands. At the old 7.0 that left ~6 min of headroom and any slow cycle paged a false alarm.
# 8.0 keeps a genuinely missed cycle (>12 h) firmly in range.
MAX_AGE_H = 8.0
REALERT_H = 12.0  # keep nagging while broken, but never hourly
BASE = Path.home() / "rosa-watch"
STATE = BASE / "state.json"
SUBS = BASE / "admin-subs.json"
VAPID_PEM = BASE / "vapid_private.pem"
VAPID_SUB = os.environ.get("VAPID_SUB", "mailto:shaharnaor@outlook.com")


def stale_message(fetched_at: datetime, now: datetime, max_age_h: float = MAX_AGE_H) -> str | None:
    """The alert text when the last good cycle is too old, else None.

    Both datetimes must be tz-aware; the published ``fetched_at`` carries an offset."""
    age_h = (now - fetched_at).total_seconds() / 3600
    if age_h <= max_age_h:
        return None
    return (
        f"Forecast data is STALE: last good cycle {age_h:.1f} h ago "
        f"(limit {max_age_h:g} h). Check rosa-instance + publish.log."
    )


def alert_is_due(state: dict, now: datetime, realert_h: float = REALERT_H) -> bool:
    """False while a recent alert already covers this problem - broken must not mean hourly."""
    last = state.get("last_alert")
    if not last:
        return True
    return (now - datetime.fromisoformat(last)).total_seconds() / 3600 >= realert_h


def push(message: str) -> int:
    from pywebpush import WebPushException, webpush

    sent = 0
    for sub in json.loads(SUBS.read_text()):
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
                data=json.dumps({"title": "Rosa watchdog", "body": message, "tag": "rosa-admin"}),
                vapid_private_key=str(VAPID_PEM),
                vapid_claims={"sub": VAPID_SUB},
            )
            sent += 1
        except WebPushException as exc:
            print(f"push failed: {exc}")
    return sent


def main() -> int:
    now = datetime.now(UTC)
    problem = None
    try:
        req = urllib.request.Request(
            f"{DATA_URL}?cb={int(time.time())}", headers={"cache-control": "no-cache"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
        problem = stale_message(datetime.fromisoformat(payload["fetched_at"]), now)
    except Exception as exc:  # unreadable CDN is page-worthy too
        problem = f"Can't read rosa-data ({type(exc).__name__}) - CDN or publish problem."

    if problem is None:
        print(f"{now.isoformat(timespec='seconds')} ok")
        return 0

    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not alert_is_due(state, now):
        print(f"{now.isoformat(timespec='seconds')} still broken, alerted recently: {problem}")
        return 0
    n = push(problem)
    STATE.write_text(json.dumps({"last_alert": now.isoformat(timespec="seconds")}))
    print(f"{now.isoformat(timespec='seconds')} alerted {n} device(s): {problem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
