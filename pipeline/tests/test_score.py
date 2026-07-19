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
        # chest-high 10s W swell, light offshore -> size 40 + period 10 + wind 40 = 90
        s = score_hour(SPOT, hour((SwellPartition(1.0, 10.0, 290.0),)))
        assert s.rating == 90
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
