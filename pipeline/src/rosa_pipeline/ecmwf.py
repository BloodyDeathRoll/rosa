"""ECMWF open-data wave member (Stage 3b) - index-driven byte-range GRIB fetches.

Live-verified 2026-07-23 (docs/rosa-stage3-plan.md): the IFS 0p25 ``wave`` stream ships a
newline-JSON ``.index`` per step with ``_offset``/``_length`` per parameter, so we fetch ONLY
the messages we need via HTTP Range requests. Our params (swh/mwd/mwp/pp1d/mp2 + the six
period-banded heights h1012..h2530) sit nearly contiguous in the file - one coalesced range
of ~10 MB per step (the fields are global; ECMWF offers no regional subsetting). pygrib
identifies every message by shortName, masked over land, on a regular 0.25 deg grid
(lat 90..-90, lon -180..179.75).

Cycle policy: only 00z/12z run the full 240 h wave horizon (06z/18z stop at 90 h - skipped);
a cycle is fully published ~8 h after cycle time, so we lag 9 h and fall back one cycle on a
first-step miss. Steps are 6-hourly: the spectral-shape quantities this member feeds
(consistency, band heights) vary slowly, and it halves the download (~400 MB/cycle).

License: ECMWF open data is CC-BY-4.0 - attributed in the published payload (roadmap §8).
"""

from __future__ import annotations

import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from .geo import dlon180
from .models import SpectralSea

BASE_URL = "https://data.ecmwf.int/forecasts"
SPECTRAL_PARAMS: tuple[str, ...] = ("swh", "mwd", "mwp", "pp1d", "mp2")
BAND_PARAMS: tuple[str, ...] = ("h1012", "h1214", "h1417", "h1721", "h2125", "h2530")
DEFAULT_PARAMS: tuple[str, ...] = SPECTRAL_PARAMS + BAND_PARAMS
# buoy-archive member: what the lead-time scorecard scores (hs, peak period ↔ DPD, dir)
# + the consistency-proxy inputs (mwp/mp2), so model-vs-measured-spectra correlation
# matures with the archive (Stage 3b acceptance)
ARCHIVE_PARAMS: tuple[str, ...] = ("swh", "mwd", "pp1d", "mwp", "mp2")
# 6-hourly to the full 240 h horizon (41 steps); native output is 3-hourly to 144 h
DEFAULT_STEPS: tuple[int, ...] = tuple(range(0, 241, 6))
CYCLE_HOURS: tuple[int, ...] = (0, 12)  # only these run the wave stream to 240 h
# pick_cycle drops its date-rollover branch on the strength of this: with 00z in
# the tuple, "the latest cycle hour at or before ready.hour" always has an answer.
assert CYCLE_HOURS[0] == 0, "pick_cycle assumes a 00z cycle; restore its rollover branch"
CYCLE_LAG_H = 9.0  # a cycle is fully on data.ecmwf.int ~8 h after cycle time
NEAREST_MAX_DEG = 0.6  # nearest wet grid node must be within this of the point
# coalesce param ranges when the skipped bytes (the ~0.5 MB wmb message between our
# bands and periods) cost less than a second request round-trip
RANGE_GAP_MAX = 600_000
GRID_STEP_DEG = 0.25
# concurrent step downloads. A step is one index GET plus the coalesced range GETs of a
# global 0.25 deg field - ~9.3 MB and ~2 s each off a workstation link (measured
# 2026-08-29; the VM's is slower, so its serial cost is the larger one). This source runs
# TWICE a cycle - the spectral member of `run --all` and the Stage-3b archive arm - so
# 41 steps are paid for twice. Four at a time caps the bytes in flight at ~37 MB, which
# is what decides the worker count here: forty 9 MB fields at once is most of a
# sub-1-GB VM.
WORKERS = 4


def pick_cycle(now: datetime) -> datetime:
    """Latest 00/12Z cycle whose wave files should be fully published."""
    ready = now - timedelta(hours=CYCLE_LAG_H)
    # no date-rollover case to handle: subtracting the lag has already carried
    # `ready` back across midnight, and 00z is always a candidate (the assert on
    # CYCLE_HOURS pins that), so the generator is never empty.
    cycle_hour = max(h for h in CYCLE_HOURS if h <= ready.hour)
    return ready.replace(hour=cycle_hour, minute=0, second=0, microsecond=0)


def _stem(cycle: datetime, step: int) -> str:
    return (
        f"{BASE_URL}/{cycle:%Y%m%d}/{cycle:%H}z/ifs/0p25/wave/{cycle:%Y%m%d%H%M%S}-{step}h-wave-fc"
    )


