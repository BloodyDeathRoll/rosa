"""GFS 0.25 deg ATMOSPHERIC wind at the coastal stations - the plan C3b A/B member.

Since 2026-09-12 the weather host is the blend arm's last per-spot Open-Meteo call, and at
1947 spots it sits at the vendor's 10,000/day line (OPEN-ITEMS 34). The exit is the move
waves already made: one NOMADS grib-filter request per (box x step), never per spot. This
module is the MEASUREMENT half of that plan - it archives the raw GFS 10 m wind at every
registered wind station each cycle under the ``.gfs_grib`` key, beside Open-Meteo's
``gfs_seamless`` (the published model) and ``icon_seamless``, so ``verify --stations
--wind-model gfs_grib`` scores all three against the same METAR/IMS readings.

Why it must be measured and not assumed: Open-Meteo has served GFS (``gfs_seamless``)
since 2026-08-30, so on paper this is the same model - but the C3 verdict (CALIBRATION.md
2026-08-26, "OM ahead before day 4") compared ICON-era OM with the WAVE file's ocean-masked
wind, never the atmos grid, and Open-Meteo's ``gfs_seamless`` folds NCEP HRRR/NAM into the
US short range and picks its cell with a land preference. The station cards decide.

The request: ``filter_gfs_0p25_1hr.pl``, ``pgrb2.0p25`` files, UGRD/VGRD at 10 m above
ground, subregion by box (live-verified 2026-09-12: a 4x3 deg Israel box is ~1.3 KB a step,
0.4-1.2 s from the workstation; f000-f120 hourly then 3-hourly to f384). Wind speed is
``hypot(u, v)`` in m/s, direction the meteorological FROM bearing, both rounded the way the
wave gribs are. Stations stand on land, so the sample is the plain nearest grid node - the
honest GRIB read, and what a ``WeatherSource`` would do for a spot's offshore point.

Steps are 3-hourly to 384 h (``BLEND_STEPS``): the production shape, so this arm is also
the prototype fetch. 9 boxes x 129 steps = 1,161 requests a cycle at the 90-station
registry, ~24 min at NOMADS_WORKERS=4 on the VM's ~5 s per request; measured on the first
live cycle, and 6-hourly is the fallback if that ever crowds the archive step.
"""

from __future__ import annotations

import math
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from .geo import lon360
from .gfswave import Box, _is_grib, cluster_boxes
from .verify import WavePoint

FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25_1hr.pl"
# 3-hourly to the full horizon - the same steps blend.GfsFullSource pulls for waves, so a
# promoted WeatherSource fetches exactly what this arm measured
STEPS: tuple[int, ...] = tuple(range(0, 385, 3))
# the pgrb2 0p25 set for a cycle is complete on NOMADS ~5 h after cycle time (f384 is the
# last to land); lag past that and fall back one cycle on a first-step miss, as gfswave does
CYCLE_LAG_H = 5.5
# nearest grid node must be within this of the station (0.25 deg grid: half a cell is
# 0.125, so this only ever refuses a station outside its own box - a bug, not weather)
NEAREST_MAX_DEG = 0.3
WORKERS = 4  # same courtesy budget as gfswave.WORKERS / blend.NOMADS_WORKERS


