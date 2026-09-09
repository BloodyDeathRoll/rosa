import itertools
import math

import pytest

from rosa_pipeline.physics import (
    BOTTOM_FRICTION_CB,
    FRICTION_KD_MIN,
    GRAVITY,
    H13_OVER_H110,
    angular_frequency,
    breaker_height_komar_gaughan,
    breaker_height_over_profile,
    celerities,
    deep_water_equivalent,
    group_speed,
    phase_speed,
    refracted_angle,
    refraction_coeff,
    shoaling_coeff,
    surf_height_over_profile,
    wave_state,
    wavenumber,
)


class TestWavenumber:
    def test_satisfies_dispersion_relation(self):
        for T, d in [(10.0, 1000.0), (8.0, 40.0), (14.0, 5.0), (6.0, 2.0), (20.0, 1.0)]:
            k = wavenumber(T, d)
            omega = 2 * math.pi / T
            assert GRAVITY * k * math.tanh(k * d) == pytest.approx(omega**2, rel=1e-6)

    def test_deep_water_limit(self):
        # d ≫ L: k → ω²/g
        T, d = 10.0, 5000.0
        omega = 2 * math.pi / T
        assert wavenumber(T, d) == pytest.approx(omega**2 / GRAVITY, rel=1e-4)

    def test_shallow_water_limit(self):
        # d ≪ L: k → ω/√(gd)
        T, d = 30.0, 0.5
        omega = 2 * math.pi / T
        assert wavenumber(T, d) == pytest.approx(omega / math.sqrt(GRAVITY * d), rel=1e-2)

    def test_rejects_dry_point(self):
        with pytest.raises(ValueError):
            wavenumber(10.0, 0.0)


class TestCelerity:
    def test_group_speed_deep_limit(self):
        # Cg → gT/4π
        T = 10.0
        assert group_speed(T, 5000.0) == pytest.approx(GRAVITY * T / (4 * math.pi), rel=1e-3)

    def test_group_speed_shallow_limit(self):
        # Cg → √(gd)
        d = 0.5
        assert group_speed(30.0, d) == pytest.approx(math.sqrt(GRAVITY * d), rel=1e-2)

    def test_phase_speed_shallow_limit(self):
        d = 0.5
        assert phase_speed(30.0, d) == pytest.approx(math.sqrt(GRAVITY * d), rel=1e-2)

    def test_group_below_phase_in_deep_water(self):
        # deep water: Cg = C/2
        assert group_speed(10.0, 5000.0) == pytest.approx(phase_speed(10.0, 5000.0) / 2, rel=1e-3)

    def test_celerities_match_independent_dispersion_arithmetic(self):
        """Dream review 2026-08-05: the shoaling march now takes (C, Cg) from one dispersion
        solve. Pin both values to the formulas computed from a separate wavenumber call, so
        the fused path can never drift from the physics it replaced."""
        for T, d in itertools.product((6.0, 10.0, 16.0), (2.0, 40.0, 4000.0)):
            k = wavenumber(T, d)
            c, cg = celerities(T, d)
            assert c == pytest.approx(angular_frequency(T) / k, rel=1e-12)
            kd = k * d
            n = 0.5 if 2 * kd > 350 else 0.5 * (1 + 2 * kd / math.sinh(2 * kd))
            assert cg == pytest.approx(n * c, rel=1e-12)

    def test_celerities_deep_overflow_branch_gives_half_c(self):
        # 2kd >> 350: sinh would overflow - the guard must return exactly n = 1/2
        c, cg = celerities(4.0, 5000.0)
        assert cg == 0.5 * c


class TestShoaling:
    def test_unity_at_reference_depth(self):
        assert shoaling_coeff(12.0, 100.0, 100.0) == pytest.approx(1.0)

    def test_shoals_up_in_shallow_water(self):
        # from deep reference into shallow water the wave grows (Ks > 1 near breaking)
        assert shoaling_coeff(12.0, 200.0, 3.0) > 1.0

    def test_slight_dip_before_shoaling(self):
        # classic shoaling curve dips just below 1 at intermediate depth before rising
        ks_mid = shoaling_coeff(12.0, 500.0, 40.0)
        assert 0.9 < ks_mid < 1.0


