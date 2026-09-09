"""Linear-wave nearshore physics (accuracy roadmap Stage 2B).

Pure primitives for transforming an offshore swell partition to its breaker height over a
depth profile: the dispersion relation, phase/group celerity, shoaling, refraction (Snell),
and depth-limited breaking. This is what retires the single ``height_coeff`` and the ``q(T)``
period fudge - period now enters the height once, physically, through the group celerity.

Conventions:
* depth ``d`` in metres, positive down; period ``T`` in seconds; heights in metres.
* angles in degrees at the public boundary, radians internally.
* ``incidence`` = angle between the swell's approach and the shore normal; 0 = straight in.

All functions are pure and unit-tested against the deep-/shallow-water limits.
"""

from __future__ import annotations

import math

import numpy as np

GRAVITY = 9.81  # m/s^2
BREAK_GAMMA = 0.78  # depth-limited breaking index: H_break ~= gamma * depth (spilling default)


def angular_frequency(period_s: float) -> float:
    return 2.0 * math.pi / period_s


def wavenumber(period_s: float, depth_m: float, *, iterations: int = 12) -> float:
    """Solve the linear dispersion relation ω² = g·k·tanh(k·d) for k (Newton iteration).

    Seeded with the deep-water guess k₀ = ω²/g; converges in a handful of steps for any
    depth. Raises on non-positive depth or period (a dry ray point has no wavenumber)."""
    if depth_m <= 0 or period_s <= 0:
        raise ValueError(f"need positive depth and period (got d={depth_m}, T={period_s})")
    omega = angular_frequency(period_s)
    omega2 = omega * omega
    k = omega2 / GRAVITY  # deep-water seed
    for _ in range(iterations):
        tanh = math.tanh(k * depth_m)
        f = GRAVITY * k * tanh - omega2
        sech2 = 1.0 - tanh * tanh
        fprime = GRAVITY * tanh + GRAVITY * k * depth_m * sech2
        step = f / fprime
        k -= step
        if k <= 0:  # overshoot guard - fall back toward the deep-water value
            k = omega2 / GRAVITY
    return k


def wave_state(period_s: float, depth_m: float) -> tuple[float, float, float]:
    """(k, C, Cg) from ONE dispersion solve.

    The random-sea march needs the WAVENUMBER as well as both celerities at every substep -
    k sets the friction orbital velocity and the Battjes-Janssen Hmax - and it was asking
    ``wavenumber`` and then ``celerities`` separately, which solved w^2 = g*k*tanh(k*d) twice
    for the same (T, d). Measured 2026-08-29: 1,097,443 wavenumber calls for ONE spot against
    550,743 celerities calls, exactly 2x, and 75% of a spot's 6.3 s went into that march.
    Returning k alongside makes it one solve. Identical arithmetic, bit-identical results."""
    k = wavenumber(period_s, depth_m)
    kd = k * depth_m
    c = angular_frequency(period_s) / k
    if 2.0 * kd > 350.0:  # sinh overflows and the ratio vanishes - deep-water n = 1/2
        return k, c, 0.5 * c
    n = 0.5 * (1.0 + 2.0 * kd / math.sinh(2.0 * kd))
    return k, c, n * c


def celerities(period_s: float, depth_m: float) -> tuple[float, float]:
    """(C, Cg) from ONE dispersion solve - the k-free view of ``wave_state``.

    The shoaling march needs both at every sampled depth and used to ask for them separately,
    which solved w^2 = g*k*tanh(k*d) twice for the same (T, d). Identical arithmetic, half the
    Newton iterations; ``phase_speed``/``group_speed`` stay as the single-value views."""
    _, c, cg = wave_state(period_s, depth_m)
    return c, cg


def phase_speed(period_s: float, depth_m: float) -> float:
    """C = ω / k."""
    return celerities(period_s, depth_m)[0]


def group_speed(period_s: float, depth_m: float) -> float:
    """Cg = n·C, n = ½(1 + 2kd/sinh 2kd). → gT/4π in deep water, √(gd) in shallow."""
    return celerities(period_s, depth_m)[1]


def shoaling_coeff(period_s: float, depth_ref_m: float, depth_m: float) -> float:
    """Ks = √(Cg_ref / Cg) - conservation of energy flux from the reference depth inward."""
    return math.sqrt(group_speed(period_s, depth_ref_m) / group_speed(period_s, depth_m))


