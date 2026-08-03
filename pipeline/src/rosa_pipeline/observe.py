"""Buoy-observation layer: ground truth for the verification harness (roadmap Stage 0).

Mirrors ``fetch.py``: a live source that can capture responses, and a fixture source that
replays them so tests never touch the network. NDBC is the first adapter (public domain);
ISRAMAR/CDIP slot in behind the same ``ObservationSource`` protocol later. ISRAMAR stays
local-validation-only (all-rights-reserved) - it must never be committed or shipped.

Parses the NDBC ``realtime2/<id>.txt`` standard-meteorological file. Wave columns:
    WDIR = wind direction (deg, FROM)    -> wdir_deg
    WSPD = wind speed (m/s)              -> wspd_ms
    WVHT = significant wave height (m)   -> hs_m
    DPD  = dominant (peak) period (s)    -> dpd_s
    APD  = average period (s), i.e. Tm02 -> apd_s   (NOT the model's mean period - see
                                           verify.py: Open-Meteo serves Tm-1,0)
    MWD  = mean wave direction (deg, from)-> mwd_deg
    WTMP = water temperature (degC)      -> wtmp_c
Missing values are the literal "MM". Rows are newest-first; we return oldest-first.

The wind columns sit on the same line as the wave columns and were parsed past until
2026-08-03. They are the only co-located wind+wave ground truth Rosa has: whether a wind
term belongs in the OFFSHORE input (an Open-Meteo Hs bias, fittable from thousands of buoy
hours) or purely in the NEARSHORE transform (fittable only from eyes) is not answerable
without them. See docs/CALIBRATION.md 2026-08-03 and open item 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from .buoys import Buoy

NDBC_REALTIME = "https://www.ndbc.noaa.gov/data/realtime2"


@dataclass(frozen=True, slots=True)
class BuoyObs:
    station: str
    time: datetime  # tz-aware UTC
    hs_m: float | None
    dpd_s: float | None
    apd_s: float | None
    mwd_deg: float | None
    wtmp_c: float | None
    # Tm-1,0 (m-1/m0) measured from the station's own spectrum - not in the standard-met
    # file, filled in by verify.with_energy_period() where spectra are published.
    tm_m10_s: float | None = None
    # co-located wind, same line of the same file (see module docstring)
    wdir_deg: float | None = None  # direction the wind blows FROM
    wspd_ms: float | None = None  # m/s, as NDBC reports it - not kph


def _num(token: str) -> float | None:
    return None if token == "MM" else float(token)


def _csv_num(parts: list[str], i: int) -> float | None:
    """A comma-column value, or None if absent/blank/placeholder."""
    if i >= len(parts) or parts[i] in ("", "-", "MM"):
        return None
    try:
        return float(parts[i])
    except ValueError:
        return None


def parse_ndbc_txt(text: str, station: str) -> list[BuoyObs]:
    """Parse an NDBC standard-met file into observations, oldest-first.

    Rows with no wave height at all (WVHT missing) are still kept - the harness filters;
    a buoy that reports only met is simply unusable for wave scoring, not an error here."""
    obs: list[BuoyObs] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if len(f) < 15:
            continue
        try:
            yr, mo, dy, hr, mn = (int(f[i]) for i in range(5))
            t = datetime(yr, mo, dy, hr, mn, tzinfo=UTC)
        except ValueError:
            continue
        obs.append(
            BuoyObs(
                station=station,
                time=t,
                hs_m=_num(f[8]),
                dpd_s=_num(f[9]),
                apd_s=_num(f[10]),
                mwd_deg=_num(f[11]),
                wtmp_c=_num(f[14]),
                wdir_deg=_num(f[5]),
                wspd_ms=_num(f[6]),
            )
        )
    obs.sort(key=lambda o: o.time)
    return obs


class ObservationSource(Protocol):
    def fetch(self, buoy: Buoy) -> list[BuoyObs]: ...


class NDBCSource:
    def __init__(self, capture_dir: Path | None = None, timeout_s: float = 30.0) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s

    def fetch(self, buoy: Buoy) -> list[BuoyObs]:
        url = f"{NDBC_REALTIME}/{buoy.id}.txt"
        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.get(url)
            resp.raise_for_status()
        text = resp.text
        if self.capture_dir is not None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            (self.capture_dir / f"ndbc_{buoy.id}.txt").write_text(text, encoding="utf-8")
        return parse_ndbc_txt(text, buoy.id)


class NDBCFixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, buoy: Buoy) -> list[BuoyObs]:
        path = self.fixtures_dir / f"ndbc_{buoy.id}.txt"
        return parse_ndbc_txt(path.read_text(encoding="utf-8"), buoy.id)


def parse_isramar_csv(text: str, station: str) -> list[BuoyObs]:
    """Parse a manual-import ISRAMAR csv into observations, oldest-first.

    Columns: ``time_utc, hs_m, period_s, dir_deg[, wtmp_c]`` - blank/`-`/`MM` = missing,
    `#` lines ignored. NOTE: ISRAMAR usually displays *peak* period; it's stored in the
    period slot the harness compares to the model's MEAN wave_period, so expect the same
    peak-vs-mean offset seen at NDBC (a known, documented bias, not an error)."""
    obs: list[BuoyObs] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            t = datetime.fromisoformat(parts[0])
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        obs.append(
            BuoyObs(
                station=station,
                time=t,
                hs_m=_csv_num(parts, 1),
                dpd_s=None,
                apd_s=_csv_num(parts, 2),
                mwd_deg=_csv_num(parts, 3),
                wtmp_c=_csv_num(parts, 4),
            )
        )
    obs.sort(key=lambda o: o.time)
    return obs


class ISRAMARLocalSource:
    """ISRAMAR truth, MANUAL-IMPORT ONLY - Rosa never fetches ISRAMAR.

    ISRAMAR data is all-rights-reserved and its download endpoints are robots-disallowed, so
    there is no automated fetch here by design (CLAUDE.md red line: manual validation during
    calibration; partnership before any integration). The operator reads the ISRAMAR real-time
    display and pastes rows into ``data/verify/isramar/<station>.csv`` - gitignored, never
    shipped, never committed. This just reads that local file."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def fetch(self, buoy: Buoy) -> list[BuoyObs]:
        path = self.root / f"{buoy.id}.csv"
        if not path.exists():
            return []
        return parse_isramar_csv(path.read_text(encoding="utf-8"), buoy.id)