class TestRefraction:
    def test_normal_incidence_unchanged(self):
        assert refracted_angle(12.0, 200.0, 5.0, 0.0) == pytest.approx(0.0)
        assert refraction_coeff(0.0, 0.0) == pytest.approx(1.0)

    def test_oblique_bends_toward_normal(self):
        # shallower water → smaller angle (waves bend to face the beach)
        a = refracted_angle(12.0, 200.0, 5.0, 40.0)
        assert 0.0 < a < 40.0

    def test_refraction_reduces_height_for_oblique(self):
        a = refracted_angle(12.0, 200.0, 5.0, 40.0)
        assert refraction_coeff(40.0, a) < 1.0


# A real deep->shallow profile (Beit Yanai, from data/spots/derived/bathy).
BEIT_YANAI_PROFILE = [180.0, 85.0, 50.0, 43.0, 34.0, 25.0, 24.0, 23.0, 15.0]


class TestBreakerOverProfile:
    def test_big_swell_is_depth_limited(self):
        # a 2 m, 14 s swell straight in breaks at gamma*d somewhere on the profile
        hb = breaker_height_over_profile(2.0, 14.0, 0.0, [10.0, 5.0, 3.0, 1.5])
        assert hb == pytest.approx(0.78 * 1.5, rel=1e-6) or hb <= 0.78 * 10.0
        assert 0 < hb <= 2.0 * 3  # sane magnitude

    def test_breaks_at_gamma_times_depth_when_the_profile_is_the_binding_constraint(self):
        """Rewritten 2026-08-03. It used to assert the answer was exactly gamma*(a SAMPLED
        depth), which is only true if the sampling interval is allowed to set the height: the
        march can break at 4 m or at 2 m but nowhere between, and on this profile it clamps a
        3 m 14 s swell to gamma*2 = 3.12 m when solving H(d) = gamma*d continuously gives
        4.15 m. The contract now is that the deeper of the two breaking criteria wins, so a
        real depth limit still caps the wave but a sampling artefact cannot shrink it."""
        profile = [50.0, 20.0, 8.0, 4.0, 2.0]
        hb = breaker_height_over_profile(3.0, 14.0, 0.0, profile)
        assert hb >= 0.78 * 2.0  # never below what the march alone would have returned
        assert hb <= 0.78 * profile[0]  # still a depth-limited height somewhere on the profile

    def test_swell_from_behind_shore_normal_is_zero(self):
        assert breaker_height_over_profile(2.0, 12.0, 95.0, [50.0, 10.0, 3.0]) == 0.0

    def test_zero_height_in_zero_out(self):
        assert breaker_height_over_profile(0.0, 12.0, 0.0, [50.0, 10.0]) == 0.0

    def test_empty_profile_is_zero(self):
        assert breaker_height_over_profile(2.0, 12.0, 0.0, []) == 0.0

    def test_zero_period_partition_is_zero(self):
        # padded/empty partitions arrive with period 0 - must not hit the dispersion solver
        assert breaker_height_over_profile(1.0, 0.0, 0.0, [50.0, 10.0, 3.0]) == 0.0

    def test_profile_that_never_reaches_the_surf_zone_closes_with_the_breaker_index(self):
        """Changed 2026-08-02. This used to assert the wave came back at its offshore height
        (0.3 m) because an all-deep profile never reaches gamma*d and the march returned the
        most-shoaled height it had. That was the bug: it is a mid-shelf height, not a breaker
        height, and it made the wave arrive no bigger than it left. The profile ends in 100 m
        of water, so the surf zone is entirely off the end of it and the breaker index owns
        the answer."""
        hb = breaker_height_over_profile(0.3, 12.0, 0.0, [200.0, 150.0, 100.0])
        assert hb == pytest.approx(breaker_height_komar_gaughan(0.3, 12.0, 0.0, 200.0), abs=1e-9)
        assert hb > 0.3  # a breaker is bigger than the swell that made it

    def test_a_shallow_profile_cannot_shrink_the_wave_below_the_index(self):
        """Rewritten 2026-08-03. This used to assert 0.78 m for a 2 m 14 s swell - the march
        reached gamma*d at the profile's 1 m sample and returned gamma*1. That is the sampling
        interval speaking, not the bathymetry: the wave really breaks around 3.8 m depth, and
        solving H(d) = gamma*d continuously over the same linear theory gives 2.98 m. 51 of the
        199 committed profiles reach 1-2 m, so the old rule clamped their biggest days to
        0.78 m. The deeper break wins now."""
        hb = breaker_height_over_profile(2.0, 14.0, 0.0, [50.0, 20.0, 8.0, 4.0, 1.0])
        assert hb == pytest.approx(breaker_height_komar_gaughan(2.0, 14.0, 0.0, 50.0), abs=1e-9)
        assert hb > 0.78 * 1.0

    def test_a_genuine_depth_limit_still_beats_the_index(self):
        """The closure is a fallback, not a replacement. The march wins wherever linear shoaling
        reaches gamma*d in deeper water than the index's own breaking depth - a steep short-period
        storm sea over a shelf. Rare (K&G sits above linear theory in almost every real sea state,
        because linear shoaling under-calls the nonlinear growth just before breaking), which is
        why the max is nearly always the index - but the depth limit is a real floor, not dead
        code, and this pins it."""
        shelf = [30.0, 18.0, 11.0, 6.7]
        hb = breaker_height_over_profile(6.0, 4.0, 0.0, shelf)
        assert hb > breaker_height_komar_gaughan(6.0, 4.0, 0.0, 30.0)
        assert any(hb == pytest.approx(0.78 * d) for d in shelf)

    def test_handoff_is_continuous_and_monotone_in_incidence(self):
        """Regression for the 2026-08-03 step. On a profile ending at 1.5 m the height used to
        jump 1.170 -> 1.303 m between 13 and 14 degrees of incidence - it got BIGGER as the
        angle got worse - because the march won on one side of the crossover and the index on
        the other. Breaker height must fall smoothly as the approach goes oblique."""
        profile = [180.0, 50.0, 20.0, 8.0, 3.0, 1.5]
        heights = [breaker_height_over_profile(0.8, 10.0, float(a), profile) for a in range(0, 86)]
        for a, (lo, hi) in enumerate(itertools.pairwise(heights)):
            # the defect was an UPWARD step - a worse angle returning a bigger wave
            assert hi <= lo + 1e-9, f"height rose from {lo:.4f} to {hi:.4f} at {a} deg"
            # the old jump was 0.133 m; what is left is the index's own gradient, which only
            # steepens approaching grazing incidence
            assert lo - hi < 0.05, f"step of {lo - hi:.4f} m at {a} deg"

    def test_period_raises_breaker_height(self):
        # longer period shoals more -> breaks bigger, all else equal
        short = breaker_height_over_profile(1.5, 7.0, 0.0, BEIT_YANAI_PROFILE)
        longp = breaker_height_over_profile(1.5, 15.0, 0.0, BEIT_YANAI_PROFILE)
        assert longp >= short


