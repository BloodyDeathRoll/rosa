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

from .verify import ang_diff

HS_FLOOR_M = 0.25  # below this, relative spread is noise (tiny abs diffs at flat seas)
COV_MAX = 0.6  # coefficient of variation at/above which agreement is 0

# Direction axis (2026-08-07): the ensemble request has always fetched
# wave_direction for every member (fetch.ENSEMBLE_HOURLY, budgeted at 3 vars x
# 4 models) but nothing read it. The member fan (widest pairwise bearing gap) is
# now measured and recorded on Agreement as a DIAGNOSTIC - it does not score.
# Scoring on it needs a calibration entry first (docs/CALIBRATION.md rule: knobs
# only from CALIBRATION.md + the Stage-0 scorecard): the obvious tolerance
# constant to borrow, transform.EXPOSURE_SHOULDER_DEG, governs per-partition
# bearings inside a spot's swell window, while wave_direction_<member> is the
# member's TOTAL-SEA mean direction - unstable by construction in bimodal seas,
# where two members forecasting the identical sea can sit 60-90 deg apart.
#
# 2026-08-11: the fan is FIVE members, not four - extract_hours appends the ECMWF
# spectral member's mwd beside the four OM bearings, so it now covers the same
# member set as n_models instead of a strict subset. The bimodal-sea caveat above
# applies to all five. Spans recorded before this date span at most four bearings;
# group by the published dir_n before pooling across that boundary.


@dataclass(frozen=True, slots=True)
class Agreement:
    score: float  # 0 (members disagree) .. 1 (tight)
    n_models: int
    hs_spread_m: float  # population stdev of member Hs
    dir_span_deg: float | None = None  # widest pairwise member bearing gap; None = <2 dirs
    # How many bearings that gap spans. NOT the same as n_models, which counts HEIGHT
    # members and includes the ECMWF spectral member (extract.extract_hours) whose bearing
    # is deliberately kept out of the fan. The widest PAIRWISE gap is n-dependent by
    # construction - k members give k(k-1)/2 pairs, so the expected maximum grows with k
    # even at identical disagreement - and k moves with lead time as the shorter-horizon
    # members (gwam ~7.3 d) drop out. A calibration entry pooling spans without k would
    # therefore read member attrition as disagreement.
    n_dirs: int = 0


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


def member_directions_at(hourly: dict, i: int) -> list[float]:
    heights_present = member_suffixes(hourly)
    dirs: list[float] = []
    for suffix in heights_present:
        arr = hourly.get(f"wave_direction_{suffix}")
        if arr is not None and i < len(arr) and arr[i] is not None:
            dirs.append(float(arr[i]) % 360.0)
    return dirs


def direction_span_deg(dirs: list[float]) -> float | None:
    """Widest pairwise bearing gap across members (the member fan), or None if <2."""
    if len(dirs) < 2:
        return None
    return max(abs(ang_diff(a, b)) for i, a in enumerate(dirs) for b in dirs[i + 1 :])


def agreement_from_members(
    heights: list[float], directions: list[float] | None = None
) -> Agreement | None:
    """Agreement over member heights, recording (never scoring) the bearing fan.

    The score is the calibrated Hs CoV score alone; ``dir_span_deg`` rides along
    as the measurement a future calibration entry needs before direction may
    demote anything (see the direction-axis comment above), with ``n_dirs`` - the
    number of bearings that span covers - beside it, because the span alone cannot
    be pooled across hours (see Agreement.n_dirs)."""
    n = len(heights)
    if n < 2:
        return None
    mean = sum(heights) / n
    spread = statistics.pstdev(heights)
    cov = spread / max(mean, HS_FLOOR_M)
    score = max(0.0, min(1.0, 1.0 - cov / COV_MAX))
    dirs = directions or []
    span = direction_span_deg(dirs)
    return Agreement(
        score=score,
        n_models=n,
        hs_spread_m=spread,
        dir_span_deg=span,
        n_dirs=len(dirs),
    )


def agreement_from_heights(heights: list[float]) -> Agreement | None:
    """Height-only agreement (kept for callers/fixtures with no direction data)."""
    return agreement_from_members(heights, None)


def agreement_at(hourly: dict, i: int) -> Agreement | None:
    return agreement_from_members(member_heights_at(hourly, i), member_directions_at(hourly, i))
