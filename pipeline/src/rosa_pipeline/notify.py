"""Swell-alert Web Push sender - runs on the VM after each publish cycle.

Hard requirement (user, 2026-07-23): one swell = ONE notification. The same event
seen from many adjacent spots (same region, peaks within GROUP_PEAK_H hours,
directions within GROUP_DIR_DEG) is grouped, and each subscription gets a single
push per group, spoken in the name of its best favorited spot ("+N more spots").
The grouping rule mirrors web/src/events.ts (client-side alerts) - keep in sync.

Layers:
- pure planning (unit-tested, offline): load_spot_events / group_events /
  plan_notifications / sent-state bookkeeping
- transport (network): fetch_subscriptions from the push API's admin surface,
  pywebpush sends signed with the VM's VAPID private key; 404/410 responses
  prune the dead subscription server-side.

A sent-state JSON keeps re-runs quiet: an event is keyed spot:peak-date and a
±1-day tolerance absorbs the peak drifting across midnight between model runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

GROUP_PEAK_H = 12.0
GROUP_DIR_DEG = 45.0
SENT_TTL_DAYS = 30
APP_ORIGIN = "https://rosa-rust.vercel.app"

# bucket → the app's display word (conditions.ts WORD map)
BUCKET_WORD = {"FLAT": "Flat", "POOR": "Poor", "FAIR": "Fair", "GOOD": "Good", "FIRING": "Epic"}

_CARDINALS = [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
]

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _cardinal(deg: float) -> str:
    return _CARDINALS[round((deg % 360) / 22.5) % 16]


def _when(dt: datetime) -> str:
    """ "Fri 11:00" in the event's own (spot-local) clock."""
    return f"{_DAYS[dt.weekday()]} {dt:%H:%M}"


@dataclass(frozen=True, slots=True)
class SpotEvent:
    spot_id: str
    spot_name: str
    region: str | None
    start: datetime
    peak: datetime
    end: datetime
    h_peak: float
    direction_deg: float | None
    rating: int
    bucket: str


@dataclass(frozen=True, slots=True)
class Notification:
    title: str
    body: str
    url: str
    tag: str
    keys: tuple[str, ...]  # sent-state keys this push settles


def event_key(e: SpotEvent) -> str:
    return f"{e.spot_id}:{e.peak.date().isoformat()}"


def load_spot_events(out_dir: Path, now: datetime) -> list[SpotEvent]:
    """Every not-yet-finished event across the published payloads."""
    events: list[SpotEvent] = []
    for path in sorted((out_dir / "spots").glob("*.json")):
        payload = json.loads(path.read_text())
        spot = payload.get("spot", {})
        for e in payload.get("events", []):
            end = datetime.fromisoformat(e["end"])
            if end < now:
                continue
            events.append(
                SpotEvent(
                    spot_id=spot["id"],
                    spot_name=spot.get("name", spot["id"]),
                    region=spot.get("region"),
                    start=datetime.fromisoformat(e["start"]),
                    peak=datetime.fromisoformat(e["peak"]),
                    end=end,
                    h_peak=float(e["h_peak"]),
                    direction_deg=e["dir"],
                    rating=int(e["rating"]),
                    bucket=e["bucket"],
                )
            )
    return events


def _same_swell(a: SpotEvent, b: SpotEvent) -> bool:
    if a.region != b.region:
        return False
    if abs((a.peak - b.peak).total_seconds()) / 3600.0 > GROUP_PEAK_H:
        return False
    if a.direction_deg is None or b.direction_deg is None:
        return True
    d = abs(a.direction_deg - b.direction_deg) % 360.0
    return min(d, 360.0 - d) <= GROUP_DIR_DEG


def group_events(events: list[SpotEvent]) -> list[list[SpotEvent]]:
    """Cluster events that are the same physical swell seen from adjacent spots."""
    groups: list[list[SpotEvent]] = []
    for e in sorted(events, key=lambda x: x.peak):
        for g in groups:
            if any(_same_swell(m, e) for m in g):
                g.append(e)
                break
        else:
            groups.append([e])
    return groups


def _was_sent(sent: set[str], e: SpotEvent) -> bool:
    """±1-day tolerance: a peak drifting across midnight is still the same swell."""
    d = e.peak.date()
    return any(f"{e.spot_id}:{(d + timedelta(days=off)).isoformat()}" in sent for off in (-1, 0, 1))


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")


