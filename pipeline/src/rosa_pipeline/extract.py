"""Turn raw API responses into typed hourly records at the offshore point."""

from __future__ import annotations

from bisect import bisect_left
from datetime import UTC, datetime, timedelta

from .confidence import agreement_from_heights, member_heights_at
from .fetch import RawForecast
from .models import HourForecast, SpectralSea, SwellPartition

# a 3-hourly published hour joins the nearest 6-hourly ECMWF step within this - the
# spectral-shape quantities it feeds vary over hours, not minutes
SPECTRAL_JOIN_TOL_H = 3.0

_SWELL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("swell_wave", "swell"),
    ("secondary_swell_wave", "swell"),
    ("tertiary_swell_wave", "swell"),
    ("wind_wave", "wind"),
)


def _merge_models(hourly: dict) -> dict:
    """Collapse a multi-model marine response (fields suffixed `_marine_best_match`,
    `_ncep_gfswave016`) into a single unsuffixed series, per hour: use best_match where
    it has data (days 0-9), else GFS-Wave (days 10-16). Anchored on wave_height so every
    field in an hour comes from one model. A single-model / fixture response passes through
    unchanged."""
    if "wave_height" in hourly:  # single model (or fixture) - nothing to merge
        return hourly
    suffixes = {k[len("wave_height_") :] for k in hourly if k.startswith("wave_height_")}
    if not suffixes:
        return hourly
    bm = next((s for s in suffixes if "best_match" in s), None)
    gf = next((s for s in suffixes if "best_match" not in s), None)
    anchor = hourly.get(f"wave_height_{bm}") if bm else None
    bases = {k.rsplit("_" + (bm or gf or ""), 1)[0] for k in hourly if k != "time"}

    merged: dict = {"time": hourly["time"]}
    n = len(hourly["time"])
    for base in bases:
        bm_arr = hourly.get(f"{base}_{bm}") if bm else None
        gf_arr = hourly.get(f"{base}_{gf}") if gf else None
        out: list = []
        for i in range(n):
            use_bm = anchor is not None and i < len(anchor) and anchor[i] is not None
            src = bm_arr if use_bm else gf_arr
            out.append(src[i] if src is not None and i < len(src) else None)
        merged[base] = out
    return merged


def _partition(hourly: dict, prefix: str, kind: str, i: int) -> SwellPartition | None:
    height = hourly[f"{prefix}_height"][i]
    direction = hourly[f"{prefix}_direction"][i]
    period = hourly[f"{prefix}_period"][i]
    if height is None or direction is None or period is None or height <= 0:
        return None
    # peak period is only published for the total/primary-swell/wind-wave (not sec/tert),
    # and absent from pre-Stage-1 fixtures - .get keeps those partitions valid with None
    peak_arr = hourly.get(f"{prefix}_peak_period")
    peak = peak_arr[i] if peak_arr is not None and i < len(peak_arr) else None
    return SwellPartition(
        height_m=height,
        period_s=period,
        direction_deg=direction,
        kind=kind,  # type: ignore[arg-type]
        peak_period_s=peak,
    )


def _nearest_spectral(
    t: datetime, spectral: list[SpectralSea], times: list[datetime]
) -> SpectralSea | None:
    """Nearest ECMWF step within SPECTRAL_JOIN_TOL_H (``times`` = sorted spectral times)."""
    if not spectral:
        return None
    i = bisect_left(times, t)
    best: SpectralSea | None = None
    best_gap = timedelta(hours=SPECTRAL_JOIN_TOL_H)
    for j in (i - 1, i):
        if 0 <= j < len(spectral):
            gap = abs(spectral[j].time - t)
            if gap <= best_gap:
                best, best_gap = spectral[j], gap
    return best


def extract_hours(
    raw: RawForecast, spectral: list[SpectralSea] | None = None
) -> list[HourForecast]:
    marine = _merge_models(raw.marine["hourly"])
    weather = raw.weather["hourly"]
    weather_index = {t: i for i, t in enumerate(weather["time"])}
    # ensemble (independent members) drives per-hour confidence; aligned by timestamp so a
    # different horizon/ordering can't misalign it. Absent in pre-Stage-1 fixtures → None.
    ens = raw.ensemble["hourly"] if raw.ensemble else None
    ens_index = {t: i for i, t in enumerate(ens["time"])} if ens else {}
    # ECMWF spectral-lite member (Stage 3b), joined per hour by nearest step
    sp_series = sorted(spectral or [], key=lambda s: s.time)
    sp_times = [s.time for s in sp_series]
    # SST comes only from best_match (~9 days); carry the last real reading into the
    # GFS-Wave tail so extended days still show a water temp (it drifts ~1 C/week).
    last_sst: float | None = None

    hours: list[HourForecast] = []
    for i, t in enumerate(marine["time"]):
        if marine["wave_height"][i] is None:
            # Beyond the marine model's horizon (~day 10 the API pads with nulls to
            # forecast_days). Publishing these as flat would fabricate a forecast.
            continue
        j = weather_index.get(t)
        if j is None:
            continue
        wind_speed = weather["wind_speed_10m"][j]
        wind_dir = weather["wind_direction_10m"][j]
        if wind_speed is None or wind_dir is None:
            # the weather API can pad nulls (seen on past_days hours at some points);
            # skipping is honest - a fabricated calm would score as fake offshore
            continue
        partitions = tuple(
            p
            for prefix, kind in _SWELL_PREFIXES
            if (p := _partition(marine, prefix, kind, i)) is not None
        )
        sst = marine["sea_surface_temperature"][i]
        if sst is not None:
            last_sst = sst
        time = datetime.fromisoformat(t).replace(tzinfo=UTC)
        sp = _nearest_spectral(time, sp_series, sp_times)
        # the ECMWF member joins the OM ensemble as one more independent voice in the
        # per-hour agreement (Stage 1 confidence axis - the plan's "two birds")
        member_hs = (
            member_heights_at(ens, ens_index[t]) if ens is not None and t in ens_index else []
        )
        if sp is not None and sp.swh is not None:
            member_hs = [*member_hs, sp.swh]
        agreement = agreement_from_heights(member_hs)
        hours.append(
            HourForecast(
                time=time,
                partitions=partitions,
                sst_c=sst if sst is not None else last_sst,
                wind_speed_kph=wind_speed,
                wind_dir_deg=wind_dir,
                wind_gusts_kph=weather["wind_gusts_10m"][j],
                # .get: absent in captures made before these were added to the fetch
                pressure_msl=(pm[j] if (pm := weather.get("pressure_msl")) else None),
                air_c=(ta[j] if (ta := weather.get("temperature_2m")) else None),
                # tide/water level (Stage 2D); .get tolerates fixtures captured before it existed
                tide_m=(sl[i] if (sl := marine.get("sea_level_height_msl")) is not None else None),
                agreement_score=agreement.score if agreement else None,
                n_models=agreement.n_models if agreement else 0,
                spectral=sp,
            )
        )
    return hours
