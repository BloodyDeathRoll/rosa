"""DWD GWAM peak periods for the blend arm (docs/rosa-peak-period-plan.md, plan A).

GFS-Wave gridded publishes per-partition MEAN periods only, so after the 2026-08-26 flip
every partition reached the transform with ``peak_period_s = None`` and rideability keyed
on the mean - the 1.6-2x under-call CALIBRATION.md 2026-07-30 measured. The Open-Meteo arm
never had that gap because its ``gwam`` member (DWD's global wave model) supplied the primary
swell's and the wind sea's peak period to ~7.3 days (`fetch.TP_MODEL`). DWD publishes that
same model directly, free, CC BY 4.0:

    https://opendata.dwd.de/weather/maritime/wave_models/gwam/grib/{00,12}/{ppts,ppww}/
    GWAM_PPTS_YYYYMMDDHH_SSS.grib2.bz2   pp1ds  "Peak wave period of total swell"  (s)
    GWAM_PPWW_YYYYMMDDHH_SSS.grib2.bz2   pp1dw  "Peak wave period of wind waves"   (s)

Verified 2026-08-26 by parsing one file of each: global regular 0.25 deg, 1440 x 699,
lat 89.25 -> -85.25, lon 0 -> 359.75, land-masked, 3-hourly steps 000-174, cycles 00Z and
12Z, the 00Z run's files last-modified 03:39Z (CYCLE_LAG_H below). One global field is
~1.2 MB unpacked; every spot is sampled from the same download, so this is O(1) in spot
count like OISST - the fetch-plane property - and costs zero Open-Meteo units.

What it restores is exactly what the OM arm had and no more: GWAM partitions the sea into
ONE swell plus the wind sea, so ``swell_wave_peak_period`` and ``wind_wave_peak_period``
are the only columns; secondary/tertiary swells never carried a peak on either arm.
Handing GWAM's swell peak to GFS's primary swell partition is the cross-model join
``fetch.py``'s TP_MODEL note already argues for: Tp feeds rideability and display, never
the dispersion march, so a Tp from another model cannot desynchronise the physics.
"""

from __future__ import annotations

import bz2
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from .geo import dlon180

BASE_URL = "https://opendata.dwd.de/weather/maritime/wave_models/gwam/grib"
# file-name stem -> the OM-shaped column extract._partition reads the peak from
PARAMS: dict[str, str] = {"ppts": "swell_wave_peak_period", "ppww": "wind_wave_peak_period"}
# measured 2026-08-26: the 00Z run's step files were last-modified 03:39Z, the 12Z run's
# 15:39Z. Four hours is the same margin gfswave.CYCLE_LAG_H keeps on NOMADS.
CYCLE_LAG_H = 4.0
STEPS: tuple[int, ...] = tuple(range(0, 175, 3))
CELL_DEG = 0.25
NEAREST_MAX_DEG = 1.0  # a coastal cell one degree out is fine for a peak period
# concurrent downloads; DWD's server is not NOMADS and has no published courtesy limit,
# but four keeps the ~118 files/cycle to a few minutes without hammering it
WORKERS = 4


@dataclass(frozen=True, slots=True)
class GwamStep:
    """One GWAM step at one point: the two peak periods, None where masked or absent."""

    time: datetime
    swell_tp: float | None
    windsea_tp: float | None


def pick_cycle(now: datetime) -> datetime:
    """Latest 00Z/12Z cycle whose files should already be on the server."""
    ready = now - timedelta(hours=CYCLE_LAG_H)
    return ready.replace(hour=0 if ready.hour < 12 else 12, minute=0, second=0, microsecond=0)


def file_url(cycle: datetime, param: str, step: int) -> str:
    return (
        f"{BASE_URL}/{cycle:%H}/{param}/GWAM_{param.upper()}_{cycle:%Y%m%d%H}_{step:03d}.grib2.bz2"
    )


def _grib_bytes(data: bytes) -> bytes:
    return bz2.decompress(data) if data[:3] == b"BZh" else data


def parse_points(data: bytes, points: list[tuple[float, float]]) -> list[float | None]:
    """The field's value at each point's nearest wet cell within NEAREST_MAX_DEG, else None.

    ``data`` may be the bz2 file as served or the bare GRIB. One message per file."""
    import numpy as np
    import pygrib

    with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
        tf.write(_grib_bytes(data))
        tf.flush()
        grbs = pygrib.open(tf.name)
        try:
            msg = grbs[1]
            values = np.ma.masked_invalid(msg.values)
            lats = np.asarray(msg.distinctLatitudes, dtype=float)
            lons = np.asarray(msg.distinctLongitudes, dtype=float)  # 0..359.75
        finally:
            grbs.close()
    field = values.filled(np.nan)
    if field.shape != (len(lats), len(lons)):
        field = field.reshape(len(lats), len(lons))
    reach = int(NEAREST_MAX_DEG / CELL_DEG)
    out: list[float | None] = []
    for lat, lon in points:
        lon360 = lon % 360.0
        i = int(np.argmin(np.abs(lats - lat)))
        j = int(np.argmin(np.abs(dlon180(lons, lon360))))
        # the lon axis is periodic: take the window by WRAPPED column index so a spot
        # just east of Greenwich still sees the cells just west of it (geo.dlon180)
        cols = np.mod(np.arange(j - reach, j + reach + 1), len(lons))
        rows = slice(max(0, i - reach), i + reach + 1)  # lat is NOT periodic
        win = field[rows, :][:, cols]
        wet = np.argwhere(np.isfinite(win) & (win > 0))
        if len(wet) == 0:
            out.append(None)
            continue
        wlat = lats[rows]
        wlon = lons[cols]
        d2 = (wlat[wet[:, 0]] - lat) ** 2 + (
            np.cos(np.radians(lat)) * dlon180(wlon[wet[:, 1]], lon360)
        ) ** 2
        k = int(np.argmin(d2))
        out.append(round(float(win[wet[k, 0], wet[k, 1]]), 2))
    return out