def plan_notifications(
    groups: list[list[SpotEvent]],
    favorites: list[str],
    sent: set[str],
    now: datetime,
) -> list[Notification]:
    """One Notification per unseen group that touches the user's favorites."""
    out: list[Notification] = []
    for group in groups:
        mine = [e for e in group if e.spot_id in favorites]
        if not mine:
            continue
        best = max(mine, key=lambda e: (e.rating, e.h_peak))
        if best.peak <= now:  # already peaked - too late to be a heads-up
            continue
        if any(_was_sent(sent, e) for e in group):
            continue
        name = best.spot_name.split(" (")[0].split(" / ")[0]
        more = len(mine) - 1
        where = best.region or name
        dir_txt = f" {_cardinal(best.direction_deg)}" if best.direction_deg is not None else ""
        body = (
            f"Builds {_when(best.start)}, peaks {_when(best.peak)} · "
            f"~{best.h_peak:.1f} m{dir_txt} · {BUCKET_WORD.get(best.bucket, best.bucket)}"
            f" at {name}"
        )
        if more > 0:
            body += f" +{more} more {'spot' if more == 1 else 'spots'}"
        out.append(
            Notification(
                title=f"New swell - {where}",
                body=body,
                url=f"{APP_ORIGIN}/#/spot/{best.spot_id}?ev={best.peak.date().isoformat()}",
                # the browser collapses same-tag notifications: a second safety
                # net for the one-swell-one-notification rule
                tag=f"rosa-{_slug(where)}-{best.peak.date().isoformat()}",
                keys=tuple(event_key(e) for e in group),
            )
        )
    return out


# ---------------------------------------------------------------- sent state


def endpoint_hash(endpoint: str) -> str:
    return sha256(endpoint.encode()).hexdigest()[:16]


