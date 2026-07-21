"""Buoy-observation layer: ground truth for the verification harness (roadmap Stage 0).

Mirrors ``fetch.py``: a live source that can capture responses, and a fixture source that
replays them so tests never touch the network. NDBC is the first adapter (public domain);
ISRAMAR/CDIP slot in behind the same ``ObservationSource`` protocol later. ISRAMAR stays
local-validation-only (all-rights-reserved) — it must never be committed or shipped.

Parses the NDBC ``realtime2/<id>.txt`` standard-meteorological file. Wave columns:
    WVHT = significant wave height (m)   -> hs_m
    DPD  = dominant (peak) period (s)    -> dpd_s
    APD  = average period (s)            -> apd_s   (compare to model MEAN wave_period)
    MWD  = mean wave direction (deg, from)-> mwd_deg
    WTMP = water temperature (degC)      -> wtmp_c
Missing values are the literal "MM". Rows are newest-first; we return oldest-first.
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


def _num(token: str) -> float | None:
    return None if token == "MM" else float(token)


def parse_ndbc_txt(text: str, station: str) -> list[BuoyObs]:
    """Parse an NDBC standard-met file into observations, oldest-first.

    Rows with no wave height at all (WVHT missing) are still kept — the harness filters;
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
