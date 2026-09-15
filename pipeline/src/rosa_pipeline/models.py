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
    period_s: float  # MEAN period - scoring/calibration uses this
    direction_deg: float
    kind: PartitionKind = "swell"
    # peak period (surf reports quote this, e.g. "6ft @ 14s") - display only for now,
    # None where the API doesn't expose it (secondary/tertiary swells, old fixtures)
    peak_period_s: float | None = None


@dataclass(frozen=True, slots=True)
class SpotCam:
    """A live cam we are permitted to embed, plus the credit that permission implies."""

    youtube_id: str  # video id of the live stream - a fallback, it rots on every restart
    by: str  # channel name, shown as the credit
    by_url: str  # channel URL, linked from the credit
    # The stream's channel (UC...) and exact title: the app finds the camera's CURRENT
    # broadcast as the newest same-title entry in the channel's feed (web/src/cams.ts).
    channel_id: str
    title: str
    note: str | None = None  # set when the camera is near the spot rather than on it
    label: str | None = None  # angle name when a spot has several cams ("Panorâmica 1")


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
    # Nearest settlement (e.g. "Puerto Escondido"), for SEARCH only - a break is famous under
    # the town's name at least as often as its own, and a search that only matches the break
    # name finds nothing for "Puerto Escondido" while holding three of its waves. Derived from
    # the nearest OSM place node, never rendered as part of the spot's name.
    town: str | None = None
    tide_best: str | None = None  # local knowledge: "low" | "mid" | "high" (never derived)
    # Live cams, only ever streams whose operator publishes them as embeddable (CLAUDE.md
    # legal red line: never scrape a cam, never touch a competitor's). Today that means
    # public YouTube live streams, embedded through YouTube's own player with the channel
    # credited. Empty for the vast majority of spots - nobody points a camera at them.
    # Several entries = several angles (each may carry a `label`).
    cams: tuple[SpotCam, ...] = ()

    @property
    def cam(self) -> SpotCam | None:
        """First (primary) cam - the one map cards and single-cam consumers use."""
        return self.cams[0] if self.cams else None


@dataclass(frozen=True, slots=True)
class SpectralSea:
    """ECMWF open-data wave fields at a point/hour (Stage 3b spectral-lite).

    Periods are three different integral measures of the 1-D spectrum - their ratios
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
    run: datetime | None = None  # model cycle (provenance, publish.model_run); None on fixtures


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
    # widest pairwise member bearing gap at this hour, deg (Agreement.dir_span_deg).
    # DIAGNOSTIC only - nothing scores on it (2026-08-07 revert); persisted so the
    # calibration entry direction scoring is gated on has a distribution to derive
    # its tolerance from. None = fewer than two member bearings.
    dir_span_deg: float | None = None
    # how many member bearings that span covers (Agreement.n_dirs). Distinct from
    # n_models above, which counts height members and includes the ECMWF member; a
    # max-pairwise gap cannot be pooled across hours without it.
    n_dir_members: int = 0
    # ECMWF spectral-lite member joined to this hour (Stage 3b); None when the member
    # wasn't fetched or the hour is beyond its 240 h horizon
    spectral: SpectralSea | None = None
    # this hour came from the GFS-Wave tail rather than best_match (extract._merge_models
    # anchors the choice on wave_height). Display provenance only - nothing scores on it.
    # Default False so fixtures, the blend arm and any single-model response are unchanged.
    from_tail: bool = False
    # the source's OWN combined significant wave height for this hour, m. Kept so the
    # partitions can be checked against it (see transform.partition_closure): Open-Meteo
    # does not always place all of its energy into the four partition fields it publishes,
    # and the partitions are all the transform ever sees. None for older fixtures.
    total_hs_m: float | None = None


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
    # Per-hour provenance of the breaker height's propagation link (CLAUDE.md principle 3:
    # per-hour, never a constant label): None = the offshore point marched over the whole
    # committed profile (the shipping path); "swan" = the Stage-4 regional model's sea at
    # the spot's handoff point, marched over the inner profile only.
    nearshore: str | None = None