def refracted_angle(
    period_s: float, depth_ref_m: float, depth_m: float, incidence_deg: float
) -> float:
    """Snell's law over celerity: sin(a) / C = const. Returns the angle at ``depth_m`` in
    degrees, or 90 if the ray refracts to grazing (its energy no longer reaches the break)."""
    c_ref = phase_speed(period_s, depth_ref_m)
    c = phase_speed(period_s, depth_m)
    sin_a = math.sin(math.radians(incidence_deg)) * c / c_ref
    if sin_a >= 1.0:
        return 90.0
    return math.degrees(math.asin(sin_a))


def refraction_coeff(incidence_ref_deg: float, incidence_deg: float) -> float:
    """Kr = sqrt(cos(a_ref) / cos(a)) - crest-spreading loss as the ray bends toward normal."""
    a_ref = math.radians(incidence_ref_deg)
    a = math.radians(incidence_deg)
    cos_a = math.cos(a)
    if cos_a <= 0:
        return 0.0
    return math.sqrt(math.cos(a_ref) / cos_a)


KOMAR_GAUGHAN_COEFF = 0.39  # Komar & Gaughan (1972), empirical fit to lab + field breakers
KOMAR_GAUGHAN_ITERS = 20  # refraction depends on the breaking depth, which depends on Kr


def deep_water_equivalent(height_m: float, period_s: float, depth_ref_m: float) -> float:
    """Undo shoaling back to deep water: H0 = H(d) x sqrt(Cg(d) / Cg_deep).

    Open-Meteo reports a partition height at a grid cell that is usually, but not always, in
    deep water for that period. Breaker indices are defined on the deep-water height, so the
    reference height has to be de-shoaled first or a spot whose profile starts shallow gets a
    silently inflated H0. Where the reference really is deep this is a no-op to 3 decimals."""
    cg_deep = GRAVITY * period_s / (4.0 * math.pi)
    return height_m * math.sqrt(group_speed(period_s, depth_ref_m) / cg_deep)


def breaker_height_komar_gaughan(
    offshore_height_m: float,
    period_s: float,
    incidence_deg: float,
    depth_ref_m: float,
    *,
    gamma: float = BREAK_GAMMA,
) -> float:
    """Breaker height from the deep-water sea state alone: Hb = 0.39 g^0.2 (T H0'^2)^0.4.

    Needed because GEBCO stops far short of the surf zone. Its shallowest sample sits at a
    median of 7 m across the fleet (13 m at Santa Teresa), so a wave would have to be ~5.5 m
    to reach gamma*d inside the profile, and in 97-100% of published hours the march never
    breaks at all - it just returns the height at the last sampled depth. That depth is the
    worst possible place to stop: it is inside the shoaling dip (Ks ~0.93) and has already
    taken the refraction loss (Kr ~0.80 at 60 deg), but none of the shallow-water growth that
    actually makes a breaker. Waves arrived SMALLER than they started, x0.74 at Santa Teresa
    and x0.69 fleet-median (2026-08-02, docs/CALIBRATION.md).

    Komar & Gaughan closes that gap without inventing bathymetry: it is an empirical fit over
    lab and field breakers that needs only H0, T and the approach angle. Refraction is iterated
    because Kr must be evaluated at the breaking depth and that depth is what we are solving
    for; ``incidence_deg`` is taken at ``depth_ref_m``, the same assumption the march makes.

    Extending the profile with invented shallow samples was the alternative and was rejected:
    the answer would then be exactly gamma x whatever final depth was made up."""
    if offshore_height_m <= 0 or period_s <= 0 or incidence_deg >= 90.0:
        return 0.0
    h0 = deep_water_equivalent(offshore_height_m, period_s, depth_ref_m)
    a_ref = math.radians(incidence_deg)
    c_ref = phase_speed(period_s, depth_ref_m)
    hb = KOMAR_GAUGHAN_COEFF * GRAVITY**0.2 * (period_s * h0**2) ** 0.4
    for _ in range(KOMAR_GAUGHAN_ITERS):
        if hb <= 0.0:
            # h0 SQUARED underflowed to zero, so hb did too and hb/gamma is not a depth to
            # ask a wavenumber for. Reachable since the random-sea march (2026-08-28): it
            # feeds this the friction-attenuated H0, and a sub-second wind-wave period -
            # 0.25 s at beit-yanai, and OM publishes wind_wave_period down to 0.0 - drives
            # atten to ~1e-210, which squares to exactly 0.0. A sea that thin has no
            # breaker, which is what the caller's max() then reads.
            return 0.0
        # The implied breaking depth hb/gamma can be DEEPER than the reference when the
        # reference sits shallow and the sea is big. Snell forward from d_ref has nothing
        # to say about deeper water - the march skips such samples (d > d_ref) for exactly
        # this reason: a faster celerity than c_ref hands back sin_a just under 1 and
        # Kr = sqrt(cos a_ref / cos alpha) is unbounded there (15.8 m from a 5.9 m sea at
        # 60 deg over a 7.2 m reference, then a cliff to the march's 5.6 m half a degree
        # later). Clamp the celerity at the reference's: breaking at-or-beyond the
        # reference refracts as Kr = 1, continuous at the handoff (c -> c_ref as
        # hb/gamma -> d_ref). Unreachable at today's committed profiles (shallowest
        # reference 18 m), so this changes nothing the fleet publishes.
        sin_a = math.sin(a_ref) * min(phase_speed(period_s, hb / gamma), c_ref) / c_ref
        if sin_a >= 1.0:
            return 0.0
        kr = math.sqrt(math.cos(a_ref) / math.cos(math.asin(sin_a)))
        nxt = KOMAR_GAUGHAN_COEFF * GRAVITY**0.2 * (period_s * (kr * h0) ** 2) ** 0.4
        if abs(nxt - hb) < 1e-4:
            return nxt
        hb = nxt
    return hb