def index_url(cycle: datetime, step: int) -> str:
    return _stem(cycle, step) + ".index"


def data_url(cycle: datetime, step: int) -> str:
    return _stem(cycle, step) + ".grib2"


def parse_index(text: str, params: tuple[str, ...]) -> list[tuple[int, int]]:
    """(offset, length) of each wanted param's GRIB message, in file order."""
    spans: list[tuple[int, int]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if rec.get("param") in params:
            spans.append((int(rec["_offset"]), int(rec["_length"])))
    return sorted(spans)


def coalesce(spans: list[tuple[int, int]], max_gap: int = RANGE_GAP_MAX) -> list[tuple[int, int]]:
    """Merge (offset, length) spans into (start, end-inclusive) byte ranges, bridging
    gaps up to ``max_gap`` - fewer requests at the cost of a few unwanted bytes."""
    if not spans:
        return []
    ranges: list[tuple[int, int]] = []
    start, end = spans[0][0], spans[0][0] + spans[0][1] - 1
    for offset, length in spans[1:]:
        if offset - (end + 1) <= max_gap:
            end = max(end, offset + length - 1)
        else:
            ranges.append((start, end))
            start, end = offset, offset + length - 1
    ranges.append((start, end))
    return ranges


def _nearest_wet(vals, lats, lons, lat: float, lon: float) -> float | None:
    """Value at the nearest unmasked node within NEAREST_MAX_DEG, else None.

    The grid is regular global 0.25 deg, so we search a small window around the direct
    index instead of scanning 1M nodes per (message, point) - this runs 41 steps x 11
    params x every point on a 1-core VM."""
    import numpy as np

    lon = ((lon + 180.0) % 360.0) - 180.0  # grid longitudes run -180..179.75
    # the full-scan fallback below keeps the seam SAFE (nothing is clipped), but the
    # distance must still wrap or a cell one step across the date line measures ~360 deg
    r = int(NEAREST_MAX_DEG / GRID_STEP_DEG) + 1
    i0 = int(np.argmin(np.abs(lats[:, 0] - lat)))
    j0 = int(np.argmin(np.abs(lons[0, :] - lon)))
    n_i, n_j = vals.shape
    if j0 - r < 0 or j0 + r + 1 > n_j:
        i_sl, j_sl = slice(0, n_i), slice(0, n_j)  # date-line seam - fall back to full scan
    else:
        i_sl = slice(max(0, i0 - r), min(n_i, i0 + r + 1))
        j_sl = slice(j0 - r, j0 + r + 1)
    v = vals[i_sl, j_sl]
    d2 = (lats[i_sl, j_sl] - lat) ** 2 + dlon180(lons[i_sl, j_sl], lon) ** 2
    if hasattr(v, "mask") and v.mask is not np.ma.nomask:
        d2 = np.where(v.mask, np.inf, d2)
    idx = np.unravel_index(np.argmin(d2), d2.shape)
    if d2[idx] > NEAREST_MAX_DEG**2:
        return None
    return round(float(v[idx]), 3)  # strip float32 noise for JSON


def parse_grib_points(
    grib_bytes: bytes,
    points: list[tuple[float, float]],
    valid: datetime,
    params: tuple[str, ...] = DEFAULT_PARAMS,
) -> list[SpectralSea | None]:
    """Sample every wanted message at each point's nearest wet node.

    A param absent from the bytes (or with no wet node in reach) is simply None for that
    point; a point with NO sampled params at all returns None. Messages are sampled one at
    a time so the 1 GB VM never holds all 11 global fields at once."""
    import pygrib

    vals_by_point: list[dict[str, float]] = [{} for _ in points]
    with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
        tf.write(grib_bytes)
        tf.flush()
        grbs = pygrib.open(tf.name)
        seen: set[str] = set()
        for m in grbs:
            name = m.shortName
            if name not in params or name in seen:
                continue
            seen.add(name)
            vals = m.values
            lats, lons = m.latlons()
            for pi, (lat, lon) in enumerate(points):
                v = _nearest_wet(vals, lats, lons, lat, lon)
                if v is not None:
                    vals_by_point[pi][name] = v
        grbs.close()

    out: list[SpectralSea | None] = []
    for d in vals_by_point:
        if not d:
            out.append(None)
            continue
        out.append(
            SpectralSea(
                time=valid,
                swh=d.get("swh"),
                mwd=d.get("mwd"),
                mwp=d.get("mwp"),
                pp1d=d.get("pp1d"),
                mp2=d.get("mp2"),
                bands=tuple((k, d[k]) for k in BAND_PARAMS if k in d),
            )
        )
    return out


class EcmwfWaves(Protocol):
    """Per-point ECMWF spectral-lite series."""

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[SpectralSea]]: ...


