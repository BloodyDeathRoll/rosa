import math

import pytest

from rosa_pipeline.physics import (
    GRAVITY,
    breaker_height_over_profile,
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
        # padded/empty partitions arrive with period 0 — must not hit the dispersion solver
        assert breaker_height_over_profile(1.0, 0.0, 0.0, [50.0, 10.0, 3.0]) == 0.0

    def test_small_swell_does_not_break_deep(self):
        # a tiny swell over an all-deep profile never reaches gamma*d -> returns a shoaled height
        hb = breaker_height_over_profile(0.3, 12.0, 0.0, [200.0, 150.0, 100.0])
        assert 0 < hb < 0.78 * 100.0
        assert hb == pytest.approx(0.3, abs=0.05)  # barely shoaled in deep water

    def test_period_raises_breaker_height(self):
        # longer period shoals more -> breaks bigger, all else equal
        short = breaker_height_over_profile(1.5, 7.0, 0.0, BEIT_YANAI_PROFILE)
        longp = breaker_height_over_profile(1.5, 15.0, 0.0, BEIT_YANAI_PROFILE)
        assert longp >= short