# Wind's effect on the breaker (open item 4; product call 2026-08-03: a blown-out sea reads
# smaller). Douglass (1990), "Influence of wind on breaking waves", J. Waterway Port Coastal
# Ocean Eng 116(6):651-663, blew onshore and offshore wind over a laboratory nearshore slope:
# onshore wind moves the break point OFFSHORE and DECREASES the breaker height-to-depth ratio
# gamma_b, offshore wind does the reverse. Feddersen & Veron (2005, J. Phys. Oceanogr. 35:1223)
# summarise the magnitudes - break-point location up to 40%, gamma_b up to 100% across the
# tested range - and state the U/c range is applicable to a natural nearshore environment. Net
# effect on the height (their wording): "with offshore wind not only do waves break closer to
# shore, but they have larger breaking-wave heights."
#
# Three things that measurement fixes, which the first attempt at this (a raw-kph multiplier on
# the published height, 2026-08-03, removed same day) got wrong:
#   * it scales on DIMENSIONLESS wind over wave speed, U_n/sqrt(g*h_b), not on kph;
#   * it is SIGNED - offshore wind raises the breaker, it is not a no-op;
#   * it belongs on the breaker height, which both branches of the hybrid produce.
#
# WIND_BREAKER_COEFF IS 0.0 ON PURPOSE - the term is inert until something can set it.
# Nothing Rosa owns can: the buoys say Open-Meteo's offshore Hs is NOT wind-biased (+6.4% ->
# +1.1% relative bias from calm to 12.5 m/s over 2,001 paired hours, so the effect is entirely
# nearshore and no buoy can reach it), and all five calibration frames sit at 1.9-23 kph, where
# any sane wind term is ~1.0 - grading them would return "every candidate identical", which
# looks like validation and is not. Douglass's number is a 1:8 laboratory beach and is an upper
# bound, not our coefficient. **To switch this on: grade 2-3 frames in a real onshore blow
# (>30 kph) and fit it.** docs/CALIBRATION.md 2026-08-03.
WIND_BREAKER_COEFF = 0.0
WIND_BREAKER_CLAMP = 0.5  # no measurement supports moving the breaker more than +-50%


def wind_breaker_factor(
    wind_normal_ms: float,
    breaking_depth_m: float,
    *,
    coeff: float = WIND_BREAKER_COEFF,
) -> float:
    """Wind's multiplier on breaker height. ``wind_normal_ms`` is the shore-normal component of
    the wind, POSITIVE OFFSHORE (blowing out to sea), negative onshore.

    Keyed on U_n/sqrt(g*h_b), the dimensionless wind-over-wave-speed Douglass parameterised on -
    at a 1.5 m breaking depth a 40 kph onshore wind is about -2.9, comparable to the +-2.3 he
    tested. Returns 1.0 exactly while ``coeff`` is 0."""
    if coeff == 0.0 or breaking_depth_m <= 0 or wind_normal_ms == 0.0:
        return 1.0
    w = wind_normal_ms / math.sqrt(GRAVITY * breaking_depth_m)
    return max(1.0 - WIND_BREAKER_CLAMP, min(1.0 + WIND_BREAKER_CLAMP, 1.0 + coeff * w))