def pick_cycle(now: datetime) -> datetime:
    ready = now - timedelta(hours=CYCLE_LAG_H)
    return ready.replace(hour=(ready.hour // 6) * 6, minute=0, second=0, microsecond=0)


def filter_url(cycle: datetime, step: int, box: Box) -> str:
    d = quote(f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos", safe="")
    f = f"gfs.t{cycle:%H}z.pgrb2.0p25.f{step:03d}"
    return (
        f"{FILTER_URL}?dir={d}&file={f}&var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on"
        f"&subregion=&toplat={box.top:g}&leftlon={box.left:g}"
        f"&rightlon={box.right:g}&bottomlat={box.bottom:g}"
    )


def wind_from_uv(u: float, v: float) -> tuple[float, float]:
    """(speed m/s, direction the wind blows FROM, deg) from grid-relative u/v. GFS 0.25
    lat/lon output is earth-relative, so no rotation is needed."""
    speed = math.hypot(u, v)
    direction = (270.0 - math.degrees(math.atan2(v, u))) % 360.0
    return speed, direction


def parse_grib_points(
    grib_bytes: bytes, points: list[tuple[float, float]], valid: datetime
) -> list[WavePoint | None]:
    """10 m wind at the nearest grid node of each point, as wind-only WavePoints (the
    station archive row shape - hs/tp/dir None). None for a point with no node in reach."""
    import numpy as np
    import pygrib

    fields: dict[str, tuple] = {}
    with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
        tf.write(grib_bytes)
        tf.flush()
        grbs = pygrib.open(tf.name)
        for m in grbs:
            if m.shortName in ("10u", "10v") and m.shortName not in fields:
                lats, lons = m.latlons()
                fields[m.shortName] = (np.asarray(m.values, dtype=float), lats, lons)
        grbs.close()
    if "10u" not in fields or "10v" not in fields:
        return [None] * len(points)
    u_vals, glats, glons = fields["10u"]
    v_vals = fields["10v"][0]
    glons = np.where(glons < 0, glons + 360.0, glons)
    out: list[WavePoint | None] = []
    for lat, lon in points:
        lon = lon360(lon)
        # ground-distance metric, the 2026-09-11 rule: a lon degree is cos(lat) of a lat one
        d2 = (glats - lat) ** 2 + ((glons - lon) * math.cos(math.radians(lat))) ** 2
        idx = np.unravel_index(int(np.argmin(d2)), d2.shape)
        if abs(glats[idx] - lat) > NEAREST_MAX_DEG or abs(glons[idx] - lon) > NEAREST_MAX_DEG:
            out.append(None)
            continue
        speed, direction = wind_from_uv(float(u_vals[idx]), float(v_vals[idx]))
        out.append(
            WavePoint(
                time=valid,
                hs=None,
                tp=None,
                dir=None,
                ws=round(speed, 3),
                wdir=round(direction, 3),
            )
        )
    return out


class GfsAtmosWind(Protocol):
    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[WavePoint]]: ...


class GfsAtmosSource:
    """Live NOMADS fetch: one grib-filter request per (box x step), every station in the
    box sampled from the same download. The same download pattern as gfswave.GFSWaveSource;
    only the dataset and the parse differ."""

    def __init__(
        self,
        capture_dir: Path | None = None,
        steps: tuple[int, ...] = STEPS,
        timeout_s: float = 60.0,
    ) -> None:
        self.capture_dir = capture_dir
        self.steps = steps
        self.timeout_s = timeout_s

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[WavePoint]]:
        series: list[list[WavePoint]] = [[] for _ in points]
        cycle = pick_cycle(datetime.now(UTC))
        with (
            httpx.Client(timeout=self.timeout_s) as client,
            ThreadPoolExecutor(max_workers=WORKERS) as pool,
        ):
            for box, members in cluster_boxes(points):
                pts = [points[i] for i in members]
                # the first step alone decides the cycle (drop back 6 h when NOMADS has
                # not published yet); the rest go through the pool, a miss skips its step
                cyc = cycle
                first = self._get(client, cyc, self.steps[0], box)
                if first is None:
                    cyc = cyc - timedelta(hours=6)
                    first = self._get(client, cyc, self.steps[0], box)
                rest = pool.map(lambda s, b=box, c=cyc: self._get(client, c, s, b), self.steps[1:])
                for step, data in zip(self.steps, [first, *rest], strict=True):
                    if data is None:
                        continue
                    if self.capture_dir is not None:
                        self.capture_dir.mkdir(parents=True, exist_ok=True)
                        (self.capture_dir / f"gfsatmos_f{step:03d}_{box.key}.grib2").write_bytes(
                            data
                        )
                    valid = cyc + timedelta(hours=step)
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
            return None  # the filter answers 200 with an HTML page for a missing file
        return resp.content


class GfsAtmosFixtureSource:
    """Replay captured gribs (tests / offline). Matches files by step + box key, ignoring
    the capture cycle; ``valid`` is stamped from a fixed cycle for determinism."""

    def __init__(self, fixtures_dir: Path, cycle: datetime | None = None) -> None:
        self.fixtures_dir = fixtures_dir
        self.cycle = cycle or datetime(2026, 9, 12, 0, tzinfo=UTC)

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[WavePoint]]:
        series: list[list[WavePoint]] = [[] for _ in points]
        for box, members in cluster_boxes(points):
            pts = [points[i] for i in members]
            for path in sorted(self.fixtures_dir.glob(f"gfsatmos_f*_{box.key}.grib2")):
                step = int(path.name.split("_")[1][1:])
                valid = self.cycle + timedelta(hours=step)
                for i, wp in zip(
                    members, parse_grib_points(path.read_bytes(), pts, valid), strict=True
                ):
                    if wp is not None:
                        series[i].append(wp)
        return series
