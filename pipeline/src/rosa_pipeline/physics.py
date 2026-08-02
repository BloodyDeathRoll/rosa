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


def phase_speed(period_s: float, depth_m: float) -> float:
    """C = ω / k."""
    return angular_frequency(period_s) / wavenumber(period_s, depth_m)


def group_speed(period_s: float, depth_m: float) -> float:
    """Cg = n·C, n = ½(1 + 2kd/sinh 2kd). → gT/4π in deep water, √(gd) in shallow."""
    k = wavenumber(period_s, depth_m)
    kd = k * depth_m
    c = angular_frequency(period_s) / k
    if 2.0 * kd > 350.0:  # sinh overflows and the ratio vanishes - deep-water n = 1/2
        return 0.5 * c
    n = 0.5 * (1.0 + 2.0 * kd / math.sinh(2.0 * kd))
    return n * c


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

    Swell arriving from behind the shore normal (incidence ≥ 90°) contributes nothing."""
    if (
        offshore_height_m <= 0
        or period_s <= 0  # a padded/empty partition (no period) transforms to nothing
        or not depths_deep_to_shallow
        or incidence_deg >= 90.0
    ):
        return 0.0
    d_ref = depths_deep_to_shallow[0]
    cg_ref = group_speed(period_s, d_ref)
    c_ref = phase_speed(period_s, d_ref)
    a_ref = math.radians(incidence_deg)
    sin_a_ref = math.sin(a_ref)
    height = offshore_height_m
    for d in depths_deep_to_shallow:
        c = angular_frequency(period_s) / wavenumber(period_s, d)
        sin_a = sin_a_ref * c / c_ref
        if sin_a >= 1.0:
            continue  # refracted to grazing at this depth - skip
        alpha = math.asin(sin_a)
        ks = math.sqrt(cg_ref / group_speed(period_s, d))
        kr = math.sqrt(math.cos(a_ref) / math.cos(alpha))
        height = offshore_height_m * ks * kr
        if height >= gamma * d:
            return gamma * d
    return breaker_height_komar_gaughan(
        offshore_height_m, period_s, incidence_deg, d_ref, gamma=gamma
    )
