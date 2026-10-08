"""Forecast source layer: Open-Meteo v1, behind an interface so the raw-grid migration
(NOMADS/ECMWF/CMEMS) only touches this module.

OpenMeteoSource fetches live and can capture the raw responses to disk;
FixtureSource replays a captured file so tests and offline runs never touch the network.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from .geo import dlon180

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
# A self-hosted Open-Meteo (2026-10-07, OPEN-ITEMS 34): the same API, run on the box from
# Open-Meteo's own AWS open-data copy, with no daily cap. Off unless ROSA_WEATHER_URL names
# it (e.g. http://127.0.0.1:8080/v1/forecast in ~/rosa/.env). The weather-host callers
# (blend's weather leg, the station/buoy wind archive) ask it first and fall back to
# WEATHER_URL on any failure, so turning it on can never cost a cycle. Its first request
# after a start can read cold from S3, hence the long timeout.
WEATHER_URL_ENV = "ROSA_WEATHER_URL"
SELF_HOSTED_TIMEOUT_S = 300.0


def self_hosted_weather_url() -> str | None:
    return os.environ.get(WEATHER_URL_ENV) or None


# The marine API from the same self-hosted Open-Meteo (2026-10-08, OPEN-ITEMS 32): the
# open-meteo-sync-marine container keeps every file the buoy archive and the om arm read,
# and a same-run comparison against marine-api.open-meteo.com was identical in every value.
# Off unless ROSA_MARINE_URL names it (http://127.0.0.1:8080/v1/marine in ~/rosa/.env);
# every marine caller asks it first and falls back to MARINE_URL on any failure.
MARINE_URL_ENV = "ROSA_MARINE_URL"


def self_hosted_marine_url() -> str | None:
    return os.environ.get(MARINE_URL_ENV) or None


def _self_hosted_marine(
    client: httpx.Client, params: dict, what: str, check: Callable[[Any], Any] | None = None
) -> Any | None:
    """One marine request from the self-hosted Open-Meteo, parsed (and ``check``ed, e.g. the
    batch attribution); None with a warning on any failure, so the caller asks MARINE_URL."""
    url = self_hosted_marine_url()
    if url is None:
        return None
    try:
        got = client.get(url, params=params, timeout=SELF_HOSTED_TIMEOUT_S)
        data = got.raise_for_status().json()
        return check(data) if check is not None else data
    except (httpx.HTTPError, ValueError) as e:
        print(
            f"warn: self-hosted marine failed for {what} ({e!r}) - "
            "asking marine-api.open-meteo.com",
            file=sys.stderr,
        )
        return None


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
# ICON was archived at the coastal stations as the A/B member ("<station>.icon") until
# 2026-09-16, when the station A/B confirmed GFS (wind speed bias -0.04 vs -0.80 m/s
# at 0-1 d, CALIBRATION.md) and the ICON leg was dropped to free weather-host quota.
WEATHER_MODEL = "gfs_seamless"


# verification harness samples the total sea-state at a buoy - no models suffix, so the
# hourly keys stay plain (wave_height/period/direction), tiny payload
MARINE_WAVE_FIELDS = ["wave_height", "wave_period", "wave_direction"]

# How far a returned location may sit from the one requested before the batch is refused
# as mis-attributed (see _check_batch_order). Open-Meteo answers with the grid CELL
# CENTRE: the coarsest wave grid behind these fields is 0.25 deg, whose worst-case centre
# offset is half a cell = 0.125 deg per axis. 0.3 deg is that with headroom. Ordering is
# no longer the cap's job: since 2026-09-14 bodies are put back in request order by their
# ``location_id`` (_order_by_location_id) before this check, so the registry may hold
# buoys closer together than the cap (the SoCal Bight CDIP net sits ~0.1 deg apart).
MAX_GRID_SNAP_DEG = 0.3


# Transient server-side failures worth a second look. A single one of these used to
# kill a whole cycle: a 503 on the last of five weather batches sank the 2026-08-16
# 08:20Z run after four minutes of successful paced fetching.
RETRY_STATUS = frozenset({500, 502, 503, 504})

# Open-Meteo names the bucket that tripped in the 429 body. ONLY the minutely cap is
# worth waiting out - it reopens by itself inside a minute. The hourly and daily buckets
# do not, so waiting on them just burns cycle wall-clock in front of a failure
# `rosa_pipeline.quota` already handles. The classification no longer hangs on that one
# vendor sentence alone (2026-08-31, Dream proposal): a Retry-After header is honored
# first, and a 429 with NO readable reason is treated as the minutely cap when the local
# quota ledger says today's budget still has room (on the marine host, the only one it
# meters - any other host gets the minute wait unasked) - if the daily bucket cannot be what
# tripped, waiting 65 s once is cheap next to the alternative, which is the exact
# 2026-08-28 failure mode (aux-leg 429 -> raise_for_status -> dead cycle) returning the
# day Open-Meteo rewords its error body. A 429 whose reason reads as another bucket is
# still never retried.
_MINUTE_LIMIT_MARKER = "minutely api request limit"
# ...and the two buckets that do NOT reopen inside a cycle, named the same way. A body
# that positively identifies one of these vetoes every retry path below, Retry-After
# included: the header says how long the SERVER wants us to wait (Open-Meteo's daily
# bucket resets at 00:00Z, so that is hours), and honoring it would spend up to
# _RETRY_AFTER_CAP_S twice per essential request in front of a failure
# `rosa_pipeline.quota` is the designed handler for. Unrecognised wording still falls
# through to the header - that is the wording-independence the 2026-08-31 change bought,
# and what test_fetch.py::test_retry_after_header_is_honored_on_a_429_whatever_the_body_says
# pins; only a bucket we can NAME is vetoed here.
_OTHER_LIMIT_MARKERS = ("hourly api request limit", "daily api request limit")
_MINUTE_RETRY_WAIT_S = 65.0
_RETRY_AFTER_CAP_S = 300.0


def _retry_wait_s(resp: httpx.Response, attempt: int, url: str | None = None) -> float | None:
    """Seconds to wait before retrying this response, or None if it is not retryable.
    ``url`` is the request that got it; None (a caller that cannot say) keeps the ledger
    arbitration below for every host."""
    if resp.status_code in RETRY_STATUS:
        return 10.0 * (attempt + 1)
    if resp.status_code != 429:
        return None
    try:
        named = str(resp.json().get("reason", "")).lower()
    except Exception:
        named = ""  # a non-JSON 429 body is unclassifiable
    if any(m in named for m in _OTHER_LIMIT_MARKERS):
        return None  # a bucket that cannot reopen in time - see _OTHER_LIMIT_MARKERS
    # the server's own answer, when it gives one - bounded, wording-independent
    retry_after = getattr(resp, "headers", {}).get("Retry-After")
    if retry_after is not None:
        try:
            return min(max(float(retry_after), 0.0), _RETRY_AFTER_CAP_S)
        except ValueError:
            pass  # an HTTP-date Retry-After: fall through to the body
    try:
        reason = str(resp.json().get("reason", ""))
    except Exception:
        reason = ""  # a non-JSON 429 body is unclassifiable
    if reason:
        return _MINUTE_RETRY_WAIT_S if _MINUTE_LIMIT_MARKER in reason.lower() else None
    # unclassifiable: let the ledger arbitrate (see the block comment above) - but only for
    # the marine host, the one it meters. The weather host was never booked there and the
    # blend arm books nothing since 2026-09-12, so for any other host a spent (or unspent)
    # ledger says nothing about its daily bucket: wait the minute once, as argued above.
    if url is not None and not url.startswith(MARINE_URL):
        return _MINUTE_RETRY_WAIT_S
    from . import quota

    return _MINUTE_RETRY_WAIT_S if quota.Ledger.load().remaining > 0.0 else None


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
            # the LAST failure is what the caller must see: an earlier attempt's 5xx kept
            # here would be returned in its place, and raise_for_status would then blame
            # the server for what was a local transport outage on the final attempts
            last_exc, last_resp = e, None
            if attempt < 2:
                print(
                    f"warn: open-meteo transport error ({e!r}), retry {attempt + 1}/2",
                    file=sys.stderr,
                )
                time.sleep(10.0 * (attempt + 1))
            continue
        if resp.status_code == 429 and not retry_429:
            return resp
        wait_s = _retry_wait_s(resp, attempt, url)
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
    params = {
        "latitude": f"{lat:g}",
        "longitude": f"{lon:g}",
        "hourly": ",".join(MARINE_WAVE_FIELDS),
        "forecast_days": FORECAST_DAYS,
    }
    with httpx.Client(timeout=timeout_s) as client:
        got = _self_hosted_marine(client, params, "1 buoy")
        if got is not None:
            return got
        resp = retrying_get(client, MARINE_URL, params)
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
    params = {
        "latitude": ",".join(f"{lat:g}" for lat, _ in coords),
        "longitude": ",".join(f"{lon:g}" for _, lon in coords),
        "hourly": ",".join(MARINE_WAVE_FIELDS),
        "forecast_days": FORECAST_DAYS,
    }

    def attributed(data: Any) -> list[dict]:
        bodies = [data] if isinstance(data, dict) else list(data)
        if len(bodies) != len(coords):
            raise ValueError(f"open-meteo returned {len(bodies)} locations for {len(coords)} buoys")
        bodies = _order_by_location_id(bodies)
        _check_batch_order(bodies, coords)
        return bodies

    with httpx.Client(timeout=timeout_s) as client:
        got = _self_hosted_marine(client, params, f"{len(coords)} buoy(s)", attributed)
        if got is not None:
            return got
        resp = retrying_get(client, MARINE_URL, params, retry_429=True)
        resp.raise_for_status()
    return attributed(resp.json())


def fetch_wind_many(
    coords: list[tuple[float, float]], *, model: str = WEATHER_MODEL, timeout_s: float = 30.0
) -> list[dict]:
    """10 m wind at many points, one comma-joined WEATHER-host request, in m/s so the
    values pair with NDBC WSPD without conversion (fetch-plane plan C3 evidence).
    Tiny: 2 vars -> weight 1/point on a host the archive otherwise never touches.
    ``model`` defaults to the published wind model."""
    if not coords:
        return []
    params = {
        "latitude": ",".join(f"{lat:g}" for lat, _ in coords),
        "longitude": ",".join(f"{lon:g}" for _, lon in coords),
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms",
        "forecast_days": FORECAST_DAYS,
        "models": model,
    }

    def attributed(data: object) -> list[dict]:
        bodies = [data] if isinstance(data, dict) else list(data)  # type: ignore[arg-type]
        if len(bodies) != len(coords):
            raise ValueError(f"open-meteo returned {len(bodies)} locations for {len(coords)} buoys")
        bodies = _order_by_location_id(bodies)
        _check_batch_order(bodies, coords)
        return bodies

    with httpx.Client(timeout=timeout_s) as client:
        self_hosted = self_hosted_weather_url()
        if self_hosted is not None:
            try:
                got = client.get(self_hosted, params=params, timeout=SELF_HOSTED_TIMEOUT_S)
                return attributed(got.raise_for_status().json())
            except (httpx.HTTPError, ValueError) as e:
                print(
                    f"warn: self-hosted weather failed for {len(coords)} wind point(s) ({e!r})"
                    " - asking api.open-meteo.com",
                    file=sys.stderr,
                )
        resp = retrying_get(client, WEATHER_URL, params)
        resp.raise_for_status()
    return attributed(resp.json())


def _order_by_location_id(bodies: list) -> list:
    """Put a multi-location response back in request order by each body's ``location_id``.

    Open-Meteo numbers the bodies of a comma-joined request 0..n-1 in request order and
    carries the number as ``location_id`` (the first body omits it - live-verified
    2026-09-14). Attributing by that id, not by list position, is what lets the buoy
    registry hold stations closer together than ``MAX_GRID_SNAP_DEG`` can tell apart: a
    swap between two nearshore Waveriders 0.1 deg apart is invisible to the coordinate
    check but impossible here. A list with no ids at all (older captures replayed as
    fixtures, single-point bodies) is returned as is; ids that are not exactly 0..n-1
    are refused rather than guessed."""
    if len(bodies) < 2 or not any(isinstance(b, dict) and "location_id" in b for b in bodies):
        return bodies
    ids = [int(b.get("location_id", 0)) if isinstance(b, dict) else -1 for b in bodies]
    if sorted(ids) != list(range(len(bodies))):
        raise ValueError(
            f"open-meteo location_id set {ids} is not 0..{len(bodies) - 1} - "
            "refusing to attribute the batch"
        )
    return [b for _, b in sorted(zip(ids, bodies, strict=True), key=lambda ib: ib[0])]


def _check_batch_order(bodies: list[dict], coords: list[tuple[float, float]]) -> None:
    """Every body must be the location it was asked for, not just the right count.

    The list is matched to ``coords`` by position after ``_order_by_location_id`` has put
    it in request order, and what it feeds is the append-only lead-time archive: a
    mis-attributed response would file one buoy's model series under another's id,
    permanently, in the store every accuracy claim is scored from. Each body already
    carries the coordinate it answers for; this is the second, independent check.

    ``MAX_GRID_SNAP_DEG`` bounds each body's OWN offset from its request rather than asking
    "which request is this body nearest to" - that test fires falsely the moment two
    requested points share a grid cell, which spot samples ~0.05 deg apart routinely do.
    So: a body sitting further than the cap from its request is caught here; a swap between
    two points closer than that is the ``location_id`` ordering's job."""
    for i, (body, (lat, lon)) in enumerate(zip(bodies, coords, strict=True)):
        blat, blon = body.get("latitude"), body.get("longitude")
        if blat is None or blon is None:
            continue  # nothing to check against (older captures replayed as fixtures)
        dlat = abs(float(blat) - lat)
        dlon = abs(dlon180(float(blon), lon))
        if max(dlat, dlon) > MAX_GRID_SNAP_DEG:
            raise ValueError(
                f"open-meteo location {i} came back at ({blat}, {blon}), "
                f"{max(dlat, dlon):.3f} deg from the ({lat}, {lon}) it was asked for "
                f"(cap {MAX_GRID_SNAP_DEG} deg) - refusing to attribute it by position"
            )


