"""Pure transform functions: wind classification, swell windowing, breaker height, phrases.

Implements CLAUDE.md "Algorithm specs" exactly; every function here is unit-tested offline.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from functools import lru_cache

from .models import SwellPartition, WindClass
from .physics import breaker_height_over_profile


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


EXPOSURE_SHOULDER_DEG = 25.0  # cosine taper beyond the swell-window edges (Stage 2C soft window)


def exposure_weight(
    direction_deg: float,
    window: tuple[float, float],
    shoulder_deg: float = EXPOSURE_SHOULDER_DEG,
) -> float:
    """Soft exposure response (Stage 2C): 1.0 for a swell inside the spot's ``swell_window``,
    then a cosine taper to 0 over ``shoulder_deg`` just beyond each edge - so a swell a few
    degrees outside the hand-tuned arc still contributes instead of being hard-dropped. Staying
    flat inside the arc keeps the existing per-spot tuning (and its calibration) intact."""
    if in_window(direction_deg, window):
        return 1.0
    lo, hi = window
    d = direction_deg % 360
    beyond = min(angle_diff(d, lo), angle_diff(d, hi))  # distance past the nearest edge
    if beyond >= shoulder_deg:
        return 0.0
    return math.cos((beyond / shoulder_deg) * (math.pi / 2.0))


SPREAD_QUADRATURE_N = 41  # samples across +-3 sigma - the taper has kinks, so sample evenly


@lru_cache(maxsize=200_000)
def _energy_fraction(mean_deg: int, sigma_deg: int, lo: float, hi: float, shoulder: float) -> float:
    """Share of a partition's energy that lands inside the window once the swell's
    directional spread is integrated. Cached on whole degrees - the inputs repeat
    endlessly across hours and spots."""
    sigma = max(1.0, float(sigma_deg))
    num = den = 0.0
    for i in range(SPREAD_QUADRATURE_N):
        off = -3.0 * sigma + (6.0 * sigma) * i / (SPREAD_QUADRATURE_N - 1)
        w = math.exp(-0.5 * (off / sigma) ** 2)
        den += w
        num += w * exposure_weight((mean_deg + off) % 360.0, (lo, hi), shoulder)
    return num / den


def spread_exposure(
    p: SwellPartition,
    window: tuple[float, float],
    shoulder_deg: float = EXPOSURE_SHOULDER_DEG,
) -> float:
    """Energy fraction of one partition that actually reaches the spot.

    A partition is not a single bearing: its energy fans out roughly +-20-35 deg
    about the mean (see spectral.parametric_spread_deg), so a swell whose mean sits
    outside the arc still delivers the part of its fan that falls inside. Treating
    it as a pencil beam is what let a 1.9 m sea offshore render as 0.0-0.1 m of
    surf at Pipeline while Surfline called 0.3-0.6 m (2026-07-29). Energy units:
    take sqrt() where an amplitude weight is wanted."""
    from .spectral import parametric_spread_deg

    return _energy_fraction(
        round(p.direction_deg) % 360,
        round(parametric_spread_deg(p)),
        window[0],
        window[1],
        shoulder_deg,
    )


def arriving_direction(direction_deg: float, window: tuple[float, float]) -> float:
    """Where the energy that reaches the spot actually comes from.

    Inside the arc that's the swell's own bearing. Outside it, only the part of
    the fan that falls inside arrives, so it comes in over the nearer edge - and
    it must be measured from there, or the refraction step would still treat the
    swell as arriving from behind the beach and cancel what the fan delivered."""
    if in_window(direction_deg, window):
        return direction_deg % 360
    lo, hi = window
    d = direction_deg % 360
    return lo if angle_diff(d, lo) <= angle_diff(d, hi) else hi


def energy_in_window(partitions: tuple[SwellPartition, ...], window: tuple[float, float]) -> float:
    return sum(p.height_m**2 * p.period_s * spread_exposure(p, window) for p in partitions)


def height_in_window(partitions: tuple[SwellPartition, ...], window: tuple[float, float]) -> float:
    """Combined significant height of the energy that reaches the spot (RMS combination)."""
    return math.sqrt(sum(p.height_m**2 * spread_exposure(p, window) for p in partitions))


TE_OVER_TP = 0.9  # Te ≈ 0.9·Tp for a JONSWAP-ish spectrum (standard ocean-engineering ratio)
# Energy in one wavelength per metre of crest: E*L = (rho*g/16)*H^2 * (g*Te^2/2pi), which is
# ~0.98*H^2*Te^2 kJ/m for rho = 1025 kg/m3, g = 9.81. Identical physics to the deep-water flux
# P = 0.49*H^2*Te kW/m, since E*L = 2*P*Te - energy is just how surf forecasts quote it.
KJ_PER_M_COEFF = 0.98


def energy_period(p: SwellPartition) -> float:
    """Energy period Te (= Tm-1,0), the period wave energy/power is actually defined on.

    Derived from the partition's PEAK period where the model publishes one; the mean period
    is the fallback only. This matters: Open-Meteo's mean period runs well below the peak for
    the same partition (Med swell 5.8 s mean vs 8.4 s peak), and energy goes as Te², so keying
    off the mean understates a real swell badly."""
    if p.peak_period_s is not None:
        return TE_OVER_TP * p.peak_period_s
    return p.period_s


def partition_closure(
    partitions: tuple[SwellPartition, ...], total_hs_m: float | None
) -> float | None:
    """What fraction of the source's own sea the published partitions actually account for.

    Significant height combines in energy, so partitions that cover the whole spectrum satisfy
    Hs_total = sqrt(sum Hs_i^2). Open-Meteo publishes four partition slots (windsea + three
    swells) and, in complex multi-modal seas, does not fit all of its energy into them: at
    Hikkaduwa the partitions RMS to ~1.6 m against its own 2.2-2.3 m total. The transform only
    ever sees partitions, so that missing energy is invisible to the forecast.

    Returns RMS(partitions)/total, a ratio of HEIGHTS: 1.0 = the partitions are the whole sea.
    Read it in energy when judging severity - the square is the energy fraction, so 0.73 of the
    height is only ~0.53 of the energy. Values slightly above 1.0 occur through rounding and are
    not meaningful. None when the source published no total (older fixtures).

    Diagnostic only - it deliberately does NOT feed the forecast. A low ratio says energy is
    missing but not its direction or period, and inventing those is exactly what Rosa does not
    do (docs/CALIBRATION.md 2026-07-30)."""
    if total_hs_m is None or total_hs_m <= 0:
        return None
    rms = math.sqrt(sum(p.height_m**2 for p in partitions))
    return rms / total_hs_m


def energy_kj_per_m(partitions: tuple[SwellPartition, ...], window: tuple[float, float]) -> float:
    """Deep-water wave energy reaching the spot, kJ per metre of crest - the kJ figure
    surf forecasts quote. Weighted by the same spread-aware exposure as the breaker
    height, so a row can never show real surf next to 0 kJ."""
    return sum(
        KJ_PER_M_COEFF * p.height_m**2 * energy_period(p) ** 2 * spread_exposure(p, window)
        for p in partitions
    )


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
            (p.height_m * period_quality(p.period_s)) ** 2 * spread_exposure(p, window)
            for p in partitions
        )
    )


GRAZING_INCIDENCE_DEG = 85.0  # steepest approach the physics will still march (see below)

# Period-power exponent (was the q(T) exponent, calibration row 2). 1.4 until 2026-08-02, when
# closing the depth march with a breaker index made the old value wrong: 1.4 had been fitted on
# top of a march that stopped at the GEBCO floor and therefore under-called every spot, so part
# of what it was "measuring" was that truncation. Refitted against the same 5 frames with the
# march closed - see docs/CALIBRATION.md 2026-08-02. Because rideability caps at 1.0 above 10 s,
# this exponent is in practice an Israel/Portugal knob: over the fleet it moves Israel x1.39 ->
# x1.06 and Portugal x1.48 -> x1.21 while Costa Rica/Nicaragua/California barely stir. 2.2 is
# the value that leaves the CALIBRATED region where its graded frames put it while the closure
# corrects the long-period regions that never had an eye frame.
RIDEABILITY_EXP = 2.2


def period_rideability(period_s: float) -> float:
    """Rideable fraction of a partition's physical breaker height (Stage 2B period-power factor).

    The physics gives the roughly-correct *physical* breaker height, but short-period windswell
    carries far less energy flux (P ~ H^2 * T) and is fast and directionally spread, so it
    "surfs" well below that height; long-period groundswell rides at full height. This is the
    grounded reframing of the old ``q(T)``: because the physics now does the shoaling, this
    factor only ATTENUATES (cap 1.0) - it can never push a wave past its depth-limited break.
    A proxy for wave power / cleanliness; retired at Stage 3 when spectral directional spread
    and power replace it. Tune the exponent from docs/CALIBRATION.md only.

    Feed it ``rideability_period(p)``, not the partition's mean period - see below."""
    return min(1.0, max(0.3, (period_s / 10.0) ** RIDEABILITY_EXP))