def breaker_height_over_profile(
    offshore_height_m: float,
    period_s: float,
    incidence_deg: float,
    depths_deep_to_shallow: list[float],
    *,
    gamma: float = BREAK_GAMMA,
) -> float:
    """March a swell partition from the deep reference (``depths[0]``) shoreward, shoaling +
    refracting it at each sampled depth, and return the breaker height.

    The wave breaks at the first depth where the transformed height reaches gamma*d (depth-
    limited breaking) -> breaker height = gamma*d there. If it never reaches that within the
    profile it breaks closer to shore than GEBCO resolves, and the profile has nothing left to
    say: ``breaker_height_komar_gaughan`` closes the last stretch from the deep-water sea state
    instead. That branch is not an edge case - it is what runs in 97-100% of published hours
    (2026-08-02). Until then this returned the height at the shallowest sample, which is a
    mid-shelf height, not a breaker height, and was systematically too small.

    **The two answers are reconciled by taking the deeper break, not by branching** (fixed
    2026-08-03). Choosing the march whenever it happened to reach gamma*d made the height jump
    UP as the approach angle got worse - 1.170 -> 1.303 m between 13 and 14 degrees of incidence
    on a profile ending at 1.5 m - because the branches disagree at the crossover. It also let
    the sampling interval set the answer: the march can only break AT a sampled depth, so a
    profile that steps 4 m -> 1 m skips the real break point and clamps a 2 m 14 s swell to
    gamma*1 = 0.78 m, 3.8x below what the same linear theory gives solved continuously (2.98 m).
    51 of 199 committed profiles reach 1-2 m, so that clamp fires on exactly their biggest days.
    A K&G height implying a breaking depth deeper than where the march found one means linear
    shoaling under-called the growth - so the wave broke at the deeper of the two, and the max
    is the physical answer. Continuous across the handoff and monotone in incidence.

    Swell arriving from behind the shore normal (incidence ≥ 90°) contributes nothing."""
    if (
        offshore_height_m <= 0
        or period_s <= 0  # a padded/empty partition (no period) transforms to nothing
        or not depths_deep_to_shallow
        or incidence_deg >= 90.0
    ):
        return 0.0
    d_ref = depths_deep_to_shallow[0]
    c_ref, cg_ref = celerities(period_s, d_ref)
    a_ref = math.radians(incidence_deg)
    sin_a_ref = math.sin(a_ref)
    height = offshore_height_m
    depth_limited = 0.0
    for d in depths_deep_to_shallow:
        if d > d_ref:
            # The ray is not monotone: 88 of the 199 committed profiles dip DEEPER somewhere
            # inside the reference sample (GEBCO shelves, canyons, the 18 km point sitting on a
            # bank). ``depths_deep_to_shallow`` is ordered by DISTANCE, not by depth, so such a
            # sample arrives after the reference the march conserves energy flux from - and
            # shoaling theory has nothing to say about a wave moving back into deeper water.
            # Marching it anyway makes Snell hand back sin_a just under 1, and Kr =
            # sqrt(cos a_ref / cos alpha) is UNBOUNDED as alpha -> 90: measured Kr up to 8.8 at
            # cantinho-bah-a and transformed heights of 43-193 m from 1-4 m swells at 11 spots,
            # which then "break" at gamma*d in 32-247 m of water. Skip it, exactly as the
            # grazing case below is skipped; the shallower samples still decide the break.
            continue
        c, cg = celerities(period_s, d)
        sin_a = sin_a_ref * c / c_ref
        if sin_a >= 1.0:
            continue  # refracted to grazing at this depth - skip
        alpha = math.asin(sin_a)
        ks = math.sqrt(cg_ref / cg)
        kr = math.sqrt(math.cos(a_ref) / math.cos(alpha))
        height = offshore_height_m * ks * kr
        if height >= gamma * d:
            depth_limited = gamma * d
            break
    return max(
        depth_limited,
        breaker_height_komar_gaughan(
            offshore_height_m, period_s, incidence_deg, d_ref, gamma=gamma
        ),
    )


