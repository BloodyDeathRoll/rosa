"""Forecast source layer: Open-Meteo v1, behind an interface so the raw-grid migration
(NOMADS/ECMWF/CMEMS) only touches this module.

OpenMeteoSource fetches live and can capture the raw responses to disk;
FixtureSource replays a captured file so tests and offline runs never touch the network.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_DAYS = 16
# Open-Meteo returns data from 00:00 UTC; a spot west of UTC would open on a "today"
# missing everything before its local midnight (Costa Rica lost 00:00-18:00). One past
# UTC day covers local midnight at any longitude; publish trims per spot to local today.
PAST_DAYS = 1
# Open-Meteo caps calls at 600/min PER API HOST, billed by weight
# (max(1, vars/10) x max(1, days/14) per location). The marine host carries both the marine
# request and the ensemble, and a model multiplies the series count, so the arithmetic at
# 16+1 days is: marine 20 vars x 3 models = 60 -> 6.0, x 17/14 = 7.3; ensemble 3 vars x 4
# models = 12 -> 1.2, x 17/14 = 1.5. Together ~8.8/point, so 600 / 8.8 ~= 68 points fit in one
# minute bucket. Batch under that and pause past a minute boundary between batches so each
# lands in a fresh window; keeps the whole coast in-quota.
#
# Was 90 while MARINE_MODELS held two models (~6.4/point, 95 points). Adding gwam for the peak
# period on 2026-08-02 pushed 90 points over the bucket and a live `run --all` took two 429s on
# the ensemble request - which degrades honestly (no confidence ensemble) rather than failing,
# so it would have rotted quietly on the VM cron. Re-derive this whenever MARINE_MODELS or
# MARINE_HOURLY changes.
MARINE_BATCH_SIZE = 65
# best_match is Open-Meteo's per-location blend but only reaches ~9 days; NOAA GFS-Wave
# runs the full 16. Request both - extract prefers best_match, falls back to GFS-Wave for
# the extended tail (per-hour, so each hour stays internally consistent).
#
# gwam rides along as the PEAK-PERIOD source only (see TP_MODEL below). Outside Europe
# best_match resolves to meteofrance_wave, which publishes no peak period at all, so Tp
# was null across 7 of 9 regions and `rideability_period` silently fell back to the mean
# everywhere but Israel and Portugal (measured 2026-08-02). It is one extra model on the
# SAME request, not an extra request, so it costs nothing against the rate limiter.
MARINE_MODELS = ["best_match", "ncep_gfswave016", "gwam"]
# Peak period is taken from this model wherever the primary chain publishes none. It is a
# deliberate cross-model join and the only one in the pipeline: Tp feeds `period_rideability`
# and the display, never the dispersion march or `period_score`, so a Tp from a different
# model cannot desynchronise the physics. Open-Meteo already does exactly this inside
# best_match over Europe - at Hilton and Supertubos its Hs is meteofrance_wave's while its
# Tp is gwam's to the centisecond - so this makes the rest of the world consistent with what
# Europe was already being served. Coverage runs to ~7.3 days; past that Tp is null again
# and the mean-period fallback stands, as it did everywhere before.
TP_MODEL = "gwam"
TP_SUFFIX = "_peak_period"
# independent members for the confidence ensemble (Stage 1) - fetched in a separate,
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
    "wave_peak_period",
    "swell_wave_peak_period",
    "wind_wave_peak_period",
    "secondary_swell_wave_height",
    "secondary_swell_wave_direction",
    "secondary_swell_wave_period",
    "tertiary_swell_wave_height",
    "tertiary_swell_wave_direction",
    "tertiary_swell_wave_period",
    "sea_surface_temperature",
    # tide / total water level (Stage 2D) - from MeteoFrance SMOC, so it returns under the
    # best_match suffix only (null under the wave model); _merge_models picks it up for days 0-9
    "sea_level_height_msl",
]
WEATHER_HOURLY = [
    "wind_speed_10m",
    "wind_direction_10m",
    "wind_gusts_10m",
    "pressure_msl",
    "temperature_2m",
]


# verification harness samples the total sea-state at a buoy - no models suffix, so the
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
    def __init__(
        self,
        capture_dir: Path | None = None,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        sleep_between_batches_s: float = 60.0,
    ) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s
        self._transport = transport  # injectable for offline tests
        self.sleep_between_batches_s = sleep_between_batches_s  # 0 to disable (tests)

    def fetch(self, lat: float, lon: float) -> RawForecast:
        return self.fetch_many([(lat, lon)])[0]

    def fetch_many(self, coords: list[tuple[float, float]]) -> list[RawForecast]:
        """Fetch every point in batches of <=MARINE_BATCH_SIZE, each batch being ONE marine +
        ONE weather + ONE ensemble request. Open-Meteo accepts comma-separated coordinates and
        returns a per-location array (a single object for one coord), so a batch is 3 requests.
        Batches beyond the first pause past a minute boundary to stay under the marine host's
        600 calls/min cap (see MARINE_BATCH_SIZE). The ensemble request (independent members,
        Hs/period/dir only) feeds Stage-1 confidence, and is the one request allowed to fail:
        see the 429 note below."""
        if not coords:
            return []
        out: list[RawForecast] = []
        batches = [
            coords[i : i + MARINE_BATCH_SIZE] for i in range(0, len(coords), MARINE_BATCH_SIZE)
        ]
        for bi, batch in enumerate(batches):
            if bi > 0 and self.sleep_between_batches_s > 0:
                print(
                    f"info: open-meteo batch {bi + 1}/{len(batches)} - pausing "
                    f"{self.sleep_between_batches_s:g}s for the marine-host minute cap",
                    file=sys.stderr,
                )
                time.sleep(self.sleep_between_batches_s)
            out.extend(self._fetch_batch(batch))
        return out

    def _fetch_batch(self, coords: list[tuple[float, float]]) -> list[RawForecast]:
        common = {
            "latitude": ",".join(f"{lat:g}" for lat, _ in coords),
            "longitude": ",".join(f"{lon:g}" for _, lon in coords),
            "forecast_days": FORECAST_DAYS,
            "past_days": PAST_DAYS,
        }
        with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
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
            ensemble: httpx.Response | None = client.get(
                MARINE_URL,
                params={
                    **common,
                    "hourly": ",".join(ENSEMBLE_HOURLY),
                    "models": ",".join(MARINE_ENSEMBLE_MODELS),
                },
            )
            # Open-Meteo bills call weight (locations x variables x days) against hourly and
            # daily buckets, so a big run can drain them. The ensemble is the last and most
            # expendable of the three requests: on 429 drop it and let confidence fall back to
            # the horizon proxy, rather than throwing away the marine + weather data already
            # fetched and publishing nothing at all.
            if ensemble.status_code == 429:
                print(
                    "warn: open-meteo 429 on the ensemble request - publishing without the "
                    "confidence ensemble (horizon proxy only)",
                    file=sys.stderr,
                )
                ensemble = None
            else:
                ensemble.raise_for_status()
        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        mj, wj = marine.json(), weather.json()
        marine_list = mj if isinstance(mj, list) else [mj]
        weather_list = wj if isinstance(wj, list) else [wj]
        if ensemble is None:
            ensemble_list: list[dict | None] = [None] * len(coords)
        else:
            ej = ensemble.json()
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
