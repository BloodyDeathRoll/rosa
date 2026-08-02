import math

import pytest

from rosa_pipeline.physics import (
    GRAVITY,
    breaker_height_komar_gaughan,
    breaker_height_over_profile,
    deep_water_equivalent,
    group_speed,
    phase_speed,
    refracted_angle,
    refraction_coeff,
    shoaling_coeff,
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

    def test_breaks_at_gamma_times_depth(self):
        hb = breaker_height_over_profile(3.0, 14.0, 0.0, [50.0, 20.0, 8.0, 4.0, 2.0])
        # breaks where H >= gamma*d; result is exactly gamma*(some sampled depth)
        assert any(hb == pytest.approx(0.78 * d) for d in [50.0, 20.0, 8.0, 4.0, 2.0])

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

    def test_a_profile_that_does_reach_the_surf_zone_still_wins(self):
        """The closure is a fallback, not a replacement - real shallow bathymetry still
        decides where a wave breaks. Only 9 of 199 committed profiles get shallow enough
        for this branch to fire under ordinary surf."""
        hb = breaker_height_over_profile(2.0, 14.0, 0.0, [50.0, 20.0, 8.0, 4.0, 1.0])
        assert hb == pytest.approx(0.78 * 1.0)  # depth-limited, not the index

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
