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
# best_match is Open-Meteo's per-location blend but only reaches ~9 days; NOAA GFS-Wave
# runs the full 16. Request both — extract prefers best_match, falls back to GFS-Wave for
# the extended tail (per-hour, so each hour stays internally consistent).
MARINE_MODELS = ["best_match", "ncep_gfswave016"]
# independent members for the confidence ensemble (Stage 1) — fetched in a separate,
# lightweight request (Hs/period/dir only) so the primary path + fixtures stay untouched.
# best_match is a blend, so it's excluded here; these disagree independently.
MARINE_ENSEMBLE_MODELS = ["ncep_gfswave016", "ewam", "gwam", "meteofrance_wave"]
ENSEMBLE_HOURLY = ["wave_height", "wave_period", "wave_direction"]

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
WEATHER_HOURLY = [
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "pressure_msl",
    "temperature_2m",
]


# verification harness samples the total sea-state at a buoy — no models suffix, so the
# hourly keys stay plain (wave_height/period/direction), tiny payload
MARINE_WAVE_FIELDS = ["wave_height", "wave_period", "wave_direction"]


def fetch_marine_waves(lat: float, lon: float, *, timeout_s: float = 30.0) -> dict:
    """Total sea-state marine forecast at one point, for buoy validation (roadmap Stage 0).
    Single best_match model (plain hourly keys); caller handles any capture/replay."""
    with httpx.Client(timeout=timeout_s) as client:
        resp = client.get(
            MARINE_URL,
            params={
                "latitude": f"{lat:g}",
                "longitude": f"{lon:g}",
                "hourly": ",".join(MARINE_WAVE_FIELDS),
                "forecast_days": FORECAST_DAYS,
            },
        )
        resp.raise_for_status()
    return resp.json()


@dataclass(frozen=True, slots=True)
class RawForecast:
    fetched_at: str  # ISO-8601 UTC
    marine: dict
    weather: dict
    ensemble: dict | None = None  # multi-model Hs/period/dir for confidence (Stage 1)


class ForecastSource(Protocol):
    def fetch(self, lat: float, lon: float) -> RawForecast: ...

    def fetch_many(self, coords: list[tuple[float, float]]) -> list[RawForecast]: ...


def fixture_key(lat: float, lon: float) -> str:
    return f"{lat:g}_{lon:g}"


class OpenMeteoSource:
    def __init__(self, capture_dir: Path | None = None, timeout_s: float = 30.0) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s

    def fetch(self, lat: float, lon: float) -> RawForecast:
        return self.fetch_many([(lat, lon)])[0]

    def fetch_many(self, coords: list[tuple[float, float]]) -> list[RawForecast]:
        """Fetch every point in ONE marine + ONE weather + ONE ensemble request. Open-Meteo
        accepts comma-separated coordinates and returns a per-location array (a single object
        for one coord), so a whole coast is 3 requests — no per-spot throttling. The ensemble
        request (independent members, Hs/period/dir only) feeds Stage-1 confidence."""
        if not coords:
            return []
        common = {
            "latitude": ",".join(f"{lat:g}" for lat, _ in coords),
            "longitude": ",".join(f"{lon:g}" for _, lon in coords),
            "forecast_days": FORECAST_DAYS,
        }
        with httpx.Client(timeout=self.timeout_s) as client:
            marine = client.get(
                MARINE_URL,
                params={
                    **common,
                    "hourly": ",".join(MARINE_HOURLY),
                    "models": ",".join(MARINE_MODELS),
                },
            )
            marine.raise_for_status()
            weather = client.get(WEATHER_URL, params={**common, "hourly": ",".join(WEATHER_HOURLY)})
            weather.raise_for_status()
            ensemble = client.get(
                MARINE_URL,
                params={
                    **common,
                    "hourly": ",".join(ENSEMBLE_HOURLY),
                    "models": ",".join(MARINE_ENSEMBLE_MODELS),
                },
            )
            ensemble.raise_for_status()
        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        mj, wj, ej = marine.json(), weather.json(), ensemble.json()
        marine_list = mj if isinstance(mj, list) else [mj]
        weather_list = wj if isinstance(wj, list) else [wj]
        ensemble_list = ej if isinstance(ej, list) else [ej]
        out: list[RawForecast] = []
        for (lat, lon), m, w, e in zip(
            coords, marine_list, weather_list, ensemble_list, strict=True
        ):
            raw = RawForecast(fetched_at=fetched_at, marine=m, weather=w, ensemble=e)
            if self.capture_dir is not None:
                self.capture_dir.mkdir(parents=True, exist_ok=True)
                (self.capture_dir / f"{fixture_key(lat, lon)}.json").write_text(
                    json.dumps(
                        {
                            "fetched_at": raw.fetched_at,
                            "marine": raw.marine,
                            "weather": raw.weather,
                            "ensemble": raw.ensemble,
                        }
                    ),
                    encoding="utf-8",
                )
            out.append(raw)
        return out


class FixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, lat: float, lon: float) -> RawForecast:
        path = self.fixtures_dir / f"{fixture_key(lat, lon)}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return RawForecast(
            fetched_at=data["fetched_at"],
            marine=data["marine"],
            weather=data["weather"],
            ensemble=data.get("ensemble"),  # absent in captures made before Stage 1
        )

    def fetch_many(self, coords: list[tuple[float, float]]) -> list[RawForecast]:
        return [self.fetch(lat, lon) for lat, lon in coords]
