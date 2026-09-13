"""Coastal wind-station registry: ground truth for the wind the forecast SHOWS (2026-08-29).

Every anemometer in the buoy registry sits offshore, and against those the model runs hot
(+0.3 to +1.6 m/s at 0-1 d, all 15 stations, CALIBRATION.md 2026-08-29). The wind a surfer
reads off the app is sampled 5.5 km out, which at every Israeli spot is the SAME weather
grid cell as the beach - a cell that is part land, part sea, and damped accordingly. No
buoy can measure that gap; a station on the coast can. This registry is those stations:

* ``metar`` - aviation METARs from NOAA's aviationweather.gov (public domain, no key):
  every reporting airfield within 25 km of a Rosa spot, ``data/stations/metar.yaml``.
  Regenerate with ``rosa-pipeline stations --discover metar`` after a spot-DB change.
  Discovery sees only airfields reporting at that hour, so it keeps a registered station
  missing from the snapshot while a spot is still in reach (since 2026-09-13).
* ``ims`` - the Israel Meteorological Service's 10-minute stations (open data, free
  token by mail from ims@ims.gov.il, ``IMS_API_TOKEN`` in the VM's ``~/rosa/.env``).
  The coastal ones stand on the beach itself, which no airport does.

A station is a wind-only truth point: the archive stores the model's 10 m wind at its
coordinate every cycle (``data/verify/stations/<id>.jsonl``), and ``verify --stations
--archive`` scores it by lead against the station's own readings - the same lead-time
harness the buoys use, wind columns only. Surfline's answer to the same problem is ~500
stations of its own; this is the free-data version of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .buoys import haversine_km


@dataclass(frozen=True, slots=True)
class Station:
    id: str  # ICAO code for metar, the numeric Envista station id (as text) for ims
    name: str
    lat: float
    lon: float
    source: str  # "metar" | "ims"


def load_stations(stations_dir: Path) -> dict[str, Station]:
    """Every ``*.yaml`` under ``stations_dir``; a missing directory is simply no stations
    (the archive and verify arms then skip, silently - a fleet without stations is the
    state every region outside METAR range is in)."""
    stations: dict[str, Station] = {}
    if not stations_dir.is_dir():
        return stations
    for path in sorted(stations_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for raw in data.get("stations") or []:
            st = Station(
                id=str(raw["id"]),
                name=str(raw["name"]),
                lat=float(raw["lat"]),
                lon=float(raw["lon"]),
                source=str(raw.get("source", "metar")),
            )
            if st.id in stations:
                raise ValueError(f"duplicate station id {st.id!r} in {path}")
            stations[st.id] = st
    return stations


def nearest_station(
    lat: float, lon: float, stations: dict[str, Station], *, radius_km: float = 25.0
) -> tuple[Station, float] | None:
    """The closest station within ``radius_km``, with its distance, or None."""
    best: tuple[Station, float] | None = None
    for st in stations.values():
        d = haversine_km(lat, lon, st.lat, st.lon)
        if d <= radius_km and (best is None or d < best[1]):
            best = (st, d)
    return best
