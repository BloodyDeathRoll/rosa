#!/usr/bin/env python3
"""Scan YouTube for live surf webcams and keep the assigned ones alive.

Method: docs/cam-scan-plan.md. Only officially embeddable YouTube LIVE streams
qualify (CLAUDE.md legal red lines) - everything is checked through the official
YouTube Data API v3 (YOUTUBE_API_KEY in env), never HTML scraping.

Usage (from repo root):
  YOUTUBE_API_KEY=... python tools/cam-scan/scan.py channels          # mine the seed networks
  YOUTUBE_API_KEY=... python tools/cam-scan/scan.py sweep             # query sweep, all regions
  YOUTUBE_API_KEY=... python tools/cam-scan/scan.py sweep --region Israel --budget 3000
  YOUTUBE_API_KEY=... python tools/cam-scan/scan.py verify            # are assigned cams still live?
  YOUTUBE_API_KEY=... python tools/cam-scan/scan.py verify --resolve --apply

Candidates land in data/cams/candidates.yaml for review - apply by editing the
spot YAMLs (a normal committable diff; no interactive gates). State that makes
runs resumable and non-repeating lives in data/cams/seen.json: quota is
budget-tracked (search=100 units, videos/channels=1), queries aren't re-run for
QUERY_TTL_DAYS, and judged video ids are never re-proposed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPOTS_DIR = ROOT / "data" / "spots"
CAMS_DIR = ROOT / "data" / "cams"
CHANNELS_FILE = Path(__file__).with_name("channels.yaml")

API = "https://www.googleapis.com/youtube/v3"
UNIT_SEARCH = 100
UNIT_LIST = 1
QUERY_TTL_DAYS = 30
MIN_LIVE_HOURS = 12.0  # younger streams are somebody's session, not a cam

# Language-aware query templates. {name} = spot name (parens stripped);
# region-level queries run once per region, spot-level once per spot.
TEMPLATES: dict[str, dict[str, list[str]]] = {
    "Israel": {
        "region": ["מצלמה חוף גלישה ישראל", "surf cam live israel beach"],
        "spot": ["חוף {name} מצלמה", "{name} israel beach cam live"],
    },
    "Costa Rica": {
        "region": ["costa rica surf cam live playa", "costa rica beach cam live"],
        "spot": ["{name} costa rica surf cam live", "camara en vivo playa {name}"],
    },
    "Nicaragua": {
        "region": ["nicaragua surf cam live playa"],
        "spot": ["{name} nicaragua surf cam live"],
    },
    "Sri Lanka": {
        "region": ["sri lanka surf cam live beach"],
        "spot": ["{name} sri lanka surf cam live"],
    },
    "Japan": {
        "region": ["ライブカメラ 波情報 サーフィン", "サーフィン ライブカメラ 海"],
        "spot": ["{name} ライブカメラ 波", "{name} surf cam live japan"],
    },
    "Portugal": {
        "region": ["livecam praia portugal surf", "portugal surf cam live"],
        "spot": ["praia {name} livecam", "{name} portugal surf cam live"],
    },
    "Philippines": {
        "region": ["philippines surf cam live siargao"],
        "spot": ["{name} philippines surf cam live"],
    },
    "California": {
        "region": ["california surf cam live beach"],
        "spot": ["{name} california surf cam live"],
    },
    "Hawaii": {
        "region": ["hawaii surf cam live north shore"],
        "spot": ["{name} hawaii surf cam live"],
    },
}


def _get(url: str, retries: int = 3) -> dict:
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:400]
            if e.code == 403 and "quota" in body.lower():
                sys.exit("FATAL: YouTube API quota exhausted - rerun tomorrow (state is saved).")
            if e.code in (400, 403, 404):
                sys.exit(
                    f"FATAL: YouTube API {e.code}: {body}\n"
                    "Is the 'YouTube Data API v3' enabled on the project, and does the key allow it?"
                )
            if i == retries - 1:
                raise
        except Exception:
            if i == retries - 1:
                raise
        time.sleep(2)
    return {}


class Api:
    """YouTube Data API v3 with unit accounting - stops before the daily cap."""

    def __init__(self, key: str, budget: int) -> None:
        self.key = key
        self.budget = budget
        self.spent = 0

    def _call(self, endpoint: str, units: int, **params: str) -> dict | None:
        if self.spent + units > self.budget:
            return None  # budget exhausted - callers treat as "stop here"
        self.spent += units
        q = urllib.parse.urlencode({**params, "key": self.key})
        return _get(f"{API}/{endpoint}?{q}")

    def search_live(
        self, *, q: str | None = None, channel_id: str | None = None
    ) -> list[dict] | None:
        params = {"part": "snippet", "type": "video", "eventType": "live", "maxResults": "25"}
        if q is not None:
            params["q"] = q
        if channel_id is not None:
            params["channelId"] = channel_id
        resp = self._call("search", UNIT_SEARCH, **params)
        return None if resp is None else resp.get("items", [])

    def videos(self, ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(ids), 50):
            resp = self._call(
                "videos",
                UNIT_LIST,
                part="snippet,status,liveStreamingDetails",
                id=",".join(ids[i : i + 50]),
            )
            if resp is None:
                break
            out.extend(resp.get("items", []))
        return out

    def channel_id(self, handle: str) -> str | None:
        resp = self._call("channels", UNIT_LIST, part="id", forHandle=handle)
        items = resp.get("items", []) if resp else []
        return items[0]["id"] if items else None


# ---------------------------------------------------------------------------
# Spot DB + state


def load_spots() -> list[dict]:
    spots: list[dict] = []
    for f in sorted(SPOTS_DIR.glob("*.yaml")):
        doc = yaml.safe_load(f.read_text(encoding="utf-8"))
        region = doc.get("region") or f.stem.replace("-", " ").title()
        for s in doc.get("spots", []):
            spots.append({**s, "region": region, "file": f.name})
    return spots


def base_name(name: str) -> str:
    """'Nazaré (Praia do Norte)' -> 'Nazaré' - the query-friendly part."""
    return re.sub(r"\s*\(.*\)$", "", str(name)).strip()


def load_state() -> dict:
    path = CAMS_DIR / "seen.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"queries": {}, "videos": {}}


def save_state(state: dict) -> None:
    CAMS_DIR.mkdir(parents=True, exist_ok=True)
    (CAMS_DIR / "seen.json").write_text(
        json.dumps(state, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def spot_cams(s: dict) -> list[dict]:
    """A spot's cam entries - handles both `cam:` (single) and `cams:` (list)."""
    if isinstance(s.get("cams"), list):
        return [c for c in s["cams"] if isinstance(c, dict) and c.get("yt")]
    c = s.get("cam")
    return [c] if isinstance(c, dict) and c.get("yt") else []