# --- Random-sea surf height (2026-08-28) -------------------------------------------------
#
# The march above transforms ONE monochromatic wave carrying the partition's whole Hs, and
# breaker_height_komar_gaughan closes the unresolved last stretch from the un-attenuated
# offshore state. Both choices run hot for a real (random, spread) sea, and the error is
# regime-dependent: worst for short-period windswell over a wide shallow shelf (the Med),
# smallest for long-period groundswell onto a steep coast. Measured at poleg 2026-08-27
# (offshore Hs 1.55 m @ 8 s): monochromatic pipeline 1.9-2.0 m vs 1.4 m from a
# Battjes-Janssen reference march - vs Surfline's 0.6-1.1 m published band.
#
# Three literature-backed corrections, no eyes involved:
#   * JONSWAP-form bottom friction (Hasselmann et al. 1973 shape): dissipation per metre
#     travelled, which is why this march needs the along-ray DISTANCE of each sample, not
#     just its depth. NOTE the coefficient is NOT SWAN's 0.038: the march applies
#     BOTTOM_FRICTION_CB over g where the SWAN energy form divides by g^2, so the effective
#     Cb is 0.038 * g ~ 0.37 m^2 s^-3, ten times the textbook swell value. The heights this
#     produces are the ones graded by eye (CALIBRATION.md 2026-08-28 and 2026-09-07); the
#     textbook coefficient would raise heights at ~2/3 of the fleet. Do not "correct" the
#     g without re-tuning the coefficient - see CALIBRATION.md 2026-09-07. At poleg the
#     shelf takes ~11% off the height before the wave ever breaks; a steep coast loses
#     ~nothing.
#   * Battjes & Janssen (1978) breaking dissipation inside the resolved profile: a random
#     sea does not break as one wave at gamma*d - the tallest fraction Qb breaks first and
#     the sea saturates gradually. Replaces the hard gamma*d cap.
#   * The Komar & Gaughan close estimates the TOP-TENTH breaker, not the significant one:
#     Caldwell & Aucan 2007 (J. Coastal Research 23(5):1237) validated exactly this
#     estimator against 404 paired days of Waimea buoy + North Shore observations and
#     found it tracks H1/10; their eq. 4 gives H1/3 = 0.79 x H1/10 (Rayleigh). Publishing
#     K&G raw was publishing the top-tenth wave as the typical one.
BOTTOM_FRICTION_CB = 0.038  # applied over g, not g^2: effective Cb ~0.37 m^2 s^-3, tuned by
# eye, NOT SWAN's 0.038 - see the header note and CALIBRATION.md 2026-09-07
BJ_GAMMA = 0.73  # Battjes-Janssen breaker parameter (their fitted value, SWAN default)
H13_OVER_H110 = 0.79  # Rayleigh: significant height of the breakers vs their top tenth
# Where bottom friction applies along the march. JONSWAP friction is a PROPAGATION term:
# it is calibrated for swell travelling over a bottom, and inside the surf zone breaking
# dissipation dominates it by orders of magnitude. Integrating it anyway across the
# kilometre-scale shallow shelf a 460 m GEBCO cell smears in front of a reef destroys the
# wave BEFORE it reaches a breaking substep, so `surf_in_profile` never records it and the
# published height collapses to ~0 at Uluwatu, G-Land and 48 other spots (CALIBRATION.md
# 2026-09-09). Candidates, graded before any default moves:
#   "always" - the shipped behaviour, friction on every substep
#   "stop"   - friction off once the sea has started breaking (qb > BREAKING_ONSET_QB)
#   "taper"  - friction scaled by (1 - qb), so it fades as the sea saturates
#   "bounded" - dissipation may SATURATE the sea, never annihilate it: within one substep
#     the height cannot be driven below what the local depth can carry. A surf zone is fed
#     continuously by the swell behind it, so a wave crossing a metre of water arrives as a
#     metre-of-water wave; it does not arrive as nothing. This bounds the JONSWAP term where
#     it diverges (orbital ~ 1/sinh(kd), squared) without rescaling it where it is doing
#     real work over a wide shelf - see CALIBRATION.md 2026-09-09.
#   "kdfloor" - friction only while kd >= FRICTION_KD_MIN. The JONSWAP orbital velocity is
#     LINEAR theory's, sigma/sinh(kd), and linear theory is not valid in the surf zone: below
#     about kd 0.5 (depth under ~ L/12) the real orbital motion is shallow-water and bounded
#     where 1/sinh(kd) is not. Cutting the term where its own derivation stops holding bounds
#     it without rescaling it over the shelf, where kd 1-3 and it is doing real work.
#   "kdtaper" - the same domain limit as kdfloor, but SMOOTH: friction scaled by
#     min(1, (kd/FRICTION_KD_MIN)^2). A hard cut-off is a discontinuity that MOVES WITH THE
#     TIDE - raising the water shifts which substeps get friction at all - and it measurably
#     broke the tide response (spots where a higher tide reads smaller went 53 -> 152).
FRICTION_MODES = ("always", "stop", "taper", "bounded", "kdfloor", "kdtaper")
FRICTION_KD_MIN = 0.6
# "kdtaper" since 2026-09-09: the shipped default. "always" published 63 of 1408 spots flat
# forever - rockaway-beach served a median h_mid of 0.00 m against a 1.60 m offshore
# partition - because the JONSWAP term diverges below kd ~0.5 and destroyed the wave before
# it could break. The HARD cut-off ("kdfloor") fixed that and broke the tide response, since
# a discontinuity in kd moves with the water level; the taper is smooth and does not.
# Flipped on its same-input fleet A/B: 63 flat spots to 6, fleet mean +0.09 m, heights move
# up only, tide response 1121/80/207 against a 1171/53/184 baseline, and the tide test
# passes. CALIBRATION.md 2026-09-09.
FRICTION_MODE = "kdtaper"
BREAKING_ONSET_QB = 0.1  # the same threshold surf_in_profile already calls "this IS surf"
_SUBSTEP_M = 25.0  # dissipation substep; segments between samples are km apart
_RHO = 1025.0  # kg/m^3 seawater


