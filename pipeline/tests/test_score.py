from datetime import UTC, datetime

from rosa_pipeline.models import HourForecast, Spot, SwellPartition
from rosa_pipeline.score import bucket, period_score, score_hour, size_score, wind_score

SPOT = Spot(
    id="test",
    name="Test",
    lat=32.0,
    lon=34.8,
    timezone="Asia/Jerusalem",
    offshore_point=(32.2, 34.55),
    offshore_direction=90.0,
    shore_normal=270.0,
    swell_window=(250.0, 340.0),
    height_coeff=1.0,
    break_type="beach",
    ideal_wind_dir=(45.0, 135.0),
    ideal_size_m=(0.6, 1.5),
)


def hour(
    partitions: tuple[SwellPartition, ...],
    wind_speed: float = 10.0,
    wind_dir: float = 90.0,
) -> HourForecast:
    return HourForecast(
        time=datetime(2026, 7, 19, 6, tzinfo=UTC),
        partitions=partitions,
        sst_c=28.0,
        wind_speed_kph=wind_speed,
        wind_dir_deg=wind_dir,
        wind_gusts_kph=None,
    )


class TestSizeScore:
    IDEAL = (0.6, 1.5)

    def test_zero(self):
        assert size_score(0.0, self.IDEAL) == 0

    def test_ramp_below_ideal(self):
        assert size_score(0.3, self.IDEAL) == 40 * 0.3 / 0.6

    def test_full_inside_ideal(self):
        assert size_score(0.6, self.IDEAL) == 40
        assert size_score(1.0, self.IDEAL) == 40
        assert size_score(1.5, self.IDEAL) == 40

    def test_taper_above_with_floor(self):
        assert size_score(3.0, self.IDEAL) == 10  # 2x ideal max -> floor
        assert size_score(6.0, self.IDEAL) == 10  # floor holds
        assert 10 < size_score(2.0, self.IDEAL) < 40


class TestPeriodScore:
    def test_spec_fixed_points(self):
        assert period_score(6.0) == 0
        assert period_score(14.0) == 20
        assert period_score(10.0) == 10

    def test_clamped(self):
        assert period_score(3.0) == 0
        assert period_score(20.0) == 20


class TestWindScore:
    OFFSHORE = 90.0

    def test_light_offshore_is_max(self):
        assert wind_score(0, 90, self.OFFSHORE) == 40
        assert wind_score(15, 90, self.OFFSHORE) == 40
        assert wind_score(15, 130, self.OFFSHORE) == 40  # theta 40 still offshore

    def test_onshore_25kph_is_zero(self):
        assert wind_score(25, 270, self.OFFSHORE) == 0  # theta 180
        assert wind_score(25, 240, self.OFFSHORE) == 0  # theta 150
        assert wind_score(40, 270, self.OFFSHORE) == 0

    def test_scales_down_with_speed(self):
        assert wind_score(30, 90, self.OFFSHORE) < wind_score(20, 90, self.OFFSHORE) < 40

    def test_scales_down_with_angle(self):
        assert wind_score(10, 270, self.OFFSHORE) < wind_score(10, 180, self.OFFSHORE) < 40


class TestBucket:
    def test_boundaries(self):
        assert bucket(0) == "FLAT"
        assert bucket(9) == "FLAT"
        assert bucket(10) == "POOR"
        assert bucket(29) == "POOR"
        assert bucket(30) == "FAIR"
        assert bucket(49) == "FAIR"
        assert bucket(50) == "GOOD"
        assert bucket(69) == "GOOD"
        assert bucket(70) == "FIRING"
        assert bucket(100) == "FIRING"