@dataclass(frozen=True, slots=True)
class RawForecast:
    fetched_at: str  # ISO-8601 UTC
    marine: dict
    weather: dict
    ensemble: dict | None = None  # multi-model Hs/period/dir for confidence (Stage 1)
    # Blend arm only: {"gfswave": iso, "ecmwf": iso | None} - the cycle the numbers came
    # from, per point (blend._model_run). None on the OM arm and on fixtures.
    model_run: dict | None = None


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
        self_hosted = self_hosted_marine_url() if url == MARINE_URL else None
        if self_hosted is not None:
            # the marine and ensemble requests ask the self-hosted copy first (OPEN-ITEMS
            # 32); a 4xx/5xx or an unparseable body there falls back to the public host
            try:
                got = client.get(self_hosted, params=params, timeout=SELF_HOSTED_TIMEOUT_S)
                got.raise_for_status().json()
                return got
            except (httpx.HTTPError, ValueError) as e:
                print(
                    f"warn: self-hosted marine failed for an om-arm batch ({e!r}) - "
                    "asking marine-api.open-meteo.com",
                    file=sys.stderr,
                )
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
        marine_list = _order_by_location_id(mj if isinstance(mj, list) else [mj])
        weather_list = _order_by_location_id(wj if isinstance(wj, list) else [wj])
        # The same attribution the archive's fetch_*_many use: bodies are put back in
        # request order by their location_id, then each must name the coordinate it
        # answers for - a mis-ordered trio would publish one spot's sea under another
        # spot's id for a whole cycle. The strict zip below only checks the COUNT.
        # Bodies without a coordinate (old captures) pass through.
        _check_batch_order(marine_list, coords)
        _check_batch_order(weather_list, coords)
        ensemble_list: list[dict | None] = [None] * len(coords)
        if ensemble is not None:
            try:
                ej = ensemble.json()
                ensemble_list = _order_by_location_id(ej if isinstance(ej, list) else [ej])
                _check_batch_order(ensemble_list, coords)
            except ValueError as e:
                # expendable, like every other ensemble failure: degrade, never sink.
                # ValueError covers every step: a 200 that is not JSON, a location_id
                # set that is not 0..n-1, a count that does not match, and a body at
                # the wrong coordinate (the first three sat outside this guard until
                # 2026-10-07 and sank the batch, marine + weather bodies included).
                print(
                    f"warn: open-meteo ensemble batch mis-attributed ({e}) - "
                    "publishing without the confidence ensemble (horizon proxy only)",
                    file=sys.stderr,
                )
                ensemble_list = [None] * len(coords)
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