def _breaking_fraction(hrms: float, hmax: float) -> float:
    """Battjes-Janssen Qb: the fraction of waves breaking, from (1-Qb)/ln(Qb) = -(Hrms/Hmax)^2.
    Fixed-point iteration on Qb = exp((Qb-1)/b); b >= 1 means the whole sea is breaking."""
    if hmax <= 0.0:
        return 1.0
    b = (hrms / hmax) ** 2
    if b >= 1.0:
        return 1.0
    if b < 1e-4:
        return 0.0
    qb = 0.5
    for _ in range(50):
        nxt = math.exp((qb - 1.0) / b)
        if abs(nxt - qb) < 1e-6:
            break
        qb = nxt
    return qb


def _march_terms(
    period_s: float,
    d_ref: float,
    c_ref: float,
    cg_ref: float,
    a_ref: float,
    sin_a_ref: float,
    fm: float,
    samples_deep_to_shallow: list[tuple[float, float]],
) -> tuple[list, ...] | None:
    """The state-independent per-substep terms of ``surf_height_over_profile`` as lists:
    (grazing, Ks, Kr, Cg, k*d, friction orbital velocity, Battjes-Janssen Hmax, dx).

    Substep centres are laid out exactly as the scalar march did - each accepted segment
    split into max(1, int(len / _SUBSTEP_M)) pieces, depth interpolated linearly to the
    piece centre, samples deeper than the reference skipped without moving the segment
    start. None when no substep survives (no accepted sample after the reference)."""
    d_mid_parts: list[np.ndarray] = []
    dx_parts: list[np.ndarray] = []
    prev_x, prev_d = samples_deep_to_shallow[0]
    for x, d in samples_deep_to_shallow[1:]:
        if d > d_ref:
            continue  # non-monotone ray - same skip, same rationale as the march above
        seg_len = abs(prev_x - x)
        n_sub = max(1, int(seg_len / _SUBSTEP_M))
        dx = seg_len / n_sub
        f = np.arange(1, n_sub + 1, dtype=np.float64) / n_sub
        d_mid_parts.append(prev_d + (d - prev_d) * (f - 0.5 / n_sub))  # substep-centre depth
        dx_parts.append(np.full(n_sub, dx))
        prev_x, prev_d = x, d
    if not d_mid_parts:
        return None
    d_mid = np.concatenate(d_mid_parts)
    dx_all = np.concatenate(dx_parts)
    # dispersion: the same Newton iteration as ``wavenumber`` (12 steps from the
    # deep-water seed, overshoot guard per step), on the whole array at once
    omega = angular_frequency(period_s)
    omega2 = omega * omega
    seed = omega2 / GRAVITY
    k = np.full_like(d_mid, seed)
    for _ in range(12):
        tanh = np.tanh(k * d_mid)
        f_val = GRAVITY * k * tanh - omega2
        sech2 = 1.0 - tanh * tanh
        fprime = GRAVITY * tanh + GRAVITY * k * d_mid * sech2
        k = k - f_val / fprime
        k = np.where(k <= 0.0, seed, k)
    kd = k * d_mid
    c = omega / k
    with np.errstate(over="ignore"):
        # 2kd > 350: sinh overflows to inf and the ratio vanishes - deep-water n = 1/2,
        # the same value the scalar guard returns
        n = 0.5 * (1.0 + 2.0 * kd / np.sinh(2.0 * kd))
    cg = n * c
    sin_a = sin_a_ref * c / c_ref
    grazing = sin_a >= 1.0
    safe_sin = np.where(grazing, 0.0, sin_a)
    ks = np.sqrt(cg_ref / cg)
    kr = np.sqrt(math.cos(a_ref) / np.cos(np.arcsin(safe_sin)))
    with np.errstate(over="ignore", divide="ignore"):
        orbital = np.where(kd < 25.0, 2.0 * math.pi * fm / np.sinh(kd), 0.0)
    hmax = 0.88 / k * np.tanh(BJ_GAMMA * kd / 0.88)
    return (
        grazing.tolist(),
        ks.tolist(),
        kr.tolist(),
        cg.tolist(),
        kd.tolist(),
        orbital.tolist(),
        hmax.tolist(),
        dx_all.tolist(),
    )


