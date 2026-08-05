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


def celerities(period_s: float, depth_m: float) -> tuple[float, float]:
    """(C, Cg) from ONE dispersion solve.

    The shoaling march needs both at every sampled depth and used to ask for them separately,
    which solved w^2 = g*k*tanh(k*d) twice for the same (T, d). Identical arithmetic, half the
    Newton iterations; ``phase_speed``/``group_speed`` stay as the single-value views."""
    k = wavenumber(period_s, depth_m)
    kd = k * depth_m
    c = angular_frequency(period_s) / k
    if 2.0 * kd > 350.0:  # sinh overflows and the ratio vanishes - deep-water n = 1/2
        return c, 0.5 * c
    n = 0.5 * (1.0 + 2.0 * kd / math.sinh(2.0 * kd))
    return c, n * c


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
        sin_a = math.sin(a_ref) * phase_speed(period_s, hb / gamma) / c_ref
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
