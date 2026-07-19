"""rosa-pipeline CLI.

Run from the repo root so the default data paths resolve:
    uv run --project pipeline rosa-pipeline run --spot beit-yanai
    uv run --project pipeline rosa-pipeline run --all

--all fetches each unique offshore point exactly once and publishes every spot
from it: 20 Israel spots share 3 points, so a full run is 3 fetches, not 20
(Open-Meteo throttles rapid per-spot fetching).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from .extract import extract_hours
from .fetch import FixtureSource, ForecastSource, OpenMeteoSource
from .models import Spot
from .publish import build_payload, update_index, write_spot_json
from .score import score_hour
from .spots import load_spots

POINT_FETCH_DELAY_S = 2.0  # politeness gap between live fetches of distinct points


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
    return parser


def group_by_point(spots: list[Spot]) -> dict[tuple[float, float], list[Spot]]:
    groups: dict[tuple[float, float], list[Spot]] = {}
    for spot in spots:
        groups.setdefault(spot.offshore_point, []).append(spot)
    return groups


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

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
    live = args.fixtures is None
    now = datetime.now(UTC)

    for i, (point, group) in enumerate(group_by_point(targets).items()):
        if live and i > 0:
            time.sleep(POINT_FETCH_DELAY_S)
        raw = source.fetch(*point)
        hours = extract_hours(raw)
        if not hours:
            print(f"no forecast hours extracted for point {point}", file=sys.stderr)
            return 1
        for spot in group:
            scored = [score_hour(spot, h) for h in hours]
            payload = build_payload(spot, scored, fetched_at=raw.fetched_at, now=now)
            path = write_spot_json(payload, args.out)
            update_index(payload, args.out)
            current = payload["current"]
            print(
                f"{spot.id}: {current['bucket']} {current['rating']}/100 · {current['phrase']} "
                f"· wind {current['wind']['class']} {current['wind']['kph']} kph → {path}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