def tide_shifted_samples(
    samples_deep_to_shallow: list[tuple[float, float]], tide_m: float
) -> list[tuple[float, float]]:
    """The (dist_m, depth_m) profile with the water column raised by ``tide_m``.

    The march ends where the seabed meets the water surface. A sample that dries at this
    tide is the SHORELINE: it is replaced by the point where the depth crosses zero,
    interpolated linearly between it and the last wet sample - the same interpolation
    between measured points the march already does - and everything shoreward of it is
    dropped, because a wave cannot pass through dry land. Deleting the dried sample instead
    (the rule until 2026-09-08) handed the march two different profiles either side of a
    5 cm tide change - one ending centimetres deep, one a whole segment further out - and
    the same 1.5 m / 10 s swell published 1.29 m at one tide and 0.00 m 5 cm higher
    (mona-vale-beach; 72 of 1407 spots stepped >= 0.2 m, Dream review 2026-09-08).
    A profile whose deep reference itself dries has no water to march in: empty."""
    if not tide_m:
        return list(samples_deep_to_shallow)
    out: list[tuple[float, float]] = []
    for x, d in samples_deep_to_shallow:
        dd = d + tide_m
        if dd > 0.0:
            out.append((x, dd))
            continue
        if out:
            px, pd = out[-1]
            out.append((px + (x - px) * pd / (pd - dd), 0.0))
        break
    return out


