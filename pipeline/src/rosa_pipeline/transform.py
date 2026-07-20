"""Pure transform functions: wind classification, swell windowing, breaker height, phrases.

Implements CLAUDE.md "Algorithm specs" exactly; every function here is unit-tested offline.
"""

from __future__ import annotations

import math

from .models import SwellPartition, WindClass


def angle_diff(a: float, b: float) -> float:
    """Smallest absolute angle between two compass directions, in [0, 180]."""
    d = abs(a - b) % 360
    return min(d, 360 - d)


def classify_wind(wind_from_deg: float, offshore_direction: float) -> WindClass:
    theta = angle_diff(wind_from_deg, offshore_direction)
    if theta <= 45:
        return "offshore"
    if theta <= 135:
        return "cross-shore"
    return "onshore"


def in_window(direction_deg: float, window: tuple[float, float]) -> bool:
    lo, hi = window
    d = direction_deg % 360
    if lo <= hi:
        return lo <= d <= hi
    return d >= lo or d <= hi  # window wraps through 360


def energy_in_window(partitions: tuple[SwellPartition, ...], window: tuple[float, float]) -> float:
    return sum(p.height_m**2 * p.period_s for p in partitions if in_window(p.direction_deg, window))


def height_in_window(partitions: tuple[SwellPartition, ...], window: tuple[float, float]) -> float:
    """Combined significant height of in-window partitions (RMS combination)."""
    return math.sqrt(sum(p.height_m**2 for p in partitions if in_window(p.direction_deg, window)))


PERIOD_EXP = 1.4  # calibration knob: 2.0 = old quadratic (too cold), 1.0 = linear (too hot)


def period_quality(period_s: float) -> float:
    """q(T) = clamp((T/10)^1.4, 0.3, 1.2): short-period windswell breaks below its offshore
    height; long-period groundswell shoals above it. Exponent set by calibration row 2
    (2026-07-20): the quadratic under-called Med windswell 2-3x vs Surfline; pure linear
    over-called it to FAIR. 1.4 keeps a ~5 s, ~0.9 m windswell day at 0.3-0.4 m POOR
    (poor-to-fair) while a flat 0.5 m day stays 0.1-0.2 m. Calibrate from docs/CALIBRATION.md."""
    return min(1.2, max(0.3, (period_s / 10.0) ** PERIOD_EXP))


def effective_height_in_window(
    partitions: tuple[SwellPartition, ...], window: tuple[float, float]
) -> float:
    """RMS combination of per-partition period-adjusted heights: sqrt(sum (H_i * q(T_i))^2)."""
    return math.sqrt(
        sum(
            (p.height_m * period_quality(p.period_s)) ** 2
            for p in partitions
            if in_window(p.direction_deg, window)
        )
    )


def dominant_partition(
    partitions: tuple[SwellPartition, ...], window: tuple[float, float]
) -> SwellPartition | None:
    candidates = [p for p in partitions if in_window(p.direction_deg, window)]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.height_m**2 * p.period_s)


def _snap(x: float) -> float:
    return round(x * 10) / 10


def breaker_range(h_in_window: float, height_coeff: float) -> tuple[float, float, float]:
    """(lo, mid, hi): h_break = H_in_window x height_coeff, displayed as +/-20% snapped to
    0.1 m, with the band widened to a real >=0.1 m spread ("0.1-0.1" isn't a range)."""
    mid = h_in_window * height_coeff
    lo = _snap(mid * 0.8)
    hi = _snap(mid * 1.2)
    if hi - lo < 0.1:
        hi = round(lo + 0.1, 1)
    return lo, mid, hi


_PHRASES: tuple[tuple[float, str], ...] = (
    (0.3, "shin-high"),
    (0.5, "knee-high"),
    (0.8, "waist-high"),
    (1.2, "chest-high"),
    (1.5, "head-high"),
    (2.0, "overhead"),
    (3.0, "well overhead"),
)


def height_phrase(h_break_mid: float) -> str:
    for limit, phrase in _PHRASES:
        if h_break_mid < limit:
            return phrase
    return "double overhead+"


def wetsuit(sst_c: float) -> str:
    """Industry-standard wetsuit bands (surfspheres-style guide)."""
    if sst_c > 24:
        return "rashguard"
    if sst_c >= 19:
        return "spring / 2mm"
    if sst_c >= 17:
        return "3/2"
    if sst_c >= 14:
        return "4/3"
    if sst_c >= 12:
        return "5/4 + boots"
    if sst_c >= 9:
        return "5/4 hooded + gloves"
    return "6/5 hooded"