class EcmwfSource:
    """Live fetch: per step, GET the .index, coalesce our params into byte ranges,
    range-GET the .grib2, sample every point from the same download."""

    def __init__(
        self,
        capture_dir: Path | None = None,
        params: tuple[str, ...] = DEFAULT_PARAMS,
        steps: tuple[int, ...] = DEFAULT_STEPS,
        timeout_s: float = 120.0,
    ) -> None:
        self.capture_dir = capture_dir
        self.params = params
        self.steps = steps
        self.timeout_s = timeout_s

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[SpectralSea]]:
        series: list[list[SpectralSea]] = [[] for _ in points]
        if not points:
            return series
        cycle = pick_cycle(datetime.now(UTC))
        with (
            httpx.Client(timeout=self.timeout_s) as client,
            ThreadPoolExecutor(max_workers=WORKERS) as pool,
        ):
            # the first step is fetched alone: it decides the cycle, and every other step
            # depends on that answer
            first = self._get_step(client, cycle, self.steps[0])
            if first is None:
                # cycle not fully published yet - drop back one and retry
                cycle = cycle - timedelta(hours=12)
                first = self._get_step(client, cycle, self.steps[0])
            self._absorb(series, points, cycle, self.steps[0], first)
            # the rest fan out WORKERS at a time. Chunked rather than mapped over all 40:
            # ThreadPoolExecutor.map submits everything immediately, and forty 9 MB global
            # fields held at once is most of this VM's memory. Absorbed in step order, so
            # each point's series stays ascending in time however the downloads finish.
            rest = self.steps[1:]
            for i in range(0, len(rest), WORKERS):
                chunk = rest[i : i + WORKERS]
                got = pool.map(lambda s, c=cycle: self._get_step(client, c, s), chunk)
                for step, data in zip(chunk, got, strict=True):
                    self._absorb(series, points, cycle, step, data)
        return series

    def _absorb(
        self,
        series: list[list[SpectralSea]],
        points: list[tuple[float, float]],
        cycle: datetime,
        step: int,
        data: bytes | None,
    ) -> None:
        """Parse one downloaded step into the per-point series. Called on the main thread
        only - parse_grib_points goes through pygrib and a temp file."""
        if data is None:
            return
        if self.capture_dir is not None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            (self.capture_dir / f"ecmwf_f{step:03d}.grib2").write_bytes(data)
        valid = cycle + timedelta(hours=step)
        for i, sp in enumerate(parse_grib_points(data, points, valid, self.params)):
            if sp is not None:
                series[i].append(sp)

    def _get_step(self, client: httpx.Client, cycle: datetime, step: int) -> bytes | None:
        try:
            idx = client.get(index_url(cycle, step))
            if idx.status_code != 200:
                return None
            ranges = coalesce(parse_index(idx.text, self.params))
            if not ranges:
                return None
            parts: list[bytes] = []
            for start, end in ranges:
                resp = client.get(data_url(cycle, step), headers={"Range": f"bytes={start}-{end}"})
                if resp.status_code not in (200, 206):
                    return None
                parts.append(resp.content)
            return b"".join(parts)
        except httpx.HTTPError:
            return None


class EcmwfFixtureSource:
    """Replay captured per-step gribs (tests / offline). ``valid`` is stamped from a
    fixed cycle for determinism."""

    def __init__(
        self,
        fixtures_dir: Path,
        cycle: datetime | None = None,
        params: tuple[str, ...] = DEFAULT_PARAMS,
    ) -> None:
        self.fixtures_dir = fixtures_dir
        self.cycle = cycle or datetime(2026, 7, 22, 0, tzinfo=UTC)
        self.params = params

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[SpectralSea]]:
        series: list[list[SpectralSea]] = [[] for _ in points]
        for path in sorted(self.fixtures_dir.glob("ecmwf_f*.grib2")):
            step = int(path.name.split("_f")[1][:3])
            valid = self.cycle + timedelta(hours=step)
            data = path.read_bytes()
            for i, sp in enumerate(parse_grib_points(data, points, valid, self.params)):
                if sp is not None:
                    series[i].append(sp)
        return series
