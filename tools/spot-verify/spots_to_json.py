#!/usr/bin/env python3
"""Flatten data/spots/*.yaml (or one file) into the [{id,name,lat,lon,source}] JSON
that shoot.mjs consumes. Optional --todo filters to spots whose source comment is
not user-verified (the ones most worth re-checking)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("yaml", type=Path)
    ap.add_argument("--out", type=Path, default=Path("-"))
    args = ap.parse_args()

    data = yaml.safe_load(args.yaml.read_text(encoding="utf-8"))
    rows = [
        {"id": s["id"], "name": s["name"], "lat": float(s["lat"]), "lon": float(s["lon"])}
        for s in data["spots"]
    ]
    text = json.dumps(rows, ensure_ascii=False, indent=2)
    if str(args.out) == "-":
        sys.stdout.write(text + "\n")
    else:
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
