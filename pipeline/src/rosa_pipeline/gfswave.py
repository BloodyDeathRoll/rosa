"""Raw NOAA GFS-Wave source (Stage 3a) — regional GRIB subsets via the NOMADS grib-filter.

Live-verified 2026-07-23 (docs/rosa-stage3-plan.md): `filter_gfswave.pl` serves a regional
subset of ``gfswave.tHHz.global.0p25.fHHH.grib2`` in ~10 KB per forecast hour, containing
wind, combined swh/perpw/dirpw, windsea (shww/mpww/wvdir) and THREE swell partitions
(shts/mpts/swdir x3) — the same partition schema Open-Meteo exposes.

This module currently powers the dual-source buoy archive (OM-vs-NOAA A/B against measured
truth). The full spot-forecast ``ForecastSource`` swap reuses the same fetch/parse when the
A/B evidence justifies promotion.

Comparison note baked in: GFS-Wave's ``perpw`` is a PEAK period, so it pairs with the buoy's
DPD (dominant period) — unlike Open-Meteo's mean ``wave_period``, which pairs with APD.
``verify`` handles this via ``GFSWAVE_VARIABLES``.

NOMADS etiquette: the raw ``pub/`` listing is 403 for scripts; the filter CGI and direct
file GETs are the sanctioned path. Requests here are few (steps x region boxes, not
per-point) and sequential.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from .verify import WavePoint

FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfswave.pl"
RESOLUTION = "0p25"
# archive sampling: every 6 h to the full 16-day horizon (65 steps) — plenty for
# lead-time skill at a fraction of the request count of the native 1-3-hourly output
DEFAULT_STEPS: tuple[int, ...] = tuple(range(0, 385, 6))
# a cycle's wave files land on NOMADS ~3.5-4 h after cycle time; only offer cycles
# at least this old, and fall back one more cycle on a miss
CYCLE_LAG_H = 4.0
BOX_PAD_DEG = 1.0  # padding around each point cluster
CLUSTER_SPAN_DEG = 20.0  # points within this span share one box
NEAREST_MAX_DEG = 0.6  # nearest wet grid node must be within this of the point


@dataclass(frozen=True, slots=True)
class Box:
    """Lat/lon box in the filter's convention (lon 0-360, left <= right)."""

    bottom: float
    top: float
    left: float
    right: float

    @property
    def key(self) -> str:
        return f"{self.bottom:g}_{self.top:g}_{self.left:g}_{self.right:g}"


def _lon360(lon: float) -> float:
    return lon % 360.0


def cluster_boxes(points: list[tuple[float, float]]) -> list[tuple[Box, list[int]]]:
    """Group points into padded fetch boxes; returns (box, indices-into-points) pairs.

    Greedy: seed a cluster with the first unassigned point, absorb every point within
    CLUSTER_SPAN_DEG in both axes (0-360 longitude). Deterministic for a fixed order."""
    out: list[tuple[Box, list[int]]] = []
    unassigned = list(range(len(points)))
    while unassigned:
        seed = unassigned.pop(0)
        members = [seed]
        s_lat, s_lon = points[seed][0], _lon360(points[seed][1])
        rest = []
        for i in unassigned:
            lat, lon = points[i][0], _lon360(points[i][1])
            if abs(lat - s_lat) <= CLUSTER_SPAN_DEG and abs(lon - s_lon) <= CLUSTER_SPAN_DEG:
                members.append(i)
            else:
                rest.append(i)
        unassigned = rest
        lats = [points[i][0] for i in members]
        lons = [_lon360(points[i][1]) for i in members]
        box = Box(
            bottom=min(lats) - BOX_PAD_DEG,
            top=max(lats) + BOX_PAD_DEG,
            left=min(lons) - BOX_PAD_DEG,
            right=max(lons) + BOX_PAD_DEG,
        )
        out.append((box, members))
    return out


def pick_cycle(now: datetime) -> datetime:
    """Latest 00/06/12/18Z cycle whose files should already be on NOMADS."""
    ready = now - timedelta(hours=CYCLE_LAG_H)
    cycle_hour = (ready.hour // 6) * 6
    return ready.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)


