import pytest

from rosa_pipeline.models import SwellPartition
from rosa_pipeline.transform import (
    angle_diff,
    breaker_range,
    classify_wind,
    dominant_partition,
    effective_height_in_window,
    energy_in_window,
    height_in_window,
    height_phrase,
    in_window,
    period_quality,
    wetsuit,
)

WINDOW = (250.0, 340.0)


def swell(h: float, t: float, d: float) -> SwellPartition:
    return SwellPartition(height_m=h, period_s=t, direction_deg=d)


class TestAngleDiff:
    def test_symmetric(self):
        assert angle_diff(90, 270) == 180
        assert angle_diff(270, 90) == 180

    def test_wraps(self):
        assert angle_diff(350, 10) == 20
        assert angle_diff(0, 360) == 0


class TestClassifyWind:
    # Israel convention: offshore_direction = 90 (E wind blows offshore)
    def test_offshore(self):
        assert classify_wind(90, 90) == "offshore"
        assert classify_wind(45, 90) == "offshore"  # boundary: theta == 45
        assert classify_wind(135, 90) == "offshore"

    def test_cross_shore(self):
        assert classify_wind(180, 90) == "cross-shore"
        assert classify_wind(225, 90) == "cross-shore"  # boundary: theta == 135
        assert classify_wind(0, 90) == "cross-shore"

    def test_onshore(self):
        assert classify_wind(270, 90) == "onshore"  # W sea breeze
        assert classify_wind(226, 90) == "onshore"


class TestInWindow:
    def test_inside_outside(self):
        assert in_window(290, WINDOW)
        assert in_window(250, WINDOW)
        assert in_window(340, WINDOW)
        assert not in_window(200, WINDOW)
        assert not in_window(350, WINDOW)

    def test_wrapping_window(self):
        window = (330.0, 30.0)
        assert in_window(350, window)
        assert in_window(10, window)
        assert not in_window(180, window)


class TestEnergy:
    def test_sums_only_in_window(self):
        partitions = (swell(1.0, 10, 290), swell(2.0, 8, 100))
        assert energy_in_window(partitions, WINDOW) == 1.0**2 * 10

    def test_empty(self):
        assert energy_in_window((), WINDOW) == 0


class TestHeightInWindow:
    def test_rms_combination(self):
        partitions = (swell(0.6, 8, 290), swell(0.8, 10, 300))
        assert height_in_window(partitions, WINDOW) == (0.6**2 + 0.8**2) ** 0.5

    def test_out_of_window_excluded(self):
        assert height_in_window((swell(2.0, 10, 100),), WINDOW) == 0


class TestPeriodQuality:
    def test_reference_period(self):
        assert period_quality(10.0) == 1.0

    def test_windswell_discounted_quadratically(self):
        assert period_quality(5.0) == pytest.approx(0.25)

    def test_clamps(self):
        assert period_quality(3.0) == 0.15  # floor
        assert period_quality(12.0) == 1.2  # groundswell cap (1.44 clamped)
        assert period_quality(20.0) == 1.2


class TestEffectiveHeight:
    def test_short_period_discounted(self):
        # calibration fix #1 (buoy-confirmed): 0.66 m @ 5.2 s surfs ankle-high ~0.18 m
        h = effective_height_in_window((swell(0.66, 5.2, 290),), WINDOW)
        assert h == pytest.approx(0.66 * 0.52**2)

    def test_long_period_boosted(self):
        h = effective_height_in_window((swell(1.0, 14.0, 290),), WINDOW)
        assert h == pytest.approx(1.2)

    def test_out_of_window_excluded(self):
        assert effective_height_in_window((swell(2.0, 12.0, 100),), WINDOW) == 0


class TestDominant:
    def test_picks_max_energy(self):
        a, b = swell(1.0, 5, 290), swell(0.8, 12, 300)  # E: 5.0 vs 7.68
        assert dominant_partition((a, b), WINDOW) == b

    def test_none_when_empty_window(self):
        assert dominant_partition((swell(1.0, 10, 100),), WINDOW) is None


class TestBreakerRange:
    def test_coeff_and_snap(self):
        lo, mid, hi = breaker_range(1.0, 1.0)
        assert (lo, mid, hi) == (0.8, 1.0, 1.2)

    def test_snapped_to_0_1(self):
        lo, _, hi = breaker_range(1.13, 1.0)
        assert lo == 0.9  # 0.904 snapped
        assert hi == 1.4  # 1.356 snapped


class TestPhrase:
    def test_boundaries(self):
        assert height_phrase(0.1) == "shin-high"
        assert height_phrase(0.3) == "knee-high"
        assert height_phrase(0.5) == "waist-high"
        assert height_phrase(0.8) == "chest-high"
        assert height_phrase(1.2) == "head-high"
        assert height_phrase(1.5) == "overhead"
        assert height_phrase(2.0) == "well overhead"
        assert height_phrase(3.5) == "double overhead+"


class TestWetsuit:
    def test_boundaries(self):
        assert wetsuit(25.0) == "rashguard"
        assert wetsuit(24.0) == "spring / 2mm"
        assert wetsuit(20.0) == "spring / 2mm"
        assert wetsuit(19.0) == "3/2"
        assert wetsuit(16.0) == "4/3"
        assert wetsuit(12.0) == "5/4 + boots"
        assert wetsuit(9.0) == "6/5 hooded"
