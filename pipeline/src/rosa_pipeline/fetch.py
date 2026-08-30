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
# 16+1 days is: marine 17 vars x 3 models = 51 -> 5.1, x 17/14 = 6.2; ensemble 3 vars x 4
# models = 12 -> 1.2, x 17/14 = 1.5. Together ~7.7/point, so 600 / 7.7 ~= 77 points fit in one
# minute bucket. Batch under that and pause past a minute boundary between batches so each
# lands in a fresh window; keeps the whole coast in-quota.
#
# Was 20 marine vars (~8.8/point, 68 points) until the three unread total-sea fields came out
# on 2026-08-16 - see MARINE_HOURLY. The batch size deliberately stays at 65: the headroom is
# the point, and raising it is a live-behaviour change that wants its own live run.
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

# The TOTAL sea's direction / mean period / peak period are NOT here, deliberately.
# `extract_hours` reads only wave_height (the horizon null-sentinel and `total_hs_m` for
# closure), sea_surface_temperature, sea_level_height_msl and the four PARTITION families -
# it has no use for the combined bearing or period, and the transform combines partitions by
# wave field rather than off a total. They were requested and dropped: 3 of 20 variables x 3
# MARINE_MODELS = 9 of the 60 series this request pays for, on the host that carries both the
# marine and the ensemble call (see MARINE_BATCH_SIZE). Verified as a no-op by publishing the
# committed fixture with those three families deleted: byte-identical payload.
# `verify.parse_marine_waves` DOES read all three - off MARINE_WAVE_FIELDS below, which is a
# separate three-variable request and is unaffected.
MARINE_HOURLY = [
    "wave_height",
    "wind_wave_height",
    "wind_wave_direction",
    "wind_wave_period",
    "swell_wave_height",
    "swell_wave_direction",
    "swell_wave_period",
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
# The 10 m wind model. No `models` param = Open-Meteo's best_match, which over Israel
# and Europe resolves to ICON. Switched to GFS on 2026-08-30 (CALIBRATION.md): the
# ~13 km ICON coastal cell damps the beach wind - Zvulun 06:00 read 3.4 kn from ICON,
# 8.3 kn from GFS, and the beach had ~9 kn (eyes). Surfline's wind is raw GFS. One
# model name, so the hourly keys stay plain (a single model is served unsuffixed).
# ICON is still fetched at the coastal stations as the A/B member (WEATHER_AB_MODEL,
# archive key "<station>.icon"); nothing is decided from one morning.
WEATHER_MODEL = "gfs_seamless"
WEATHER_AB_MODEL = "icon_seamless"


# verification harness samples the total sea-state at a buoy - no models suffix, so the
# hourly keys stay plain (wave_height/period/direction), tiny payload
MARINE_WAVE_FIELDS = ["wave_height", "wave_period", "wave_direction"]


# Transient server-side failures worth a second look. A single one of these used to
# kill a whole cycle: a 503 on the last of five weather batches sank the 2026-08-16
# 08:20Z run after four minutes of successful paced fetching.
RETRY_STATUS = frozenset({500, 502, 503, 504})

# Open-Meteo names the bucket that tripped in the 429 body. ONLY the minutely cap is
# worth waiting out - it reopens by itself inside a minute. The hourly and daily buckets
# do not, so waiting on them just burns cycle wall-clock in front of a failure
# `rosa_pipeline.quota` already handles. A 429 we cannot positively identify as the
# minutely cap is therefore not retried.
_MINUTE_LIMIT_MARKER = "minutely api request limit"
_MINUTE_RETRY_WAIT_S = 65.0


def _retry_wait_s(resp: httpx.Response, attempt: int) -> float | None:
    """Seconds to wait before retrying this response, or None if it is not retryable."""
    if resp.status_code in RETRY_STATUS:
        return 10.0 * (attempt + 1)
    if resp.status_code == 429:
        try:
            reason = str(resp.json().get("reason", ""))
        except Exception:  # a non-JSON 429 is simply unclassifiable
            return None
        return _MINUTE_RETRY_WAIT_S if _MINUTE_LIMIT_MARKER in reason.lower() else None
    return None


def retrying_get(
    client: httpx.Client, url: str, params: dict, *, retry_429: bool = False
) -> httpx.Response:
    """One GET with bounded retries on transport errors and transient HTTP failures.

    A fleet run spans minutes of network exposure, and one transient TLS handshake
    timeout used to kill a whole run - four consecutive fleet captures died that way
    on 2026-08-15 while single requests succeeded in 0.3 s, and the same class of
    failure could sink the ESSENTIAL archive step on the VM.

    5xx is retried for every caller (2026-08-16: a lone 503 on the last of five weather
    batches killed a cycle). 429 is retried only when `retry_429` is set - i.e. on the
    two ESSENTIAL requests - and then only for the minutely cap, which clears by itself.
    An hourly- or daily-bucket 429 is never retried: `rosa_pipeline.quota` is the
    designed handler and those buckets do not reopen in time to help. The expendable
    ensemble request leaves `retry_429` off so its documented degrade-to-horizon-proxy
    path stays immediate.

    Exhausted HTTP retries return the last response, so each caller's own handling
    (the ensemble-429 degrade, raise_for_status) stays authoritative."""
    last_exc: Exception | None = None
    last_resp: httpx.Response | None = None
    for attempt in range(3):
        try:
            resp = client.get(url, params=params)
        except httpx.TransportError as e:
            last_exc = e
            if attempt < 2:
                print(
                    f"warn: open-meteo transport error ({e!r}), retry {attempt + 1}/2",
                    file=sys.stderr,
                )
                time.sleep(10.0 * (attempt + 1))
            continue
        if resp.status_code == 429 and not retry_429:
            return resp
        wait_s = _retry_wait_s(resp, attempt)
        if wait_s is None:
            return resp
        last_resp, last_exc = resp, None
        if attempt == 2:
            break
        print(
            f"warn: open-meteo HTTP {resp.status_code} on {url} - "
            f"retry {attempt + 1}/2 in {wait_s:g}s",
            file=sys.stderr,
        )
        time.sleep(wait_s)
    if last_resp is not None:
        return last_resp
    raise last_exc  # type: ignore[misc]  # loop always sets one of the two before falling through


def fetch_marine_waves(lat: float, lon: float, *, timeout_s: float = 30.0) -> dict:
    """Total sea-state marine forecast at one point, for buoy validation (roadmap Stage 0).
    Single best_match model (plain hourly keys); caller handles any capture/replay."""
    with httpx.Client(timeout=timeout_s) as client:
        resp = retrying_get(
            client,
            MARINE_URL,
            {
                "latitude": f"{lat:g}",
                "longitude": f"{lon:g}",
                "hourly": ",".join(MARINE_WAVE_FIELDS),
                "forecast_days": FORECAST_DAYS,
            },
        )
        resp.raise_for_status()
    return resp.json()


def fetch_marine_waves_many(
    coords: list[tuple[float, float]], *, timeout_s: float = 30.0
) -> list[dict]:
    """Total sea-state at many points in one comma-joined request (the
    ``OpenMeteoSource._fetch_batch`` idiom), for the archive fleet run: one call
    against the marine host instead of one per buoy. Open-Meteo answers a
    multi-location query with a list of per-location bodies (a single point comes
    back as a bare dict); each element matches ``fetch_marine_waves``'s shape, so
    per-buoy capture files and ``parse_marine_waves`` are unaffected.

    ``retry_429``: this is the archive's fleet request (and verify --all-buoys' nowcast
    batch), and the archive is append-only - an hour lost to a minutely 429 can never be
    back-filled, so it is worth the 65 s wait exactly like the two ESSENTIAL requests in
    ``_fetch_batch``. A daily-bucket 429 still fails fast (``_retry_wait_s`` refuses it);
    ``fetch_wind_many`` stays fail-fast on purpose - wind columns are decision data the
    archive already degrades without."""
    if not coords:
        return []
    with httpx.Client(timeout=timeout_s) as client:
        resp = retrying_get(
            client,
            MARINE_URL,
            {
                "latitude": ",".join(f"{lat:g}" for lat, _ in coords),
                "longitude": ",".join(f"{lon:g}" for _, lon in coords),
                "hourly": ",".join(MARINE_WAVE_FIELDS),
                "forecast_days": FORECAST_DAYS,
            },
            retry_429=True,
        )
        resp.raise_for_status()
    data = resp.json()
    bodies = [data] if isinstance(data, dict) else list(data)
    if len(bodies) != len(coords):
        raise ValueError(f"open-meteo returned {len(bodies)} locations for {len(coords)} buoys")
    return bodies


def fetch_wind_many(
    coords: list[tuple[float, float]], *, model: str = WEATHER_MODEL, timeout_s: float = 30.0
) -> list[dict]:
    """10 m wind at many points, one comma-joined WEATHER-host request, in m/s so the
    values pair with NDBC WSPD without conversion (fetch-plane plan C3 evidence).
    Tiny: 2 vars -> weight 1/point on a host the archive otherwise never touches.
    ``model`` defaults to the published wind model; the station arm also asks for
    WEATHER_AB_MODEL so the two can be scored against the same observations."""
    if not coords:
        return []
    with httpx.Client(timeout=timeout_s) as client:
        resp = retrying_get(
            client,
            WEATHER_URL,
            {
                "latitude": ",".join(f"{lat:g}" for lat, _ in coords),
                "longitude": ",".join(f"{lon:g}" for _, lon in coords),
                "hourly": "wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "ms",
                "forecast_days": FORECAST_DAYS,
                "models": model,
            },
        )
        resp.raise_for_status()
    data = resp.json()
    bodies = [data] if isinstance(data, dict) else list(data)
    if len(bodies) != len(coords):
        raise ValueError(f"open-meteo returned {len(bodies)} locations for {len(coords)} buoys")
    return bodies


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

    def _get_retrying(
        self, client: httpx.Client, url: str, params: dict, *, retry_429: bool = False
    ) -> httpx.Response:
        return retrying_get(client, url, params, retry_429=retry_429)

    def _fetch_batch(self, coords: list[tuple[float, float]]) -> list[RawForecast]:
        common = {
            "latitude": ",".join(f"{lat:g}" for lat, _ in coords),
            "longitude": ",".join(f"{lon:g}" for _, lon in coords),
            "forecast_days": FORECAST_DAYS,
            "past_days": PAST_DAYS,
        }
        with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
            marine = self._get_retrying(
                client,
                MARINE_URL,
                {
                    **common,
                    "hourly": ",".join(MARINE_HOURLY),
                    "models": ",".join(MARINE_MODELS),
                },
                retry_429=True,
            )
            marine.raise_for_status()
            weather = self._get_retrying(
                client,
                WEATHER_URL,
                {**common, "hourly": ",".join(WEATHER_HOURLY), "models": WEATHER_MODEL},
                retry_429=True,
            )
            weather.raise_for_status()
            # The ensemble is the last and most expendable of the three requests: on ANY
            # failure - a 429 (Open-Meteo bills call weight against hourly and daily
            # buckets, so a big run can drain them), a 5xx that outlasts the retries, or a
            # transport error - drop it and let confidence fall back to the horizon proxy,
            # rather than throwing away the marine + weather data already fetched and
            # publishing nothing at all. Until 2026-08-21 only the literal-429 case
            # degraded; the other two raised and sank the whole batch.
            ensemble: httpx.Response | None
            try:
                ensemble = self._get_retrying(
                    client,
                    MARINE_URL,
                    {
                        **common,
                        "hourly": ",".join(ENSEMBLE_HOURLY),
                        "models": ",".join(MARINE_ENSEMBLE_MODELS),
                    },
                )
            except httpx.TransportError as e:
                print(
                    f"warn: open-meteo transport error on the ensemble request ({e!r}) - "
                    "publishing without the confidence ensemble (horizon proxy only)",
                    file=sys.stderr,
                )
                ensemble = None
            if ensemble is not None and ensemble.status_code >= 400:
                print(
                    f"warn: open-meteo {ensemble.status_code} on the ensemble request - "
                    "publishing without the confidence ensemble (horizon proxy only)",
                    file=sys.stderr,
                )
                ensemble = None
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