def assigned_cam_ids(spots: list[dict]) -> set[str]:
    return {c["yt"] for s in spots for c in spot_cams(s)}


def query_fresh(state: dict, q: str) -> bool:
    ran = state["queries"].get(q)
    if not ran:
        return False
    return datetime.fromisoformat(ran) > datetime.now(UTC) - timedelta(days=QUERY_TTL_DAYS)


# ---------------------------------------------------------------------------
# Filtering + matching


def live_hours(video: dict) -> float | None:
    start = video.get("liveStreamingDetails", {}).get("actualStartTime")
    if not start:
        return None
    dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
    return (datetime.now(UTC) - dt).total_seconds() / 3600


def keep_reason(video: dict, min_hours: float) -> str | None:
    """None = keep; otherwise why the candidate is dropped."""
    if video.get("snippet", {}).get("liveBroadcastContent") != "live":
        return "not-live"
    if not video.get("status", {}).get("embeddable", False):
        return "not-embeddable"
    hours = live_hours(video)
    if hours is None or hours < min_hours:
        return f"live-only-{0 if hours is None else round(hours, 1)}h"
    return None


def match_spot(title: str, spots: list[dict], hint: dict | None) -> tuple[dict | None, str]:
    """(spot, how). The query's own spot is the hint; otherwise scan spot names."""
    lowered = title.lower()
    for s in spots:
        nm = base_name(s["name"]).lower()
        if len(nm) >= 4 and nm in lowered:
            return s, "title-name"
    if hint is not None:
        return hint, "source-query"
    return None, "unmatched"