class TestScoreHour:
    def test_good_day(self):
        # chest-high 10s W swell, light offshore -> size 40 + period 10 + wind 33 = 83
        # (q(10) = 1.0 so effective height == raw; wind gate (40+10)/60 = 0.83, not saturated)
        s = score_hour(SPOT, hour((SwellPartition(1.0, 10.0, 290.0),)))
        assert s.rating == 83
        assert s.bucket == "FIRING"
        assert s.wind_class == "offshore"
        assert s.phrase == "chest-high"

    def test_flat_gate_perfect_wind(self):
        # no swell at all: perfect offshore wind must NOT produce a FAIR rating
        s = score_hour(SPOT, hour(()))
        assert s.rating == 0
        assert s.bucket == "FLAT"

    def test_flat_gate_out_of_window_swell(self):
        # swell exists but none reaches the break
        s = score_hour(SPOT, hour((SwellPartition(1.5, 12.0, 100.0),)))
        assert s.bucket == "FLAT"
        assert s.energy == 0

    def test_out_of_window_still_displayed(self):
        s = score_hour(SPOT, hour((SwellPartition(1.5, 12.0, 100.0),)))
        assert len(s.hour.partitions) == 1  # partition kept for display

    def test_onshore_blown_out(self):
        # good swell, 30 kph onshore: size 40 + period 10 + wind 0 = 50
        s = score_hour(SPOT, hour((SwellPartition(1.0, 10.0, 290.0),), 30.0, 270.0))
        assert s.wind_score == 0
        assert s.rating == 50
        assert s.wind_class == "onshore"

    def test_tide_shifts_breaker_height(self):
        # Stage 2D: with a depth profile, higher water breaks the (depth-limited) wave at a
        # deeper point -> a bigger breaker. Micro-tidal spots barely move; this is a big swing.
        from dataclasses import replace

        wet = [(4000.0, 30.0), (1000.0, 12.0), (400.0, 5.0), (150.0, 2.0)]
        parts = (SwellPartition(2.0, 14.0, 290.0),)
        low = score_hour(SPOT, hour(parts), wet)  # tide_m None
        high = score_hour(SPOT, replace(hour(parts), tide_m=1.5), wet)
        assert high.h_break_mid > low.h_break_mid


class TestCalibrationFix1:
    """Regression for the two failure modes fix #1 caught, held under the row-2 (linear q,
    2026-07-20) recalibration: a cross-shore daytime windswell stays POOR, and a perfect
    night land breeze on the same swell can't inflate past FAIR (it was FIRING 77).
    Row 2 (q exp 1.4) reads the height moderately higher than the old quadratic to match
    Surfline LOTUS without over-calling - this windswell stays shin-high POOR. See
    docs/CALIBRATION.md."""

    WINDSWELL = (SwellPartition(0.66, 5.2, 290.0),)

    def test_windswell_daytime_rating(self):
        s = score_hour(SPOT, hour(self.WINDSWELL, 12.9, 216.0))  # the audited conditions
        assert s.phrase == "shin-high"  # row 2 exp 1.4 reads ~0.26 m
        assert s.bucket == "POOR"  # cross-shore wind keeps it POOR (rating 22)
        assert s.rating < 30

    def test_night_land_breeze_cannot_fire(self):
        # perfect light offshore on the same swell: was FIRING 77, must never fire
        s = score_hour(SPOT, hour(self.WINDSWELL, 6.4, 90.0))
        assert s.bucket == "POOR"  # never GOOD/FIRING off wind alone (rating 29)
        assert s.wind_score < 40  # wind gate (denom 60) still clamps the stored value

    def test_wind_gate_saturates_on_real_swell(self):
        # size 40 + period 20 >= 60 -> gate is 1, wind untouched
        s = score_hour(SPOT, hour((SwellPartition(1.0, 14.0, 290.0),)))
        assert s.wind_score == 40


def test_wind_gate_docstring_matches_the_constant():
    """Dream review 2026-08-05: the module docstring said the gate divides by 30 while
    WIND_GATE_PTS is 60. The formula is published in-app ("why this rating"), so the
    docstring is spec, not decoration - hold it to the named constant."""
    import rosa_pipeline.score as score_mod

    assert score_mod.__doc__ is not None
    assert f"(size + period) / {score_mod.WIND_GATE_PTS:.0f}" in score_mod.__doc__