class TestKomarGaughan:
    """Breaker index that closes the march where GEBCO runs out (2026-08-02)."""

    def test_breaker_exceeds_the_deep_water_height(self):
        """The whole reason the truncated march was wrong: shoaling into the surf zone makes
        a wave bigger, and stopping at 7-13 m of water made it arrive smaller."""
        assert breaker_height_komar_gaughan(1.0, 12.0, 0.0, 200.0) > 1.0

    def test_grows_with_height_and_with_period(self):
        big = breaker_height_komar_gaughan(2.0, 12.0, 0.0, 200.0)
        small = breaker_height_komar_gaughan(1.0, 12.0, 0.0, 200.0)
        longp = breaker_height_komar_gaughan(1.0, 16.0, 0.0, 200.0)
        assert big > small and longp > small

    def test_oblique_swell_breaks_smaller_than_straight_in(self):
        straight = breaker_height_komar_gaughan(1.0, 12.0, 0.0, 200.0)
        oblique = breaker_height_komar_gaughan(1.0, 12.0, 60.0, 200.0)
        assert 0 < oblique < straight

    def test_swell_from_behind_the_shore_normal_is_zero(self):
        assert breaker_height_komar_gaughan(1.0, 12.0, 90.0, 200.0) == 0.0

    def test_degenerate_inputs_are_zero(self):
        assert breaker_height_komar_gaughan(0.0, 12.0, 0.0, 200.0) == 0.0
        assert breaker_height_komar_gaughan(1.0, 0.0, 0.0, 200.0) == 0.0

    def test_known_value(self):
        """Hb = 0.39 g^0.2 (T H0^2)^0.4, straight in so Kr = 1 and the iteration is a no-op."""
        expected = 0.39 * GRAVITY**0.2 * (12.0 * 1.0**2) ** 0.4
        assert breaker_height_komar_gaughan(1.0, 12.0, 0.0, 5000.0) == pytest.approx(
            expected, rel=1e-3
        )


