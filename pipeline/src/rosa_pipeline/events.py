"""Swell-event detection (CLAUDE.md algorithm spec) — feeds alerts + swell stories.

An event is a contiguous >= 12 h window where in-window energy is >= 2x the trailing
48 h median, with rating >= GOOD at the peak. Emitted as {start, peak, end, peak_height,
direction} into the published payload; the frontend/alerts layer renders it.

Implementation choices (documented, not in the spec):
- The trailing median needs >= MIN_TRAILING_H hours of history, so an event already in
  progress at the very start of the series can't be detected — honest: with no baseline
  there is no "2x baseline".
- The median is floored (MEDIAN_FLOOR) so a dead-flat spell doesn't make 2x-nothing
  qualify every ripple; the GOOD-at-peak gate does the rest.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from .models import ScoredHour

MIN_EVENT_H = 12.0  # contiguous elevated window must span at least this
TRAILING_H = 48.0  # baseline window
MIN_TRAILING_H = 12  # need at least this many trailing hours to call a baseline
ENERGY_FACTOR = 2.0  # elevated = energy >= factor x trailing median
MEDIAN_FLOOR = 0.5  # m^2*s — 2x a dead-flat baseline is still nothing
GOOD_RATING = 50


@dataclass(frozen=True, slots=True)
class SwellEvent:
    start: datetime
    peak: datetime
    end: datetime
    peak_height_m: float  # h_break midpoint at the peak hour
    direction_deg: float | None  # dominant partition direction at the peak
    peak_rating: int
    peak_bucket: str


def _elevated(scored: list[ScoredHour]) -> list[bool]:
    """Per hour: is in-window energy >= 2x the (floored) trailing 48 h median?"""
    out: list[bool] = []
    for i, s in enumerate(scored):
        t0 = s.hour.time - timedelta(hours=TRAILING_H)
        trailing = [p.energy for p in scored[:i] if p.hour.time >= t0]
        if len(trailing) < MIN_TRAILING_H:
            out.append(False)
            continue
        baseline = max(median(trailing), MEDIAN_FLOOR)
        out.append(s.energy >= ENERGY_FACTOR * baseline)
    return out


def detect_events(scored: list[ScoredHour]) -> list[SwellEvent]:
    """Contiguous elevated runs >= 12 h whose peak hour rates GOOD or better."""
    if not scored:
        return []
    elevated = _elevated(scored)
    events: list[SwellEvent] = []
    i = 0
    n = len(scored)
    while i < n:
        if not elevated[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and elevated[j + 1]:
            j += 1
        run = scored[i : j + 1]
        span_h = (run[-1].hour.time - run[0].hour.time).total_seconds() / 3600.0
        if span_h >= MIN_EVENT_H:
            peak = max(run, key=lambda s: s.energy)
            if peak.rating >= GOOD_RATING:
                events.append(
                    SwellEvent(
                        start=run[0].hour.time,
                        peak=peak.hour.time,
                        end=run[-1].hour.time,
                        peak_height_m=round(peak.h_break_mid, 1),
                        direction_deg=(
                            peak.dominant.direction_deg if peak.dominant is not None else None
                        ),
                        peak_rating=peak.rating,
                        peak_bucket=peak.bucket,
                    )
                )
        i = j + 1
    return events
