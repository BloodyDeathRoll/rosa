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
    profile it breaks even closer to shore than GEBCO resolves, so we return the most-shoaled
    height reached (a per-spot residual coefficient absorbs that sub-grid surf-zone gap).

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
    return min(height, gamma * depths_deep_to_shallow[-1])