class TestDeepWaterEquivalent:
    def test_deep_reference_is_a_no_op(self):
        # 200 m is deep for a 12 s wave (L0 = 225 m), so there is nothing to undo
        assert deep_water_equivalent(1.0, 12.0, 200.0) == pytest.approx(1.0, abs=1e-3)

    def test_shallow_reference_is_de_shoaled(self):
        """A partition height reported over a 20 m shelf is already shoaled; feeding it to a
        breaker index as if it were a deep-water height would double-count that growth."""
        assert deep_water_equivalent(1.0, 14.0, 20.0) != pytest.approx(1.0, abs=1e-3)

    def test_round_trips_against_the_shoaling_coefficient(self):
        h0 = deep_water_equivalent(1.0, 14.0, 20.0)
        assert h0 * shoaling_coeff(14.0, 1e5, 20.0) == pytest.approx(1.0, rel=1e-3)


def test_komar_gaughan_survives_an_underflowed_offshore_height() -> None:
    """A sea attenuated to ~1e-210 m has no breaker - and must not raise asking for one.

    The random-sea march feeds this the FRICTION-ATTENUATED H0, so a degenerate partition
    (beit-yanai's 0.25 s wind wave; OM publishes wind_wave_period down to 0.0) drives atten
    to ~1e-210. h0 SQUARED then underflows to exactly 0.0, hb with it, and the refraction
    iteration asked phase_speed() for the celerity at depth hb/gamma = 0.0 - which is not a
    depth. That killed the whole spot: one hour's ValueError aborted beit-yanai's publish
    (test_quota.py::test_fixture_replay_is_exempt, regression from 2026-08-28's cdd6e1a).
    """
    assert breaker_height_komar_gaughan(2.98820516805073e-210, 0.25, 59.0, 192.039) == 0.0


def test_wave_state_and_celerities_agree_exactly() -> None:
    """wave_state is celerities plus the k it already solved for. The random-sea march asked
    wavenumber() and then celerities() for the SAME (T, d), solving the dispersion relation
    twice per substep - 1,097,443 solves for one spot, measured 2026-08-29. Collapsing them
    is only safe if it is the same arithmetic, so pin bit-equality, not approximate equality.
    """
    for T, d in [(10.0, 1000.0), (8.0, 40.0), (14.0, 5.0), (6.0, 2.0), (20.0, 1.0), (2.0, 900.0)]:
        k, c, cg = wave_state(T, d)
        assert (c, cg) == celerities(T, d)
        assert k == wavenumber(T, d)
        assert phase_speed(T, d) == c


# --- the vectorised march vs the scalar one it replaced (2026-08-30) ---------------------
# ``surf_height_over_profile`` precomputes every state-independent substep term with numpy
# and keeps only the dissipation recurrence as a loop. This is the scalar march it replaced,
# verbatim, so the contract "same arithmetic, same substeps, same skips" stays testable:
# on all 623 committed profiles x 48 (H, T, angle) cases the worst difference was 2.4e-15.