def filter_url(cycle: datetime, step: int, box: Box) -> str:
    d = quote(f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/wave/gridded", safe="")
    f = f"gfswave.t{cycle:%H}z.global.{RESOLUTION}.f{step:03d}.grib2"
    return (
        f"{FILTER_URL}?dir={d}&file={f}&all_var=on&subregion="
        f"&toplat={box.top:g}&leftlon={box.left:g}&rightlon={box.right:g}&bottomlat={box.bottom:g}"
    )


def _is_grib(data: bytes) -> bool:
    return data[:4] == b"GRIB"


def parse_grib_points(
    grib_bytes: bytes, points: list[tuple[float, float]], valid: datetime
) -> list[WavePoint | None]:
    """Extract (hs=swh, tp=perpw, dir=dirpw) at the nearest wet grid node of each point.

    Returns one WavePoint (or None if no wet node within NEAREST_MAX_DEG) per input point.
    pygrib wants a file path, so the bytes hit a temp file briefly."""
    import numpy as np
    import pygrib

    with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
        tf.write(grib_bytes)
        tf.flush()
        grbs = pygrib.open(tf.name)
        fields: dict[str, tuple] = {}
        for m in grbs:
            if m.shortName in ("swh", "perpw", "dirpw") and m.shortName not in fields:
                vals = m.values  # masked array over land
                lats, lons = m.latlons()
                fields[m.shortName] = (vals, lats, lons)
        grbs.close()

    out: list[WavePoint | None] = []
    for lat, lon in points:
        lon = _lon360(lon)
        vals_by_name: dict[str, float | None] = {}
        ok = True
        for name in ("swh", "perpw", "dirpw"):
            if name not in fields:
                vals_by_name[name] = None
                continue
            vals, glats, glons = fields[name]
            d2 = (glats - lat) ** 2 + (np.mod(glons, 360.0) - lon) ** 2
            if hasattr(vals, "mask") and vals.mask is not np.ma.nomask:
                d2 = np.where(vals.mask, np.inf, d2)
            idx = np.unravel_index(np.argmin(d2), d2.shape)
            if d2[idx] > NEAREST_MAX_DEG**2:
                ok = False
                break
            vals_by_name[name] = round(float(vals[idx]), 3)  # strip float32 noise for JSONL
        if not ok:
            out.append(None)
            continue
        out.append(
            WavePoint(
                time=valid,
                hs=vals_by_name["swh"],
                tp=vals_by_name["perpw"],
                dir=vals_by_name["dirpw"],
            )
        )
    return out


class GFSWaveWaves(Protocol):
    """Per-point GFS-Wave series for the buoy archive."""

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[WavePoint]]: ...


class GFSWaveSource:
    """Live NOMADS fetch: one grib-filter request per (region box x step), values for
    every point in the box extracted from the same download."""

    def __init__(
        self,
        capture_dir: Path | None = None,
        steps: tuple[int, ...] = DEFAULT_STEPS,
        timeout_s: float = 60.0,
    ) -> None:
        self.capture_dir = capture_dir
        self.steps = steps
        self.timeout_s = timeout_s

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[WavePoint]]:
        series: list[list[WavePoint]] = [[] for _ in points]
        cycle = pick_cycle(datetime.now(UTC))
        with httpx.Client(timeout=self.timeout_s) as client:
            for box, members in cluster_boxes(points):
                cyc = cycle
                for step in self.steps:
                    data = self._get(client, cyc, step, box)
                    if data is None and step == self.steps[0]:
                        # cycle not on NOMADS yet — drop back one and retry this box
                        cyc = cyc - timedelta(hours=6)
                        data = self._get(client, cyc, step, box)
                    if data is None:
                        continue
                    if self.capture_dir is not None:
                        self.capture_dir.mkdir(parents=True, exist_ok=True)
                        name = f"gfswave_f{step:03d}_{box.key}.grib2"
                        (self.capture_dir / name).write_bytes(data)
                    valid = cyc + timedelta(hours=step)
                    pts = [points[i] for i in members]
                    for i, wp in zip(members, parse_grib_points(data, pts, valid), strict=True):
                        if wp is not None:
                            series[i].append(wp)
        return series

    def _get(self, client: httpx.Client, cycle: datetime, step: int, box: Box) -> bytes | None:
        try:
            resp = client.get(filter_url(cycle, step, box))
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or not _is_grib(resp.content):
            return None  # filter answers 200 with an HTML error page for missing files
        return resp.content


class GFSWaveFixtureSource:
    """Replay captured gribs (tests / offline). Matches files by step + box key,
    ignoring the capture cycle; ``valid`` is stamped from a fixed cycle for determinism."""

    def __init__(self, fixtures_dir: Path, cycle: datetime | None = None) -> None:
        self.fixtures_dir = fixtures_dir
        self.cycle = cycle or datetime(2026, 7, 23, 0, tzinfo=UTC)

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[WavePoint]]:
        series: list[list[WavePoint]] = [[] for _ in points]
        for box, members in cluster_boxes(points):
            for path in sorted(self.fixtures_dir.glob(f"gfswave_f*_{box.key}.grib2")):
                step = int(path.name.split("_f")[1][:3])
                valid = self.cycle + timedelta(hours=step)
                pts = [points[i] for i in members]
                data = path.read_bytes()
                for i, wp in zip(members, parse_grib_points(data, pts, valid), strict=True):
                    if wp is not None:
                        series[i].append(wp)
        return series
