"""rosa-pipeline CLI.

Run from the repo root so the default data paths resolve:
    uv run --project pipeline rosa-pipeline run --spot beit-yanai
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from .extract import extract_hours
from .fetch import FixtureSource, ForecastSource, OpenMeteoSource
from .publish import build_payload, update_index, write_spot_json
from .score import score_hour
from .spots import load_spots


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rosa-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="fetch, score and publish a spot forecast")
    run.add_argument("--spot", required=True, help="spot id, e.g. beit-yanai")
    run.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    run.add_argument("--out", type=Path, default=Path("data/out"))
    run.add_argument(
        "--fixtures", type=Path, default=None, help="replay captured responses (offline)"
    )
    run.add_argument("--capture", type=Path, default=None, help="capture raw responses to this dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    spots = load_spots(args.spots_dir)
    spot = spots.get(args.spot)
    if spot is None:
        print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
        return 2

    source: ForecastSource = (
        FixtureSource(args.fixtures)
        if args.fixtures is not None
        else OpenMeteoSource(capture_dir=args.capture)
    )
    raw = source.fetch(*spot.offshore_point)
    scored = [score_hour(spot, h) for h in extract_hours(raw)]
    if not scored:
        print("no forecast hours extracted", file=sys.stderr)
        return 1

    payload = build_payload(spot, scored, fetched_at=raw.fetched_at, now=datetime.now(UTC))
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