def load_state(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        return raw.get("sent", {}) if isinstance(raw, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(path: Path, sent: dict[str, str], now: datetime) -> None:
    cutoff = now - timedelta(days=SENT_TTL_DAYS)
    kept = {k: v for k, v in sent.items() if datetime.fromisoformat(v) >= cutoff}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sent": kept}, indent=1, sort_keys=True))


def sent_for(sent: dict[str, str], ehash: str) -> set[str]:
    prefix = f"{ehash}|"
    return {k.removeprefix(prefix) for k in sent if k.startswith(prefix)}


def mark_sent(sent: dict[str, str], ehash: str, keys: tuple[str, ...], now: datetime) -> None:
    for k in keys:
        sent[f"{ehash}|{k}"] = now.isoformat()


# ----------------------------------------------------------------- transport


def fetch_subscriptions(subs_url: str, admin_secret: str) -> list[dict]:
    import httpx

    r = httpx.get(subs_url, headers={"x-admin-secret": admin_secret}, timeout=30)
    r.raise_for_status()
    subs = r.json()
    return [s for s in subs if isinstance(s, dict) and "endpoint" in s and "keys" in s]


def send_alert(
    message: str,
    admin_subs_path: Path,
    vapid_private_key: Path,
    vapid_sub: str,
) -> int:
    """Ops alert (cycle failure / stale-data watchdog): a plain push sent ONLY to
    the admin devices snapshotted in admin_subs_path - never the public subscriber
    list. Returns pushes delivered; a dead endpoint is reported, not pruned (the
    snapshot is maintained by hand, see deploy/oracle/README.md)."""
    from pywebpush import WebPushException, webpush

    subs = json.loads(admin_subs_path.read_text())
    sent = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
                data=json.dumps({"title": "Rosa pipeline", "body": message, "tag": "rosa-admin"}),
                vapid_private_key=str(vapid_private_key),
                vapid_claims={"sub": vapid_sub},
            )
            sent += 1
        except WebPushException as exc:
            print(f"alert: push failed for {endpoint_hash(sub['endpoint'])}: {exc}")
    return sent


def prune_subscription(subs_url: str, admin_secret: str, endpoint: str) -> None:
    import httpx

    httpx.request(
        "DELETE",
        subs_url,
        headers={"x-admin-secret": admin_secret},
        json={"endpoint": endpoint},
        timeout=30,
    )


def send_notifications(
    out_dir: Path,
    state_path: Path,
    subs_url: str,
    admin_secret: str,
    vapid_private_key: Path,
    vapid_sub: str,
    now: datetime | None = None,
    dry_run: bool = False,
    feedback_dir: Path | None = None,
) -> int:
    """Plan and send per subscription; returns the number of pushes sent.

    Also pulls crowd 👍👎 rows into the calibration store (feedback_dir) - same
    cycle, same secrets."""
    now = now or datetime.now(UTC)
    groups = group_events(load_spot_events(out_dir, now))
    candidates = load_feedback_candidates(out_dir, now)
    if not groups and not candidates:
        print("notify: no active events, no feedback candidates")
    else:
        subs = fetch_subscriptions(subs_url, admin_secret)
        print(
            f"notify: {sum(len(g) for g in groups)} events in {len(groups)} groups, "
            f"{len(candidates)} feedback candidates, {len(subs)} subs"
        )
        state = load_state(state_path)
        regions = spot_regions(out_dir)
        sent_count = 0
        for sub in subs:
            ehash = endpoint_hash(sub["endpoint"])
            sent_keys = sent_for(state, ehash)
            spots = sub.get("spots", [])
            plans: list[tuple[Notification, dict]] = [
                (n, {"title": n.title, "body": n.body, "url": n.url, "tag": n.tag})
                for n in plan_notifications(groups, spots, sent_keys, now)
            ]
            # evening 👍👎 ask - only for subs that keep "Spot feedback" on
            if sub.get("feedback", True):
                fb = plan_feedback_push(candidates, spots, sent_keys, sub.get("home"), regions)
                if fb is not None:
                    plans.append((fb[0], feedback_payload(fb[0], fb[1])))
            for n, payload in plans:
                if dry_run:
                    print(f"  DRY {ehash}: {n.title} | {n.body}")
                    continue
                try:
                    from pywebpush import WebPushException, webpush

                    webpush(
                        subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
                        data=json.dumps(payload),
                        vapid_private_key=str(vapid_private_key),
                        vapid_claims={"sub": vapid_sub},
                    )
                except WebPushException as exc:
                    status = exc.response.status_code if exc.response is not None else None
                    print(f"  push failed ({status}) for {ehash}: {exc}")
                    if status in (404, 410):  # endpoint gone - forget the device
                        prune_subscription(subs_url, admin_secret, sub["endpoint"])
                    continue
                mark_sent(state, ehash, n.keys, now)
                sent_count += 1
                print(f"  sent {ehash}: {n.title} | {n.body}")
        if not dry_run:
            save_state(state_path, state, now)
        print(f"notify: {sent_count} pushes sent")

    if feedback_dir is not None and not dry_run:
        try:
            pulled = pull_feedback(
                subs_url.replace("/api/subs", "/api/feedback"), admin_secret, feedback_dir
            )
            print(f"notify: {pulled} feedback rows pulled")
        except Exception as exc:  # the pull must never sink the send cycle
            print(f"warn: feedback pull failed: {exc}")
    return 0 if (not groups and not candidates) else sent_count


# ------------------------------------------------------- feedback loop (v0.2)


FEEDBACK_MIN_RATING = 50  # only ask about days Rosa called GOOD+
FEEDBACK_LOCAL_HOUR = (17, 22)  # spot-local evening window for the ask


@dataclass(frozen=True, slots=True)
class FeedbackCandidate:
    """A favorited-spot day worth grading: today, spot-local evening, GOOD+."""

    spot_id: str
    spot_name: str
    date: str  # spot-local YYYY-MM-DD
    rating: int
    bucket: str
    h: tuple[float, float] | None
    at: str  # best hour's spot-local ISO - the session being graded
    predicted: dict
    region: str = ""  # the ask never crosses regions - see plan_feedback_push


def load_feedback_candidates(out_dir: Path, now: datetime) -> list[FeedbackCandidate]:
    """Spots whose local clock is in the evening window and whose today was GOOD+."""
    from zoneinfo import ZoneInfo

    out: list[FeedbackCandidate] = []
    for path in sorted((out_dir / "spots").glob("*.json")):
        payload = json.loads(path.read_text())
        spot = payload.get("spot", {})
        try:
            local = now.astimezone(ZoneInfo(spot.get("timezone", "UTC")))
        except (KeyError, ValueError):
            continue
        if not (FEEDBACK_LOCAL_HOUR[0] <= local.hour <= FEEDBACK_LOCAL_HOUR[1]):
            continue
        today = local.date().isoformat()
        day = next((d for d in payload.get("days", []) if d.get("date") == today), None)
        if day is None or int(day.get("rating_max", 0)) < FEEDBACK_MIN_RATING:
            continue
        hours = [h for h in payload.get("hours", []) if h.get("t", "").startswith(today)]
        if not hours:
            continue
        best = max(hours, key=lambda h: h.get("rating", 0))
        out.append(
            FeedbackCandidate(
                spot_id=spot["id"],
                spot_name=spot.get("name", spot["id"]),
                date=today,
                rating=int(day.get("rating_max", 0)),
                bucket=day.get("bucket", ""),
                h=tuple(day["h_max"]) if day.get("h_max") else None,
                at=best.get("t", f"{today}T12:00"),
                predicted={
                    "rating": best.get("rating"),
                    "bucket": best.get("bucket"),
                    "h": best.get("h"),
                    "phrase": best.get("phrase"),
                },
                region=spot.get("region", ""),
            )
        )
    return out


def spot_regions(out_dir: Path) -> dict[str, str]:
    """spot id → region, read from the published index (cheap, one small file)."""
    try:
        index = json.loads((out_dir / "index.json").read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {sid: e.get("region", "") for sid, e in index.get("spots", {}).items()}


def feedback_key(spot_id: str, date: str) -> str:
    return f"fb:{spot_id}:{date}"


def last_asked(sent: set[str], spot_id: str) -> str:
    """Most recent date this spot was asked about ("" = never), from the sent keys."""
    prefix = f"fb:{spot_id}:"
    dates = [k.removeprefix(prefix) for k in sent if k.startswith(prefix)]
    return max(dates) if dates else ""


def plan_feedback_push(
    candidates: list[FeedbackCandidate],
    favorites: list[str],
    sent: set[str],
    home: str | None = None,
    regions: dict[str, str] | None = None,
) -> tuple[Notification, FeedbackCandidate] | None:
    """Pick the ONE spot to ask this subscription about tonight, or None.

    Rules, in order:
    - At most one ask per subscription per day (anti-spam).
    - Never cross regions: someone in Israel surfed Zvulun, not Tamarindo. The
      region comes from `home` (the device's nearest spot, sent with the
      subscription); with no home known we can't tell, and the old
      favorites-only behaviour stands.
    - Rotate: among eligible spots the one asked longest ago wins (never-asked
      first), so a run of good days spreads the asks across the favorites
      instead of hammering the best-rated one.
    - No favorites: ask about `home` itself, when its day was good enough to be
      a candidate at all.
    """
    mine = [c for c in candidates if c.spot_id in favorites]
    home_region = (regions or {}).get(home or "", "")
    if home_region:
        mine = [c for c in mine if c.region == home_region]
    if not mine and home:
        # nothing favorited nearby - fall back to the spot they're standing next to
        mine = [c for c in candidates if c.spot_id == home]
    if not mine:
        return None
    # a feedback ask already went out for any of today's candidate dates → quiet
    if any(feedback_key(c.spot_id, c.date) in sent for c in mine) or any(
        k.startswith("fb:") and k.endswith(c.date) for c in mine for k in sent
    ):
        return None
    best = min(mine, key=lambda c: (last_asked(sent, c.spot_id), -c.rating))
    name = best.spot_name.split(" (")[0].split(" / ")[0]
    word = BUCKET_WORD.get(best.bucket, best.bucket)
    h_txt = f" {best.h[0]:.1f}-{best.h[1]:.1f} m" if best.h else ""
    # step 1 of the ask: did you surf it at all - the service worker raises the
    # "how was the forecast?" step only on yes (a grade from someone who never
    # paddled out is noise in the calibration log)
    n = Notification(
        title=f"Surfed {name} today?",
        body=f"Rosa called {word} ·{h_txt}",
        url=f"{APP_ORIGIN}/#/spot/{best.spot_id}",
        tag=f"rosa-fb-{best.spot_id}-{best.date}",
        keys=(feedback_key(best.spot_id, best.date),),
    )
    return n, best


# the extra payload block a feedback push carries. Step 1 offers yes/no to
# "surfed it?"; the service worker answers "no" by dismissing and "yes" by
# raising step 2 (👍/👎), which it POSTs straight to the feedback API - the app
# never has to open. Older workers that only know up/down still answer, since
# the feedback block itself is unchanged.
def feedback_payload(n: Notification, c: FeedbackCandidate) -> dict:
    return {
        "title": n.title,
        "body": n.body,
        "url": n.url,
        "tag": n.tag,
        "actions": [
            {"action": "surfed-yes", "title": "✓ Yes"},
            {"action": "surfed-no", "title": "✕ No"},
        ],
        "feedback": {
            "spot": c.spot_id,
            "at": c.at,
            "predicted": c.predicted,
            "source": "push",
        },
    }


def pull_feedback(feedback_url: str, admin_secret: str, feedback_dir: Path) -> int:
    """Merge crowd 👍👎 rows from the API into the local calibration store, then
    prune the pulled blobs server-side. Dedupe by the API-side row id."""
    import httpx

    from .archive import FileArchiveStore

    r = httpx.get(feedback_url, headers={"x-admin-secret": admin_secret}, timeout=30)
    r.raise_for_status()
    rows = [x for x in r.json() if isinstance(x, dict) and "id" in x and "spot" in x]
    if not rows:
        return 0
    store = FileArchiveStore(feedback_dir)
    seen_ids = {row.get("id") for row in store.read("feedback")}
    fresh = [row for row in rows if row["id"] not in seen_ids]
    store.append("feedback", fresh)
    httpx.request(
        "DELETE",
        feedback_url,
        headers={"x-admin-secret": admin_secret},
        json={"ids": [row["id"] for row in rows]},
        timeout=30,
    )
    return len(fresh)
