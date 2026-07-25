"""Multi-model agreement → forecast confidence (roadmap Stage 1, improvement #7).

Rosa's old "confidence" was a placeholder keyed only on lead time. Real confidence comes
from how much *independent* wave models agree at a given hour: tight spread across GFS-Wave,
EWAM, GWAM and MeteoFrance-WAM = trustworthy; wide spread = a coin toss the UI should flag.

We measure agreement on significant wave height (what surfers care about most), as the
coefficient of variation across members, floored so tiny absolute differences at near-flat
seas don't read as disagreement. `publish` then caps it by the forecast horizon (even
perfect agreement at day 14 isn't high confidence) - the two signals combine, honestly.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

HS_FLOOR_M = 0.25  # below this, relative spread is noise (tiny abs diffs at flat seas)
COV_MAX = 0.6  # coefficient of variation at/above which agreement is 0


@dataclass(frozen=True, slots=True)
class Agreement:
    score: float  # 0 (members disagree) .. 1 (tight)
    n_models: int
    hs_spread_m: float  # population stdev of member Hs


def member_suffixes(hourly: dict) -> list[str]:
    """Model suffixes present as ``wave_height_<suffix>`` columns (the ensemble members)."""
    return sorted({k[len("wave_height_") :] for k in hourly if k.startswith("wave_height_")})


def member_heights_at(hourly: dict, i: int) -> list[float]:
    heights: list[float] = []
    for suffix in member_suffixes(hourly):
        arr = hourly.get(f"wave_height_{suffix}")
        if arr is not None and i < len(arr) and arr[i] is not None and arr[i] >= 0:
            heights.append(float(arr[i]))
    return heights


def agreement_from_heights(heights: list[float]) -> Agreement | None:
    """Agreement over member wave heights, or None if fewer than 2 members reported."""
    n = len(heights)
    if n < 2:
        return None
    mean = sum(heights) / n
    spread = statistics.pstdev(heights)
    cov = spread / max(mean, HS_FLOOR_M)
    score = max(0.0, min(1.0, 1.0 - cov / COV_MAX))
    return Agreement(score=score, n_models=n, hs_spread_m=spread)


def agreement_at(hourly: dict, i: int) -> Agreement | None:
    return agreement_from_heights(member_heights_at(hourly, i))