def rideability_period(p: SwellPartition) -> float:
    """The period ``period_rideability`` keys on: the partition's PEAK period, falling back
    to the mean only where the model publishes no Tp (Stage 2E, 2026-07-30).

    Tp is the period of the energy-carrying waves a surfer actually rides, and Open-Meteo's
    mean period runs far below it for the same partition (Med swell 5.9 s mean vs 8.4 s peak).
    Keying the attenuation on the mean under-called real Med swell 1.6-2x against the user's
    own eyes at three graded frames (Hilton 07-25 + 07-26, Poleg 07-27) and every mean-keyed
    candidate missed all three, at any exponent - docs/CALIBRATION.md 2026-07-30. It also puts the
    height path on the same period family as ``energy_period`` and the published kJ, which
    already keyed off Tp.

    The effect is confined to short-period seas: rideability saturates at its 1.0 cap above
    ~10 s, so every partition at or above ~8 s is bit-identical to the old behaviour."""
    return p.peak_period_s if p.peak_period_s is not None else p.period_s


# Inverse of the Komar & Gaughan height exponent: Hb ~ (T H0^2)^0.4, so Hb^2.5 is linear in
# the offshore energy flux T*H0^2. Summing partitions in Hb^2.5 and taking the 0.4 power is
# therefore *exactly* "add the offshore energy, then apply the breaker index once" - which is
# the only way to combine that does not run the nonlinear index N times over. (The
# depth-limited branch of the march is not a power law, so for the 0-3% of hours that break
# inside the profile this is an approximation rather than an identity.)
FIELD_ENERGY_EXP = 2.5


