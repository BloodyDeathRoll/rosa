"""Swell-alert Web Push sender — runs on the VM after each publish cycle.

Hard requirement (user, 2026-07-23): one swell = ONE notification. The same event
seen from many adjacent spots (same region, peaks within GROUP_PEAK_H hours,
directions within GROUP_DIR_DEG) is grouped, and each subscription gets a single
push per group, spoken in the name of its best favorited spot ("+N more spots").
The grouping rule mirrors web/src/events.ts (client-side alerts) — keep in sync.

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
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _cardinal(deg: float) -> str:
    return _CARDINALS[round((deg % 360) / 22.5) % 16]


def _when(dt: datetime) -> str:
    """"Fri 11:00" in the event's own (spot-local) clock."""
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
    return any(
        f"{e.spot_id}:{(d + timedelta(days=off)).isoformat()}" in sent for off in (-1, 0, 1)
    )


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
        if best.peak <= now:  # already peaked — too late to be a heads-up
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
                title=f"New swell — {where}",
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
) -> int:
    """Plan and send per subscription; returns the number of pushes sent."""
    now = now or datetime.now(UTC)
    groups = group_events(load_spot_events(out_dir, now))
    if not groups:
        print("notify: no active events")
        return 0
    subs = fetch_subscriptions(subs_url, admin_secret)
    print(f"notify: {sum(len(g) for g in groups)} events in {len(groups)} groups, {len(subs)} subs")
    state = load_state(state_path)
    sent_count = 0
    for sub in subs:
        ehash = endpoint_hash(sub["endpoint"])
        plans = plan_notifications(groups, sub.get("spots", []), sent_for(state, ehash), now)
        for n in plans:
            if dry_run:
                print(f"  DRY {ehash}: {n.title} | {n.body}")
                continue
            try:
                from pywebpush import WebPushException, webpush

                webpush(
                    subscription_info={"endpoint": sub["endpoint"], "keys": sub["keys"]},
                    data=json.dumps(
                        {"title": n.title, "body": n.body, "url": n.url, "tag": n.tag}
                    ),
                    vapid_private_key=str(vapid_private_key),
                    vapid_claims={"sub": vapid_sub},
                )
            except WebPushException as exc:
                status = exc.response.status_code if exc.response is not None else None
                print(f"  push failed ({status}) for {ehash}: {exc}")
                if status in (404, 410):  # endpoint gone — forget the device
                    prune_subscription(subs_url, admin_secret, sub["endpoint"])
                continue
            mark_sent(state, ehash, n.keys, now)
            sent_count += 1
            print(f"  sent {ehash}: {n.title} | {n.body}")
    if not dry_run:
        save_state(state_path, state, now)
    print(f"notify: {sent_count} pushes sent")
    return sent_count
