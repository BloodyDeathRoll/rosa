"""Turn raw API responses into typed hourly records at the offshore point."""

from __future__ import annotations

from datetime import UTC, datetime

from .fetch import RawForecast
from .models import HourForecast, SwellPartition

_SWELL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("swell_wave", "swell"),
    ("secondary_swell_wave", "swell"),
    ("tertiary_swell_wave", "swell"),
    ("wind_wave", "wind"),
)


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
    marine = raw.marine["hourly"]
    weather = raw.weather["hourly"]
    weather_index = {t: i for i, t in enumerate(weather["time"])}

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
        hours.append(
            HourForecast(
                time=datetime.fromisoformat(t).replace(tzinfo=UTC),
                partitions=partitions,
                sst_c=marine["sea_surface_temperature"][i],
                wind_speed_kph=weather["wind_speed_10m"][j],
                wind_dir_deg=weather["wind_direction_10m"][j],
                wind_gusts_kph=weather["wind_gusts_10m"][j],
            )
        )
    return hours
