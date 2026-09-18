"""The Stage-4 nearshore arm's reader (docs/rosa-stage4-plan.md 4.4).

`rosa-pipeline swan` + `run.sh` leave, per step and grid, a SWAN TABLE of the sea at every
output point - the spot's handoff point (~15 m on its own ray, tools/swan-grid). This
module turns those tables into one series per spot and hands `score_hour` the sea for an
hour, so the breaker march starts at the handoff point instead of the offshore point.

What it deliberately does NOT do: touch the partitions the payload displays, the rating's
period/wind terms, or any hour it has no sea for. A missing step, a dry cell, a run that
never happened - each falls back to the shipping path for that hour, and the payload says
so per hour (`ScoredHour.nearshore`), never with a blank.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .models import SwellPartition

# Hourly forecast hours between 3-hourly SWAN steps are interpolated; past this gap from
# the nearest step the hour falls back to the march (a purged or failed step, the tail).
MAX_GAP_H = 3.0
SOURCE = "swan"


@dataclass(frozen=True, slots=True)
class NearshoreSea:
    """SWAN's total sea at a spot's handoff point for one moment."""

    time: datetime
    hs: float
    tm01: float
    tps: float
    direction: float  # nautical, degrees FROM
    dspr: float
    depth_m: float  # the grid's depth at the handoff point (tide not included)
    handoff_m: float  # distance from the pin along the ray
    source: str = SOURCE

    def partition(self) -> SwellPartition:
        return SwellPartition(
            height_m=self.hs,
            period_s=self.tm01,
            direction_deg=self.direction,
            kind="swell",
            peak_period_s=self.tps,
        )


def inner_samples(
    wet_samples: list[tuple[float, float]], sea: NearshoreSea
) -> list[tuple[float, float]]:
    """The committed profile from the handoff point inward: (dist_m, depth_m) deep -> shallow,
    starting with the handoff point itself at the model grid's depth there. The profile's
    own samples further out are the part SWAN has already propagated through."""
    inner = [(d, z) for d, z in wet_samples if d < sea.handoff_m]
    return [(sea.handoff_m, sea.depth_m), *inner]


# --- SWAN tables --------------------------------------------------------------------------


def read_table(path: Path) -> list[dict[str, float]]:
    """A SWAN `TABLE ... HEAD` file: comment lines start with %, the column names sit on the
    % line that precedes the units line, data rows follow. Column names as SWAN prints them
    (Xp, Yp, Depth, Hsig, TPsmoo, Dir, Dspr, Tm01)."""
    names: list[str] | None = None
    rows: list[dict[str, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("%"):
            parts = line[1:].split()
            if parts and parts[0] == "Xp":
                names = parts
            continue
        if not line.strip():
            continue
        if names is None:
            raise ValueError(f"{path}: data before the column header")
        vals = [float(v) for v in line.split()]
        rows.append(dict(zip(names, vals, strict=False)))
    return rows


def _valid(row: dict[str, float]) -> bool:
    # SWAN prints -99 / -9 / -999 exception values at dry or unresolved points
    return (
        row.get("Depth", -99.0) > 0 and row.get("Hsig", -9.0) >= 0 and row.get("Dir", -999.0) >= 0
    )


def load_run(run_dir: Path, points_json: Path) -> dict[str, list[NearshoreSea]]:
    """One time-ordered series per spot from a completed run directory.

    ``points.json`` (tools/swan-grid) says which grid holds each spot's handoff point and
    in which order the points were written - the nest tables (`spots_fNNN_<nest>.tab`) list
    that nest's points in that order, the outer table (`spots_fNNN.tab`) lists them all.
    A nest's row wins over the outer's; a step with no table is simply absent."""
    points = json.loads(points_json.read_text(encoding="utf-8"))
    cycle_info = json.loads((run_dir / "cycle.json").read_text(encoding="utf-8"))
    cycle = datetime.fromisoformat(cycle_info["cycle"])
    by_grid: dict[str, list[dict]] = {}
    for p in points:
        by_grid.setdefault(p["grid"], []).append(p)
    series: dict[str, list[NearshoreSea]] = {}
    for step in cycle_info["steps"]:
        tag = f"f{step:03d}"
        valid = cycle + timedelta(hours=step)
        seen: set[str] = set()
        for grid, mine in by_grid.items():
            table = run_dir / f"spots_{tag}_{grid}.tab"
            if grid == "outer" or not table.exists():
                continue
            _take(series, table, mine, valid, seen)
        outer = run_dir / f"spots_{tag}.tab"
        if outer.exists():
            _take(series, outer, points, valid, seen)
    for s in series.values():
        s.sort(key=lambda n: n.time)
    return series


def _take(
    series: dict[str, list[NearshoreSea]],
    table: Path,
    points: list[dict],
    valid: datetime,
    seen: set[str],
) -> None:
    rows = read_table(table)
    if len(rows) != len(points):
        raise ValueError(f"{table}: {len(rows)} rows for {len(points)} points")
    for row, p in zip(rows, points, strict=True):
        if p["spot"] in seen or not _valid(row):
            continue
        seen.add(p["spot"])
        series.setdefault(p["spot"], []).append(
            NearshoreSea(
                time=valid,
                hs=row["Hsig"],
                tm01=row.get("Tm01", row["TPsmoo"]),
                tps=row["TPsmoo"],
                direction=row["Dir"] % 360.0,
                dspr=row.get("Dspr", 0.0),
                depth_m=row["Depth"],
                handoff_m=p["handoff_km"] * 1000.0,
            )
        )


def load_buoys(run_dir: Path) -> dict[str, list[NearshoreSea]]:
    """SWAN's sea at the registered buoys, one series per buoy id, from a completed run:
    ``buoys.json`` (grid -> buoy ids in table order, written by `rosa-pipeline swan`) and
    the per-step ``buoys_fNNN[_<nest>].tab`` tables. Same rules as `load_run`: nest row
    wins, exception values skipped, missing steps absent. ``handoff_m`` is 0 - a buoy is
    its own point."""
    buoys_json = run_dir / "buoys.json"
    if not buoys_json.exists():
        return {}
    by_grid: dict[str, list[str]] = json.loads(buoys_json.read_text(encoding="utf-8"))
    cycle_info = json.loads((run_dir / "cycle.json").read_text(encoding="utf-8"))
    cycle = datetime.fromisoformat(cycle_info["cycle"])
    series: dict[str, list[NearshoreSea]] = {}
    for step in cycle_info["steps"]:
        tag = f"f{step:03d}"
        valid = cycle + timedelta(hours=step)
        seen: set[str] = set()
        for grid, ids in by_grid.items():
            table = run_dir / (f"buoys_{tag}.tab" if grid == "outer" else f"buoys_{tag}_{grid}.tab")
            if not table.exists():
                continue
            points = [{"spot": bid, "handoff_km": 0.0} for bid in ids]
            _take(series, table, points, valid, seen)
    for s in series.values():
        s.sort(key=lambda n: n.time)
    return series


def archive_rows(
    series: list[NearshoreSea], cycle: datetime, run_time: datetime | None = None
) -> list[dict]:
    """Append-ready archive rows in the members' shape (archive.rows_from_model): tp is the
    PEAK period, so the scorecard pairs it with the buoy's DPD like gfswave/ecmwf.

    ``run_time`` is the archive's invocation time, the stamp every other member carries
    (cli ``now``): lead = valid - run, and the 4.5 A/B reads this member against
    gfswave/blend PER LEAD BUCKET, so a row stamped with the GFS model cycle (4-10 h
    older) scored the analysis hours the other cards drop and sat one bucket late at
    every edge. The cycle still rides along as ``cycle`` - an extra key the scorecard
    ignores. None keeps the cycle as the stamp, for a caller with no invocation time."""
    run_iso = (run_time or cycle).isoformat(timespec="seconds")
    extra = {"cycle": cycle.isoformat(timespec="seconds")} if run_time is not None else {}
    return [
        {
            "run": run_iso,
            "valid": s.time.isoformat(timespec="seconds"),
            "hs": round(s.hs, 3),
            "tp": round(s.tps, 3),
            "dir": round(s.direction, 1),
            "tm01": round(s.tm01, 3),
            "dspr": round(s.dspr, 1),
            **extra,
        }
        for s in series
    ]


# --- per-hour lookup ----------------------------------------------------------------------


def _lerp(a: float, b: float, w: float) -> float:
    return a + (b - a) * w


def _circ(a: float, b: float, w: float) -> float:
    d = ((b - a + 180.0) % 360.0) - 180.0
    return (a + d * w) % 360.0


def nearshore_at(
    series: list[NearshoreSea] | None, t: datetime, max_gap_h: float = MAX_GAP_H
) -> NearshoreSea | None:
    """The sea at ``t``: an exact step, a linear blend of the two bracketing steps (direction
    circular), or None when the nearest step is further than ``max_gap_h`` away."""
    if not series:
        return None
    times = [s.time for s in series]
    k = bisect_left(times, t)
    if k < len(series) and times[k] == t:
        return series[k]
    before = series[k - 1] if k > 0 else None
    after = series[k] if k < len(series) else None
    if before is not None and after is not None:
        span = (after.time - before.time).total_seconds() / 3600.0
        if span <= 2 * max_gap_h:
            w = (t - before.time).total_seconds() / 3600.0 / span
            return NearshoreSea(
                time=t,
                hs=_lerp(before.hs, after.hs, w),
                tm01=_lerp(before.tm01, after.tm01, w),
                tps=_lerp(before.tps, after.tps, w),
                direction=_circ(before.direction, after.direction, w),
                dspr=_lerp(before.dspr, after.dspr, w),
                depth_m=before.depth_m,
                handoff_m=before.handoff_m,
                source=before.source,
            )
    nearest = min(
        (s for s in (before, after) if s is not None),
        key=lambda s: abs((s.time - t).total_seconds()),
    )
    if abs((nearest.time - t).total_seconds()) / 3600.0 <= max_gap_h and not math.isnan(nearest.hs):
        return NearshoreSea(
            time=t,
            hs=nearest.hs,
            tm01=nearest.tm01,
            tps=nearest.tps,
            direction=nearest.direction,
            dspr=nearest.dspr,
            depth_m=nearest.depth_m,
            handoff_m=nearest.handoff_m,
            source=nearest.source,
        )
    return None