def field_coherence(delta_deg: float, spread_a_deg: float, spread_b_deg: float) -> float:
    """How much two swell trains behave as ONE wave field, from their angular separation.

    1.0 when they arrive from the same bearing, tapering to 0 once their directional fans
    no longer overlap (separation >= the sum of the two spreads). Deliberately smooth: a
    hard threshold makes the published height jump ~0.2 m on the 1-3 deg direction wander
    Open-Meteo's partitions show all the time (docs/CALIBRATION.md 2026-07-29), while this
    taper moves it ~0.02 m."""
    arc = spread_a_deg + spread_b_deg
    if delta_deg >= arc:
        return 0.0
    if arc <= 0.0:
        return 1.0
    return math.cos((delta_deg / arc) * (math.pi / 2.0)) ** 2


def breaker_height_from_profile(
    partitions: tuple[SwellPartition, ...],
    window: tuple[float, float],
    shore_normal: float,
    wet_depths: list[float],
    *,
    rideability: Callable[[SwellPartition], float] | None = None,
) -> float:
    """Breaker height of the dominant WAVE FIELD (Stage 2B hybrid + the 2026-08-03 combine
    fix): real physics for the geometry (shoaling + refraction + depth-limited breaking over
    the spot's bathymetry) times a period-power rideability factor for windswell quality.

    Incidence is the partition's approach angle relative to the spot's shore normal; the
    physics march zeroes anything arriving from behind it (>= 90 deg).

    **Partitions are combined by field, not RMS'd.** Until 2026-08-03 this returned
    ``sqrt(sum Hb_i^2)`` - each partition marched to its own breaker height and those heights
    then added in energy. That is wrong twice over. It applies the breaker index once per
    partition, and the index is sublinear in height (Hb ~ H0^0.8), so N small partitions
    transform to more surf than the one sea they actually are; and it assumes two trains
    crossing at 55 deg merge into a single bigger breaking wave, when they in fact break at
    different angles on different parts of the beach and a surfer rides one or the other.
    At Santa Teresa on 2026-08-02 the two effects together published 1.0-1.8 m against
    Surfline's 0.6-1.1 m and the user's own ">1 m" (docs/CALIBRATION.md 2026-08-03).

    So: trains whose directional fans still overlap are one field and their energy adds
    (``FIELD_ENERGY_EXP`` makes that sum exactly "combine offshore, transform once");
    trains further apart than that are separate crossing seas, discounted by
    ``field_coherence`` toward the dominant one alone. A single in-window partition is
    bit-identical to the old behaviour - only multi-swell hours move.

    ``rideability`` lets the Stage-2E experiment harness (experiment.py) inject candidate
    attenuation factors. Production never passes it: the default is exactly the shipping
    ``period_rideability(rideability_period(p))`` - peak-keyed since 2026-07-30."""
    from .spectral import parametric_spread_deg

    breakers: list[tuple[float, float, float]] = []  # (Hb, direction, spread)
    for p in partitions:
        w = math.sqrt(spread_exposure(p, window))  # energy fraction -> amplitude
        if w <= 0.0:
            continue
        # the energy that arrives comes from inside the arc, so the angle it
        # arrives at is the arc's, not the fan's mean - a swell whose mean sits
        # behind the headland still refracts in from the open side
        incidence = angle_diff(arriving_direction(p.direction_deg, window), shore_normal)
        # A window reaching past the shore normal is the spot's own local knowledge
        # saying that arc does reach the break (wrapping points, bay mouths), so
        # honour it at grazing incidence rather than letting the derived normal
        # cancel it outright - refraction leaves little, but never nothing.
        incidence = min(incidence, GRAZING_INCIDENCE_DEG)
        hb = breaker_height_over_profile(p.height_m, p.period_s, incidence, wet_depths)
        factor = (
            rideability(p) if rideability is not None else period_rideability(rideability_period(p))
        )
        hb *= factor * w
        if hb > 0.0:
            breakers.append((hb, p.direction_deg, parametric_spread_deg(p)))
    if not breakers:
        return 0.0
    _, dir_dom, spread_dom = max(breakers, key=lambda b: b[0])
    total = sum(
        field_coherence(angle_diff(d, dir_dom), s, spread_dom) * hb**FIELD_ENERGY_EXP
        for hb, d, s in breakers
    )
    return total ** (1.0 / FIELD_ENERGY_EXP)


def dominant_partition(
    partitions: tuple[SwellPartition, ...], window: tuple[float, float]
) -> SwellPartition | None:
    """The exposure-weighted dominant partition - includes swells within the soft-window
    shoulder so a just-outside swell can drive period/flat-gating consistently with the
    breaker height (Stage 2C)."""
    scored = [(p, p.height_m**2 * p.period_s * spread_exposure(p, window)) for p in partitions]
    scored = [(p, s) for p, s in scored if s > 0]
    if not scored:
        return None
    return max(scored, key=lambda ps: ps[1])[0]


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