def _scalar_march(
    offshore_height_m, period_s, incidence_deg, samples, *, friction_cb, friction_kd_min
):
    from rosa_pipeline.physics import _RHO, _SUBSTEP_M, BJ_GAMMA, _breaking_fraction

    x_ref, d_ref = samples[0]
    c_ref, cg_ref = celerities(period_s, d_ref)
    a_ref = math.radians(incidence_deg)
    sin_a_ref = math.sin(a_ref)
    fm = 1.0 / period_s
    atten = 1.0
    surf_in_profile = 0.0
    prev_x, prev_d = x_ref, d_ref
    for x, d in samples[1:]:
        if d > d_ref:
            continue
        seg_len = abs(prev_x - x)
        n_sub = max(1, int(seg_len / _SUBSTEP_M))
        dx = seg_len / n_sub
        for i in range(1, n_sub + 1):
            f = i / n_sub
            d_mid = prev_d + (d - prev_d) * (f - 0.5 / n_sub)
            k, c, cg = wave_state(period_s, d_mid)
            sin_a = sin_a_ref * c / c_ref
            if sin_a >= 1.0:
                continue
            ks = math.sqrt(cg_ref / cg)
            kr = math.sqrt(math.cos(a_ref) / math.cos(math.asin(sin_a)))
            height = offshore_height_m * ks * kr * atten
            if height <= 0.0:
                continue
            hrms = height / math.sqrt(2.0)
            energy = _RHO * GRAVITY * hrms * hrms / 8.0
            flux = energy * cg
            kd = k * d_mid
            d_fric = 0.0
            if kd < 25.0:
                orbital = 2.0 * math.pi * fm / math.sinh(kd)
                # the shipped domain limit (FRICTION_MODE "kdtaper", 2026-09-09): JONSWAP's
                # orbital velocity is linear theory's, and linear theory does not hold in
                # the surf zone - below kd_min the term is faded out as (kd/kd_min)^2
                # rather than left to diverge as 1/sinh(kd)^2
                scale = 1.0
                if kd < friction_kd_min:
                    r = kd / friction_kd_min
                    scale = r * r
                d_fric = scale * friction_cb / GRAVITY * orbital * orbital * energy
            hmax = 0.88 / k * math.tanh(BJ_GAMMA * kd / 0.88)
            qb = _breaking_fraction(hrms, hmax)
            d_break = 0.25 * qb * fm * _RHO * GRAVITY * hmax * hmax
            if qb > 0.1:
                surf_in_profile = max(surf_in_profile, height)
            loss = (d_fric + d_break) * dx
            if flux > 0.0 and loss > 0.0:
                atten *= math.exp(-0.5 * loss / flux)
        prev_x, prev_d = x, d
    return max(
        surf_in_profile,
        H13_OVER_H110
        * breaker_height_komar_gaughan(offshore_height_m * atten, period_s, incidence_deg, d_ref),
    )


_MARCH_PROFILES = {
    # a textbook shelf, a non-monotone ray (the 12 m sample deeper than its predecessor is
    # skipped without moving the segment start), and a one-sample-past-reference stub
    "shelf": [(18000.0, 180.0), (8000.0, 50.0), (2000.0, 20.0), (1000.0, 8.0), (250.0, 1.5)],
    "bump": [(9000.0, 60.0), (6000.0, 9.0), (4000.0, 12.0), (2000.0, 5.0), (300.0, 2.0)],
    "stub": [(400.0, 30.0), (100.0, 3.0)],
}


@pytest.mark.parametrize("name", sorted(_MARCH_PROFILES))
@pytest.mark.parametrize(
    ("h", "t", "a"), [(0.3, 5.0, 0.0), (1.0, 8.3, 25.0), (2.5, 12.0, 60.0), (5.0, 17.0, 10.0)]
)
def test_vectorised_march_matches_the_scalar_one(name: str, h: float, t: float, a: float):
    samples = _MARCH_PROFILES[name]
    ref = _scalar_march(
        h, t, a, samples, friction_cb=BOTTOM_FRICTION_CB, friction_kd_min=FRICTION_KD_MIN
    )
    got = surf_height_over_profile(h, t, a, samples)
    assert got == pytest.approx(ref, rel=1e-12, abs=1e-15)


def test_vectorised_march_matches_the_scalar_one_on_committed_profiles():
    """Three real rays from the DB (deep Pacific point break, Med beach, atoll reef), so a
    substep layout the toy profiles cannot produce is covered too."""
    from pathlib import Path

    from rosa_pipeline.bathymetry import load_profile

    bathy = Path(__file__).resolve().parents[2] / "data" / "spots" / "derived" / "bathy"
    for sid in ("zvulun", "okuragahama", "steamer-lane"):
        prof = load_profile(sid, bathy)
        if prof is None:
            pytest.skip(f"{sid} has no committed profile")
        samples = prof.wet_samples_deep_to_shallow()
        for h, t, a in ((1.0, 8.3, 25.0), (2.5, 14.0, 0.0)):
            ref = _scalar_march(
                h, t, a, samples, friction_cb=BOTTOM_FRICTION_CB, friction_kd_min=FRICTION_KD_MIN
            )
            assert surf_height_over_profile(h, t, a, samples) == pytest.approx(ref, rel=1e-12)
