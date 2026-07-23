"""Core datatypes shared across pipeline stages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

PartitionKind = Literal["swell", "wind"]
WindClass = Literal["offshore", "cross-shore", "onshore"]
Bucket = Literal["FLAT", "POOR", "FAIR", "GOOD", "FIRING"]


@dataclass(frozen=True, slots=True)
class SwellPartition:
    height_m: float
    period_s: float  # MEAN period — scoring/calibration uses this
    direction_deg: float
    kind: PartitionKind = "swell"
    # peak period (surf reports quote this, e.g. "6ft @ 14s") — display only for now,
    # None where the API doesn't expose it (secondary/tertiary swells, old fixtures)
    peak_period_s: float | None = None


@dataclass(frozen=True, slots=True)
class Spot:
    id: str
    name: str
    lat: float
    lon: float
    timezone: str
    offshore_point: tuple[float, float]  # (lat, lon) deep-water extraction point
    offshore_direction: float  # compass direction the offshore WIND blows FROM (wind scoring)
    shore_normal: float  # seaward-facing azimuth (WAVE geometry: bathymetry ray, refraction).
    # Distinct from offshore_direction: at point breaks the ideal wind can differ from the
    # coast's true seaward normal (e.g. Arugam Bay faces ~E while its best wind is SW).
    swell_window: tuple[float, float]  # (lo, hi) degrees; may wrap through 360
    height_coeff: float
    break_type: str
    ideal_wind_dir: tuple[float, float]
    ideal_size_m: tuple[float, float]
    region: str = ""  # display country/area (e.g. "Israel"); used for search
    tide_best: str | None = None  # local knowledge: "low" | "mid" | "high" (never derived)


@dataclass(frozen=True, slots=True)
class SpectralSea:
    """ECMWF open-data wave fields at a point/hour (Stage 3b spectral-lite).

    Periods are three different integral measures of the 1-D spectrum — their ratios
    estimate spectral narrowness (the consistency proxy). ``bands`` holds the six
    period-banded significant heights (h1012..h2530), a coarse 1-D spectrum over the
    groundswell range that neither Open-Meteo nor NOAA gridded expose."""

    time: datetime  # tz-aware UTC
    swh: float | None = None  # combined significant wave height, m
    mwd: float | None = None  # mean wave direction, deg
    mwp: float | None = None  # mean period Tm-1,0, s (energy period)
    pp1d: float | None = None  # peak period Tp, s
    mp2: float | None = None  # mean zero-crossing period Tm02, s
    bands: tuple[tuple[str, float], ...] = ()  # (param, Hs m), e.g. ("h1417", 0.4)


@dataclass(frozen=True, slots=True)
class HourForecast:
    time: datetime  # tz-aware UTC
    partitions: tuple[SwellPartition, ...]
    sst_c: float | None
    wind_speed_kph: float
    wind_dir_deg: float
    wind_gusts_kph: float | None
    pressure_msl: float | None = None  # hPa (= mb)
    air_c: float | None = None
    tide_m: float | None = None  # total water level rel. MSL (Stage 2D); None beyond its horizon
    # multi-model agreement at this hour (Stage 1): 0 = models disagree, 1 = tight;
    # None when no ensemble was fetched (older fixtures) → confidence falls back to horizon
    agreement_score: float | None = None
    n_models: int = 0
    # ECMWF spectral-lite member joined to this hour (Stage 3b); None when the member
    # wasn't fetched or the hour is beyond its 240 h horizon
    spectral: SpectralSea | None = None


@dataclass(frozen=True, slots=True)
class ScoredHour:
    hour: HourForecast
    h_break_lo: float
    h_break_mid: float
    h_break_hi: float
    phrase: str
    wind_class: WindClass
    energy: float  # sum(H^2 * T) of in-window partitions
    dominant: SwellPartition | None
    size_score: float
    period_score: float
    wind_score: float
    rating: int
    bucket: Bucket
    wetsuit: str | None
