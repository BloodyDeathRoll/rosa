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
INDEX_URL = "https://rosa-data-opal.vercel.app/data/index.json"
# Cycles run every 6 h, but `fetched_at` is stamped when a cycle STARTS and the data only
# reaches the CDN 60-90 min later, so served age peaks near 6.9 h just before each publish
# lands. At the old 7.0 that left ~6 min of headroom and any slow cycle paged a false alarm.
# 8.0 keeps a genuinely missed cycle (>12 h) firmly in range.
MAX_AGE_H = 8.0
# ...but one spot cannot answer for the fleet. Since 2026-08-28 `run --all` returns exit 4
# on a PARTIAL run - a small share of spots failed, the rest published - and publish.sh
# deploys it, so the failed spots keep serving their PREVIOUS payload while beit-yanai
# refreshes on time. That trade is only honest if a spot left behind cycle after cycle gets
# noticed, and the single-spot check above is blind to it by construction. So the index's
# per-spot generated_at is swept too.
#
# 24 h is deliberately far above MAX_AGE_H: cycles are 6 h apart, so a spot that missed one
# reads 6-12 h and must NOT page - that is the partial run working as designed. Past 24 h it
# has missed about four consecutive cycles, which is rot, not a blip.
MAX_SPOT_AGE_H = 24.0
MAX_SPOTS_NAMED = 5  # the alert names the worst offenders; the log names more of them
MAX_SPOTS_LOGGED = 40  # ...but not all 624 on one line, every hour, during an outage
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


def rotting_spots(
    index: dict, now: datetime, max_age_h: float = MAX_SPOT_AGE_H
) -> list[tuple[str, float]]:
    """(spot id, age in hours) for every spot the fleet has left behind, oldest first.

    Reads the index rather than 624 payloads: one request already carries every spot's
    generated_at. A spot with no timestamp is skipped, not assumed stale - a schema gap must
    not masquerade as rot."""
    out = []
    for spot_id, entry in (index.get("spots") or {}).items():
        stamp = entry.get("generated_at")
        if not stamp:
            continue
        age_h = (now - datetime.fromisoformat(stamp)).total_seconds() / 3600
        if age_h > max_age_h:
            out.append((spot_id, age_h))
    return sorted(out, key=lambda pair: -pair[1])


def rot_message(
    rotting: list[tuple[str, float]], total: int, max_age_h: float = MAX_SPOT_AGE_H
) -> str | None:
    """The alert text when individual spots have rotted behind a publishing fleet, else None."""
    if not rotting:
        return None
    named = ", ".join(f"{spot_id} {age_h:.0f} h" for spot_id, age_h in rotting[:MAX_SPOTS_NAMED])
    more = f" +{len(rotting) - MAX_SPOTS_NAMED} more" if len(rotting) > MAX_SPOTS_NAMED else ""
    # The whole fleet rotting is not a partial cycle - it is no cycle, and pointing at
    # publish.log's failing ids would send the reader looking for a list that isn't there.
    cause = (
        "No cycle has landed - check rosa-instance + publish.log."
        if len(rotting) == total
        else "A partial cycle is leaving them behind - check publish.log for the failing ids."
    )
    return f"{len(rotting)} of {total} spot(s) STALE past {max_age_h:g} h: {named}{more}. {cause}"


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


def fetch(url: str) -> dict:
    """Cache-busted read of a published JSON file."""
    req = urllib.request.Request(
        f"{url}?cb={int(time.time())}", headers={"cache-control": "no-cache"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def main() -> int:
    now = datetime.now(UTC)
    # Two independent questions, both asked every run: is the CYCLE landing at all (one spot
    # answers that), and is any SPOT being left behind by a cycle that is landing (only the
    # index answers that). Collected rather than short-circuited so one push carries both.
    problems = []
    try:
        payload = fetch(DATA_URL)
        problems.append(stale_message(datetime.fromisoformat(payload["fetched_at"]), now))
    except Exception as exc:  # unreadable CDN is page-worthy too
        problems.append(f"Can't read rosa-data ({type(exc).__name__}) - CDN or publish problem.")
    try:
        index = fetch(INDEX_URL)
        spots = index.get("spots") or {}
        rotting = rotting_spots(index, now)
        if rotting:
            shown = ", ".join(f"{s} {a:.1f}h" for s, a in rotting[:MAX_SPOTS_LOGGED])
            rest = len(rotting) - MAX_SPOTS_LOGGED
            print(f"rotting {len(rotting)}: {shown}" + (f" +{rest} more" if rest > 0 else ""))
        problems.append(rot_message(rotting, len(spots)))
    except Exception as exc:
        problems.append(f"Can't read the spot index ({type(exc).__name__}) - CDN or publish problem.")

    problem = " ".join(p for p in problems if p) or None
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
