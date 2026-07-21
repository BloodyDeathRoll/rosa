"""Turn raw API responses into typed hourly records at the offshore point."""

from __future__ import annotations

from datetime import UTC, datetime

from .confidence import agreement_at
from .fetch import RawForecast
from .models import HourForecast, SwellPartition

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
    if "wave_height" in hourly:  # single model (or fixture) — nothing to merge
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
    return SwellPartition(
        height_m=height,
        period_s=period,
        direction_deg=direction,
        kind=kind,  # type: ignore[arg-type]
    )


def extract_hours(raw: RawForecast) -> list[HourForecast]:
    marine = _merge_models(raw.marine["hourly"])
    weather = raw.weather["hourly"]
    weather_index = {t: i for i, t in enumerate(weather["time"])}
    # ensemble (independent members) drives per-hour confidence; aligned by timestamp so a
    # different horizon/ordering can't misalign it. Absent in pre-Stage-1 fixtures → None.
    ens = raw.ensemble["hourly"] if raw.ensemble else None
    ens_index = {t: i for i, t in enumerate(ens["time"])} if ens else {}
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
        partitions = tuple(
            p
            for prefix, kind in _SWELL_PREFIXES
            if (p := _partition(marine, prefix, kind, i)) is not None
        )
        sst = marine["sea_surface_temperature"][i]
        if sst is not None:
            last_sst = sst
        agreement = agreement_at(ens, ens_index[t]) if ens is not None and t in ens_index else None
        hours.append(
            HourForecast(
                time=datetime.fromisoformat(t).replace(tzinfo=UTC),
                partitions=partitions,
                sst_c=sst if sst is not None else last_sst,
                wind_speed_kph=weather["wind_speed_10m"][j],
                wind_dir_deg=weather["wind_direction_10m"][j],
                wind_gusts_kph=weather["wind_gusts_10m"][j],
                # .get: absent in captures made before these were added to the fetch
                pressure_msl=(pm[j] if (pm := weather.get("pressure_msl")) else None),
                air_c=(ta[j] if (ta := weather.get("temperature_2m")) else None),
                agreement_score=agreement.score if agreement else None,
                n_models=agreement.n_models if agreement else 0,
            )
        )
    return hours