def _assemble(
    points: list[tuple[float, float]],
    sampled: dict[tuple[str, int], list[float | None]],
    cycle: datetime,
) -> list[list[GwamStep]]:
    """Per-point step series from per-(param, step) point samples; a step present for
    neither param is dropped, one present for a single param keeps the other None."""
    series: list[list[GwamStep]] = [[] for _ in points]
    steps = sorted({s for _, s in sampled})
    for step in steps:
        ts = sampled.get(("ppts", step))
        tw = sampled.get(("ppww", step))
        valid = cycle + timedelta(hours=step)
        for i in range(len(points)):
            series[i].append(
                GwamStep(
                    time=valid,
                    swell_tp=ts[i] if ts is not None else None,
                    windsea_tp=tw[i] if tw is not None else None,
                )
            )
    return series


class GwamPeaks(Protocol):
    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[GwamStep]]: ...


class GwamSource:
    """Live DWD fetch: both params for every step of the latest cycle, sampled at every
    point from the same download, one global field in memory at a time."""

    def __init__(
        self,
        capture_dir: Path | None = None,
        steps: tuple[int, ...] = STEPS,
        timeout_s: float = 60.0,
    ) -> None:
        self.capture_dir = capture_dir
        self.steps = steps
        self.timeout_s = timeout_s

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[GwamStep]]:
        if not points:
            return []
        cycle = pick_cycle(datetime.now(UTC))
        sampled: dict[tuple[str, int], list[float | None]] = {}
        with (
            httpx.Client(timeout=self.timeout_s) as client,
            ThreadPoolExecutor(max_workers=WORKERS) as pool,
        ):
            # probe the first step alone: it decides the cycle (drop back 12 h when the
            # server has not published yet), and every other request depends on it
            first = self._get(client, cycle, "ppts", self.steps[0])
            if first is None:
                cycle = cycle - timedelta(hours=12)
                first = self._get(client, cycle, "ppts", self.steps[0])
            wanted = [
                (param, step)
                for step in self.steps
                for param in PARAMS
                if not (param == "ppts" and step == self.steps[0])
            ]
            fetched = pool.map(lambda w, c=cycle: self._get(client, c, w[0], w[1]), wanted)
            # parse on the main thread (pygrib via temp files), one field at a time
            for (param, step), data in zip(
                [("ppts", self.steps[0]), *wanted], [first, *fetched], strict=True
            ):
                if data is None:
                    continue
                if self.capture_dir is not None:
                    self.capture_dir.mkdir(parents=True, exist_ok=True)
                    (self.capture_dir / f"gwam_{param}_f{step:03d}.grib2.bz2").write_bytes(data)
                try:
                    sampled[(param, step)] = parse_points(data, points)
                except Exception as e:  # one bad file costs its step, never the run
                    print(f"warn: gwam {param} f{step:03d} unreadable: {e!r}", file=sys.stderr)
        return _assemble(points, sampled, cycle)

    def _get(self, client: httpx.Client, cycle: datetime, param: str, step: int) -> bytes | None:
        try:
            resp = client.get(file_url(cycle, param, step))
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or resp.content[:3] != b"BZh":
            return None
        return resp.content


class GwamFixtureSource:
    """Replay captured ``gwam_{param}_fSSS.grib2.bz2`` files; ``valid`` stamped from a
    fixed cycle like GfsFullFixtureSource, so the fixture's real date does not matter."""

    def __init__(self, fixtures_dir: Path, cycle: datetime | None = None) -> None:
        self.fixtures_dir = fixtures_dir
        self.cycle = cycle or datetime(2026, 8, 14, 0, tzinfo=UTC)

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[GwamStep]]:
        sampled: dict[tuple[str, int], list[float | None]] = {}
        for path in sorted(self.fixtures_dir.glob("gwam_*_f*.grib2*")):
            param = path.name.split("_")[1]
            step = int(path.name.split("_f")[1][:3])
            if param in PARAMS:
                sampled[(param, step)] = parse_points(path.read_bytes(), points)
        return _assemble(points, sampled, self.cycle)
