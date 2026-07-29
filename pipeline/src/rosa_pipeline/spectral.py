"""Spectral-lite derivations from the ECMWF wave member (Stage 3b) - pure functions.

Three honest, bounded recoveries of spectral information from what the free world
publishes (docs/rosa-stage3-plan.md §3b; full 2-D spectra arrive only when Stage 4 runs
WW3/SWAN ourselves):

- **Missed-swell guard**: the six period-banded heights (h1012..h2530) are a coarse 1-D
  spectrum over the whole groundswell range - if a band carries height that no reported
  partition accounts for, the sorter dropped or merged a swell, and we surface it.
- **Consistency proxy**: spectral narrowness estimated from the ratios of three integral
  periods (Tp/Tm02, Tm-1,0/Tm02) → the "setty vs. lully" 0-100. Displayed, never folded
  into the rating (orthogonal axis, roadmap improvement).
- **Parametric spread**: an ASSUMED directional spread per partition class (windsea wide,
  long swell narrow) - modeled, not observed; the validation against NDBC measured
  spectra publishes its error bound (plan acceptance), until then label it modeled.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .models import SpectralSea, SwellPartition

# (param, period lo, period hi) - ECMWF h<lo><hi>: Hs of all waves with T in [lo, hi] s
BANDS: tuple[tuple[str, float, float], ...] = (
    ("h1012", 10.0, 12.0),
    ("h1214", 12.0, 14.0),
    ("h1417", 14.0, 17.0),
    ("h1721", 17.0, 21.0),
    ("h2125", 21.0, 25.0),
    ("h2530", 25.0, 30.0),
)
# a partition credits a band if its period falls within this pad of the band's edges -
# partition peaks are quantized and a real swell's energy straddles band boundaries
BAND_MATCH_PAD_S = 1.0
# unaccounted band height below this is spectral noise, not a missed swell
MISSED_MIN_HS_M = 0.3

# consistency anchors: period-ratio widths for reference spectra. Narrow anchors are an
# old clean groundswell (all three periods converge); broad anchors are a PM/JONSWAP-wide
# windsea (Tp/Tm02 ~ 1.3-1.4, Tm-1,0/Tm02 ~ 1.1-1.15). Proxy constants - validate against
# buoy spectra (plan acceptance) and tune from the calibration log only.
W1_NARROW, W1_BROAD = 0.15, 0.50  # w1 = Tp/Tm02 - 1
W2_NARROW, W2_BROAD = 0.03, 0.15  # w2 = Tm-1,0/Tm02 - 1

# assumed directional spread (one-sided sigma, degrees). Seeded from literature
# (windsea 30-40, long groundswell 10-15 per Ewans/Forristall), then CALIBRATED against
# measured buoy sigma@peak (CALIBRATION.md 2026-07-23 spectra sweep, 12 stations,
# ~22k hrs): the Datawell Waverider stations - the clean directional instruments -
# converge on ~24 deg for >=14 s peaks (Harvest n=534: 25.4, Torrey Pines n=937: 23.5),
# so the long-swell value moved 15 -> 24; the other classes measured within a few
# degrees of their assumptions and stand. Discus-hull sigma reads 39-64 deg for the
# same class - instrument broadening, not truth; never tune from those.
SPREAD_WINDSEA_DEG = 35.0
SPREAD_SHORT_SWELL_DEG = 25.0  # T < 10 s
SPREAD_MID_SWELL_DEG = 20.0  # 10-14 s
SPREAD_LONG_SWELL_DEG = 24.0  # >= 14 s (measured, was 15 from literature)


@dataclass(frozen=True, slots=True)
class MissedSwell:
    period_lo_s: float
    period_hi_s: float
    height_m: float  # unaccounted significant height in the band


def _partition_period(p: SwellPartition) -> float:
    """Peak period when published (band heights bin by spectral component period, which a
    partition's energy concentrates near its peak), else the mean period."""
    return p.peak_period_s if p.peak_period_s is not None else p.period_s


def missed_swells(sea: SpectralSea, partitions: tuple[SwellPartition, ...]) -> list[MissedSwell]:
    """Band energy the partitions can't explain - banded height cannot hide from the sorter.

    Per band, the accounted height is the RMS of partitions whose period falls inside the
    (padded) band; crediting each partition's FULL height to its band is deliberately
    conservative - a guard must not cry wolf when a long swell's energy merely straddles
    band edges. The residual sqrt(band^2 - accounted^2) above MISSED_MIN_HS_M is surfaced."""
    bands = dict(sea.bands)
    out: list[MissedSwell] = []
    for param, lo, hi in BANDS:
        band_h = bands.get(param)
        if band_h is None or band_h < MISSED_MIN_HS_M:
            continue
        accounted_sq = sum(
            p.height_m**2
            for p in partitions
            if lo - BAND_MATCH_PAD_S <= _partition_period(p) <= hi + BAND_MATCH_PAD_S
        )
        residual = math.sqrt(max(0.0, band_h**2 - accounted_sq))
        if residual >= MISSED_MIN_HS_M:
            out.append(MissedSwell(period_lo_s=lo, period_hi_s=hi, height_m=round(residual, 2)))
    return out


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def consistency_from_periods(pp1d: float, mwp: float, mp2: float) -> int:
    """The consistency formula on bare periods - shared by the model member and the
    buoy-spectra validation harness (which feeds it MEASURED Tp/Tm-1,0/Tm02)."""
    w1 = pp1d / mp2 - 1.0
    w2 = mwp / mp2 - 1.0
    s1 = _clamp01((W1_BROAD - w1) / (W1_BROAD - W1_NARROW))
    s2 = _clamp01((W2_BROAD - w2) / (W2_BROAD - W2_NARROW))
    return round(100.0 * (s1 + s2) / 2.0)


def consistency_score(sea: SpectralSea) -> int | None:
    """Groundswell consistency ("setty vs. lully") 0-100 from spectral narrowness.

    For a narrow spectrum the three integral periods converge (ratios → 1): energy arrives
    in organized long-crested sets. A broad or mixed spectrum spreads them apart: lully,
    disorganized. Two ratio widths are scored against reference anchors and averaged -
    pp1d alone is noisy in bimodal seas (the peak jumps between partitions), so the stable
    Tm-1,0/Tm02 ratio carries equal weight. None when the member lacks any of the periods."""
    if sea.pp1d is None or sea.mp2 is None or sea.mwp is None or sea.mp2 <= 0:
        return None
    return consistency_from_periods(sea.pp1d, sea.mwp, sea.mp2)


def parametric_spread_deg(p: SwellPartition) -> float:
    """Assumed directional spread for a partition class - MODELED, not observed."""
    if p.kind == "wind":
        return SPREAD_WINDSEA_DEG
    t = _partition_period(p)
    if t < 10.0:
        return SPREAD_SHORT_SWELL_DEG
    if t < 14.0:
        return SPREAD_MID_SWELL_DEG
    return SPREAD_LONG_SWELL_DEG