def geocode_title(title: str) -> tuple[float, float] | None:
    """Optional distance sanity: Google legacy Places textsearch, same provider
    and env var as tools/spot-verify (GOOGLE_MAPS_API_KEY)."""
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key:
        return None
    cleaned = re.sub(r"(live|cam|webcam|stream|surf|beach|4k|hd|24/7)", " ", title, flags=re.I)
    q = urllib.parse.urlencode({"query": cleaned.strip(), "key": key})
    resp = _get(f"https://maps.googleapis.com/maps/api/place/textsearch/json?{q}")
    results = resp.get("results", [])
    if not results:
        return None
    loc = results[0]["geometry"]["location"]
    return float(loc["lat"]), float(loc["lng"])


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    import math

    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (
        math.sin((la2 - la1) / 2) ** 2
        + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# Candidate collection (shared by sweep + channels)


def judge_candidates(
    api: Api,
    found: dict[str, dict],  # video id -> {source info}
    spots: list[dict],
    state: dict,
    args: argparse.Namespace,
) -> list[dict]:
    fresh_ids = [v for v in found if v not in state["videos"]]
    if not fresh_ids:
        return []
    candidates: list[dict] = []
    for video in api.videos(fresh_ids):
        vid = video["id"]
        drop = keep_reason(video, args.min_live_hours)
        if drop:
            state["videos"][vid] = drop
            continue
        sn = video["snippet"]
        src = found[vid]
        spot, how = match_spot(sn["title"], spots, src.get("hint"))
        entry: dict = {
            "yt": vid,
            "title": sn["title"],
            "by": sn["channelTitle"],
            "by_url": f"https://www.youtube.com/channel/{sn['channelId']}",
            "live_hours": round(live_hours(video) or 0, 1),
            "found_via": src["via"],
            "match": how,
        }
        if spot is not None:
            entry["spot"] = spot["id"]
            entry["spot_file"] = spot["file"]
            if args.geocode:
                loc = geocode_title(sn["title"])
                if loc is not None:
                    entry["distance_km"] = round(km(loc, (spot["lat"], spot["lon"])), 1)
        state["videos"][vid] = "candidate"
        candidates.append(entry)
    return candidates


def write_candidates(new: list[dict]) -> None:
    CAMS_DIR.mkdir(parents=True, exist_ok=True)
    path = CAMS_DIR / "candidates.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else None
    existing = doc.get("candidates", []) if doc else []
    have = {c["yt"] for c in existing}
    merged = existing + [c for c in new if c["yt"] not in have]
    matched = [c for c in merged if "spot" in c]
    unmatched = [c for c in merged if "spot" not in c]
    path.write_text(
        "# Live-cam candidates - review, then add accepted ones to the spot YAMLs as\n"
        "# cam: { yt, by, by_url[, note] } and their channel to tools/cam-scan/channels.yaml.\n"
        "# Unmatched cams double as spot-discovery signals (docs/cam-scan-plan.md §3).\n"
        + yaml.safe_dump(
            {"candidates": matched + unmatched}, allow_unicode=True, sort_keys=False, width=100
        ),
        encoding="utf-8",
    )
    print(f"candidates.yaml: +{len(new)} new ({len(matched)} matched / {len(unmatched)} unmatched)")


# ---------------------------------------------------------------------------
# Commands


def cmd_channels(api: Api, args: argparse.Namespace) -> None:
    spots = load_spots()
    state = load_state()
    seeds = yaml.safe_load(CHANNELS_FILE.read_text(encoding="utf-8"))["channels"]
    have = assigned_cam_ids(spots)
    found: dict[str, dict] = {}
    for seed in seeds:
        cid = api.channel_id(seed["handle"])
        if cid is None:
            print(f"  {seed['name']}: handle not found (or budget out)")
            continue
        items = api.search_live(channel_id=cid)
        if items is None:
            print("budget exhausted - stopping (state saved)")
            break
        live = [i for i in items if i["id"]["videoId"] not in have]
        print(f"  {seed['name']}: {len(items)} live, {len(live)} new")
        for i in live:
            found.setdefault(i["id"]["videoId"], {"via": f"channel:{seed['handle']}", "hint": None})
    new = judge_candidates(api, found, spots, state, args)
    save_state(state)
    write_candidates(new)
    print(f"spent {api.spent} units")


def cmd_sweep(api: Api, args: argparse.Namespace) -> None:
    spots = load_spots()
    state = load_state()
    have = assigned_cam_ids(spots)
    regions = [args.region] if args.region else list(TEMPLATES)
    found: dict[str, dict] = {}

    def run_query(q: str, hint: dict | None) -> bool:
        """False = budget exhausted."""
        if query_fresh(state, q):
            return True
        items = api.search_live(q=q)
        if items is None:
            return False
        state["queries"][q] = datetime.now(UTC).isoformat()
        for i in items:
            vid = i["id"]["videoId"]
            if vid not in have:
                found.setdefault(vid, {"via": f"query:{q}", "hint": hint})
        return True

    out_of_budget = False
    for region in regions:
        t = TEMPLATES.get(region)
        if t is None:
            sys.exit(f"unknown region {region!r} - known: {', '.join(TEMPLATES)}")
        for q in t["region"]:
            if not run_query(q, None):
                out_of_budget = True
                break
        if out_of_budget:
            break
        # spots without a cam yet, one templated query each (round-robin the
        # template list so repeated sweeps vary the phrasing)
        for n, spot in enumerate(s for s in spots if s["region"] == region and "cam" not in s):
            q = t["spot"][n % len(t["spot"])].format(name=base_name(spot["name"]))
            if not run_query(q, spot):
                out_of_budget = True
                break
        if out_of_budget:
            break
    new = judge_candidates(api, found, spots, state, args)
    save_state(state)
    write_candidates(new)
    print(
        f"spent {api.spent} units"
        + (" - budget exhausted, rerun to continue" if out_of_budget else "")
    )


def cmd_verify(api: Api, args: argparse.Namespace) -> None:
    spots = load_spots()
    cams = [(s, c) for s in spots for c in spot_cams(s)]
    if not cams:
        print("no cams assigned")
        return
    by_id = {c["yt"]: (s, c) for s, c in cams}
    videos = {v["id"]: v for v in api.videos(list(by_id))}
    dead: list[tuple[dict, dict, str]] = []
    for vid, (spot, cam) in by_id.items():
        v = videos.get(vid)
        problem = "gone" if v is None else keep_reason(v, 0.0)
        if problem is None:
            print(f"  OK   {spot['id']}: {vid} ({cam['by']})")
        else:
            print(f"  DEAD {spot['id']}: {vid} - {problem}")
            dead.append((spot, cam, problem))
    if not dead:
        return
    if not args.resolve:
        print(
            f"{len(dead)} dead cam(s). Re-run with --resolve to find replacements (100 units each)."
        )
        return
    for spot, cam, _ in dead:
        cid = urllib.parse.urlparse(cam.get("by_url", "")).path.rstrip("/").rsplit("/", 1)[-1]
        if cid.startswith("@"):
            cid = api.channel_id(cid.lstrip("@")) or ""
        items = api.search_live(channel_id=cid) if cid.startswith("UC") else []
        if items is None:
            print("budget exhausted")
            break
        if not items:
            print(f"  {spot['id']}: channel has no live stream - remove the cam?")
            continue
        new_id = items[0]["id"]["videoId"]
        print(
            f"  {spot['id']}: current live stream is {new_id} ({items[0]['snippet']['title'][:60]})"
        )
        if args.apply:
            path = SPOTS_DIR / spot["file"]
            text = path.read_text(encoding="utf-8")
            patched = text.replace(f'yt: "{cam["yt"]}"', f'yt: "{new_id}"')
            if patched != text:
                path.write_text(patched, encoding="utf-8")
                print(f"    patched {spot['file']}")
            else:
                print(f"    could not patch {spot['file']} - yt id string not found")
    print(f"spent {api.spent} units")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("command", choices=["channels", "sweep", "verify"])
    p.add_argument("--region", help="sweep a single region (e.g. Israel)")
    p.add_argument("--budget", type=int, default=9000, help="API units to spend (default 9000)")
    p.add_argument("--min-live-hours", type=float, default=MIN_LIVE_HOURS)
    p.add_argument("--geocode", action="store_true", help="distance sanity via GOOGLE_MAPS_API_KEY")
    p.add_argument("--resolve", action="store_true", help="verify: find replacement streams")
    p.add_argument(
        "--apply", action="store_true", help="verify --resolve: patch spot YAMLs in place"
    )
    args = p.parse_args()

    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        sys.exit(
            "YOUTUBE_API_KEY is not set. Enable 'YouTube Data API v3' on the Google Cloud\n"
            "project, create/allow an API key for it, then: export YOUTUBE_API_KEY=..."
        )
    api = Api(key, args.budget)
    {"channels": cmd_channels, "sweep": cmd_sweep, "verify": cmd_verify}[args.command](api, args)


if __name__ == "__main__":
    main()
