"""rosa-pipeline CLI.

Run from the repo root so the default data paths resolve:
    uv run --project pipeline rosa-pipeline run --spot beit-yanai
    uv run --project pipeline rosa-pipeline run --all
    uv run --project pipeline rosa-pipeline verify --buoy 46042
    uv run --project pipeline rosa-pipeline verify --near beit-yanai

`run --all` samples each spot's own offshore point and publishes it. Every unique point
is fetched in a single batched request (fetch_many), so a full 40-spot run is 2 requests.

`verify` scores the offshore model at a buoy against that buoy's observations (roadmap
Stage 0) — the accuracy backbone. Israel has no NDBC buoy in range; `--near` says so
honestly (its truth is ISRAMAR, local-only, plus the surfer 👍👎 loop).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .archive import FileArchiveStore, rows_from_model
from .buoys import Buoy, load_all_buoys, nearest_buoys
from .extract import extract_hours
from .fetch import FixtureSource, ForecastSource, OpenMeteoSource, fetch_marine_waves
from .models import Spot
from .observe import ISRAMARLocalSource, NDBCFixtureSource, NDBCSource
from .publish import build_payload, update_index, write_spot_json
from .score import score_hour
from .spots import load_spots
from .verify import (
    build_scorecard,
    lead_time_scorecard,
    parse_marine_waves,
    render_lead_scorecard,
    render_scorecard,
)

ARCHIVE_DIR = Path("data/verify/archive")
ISRAMAR_DIR = Path("data/verify/isramar")  # local-only, gitignored (all-rights-reserved)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rosa-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="fetch, score and publish spot forecasts")
    which = run.add_mutually_exclusive_group(required=True)
    which.add_argument("--spot", help="spot id, e.g. beit-yanai")
    which.add_argument("--all", action="store_true", help="publish every spot in the DB")
    run.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    run.add_argument("--out", type=Path, default=Path("data/out"))
    run.add_argument(
        "--fixtures", type=Path, default=None, help="replay captured responses (offline)"
    )
    run.add_argument("--capture", type=Path, default=None, help="capture raw responses to this dir")

    verify = sub.add_parser("verify", help="score the offshore model against buoy observations")
    target = verify.add_mutually_exclusive_group(required=True)
    target.add_argument("--buoy", help="buoy id from the registry, e.g. 46042")
    target.add_argument("--near", help="spot id — score the nearest in-range buoy(s)")
    verify.add_argument("--buoys-dir", type=Path, default=Path("data/buoys"))
    verify.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    verify.add_argument("--radius-km", type=float, default=150.0, help="--near search radius")
    verify.add_argument("--limit", type=int, default=1, help="--near: max buoys to score")
    verify.add_argument("--tol-min", type=int, default=30, help="model/obs time-match tolerance")
    verify.add_argument("--isramar-dir", type=Path, default=ISRAMAR_DIR)
    verify.add_argument(
        "--archive",
        action="store_true",
        help="score archived forecasts by lead time (instead of the live nowcast)",
    )
    verify.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    verify.add_argument("--fixtures", type=Path, default=None, help="replay marine json (offline)")
    verify.add_argument("--obs-fixtures", type=Path, default=None, help="replay NDBC txt (offline)")
    verify.add_argument("--capture", type=Path, default=None, help="capture responses to this dir")

    archive = sub.add_parser(
        "archive", help="append the current forecast at buoys to the lead-time archive"
    )
    archive.add_argument("--buoy", help="one buoy id; default = every buoy in the registry")
    archive.add_argument("--buoys-dir", type=Path, default=Path("data/buoys"))
    archive.add_argument("--isramar-dir", type=Path, default=ISRAMAR_DIR)
    archive.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    archive.add_argument("--fixtures", type=Path, default=None, help="replay marine json (offline)")
    archive.add_argument("--capture", type=Path, default=None, help="capture responses to this dir")
    return parser


def group_by_point(spots: list[Spot]) -> dict[tuple[float, float], list[Spot]]:
    groups: dict[tuple[float, float], list[Spot]] = {}
    for spot in spots:
        groups.setdefault(spot.offshore_point, []).append(spot)
    return groups


def _cmd_run(args: argparse.Namespace) -> int:
    spots = load_spots(args.spots_dir)
    if args.all:
        targets = list(spots.values())
    else:
        target = spots.get(args.spot)
        if target is None:
            print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
            return 2
        targets = [target]

    source: ForecastSource = (
        FixtureSource(args.fixtures)
        if args.fixtures is not None
        else OpenMeteoSource(capture_dir=args.capture)
    )
    now = datetime.now(UTC)

    # one deep-water sample per unique offshore point; each spot may have its own, so a
    # full run fetches them all in a single batched request (fetch_many) — no throttling.
    groups = group_by_point(targets)
    points = list(groups)
    raws = source.fetch_many(points)

    published = 0
    for point, raw in zip(points, raws, strict=True):
        hours = extract_hours(raw)
        if not hours:
            # a derived point that landed on a dry grid cell — skip its spots, keep going
            ids = ", ".join(s.id for s in groups[point])
            print(f"warning: no forecast at point {point} — skipping {ids}", file=sys.stderr)
            continue
        for spot in groups[point]:
            scored = [score_hour(spot, h) for h in hours]
            payload = build_payload(spot, scored, fetched_at=raw.fetched_at, now=now)
            path = write_spot_json(payload, args.out)
            update_index(payload, args.out)
            current = payload["current"]
            published += 1
            print(
                f"{spot.id}: {current['bucket']} {current['rating']}/100 · {current['phrase']} "
                f"· wind {current['wind']['class']} {current['wind']['kph']} kph → {path}"
            )
    if published == 0:
        print("no spots published", file=sys.stderr)
        return 1
    return 0


def _obs_for(buoy: Buoy, args: argparse.Namespace):
    if buoy.source == "isramar":
        # never fetched — reads the local manual-import csv only (all-rights-reserved)
        return ISRAMARLocalSource(args.isramar_dir).fetch(buoy)
    if getattr(args, "obs_fixtures", None) is not None:
        return NDBCFixtureSource(args.obs_fixtures).fetch(buoy)
    return NDBCSource(capture_dir=args.capture).fetch(buoy)


def _model_for(buoy: Buoy, args: argparse.Namespace):
    if args.fixtures is not None:
        marine = json.loads((args.fixtures / f"marine_{buoy.id}.json").read_text(encoding="utf-8"))
    else:
        marine = fetch_marine_waves(buoy.lat, buoy.lon)
        if args.capture is not None:
            args.capture.mkdir(parents=True, exist_ok=True)
            (args.capture / f"marine_{buoy.id}.json").write_text(
                json.dumps(marine), encoding="utf-8"
            )
    return parse_marine_waves(marine)


def _cmd_verify(args: argparse.Namespace) -> int:
    buoys = load_all_buoys(args.buoys_dir, args.isramar_dir)

    targets: list[tuple[Buoy, float | None]]
    if args.buoy:
        buoy = buoys.get(str(args.buoy))
        if buoy is None:
            print(f"unknown buoy {args.buoy!r}; known: {', '.join(sorted(buoys))}", file=sys.stderr)
            return 2
        targets = [(buoy, None)]
    else:
        spots = load_spots(args.spots_dir)
        spot = spots.get(args.near)
        if spot is None:
            print(f"unknown spot {args.near!r}", file=sys.stderr)
            return 2
        near = nearest_buoys(
            spot.lat, spot.lon, buoys, radius_km=args.radius_km, limit=args.limit
        )
        if not near:
            print(
                f"no buoy within {args.radius_km:.0f} km of {spot.name} — "
                "no open wave truth here.\n  (eastern-Med spots are validated via "
                "ISRAMAR, local-only, + the surfer 👍👎 loop)"
            )
            return 0
        targets = list(near)

    for buoy, dist in targets:
        obs = _obs_for(buoy, args)
        if args.archive:
            rows = FileArchiveStore(args.archive_dir).read(buoy.id)
            by_lead = lead_time_scorecard(rows, obs, tol_min=args.tol_min)
            print(render_lead_scorecard(buoy, by_lead))
        else:
            model = _model_for(buoy, args)
            scores = build_scorecard(model, obs, tol_min=args.tol_min)
            print(render_scorecard(buoy, dist, scores))
    return 0


def _cmd_archive(args: argparse.Namespace) -> int:
    buoys = load_all_buoys(args.buoys_dir, args.isramar_dir)
    if args.buoy:
        buoy = buoys.get(str(args.buoy))
        if buoy is None:
            print(f"unknown buoy {args.buoy!r}; known: {', '.join(sorted(buoys))}", file=sys.stderr)
            return 2
        targets = [buoy]
    else:
        targets = list(buoys.values())

    store = FileArchiveStore(args.archive_dir)
    now = datetime.now(UTC)
    for buoy in targets:
        model = _model_for(buoy, args)
        rows = rows_from_model(now, model)
        store.append(buoy.id, rows)
        print(
            f"{buoy.id}: archived {len(rows)} forecast rows @ {now.isoformat(timespec='seconds')}"
            f" → {args.archive_dir / (buoy.id + '.jsonl')}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "archive":
        return _cmd_archive(args)
    return _cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
