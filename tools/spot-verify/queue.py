#!/usr/bin/env python3
"""Build the next batch of spots whose pin still needs satellite verification.

The queue leg of the sat-verification loop (see JUDGING.md). Reads data/spots/*.yaml,
drops anything already user-verified / sat-verified or already judged in an earlier
batch, orders weakest-authority-first, and writes the [{id,name,lat,lon}] JSON that
tools/spot-seed/render.py consumes, plus a queue.md the judging session reads.

  python tools/spot-verify/queue.py --status
  python tools/spot-verify/queue.py --batch 12 [--region israel] [--out DIR]
  python tools/spot-verify/queue.py --mark DIR/queue.json [--date YYYY-MM-DD]

Verification state lives in each spot's trailing "# ..." source tag (the authority
ladder in docs/SPOT-DB.md). A tag naming user-verified or sat-verified means the PIN
is settled — a trailing "TODO verify" on such a line refers to the tuning params, not
the coordinate, so it does NOT re-queue the spot.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SPOTS = ROOT / "data" / "spots"
STATE = HERE / ".state" / "judged.txt"
WORK = HERE / "work"

# weakest authority first — these get the satellite look before better-sourced pins
LADDER = [
    (("approx", "guess", "from-memory"), 0, "approx"),
    (("osm",), 1, "osm"),
    (("websearch",), 2, "websearch"),
    (("google-geocoded", "geocoded"), 3, "geocoded"),
]
VERIFIED = ("user-verified", "sat-verified")


def _tag_for(raw: str, spot_id: str) -> str:
    """Trailing '# ...' comment on the line that declares this spot id, lowercased."""
    pat = re.compile(rf"\bid:\s*{re.escape(spot_id)}\b")
    for line in raw.splitlines():
        if pat.search(line) and "#" in line:
            return line.split("#", 1)[1].strip().lower()
    return ""


def _rank(tag: str) -> tuple[int, str]:
    for needles, rank, label in LADDER:
        if any(n in tag for n in needles):
            return rank, label
    return 0, "untagged"


def load_spots(region: str | None = None) -> list[dict]:
    rows = []
    for f in sorted(SPOTS.glob("*.yaml")):
        if region and f.stem != region:
            continue
        raw = f.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        for s in data.get("spots", []):
            tag = _tag_for(raw, s["id"])
            rank, label = _rank(tag)
            rows.append(
                {
                    "id": s["id"],
                    "name": s["name"],
                    "lat": float(s["lat"]),
                    "lon": float(s["lon"]),
                    "region": f.stem,
                    "tag": tag,
                    "source": label,
                    "rank": rank,
                    "verified": any(v in tag for v in VERIFIED),
                }
            )
    return rows


def load_judged() -> set[str]:
    if not STATE.exists():
        return set()
    return {
        line.split("\t")[0].strip()
        for line in STATE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def cmd_status(rows: list[dict], judged: set[str]) -> None:
    regions: dict[str, list[int]] = {}
    for r in rows:
        # [verified, judged-not-yet-applied, outstanding]
        b = regions.setdefault(r["region"], [0, 0, 0])
        if r["verified"]:
            b[0] += 1
        elif r["id"] in judged:
            b[1] += 1
        else:
            b[2] += 1
    w = max(len(k) for k in regions) if regions else 6
    print(f"{'region':<{w}}  verified  judged  outstanding")
    tot = [0, 0, 0]
    for region in sorted(regions):
        v, j, o = regions[region]
        tot = [tot[0] + v, tot[1] + j, tot[2] + o]
        print(f"{region:<{w}}  {v:>8}  {j:>6}  {o:>11}")
    print(f"{'TOTAL':<{w}}  {tot[0]:>8}  {tot[1]:>6}  {tot[2]:>11}")


def cmd_queue(rows: list[dict], judged: set[str], batch: int, out: Path) -> int:
    pending = [r for r in rows if not r["verified"] and r["id"] not in judged]
    pending.sort(key=lambda r: (r["rank"], r["region"], r["id"]))
    picked = pending[:batch]
    if not picked:
        print("queue empty — every spot is verified or already judged.", file=sys.stderr)
        return 1

    out.mkdir(parents=True, exist_ok=True)
    qjson = out / "queue.json"
    qjson.write_text(
        json.dumps(
            [{k: r[k] for k in ("id", "name", "lat", "lon")} for r in picked],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        f"# Judging queue — {len(picked)} spots ({len(pending)} outstanding overall)",
        "",
        "| id | name | region | current lat,lon | current source |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| `{r['id']}` | {r['name']} | {r['region']} | {r['lat']}, {r['lon']} | {r['source']} |"
        for r in picked
    ]
    lines += ["", f"Tiles: `{out}/<id>.png` · procedure: `tools/spot-verify/JUDGING.md`", ""]
    (out / "queue.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"{len(picked)} spots → {qjson}", file=sys.stderr)
    print(f"next: python tools/spot-seed/render.py --file {qjson} --out {out}", file=sys.stderr)
    print(qjson)
    return 0


def cmd_mark(queue_json: Path, date: str) -> int:
    ids = [r["id"] for r in json.loads(queue_json.read_text(encoding="utf-8"))]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    already = load_judged()
    new = [i for i in ids if i not in already]
    with STATE.open("a", encoding="utf-8") as fh:
        for i in new:
            fh.write(f"{i}\t{date}\n")
    print(f"marked {len(new)} judged ({len(ids) - len(new)} already recorded) → {STATE}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--region", help="limit to one data/spots/<region>.yaml")
    ap.add_argument("--batch", type=int, default=12, help="spots per batch (default 12)")
    ap.add_argument("--out", type=Path, help="output dir (default tools/spot-verify/work/<date>)")
    ap.add_argument("--status", action="store_true", help="print per-region progress and exit")
    ap.add_argument("--mark", type=Path, metavar="QUEUE_JSON", help="record a batch as judged")
    ap.add_argument("--date", default=dt.date.today().isoformat())
    a = ap.parse_args()

    if a.mark:
        return cmd_mark(a.mark, a.date)

    rows = load_spots(a.region)
    if not rows:
        print(f"no spots found (region={a.region!r})", file=sys.stderr)
        return 1
    judged = load_judged()
    if a.status:
        cmd_status(rows, judged)
        return 0
    return cmd_queue(rows, judged, a.batch, a.out or (WORK / a.date))


if __name__ == "__main__":
    raise SystemExit(main())
