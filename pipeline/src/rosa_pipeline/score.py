"""Rating v1 (0-100): size 0-40 + period 0-20 + wind 0-40 -> bucket.

Spec fixed points (CLAUDE.md):
- period: linear, 6 s -> 0 pts, 14 s -> 20 pts
- wind: offshore <= 15 kph -> 40; onshore >= 25 kph -> 0; scales down with speed and angle
- buckets: 0-9 FLAT, 10-29 POOR, 30-49 FAIR, 50-69 GOOD, 70+ FIRING

Where the spec is a curve description rather than a formula, the exact shape chosen here
is published in-app ("why this rating") and tuned only via the calibration log:
- size: linear ramp 0 -> ideal lo, flat 40 across [lo, hi], linear taper above hi with a
  floor of 10 pts reached at 2x hi (oversize is degraded, never zeroed).
- wind: score = 40 x angle_factor x speed_factor. angle_factor is 1 up to 45 deg off
  offshore, then linear to 0 at 180 deg. speed_factor is 1 up to 15 kph, then linear to 0
  at a max speed that shrinks with angle: 40 kph when offshore, 25 kph when onshore.
- wind gate (calibration fix #1, 2026-07-19): wind points are scaled by
  min(1, (size + period) / 30) before summing - offshore wind polishes waves that exist,
  it never creates rating on its own. ScoredHour.wind_score holds the gated value.
- flat gate: with no in-window partition or h_break_mid < 0.15 m, rating = size component
  only (a flat day with perfect offshore wind must read FLAT, not FAIR).

Breaker height uses the period-adjusted effective height (transform.period_quality):
a 0.66 m @ 5 s windswell surfs like ~0.18 m, not waist-high (calibration fix #1,
quadratic q confirmed against ISRAMAR Hadera buoy + cam observation).
"""

from __future__ import annotations

from .models import Bucket, HourForecast, ScoredHour, Spot
from .transform import (
    angle_diff,
    breaker_height_from_profile,
    breaker_range,
    classify_wind,
    dominant_partition,
    effective_height_in_window,
    energy_in_window,
    height_phrase,
    wetsuit,
)

SIZE_MAX = 40.0
PERIOD_MAX = 20.0
WIND_MAX = 40.0
FLAT_HEIGHT_M = 0.15
OVERSIZE_FLOOR = 10.0
WIND_GATE_PTS = 60.0


def size_score(h_break_mid: float, ideal_size_m: tuple[float, float]) -> float:
    lo, hi = ideal_size_m
    if h_break_mid <= 0:
        return 0.0
    if h_break_mid < lo:
        return SIZE_MAX * h_break_mid / lo
    if h_break_mid <= hi:
        return SIZE_MAX
    tapered = SIZE_MAX * (1 - 0.75 * (h_break_mid - hi) / hi)
    return max(OVERSIZE_FLOOR, tapered)


def period_score(period_s: float) -> float:
    return min(1.0, max(0.0, (period_s - 6.0) / 8.0)) * PERIOD_MAX


def wind_score(speed_kph: float, wind_from_deg: float, offshore_direction: float) -> float:
    theta = angle_diff(wind_from_deg, offshore_direction)
    angle_factor = 1.0 if theta <= 45 else max(0.0, 1 - (theta - 45) / 135)
    if theta <= 45:
        v_max = 40.0
    elif theta >= 135:
        v_max = 25.0
    else:
        v_max = 40.0 - 15.0 * (theta - 45) / 90
    speed_factor = 1.0 if speed_kph <= 15 else max(0.0, 1 - (speed_kph - 15) / (v_max - 15))
    return WIND_MAX * angle_factor * speed_factor


def bucket(rating: int) -> Bucket:
    if rating < 10:
        return "FLAT"
    if rating < 30:
        return "POOR"
    if rating < 50:
        return "FAIR"
    if rating < 70:
        return "GOOD"
    return "FIRING"


def score_hour(spot: Spot, hour: HourForecast, wet_depths: list[float] | None = None) -> ScoredHour:
    window = spot.swell_window
    dominant = dominant_partition(hour.partitions, window)
    energy = energy_in_window(hour.partitions, window)
    # Stage 2B: with the spot's bathymetry profile, breaker height comes from real physics
    # (shoaling + refraction + depth-limited breaking). Falls back to the q(T) transform
    # when no profile is available (retired fully in Stage 2E once physics is recalibrated).
    if wet_depths:
        # tide raises/lowers the water column, so the wave breaks at a deeper/shallower point
        # (Stage 2D). Micro-tidal Med barely moves; macro-tidal spots (Costa Rica) shift a lot.
        depths = wet_depths
        if hour.tide_m:
            depths = [d + hour.tide_m for d in wet_depths if d + hour.tide_m > 0]
        h_eff = breaker_height_from_profile(hour.partitions, window, spot.shore_normal, depths)
    else:
        h_eff = effective_height_in_window(hour.partitions, window)
    h_lo, h_mid, h_hi = breaker_range(h_eff, spot.height_coeff)

    size = size_score(h_mid, spot.ideal_size_m)
    period = period_score(dominant.period_s) if dominant else 0.0
    wind = wind_score(hour.wind_speed_kph, hour.wind_dir_deg, spot.offshore_direction)
    wind_gated = wind * min(1.0, (size + period) / WIND_GATE_PTS)

    flat = dominant is None or h_mid < FLAT_HEIGHT_M
    rating = round(size if flat else size + period + wind_gated)

    return ScoredHour(
        hour=hour,
        h_break_lo=h_lo,
        h_break_mid=h_mid,
        h_break_hi=h_hi,
        phrase=height_phrase(h_mid),
        wind_class=classify_wind(hour.wind_dir_deg, spot.offshore_direction),
        energy=energy,
        dominant=dominant,
        size_score=size,
        period_score=period,
        wind_score=wind_gated,
        rating=rating,
        bucket=bucket(rating),
        wetsuit=wetsuit(hour.sst_c) if hour.sst_c is not None else None,
    )
