"""Forecast source layer: Open-Meteo v1, behind an interface so the raw-grid migration
(NOMADS/ECMWF/CMEMS) only touches this module.

OpenMeteoSource fetches live and can capture the raw responses to disk;
FixtureSource replays a captured file so tests and offline runs never touch the network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 16

MARINE_HOURLY = [
    "wave_height",
    "wave_direction",
    "wave_period",
    "wind_wave_height",
    "wind_wave_direction",
    "wind_wave_period",
    "swell_wave_height",
    "swell_wave_direction",
    "swell_wave_period",
    "secondary_swell_wave_height",
    "secondary_swell_wave_direction",
    "secondary_swell_wave_period",
    "tertiary_swell_wave_height",
    "tertiary_swell_wave_direction",
    "tertiary_swell_wave_period",
    "sea_surface_temperature",
]
WEATHER_HOURLY = ["wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"]


@dataclass(frozen=True, slots=True)
class RawForecast:
    fetched_at: str  # ISO-8601 UTC
    marine: dict
    weather: dict


class ForecastSource(Protocol):
    def fetch(self, lat: float, lon: float) -> RawForecast: ...


def fixture_key(lat: float, lon: float) -> str:
    return f"{lat:g}_{lon:g}"


class OpenMeteoSource:
    def __init__(self, capture_dir: Path | None = None, timeout_s: float = 30.0) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s

    def fetch(self, lat: float, lon: float) -> RawForecast:
        common = {"latitude": lat, "longitude": lon, "forecast_days": FORECAST_DAYS}
        with httpx.Client(timeout=self.timeout_s) as client:
            marine = client.get(MARINE_URL, params={**common, "hourly": ",".join(MARINE_HOURLY)})
            marine.raise_for_status()
            weather = client.get(WEATHER_URL, params={**common, "hourly": ",".join(WEATHER_HOURLY)})
            weather.raise_for_status()
        raw = RawForecast(
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
            marine=marine.json(),
            weather=weather.json(),
        )
        if self.capture_dir is not None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            path = self.capture_dir / f"{fixture_key(lat, lon)}.json"
            path.write_text(
                json.dumps(
                    {"fetched_at": raw.fetched_at, "marine": raw.marine, "weather": raw.weather}
                ),
                encoding="utf-8",
            )
        return raw


class FixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, lat: float, lon: float) -> RawForecast:
        path = self.fixtures_dir / f"{fixture_key(lat, lon)}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return RawForecast(
            fetched_at=data["fetched_at"], marine=data["marine"], weather=data["weather"]
        )