def surf_height_over_profile(
    offshore_height_m: float,
    period_s: float,
    incidence_deg: float,
    samples_deep_to_shallow: list[tuple[float, float]],
    *,
    gamma: float = BREAK_GAMMA,
    friction_cb: float = BOTTOM_FRICTION_CB,
    friction_mode: str = FRICTION_MODE,
    friction_kd_min: float = FRICTION_KD_MIN,
) -> float:
    """Significant surf height of a random sea over the measured profile.

    Same skeleton as ``breaker_height_over_profile`` - conserve energy flux inward from the
    deep reference, Snell refraction, skip samples deeper than the reference and rays
    refracted to grazing, close the stretch GEBCO cannot resolve with Komar & Gaughan - with
    the three random-sea corrections documented above. ``samples_deep_to_shallow`` is
    (dist_m, depth_m) pairs, ordered deep to shallow (``DepthProfile.wet_samples_deep_to_shallow``).

    Between accepted samples the depth is interpolated linearly in ~100 m substeps so a
    4 km segment cannot swallow a dissipation zone whole. Interpolating between MEASURED
    points is not the prohibited invented-shallow-sample append: the march never continues
    past the shallowest measured sample - the K&G close covers that stretch, fed the
    friction-attenuated offshore height instead of the raw one."""
    if (
        offshore_height_m <= 0
        or period_s <= 0
        or not samples_deep_to_shallow
        or incidence_deg >= 90.0
    ):
        return 0.0
    _x_ref, d_ref = samples_deep_to_shallow[0]
    c_ref, cg_ref = celerities(period_s, d_ref)
    a_ref = math.radians(incidence_deg)
    sin_a_ref = math.sin(a_ref)
    fm = 1.0 / period_s
    # Everything a substep needs that does NOT depend on the running dissipation state -
    # the dispersion solve, both celerities, Snell, shoaling, refraction, the friction
    # orbital and the Battjes-Janssen Hmax - is a function of (T, depth) alone, so it is
    # computed for every substep at once (numpy, same iteration count and operation
    # order as the scalar solve). Only the recurrence itself - the height at each
    # substep feeds the breaking fraction that sets the next attenuation - stays a loop.
    # Measured 2026-08-30 on one spot: 612,843 scalar wave_state calls, 3.6 s of a 5 s
    # spot, became ~1.4 s; results agree with the scalar march to ~1e-13 relative.
    terms = _march_terms(
        period_s, d_ref, c_ref, cg_ref, a_ref, sin_a_ref, fm, samples_deep_to_shallow
    )
    if terms is None:
        return H13_OVER_H110 * breaker_height_komar_gaughan(
            offshore_height_m, period_s, incidence_deg, d_ref, gamma=gamma
        )
    grazing, ks, kr, cg, kd, orbital, hmax, dx = terms
    atten = 1.0  # cumulative dissipation factor on height (friction + breaking)
    surf_in_profile = 0.0
    broken = False  # has the sea started breaking anywhere shoreward of here
    sqrt2 = math.sqrt(2.0)
    for i in range(len(dx)):
        if grazing[i]:
            continue  # grazing - no transform, no dissipation accounted
        height = offshore_height_m * ks[i] * kr[i] * atten
        if height <= 0.0:
            continue
        hrms = height / sqrt2
        energy = _RHO * GRAVITY * hrms * hrms / 8.0
        flux = energy * cg[i]
        # JONSWAP-form bottom friction (guard the sinh overflow in deep water). The law's
        # energy form is Cb / g^2 * (sigma/sinh kd)^2 * E; this line divides by g once, so
        # friction_cb is an EFFECTIVE coefficient ~g times the textbook Cb. Deliberate and
        # calibrated (CALIBRATION.md 2026-09-07) - changing it moves published heights.
        # Battjes-Janssen breaking first: whether the sea is breaking here decides how
        # much of the friction term applies (see FRICTION_MODES).
        qb = _breaking_fraction(hrms, hmax[i])
        d_break = 0.25 * qb * fm * _RHO * GRAVITY * hmax[i] * hmax[i]
        breaking = qb > BREAKING_ONSET_QB
        if breaking:  # the sea is actively breaking here - this IS surf
            surf_in_profile = max(surf_in_profile, height)
            broken = True
        d_fric = 0.0
        if kd[i] < 25.0 and not (friction_mode == "kdfloor" and kd[i] < friction_kd_min):
            scale = 1.0
            if friction_mode == "kdtaper" and kd[i] < friction_kd_min:
                r = kd[i] / friction_kd_min
                scale = r * r
            elif friction_mode == "stop":
                scale = 0.0 if broken else 1.0
            elif friction_mode == "taper":
                scale = max(0.0, 1.0 - qb)
            if scale > 0.0:
                d_fric = scale * friction_cb / GRAVITY * orbital[i] * orbital[i] * energy
        loss = (d_fric + d_break) * dx[i]
        if flux > 0.0 and loss > 0.0:
            # exp(-x/2) == sqrt(1-x) to first order, but stays positive when a
            # saturated substep dissipates more than the segment's flux carries
            atten *= math.exp(-0.5 * loss / flux)
            if friction_mode == "bounded":
                # The floor is the depth-limited height, or the height the wave already
                # had if that is smaller - dissipation saturates a sea, it does not empty
                # one. Expressed on `atten` because that is what the next substep reads;
                # ks/kr at this substep convert the height floor into an attenuation floor.
                shoaled = offshore_height_m * ks[i] * kr[i]
                if shoaled > 0.0:
                    atten = max(atten, min(height, hmax[i]) / shoaled)
    return max(
        surf_in_profile,
        H13_OVER_H110
        * breaker_height_komar_gaughan(
            offshore_height_m * atten, period_s, incidence_deg, d_ref, gamma=gamma
        ),
    )
