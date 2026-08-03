import math

import pytest

from rosa_pipeline.models import SwellPartition
from rosa_pipeline.physics import breaker_height_over_profile
from rosa_pipeline.transform import (
    EXPOSURE_SHOULDER_DEG,
    FIELD_ENERGY_EXP,
    RIDEABILITY_EXP,
    angle_diff,
    breaker_height_from_profile,
    breaker_range,
    classify_wind,
    dominant_partition,
    effective_height_in_window,
    energy_in_window,
    energy_kj_per_m,
    energy_period,
    exposure_weight,
    field_coherence,
    height_in_window,
    height_phrase,
    in_window,
    partition_closure,
    period_quality,
    period_rideability,
    rideability_period,
    spread_exposure,
    wetsuit,
)

WINDOW = (250.0, 340.0)
# Wide enough that a partition at 290-300 keeps its whole directional fan inside
# the arc, so the formula tests below read exactly - windowing itself is tested
# against WINDOW (see TestSpreadExposure).
WIDE = (200.0, 20.0)


def swell(h: float, t: float, d: float) -> SwellPartition:
    return SwellPartition(height_m=h, period_s=t, direction_deg=d)


class TestPeriodRideability:
    def test_groundswell_rides_full(self):
        assert period_rideability(10.0) == 1.0
        assert period_rideability(14.0) == 1.0  # capped at 1.0, never amplifies

    def test_windswell_attenuated_to_floor(self):
        assert period_rideability(4.0) == 0.3  # (0.4)^exp is well under the floor
        assert period_rideability(2.0) == 0.3

    def test_midrange_between_floor_and_one(self):
        # tracks the constant rather than pinning it - the exponent is a calibration knob
        # (1.4 until 2026-08-02, 2.2 after the depth march was closed)
        assert period_rideability(6.0) == pytest.approx((0.6) ** RIDEABILITY_EXP)
        assert 0.3 < period_rideability(6.0) < 1.0


class TestRideabilityPeriod:
    """Stage 2E (2026-07-30): rideability keys on Tp, not the mean period."""

    def test_prefers_the_peak_period(self):
        p = SwellPartition(height_m=1.0, period_s=5.9, direction_deg=290.0, peak_period_s=8.4)
        assert rideability_period(p) == 8.4

    def test_falls_back_to_mean_when_the_model_publishes_no_peak(self):
        p = SwellPartition(height_m=1.0, period_s=5.9, direction_deg=290.0)
        assert rideability_period(p) == 5.9

    def test_breaker_height_uses_the_peak_period(self):
        """The production default must attenuate on Tp: the same sea with a peak period
        declared has to break higher than one the model gave only a mean for."""
        depths = [40.0, 20.0, 10.0, 6.0, 3.0, 1.5, 0.8]
        mean_only = (SwellPartition(height_m=1.4, period_s=5.9, direction_deg=290.0),)
        with_peak = (
            SwellPartition(height_m=1.4, period_s=5.9, direction_deg=290.0, peak_period_s=8.4),
        )
        h_mean = breaker_height_from_profile(mean_only, WIDE, 290.0, depths)
        h_peak = breaker_height_from_profile(with_peak, WIDE, 290.0, depths)
        assert h_peak > h_mean

    def test_long_period_swell_is_unchanged_by_the_key(self):
        """Above the 1.0 cap the key cannot matter - this is why the change left every
        groundswell region bit-identical (CALIBRATION.md 2026-07-30)."""
        depths = [40.0, 20.0, 10.0, 6.0, 3.0, 1.5, 0.8]
        mean_only = (SwellPartition(height_m=1.4, period_s=12.0, direction_deg=290.0),)
        with_peak = (
            SwellPartition(height_m=1.4, period_s=12.0, direction_deg=290.0, peak_period_s=15.0),
        )
        assert breaker_height_from_profile(with_peak, WIDE, 290.0, depths) == pytest.approx(
            breaker_height_from_profile(mean_only, WIDE, 290.0, depths)
        )


class TestPartitionClosure:
    """2026-07-30: Open-Meteo does not always fit all its energy into the four partition
    fields it publishes, and the partitions are all the transform sees."""

    def test_full_closure_when_partitions_are_the_whole_sea(self):
        parts = (swell(1.2, 10.0, 290.0), swell(0.9, 6.0, 300.0))
        total = math.sqrt(1.2**2 + 0.9**2)
        assert partition_closure(parts, total) == pytest.approx(1.0)

    def test_detects_unaccounted_energy(self):
        """The live Hikkaduwa case: 1.02/1.04/0.72 m of partitions against a 2.24 m total."""
        parts = (
            swell(1.02, 4.0, 248.0),
            swell(1.04, 10.0, 186.0),
            swell(0.72, 17.0, 188.0),
        )
        c = partition_closure(parts, 2.24)
        assert c == pytest.approx(0.72, abs=0.01)

    def test_none_without_a_source_total(self):
        assert partition_closure((swell(1.0, 10.0, 290.0),), None) is None
        assert partition_closure((swell(1.0, 10.0, 290.0),), 0.0) is None

    def test_combines_in_energy_not_height(self):
        """Two equal partitions make a sea sqrt(2)x one of them, not 2x - closure must use
        the energy sum, or every multi-swell hour would look like it was missing sea."""
        parts = (swell(1.0, 10.0, 290.0), swell(1.0, 10.0, 300.0))
        assert partition_closure(parts, 2.0) == pytest.approx(math.sqrt(2) / 2)


class TestExposureWeight:
    def test_full_inside_window_including_edges(self):
        assert exposure_weight(295.0, WINDOW) == 1.0
        assert exposure_weight(250.0, WINDOW) == 1.0  # edges are inside
        assert exposure_weight(340.0, WINDOW) == 1.0

    def test_cosine_taper_just_beyond_edge(self):
        w = exposure_weight(350.0, WINDOW)  # 10° past the 340 edge
        assert w == pytest.approx(math.cos((10.0 / EXPOSURE_SHOULDER_DEG) * (math.pi / 2)))
        assert 0.0 < w < 1.0

    def test_symmetric_either_side(self):
        assert exposure_weight(240.0, WINDOW) == pytest.approx(exposure_weight(350.0, WINDOW))

    def test_zero_beyond_shoulder(self):
        assert exposure_weight(340.0 + EXPOSURE_SHOULDER_DEG + 5, WINDOW) == 0.0
        assert exposure_weight(100.0, WINDOW) == 0.0


# deep -> shallow depth profile for the transform tests (straight-in when shore_normal == dir)
PROFILE_FIX = [180.0, 50.0, 20.0, 8.0, 3.0, 1.5]
# As above but stopping where GEBCO really does (~8 m), so every partition takes the
# breaker-index branch and no march/index step can be mistaken for combine behaviour.
DEEP_FIX = [180.0, 50.0, 20.0, 8.0]


class TestBreakerHeightFromProfile:
    def test_windswell_rides_well_below_physical_height(self):
        h = breaker_height_from_profile((swell(0.6, 4.0, 290.0),), WINDOW, 290.0, PROFILE_FIX)
        assert 0.0 < h < 0.3  # short period pulled down by the rideability floor

    def test_groundswell_bigger_than_windswell_same_height(self):
        wind = breaker_height_from_profile((swell(1.0, 4.0, 290.0),), WINDOW, 290.0, PROFILE_FIX)
        ground = breaker_height_from_profile((swell(1.0, 14.0, 290.0),), WINDOW, 290.0, PROFILE_FIX)
        assert ground > wind

    def test_out_of_window_partition_excluded(self):
        h = breaker_height_from_profile((swell(1.5, 12.0, 100.0),), WINDOW, 290.0, PROFILE_FIX)
        assert h == 0.0

    def test_swell_outside_the_arc_still_delivers_its_fan(self):
        # a swell whose mean sits outside the window still lands part of its
        # directional fan inside it - below an in-window one, but never zero
        # (the Pipeline case, 2026-07-29). Only a swell whose whole fan misses
        # the arc drops out.
        fx, sn = PROFILE_FIX, 295.0
        inside = breaker_height_from_profile((swell(1.0, 12.0, 295.0),), WINDOW, sn, fx)
        outside = breaker_height_from_profile((swell(1.0, 12.0, 355.0),), WINDOW, sn, fx)
        far = breaker_height_from_profile((swell(1.0, 12.0, 100.0),), WINDOW, sn, fx)
        assert 0.0 < outside < inside
        assert far == 0.0

    # --- partition combination (rewritten 2026-08-03; was `test_rms_combines_partitions`,
    # which pinned sqrt(sum Hb^2). That double-counted: it ran the sublinear breaker index
    # once per partition AND merged crossing trains into one wave. See CALIBRATION.md.)

    def test_one_partition_is_untouched_by_the_field_combine(self):
        # the regression that matters: single-swell hours must be bit-identical to
        # the pre-2026-08-03 transform, so the Israel eye frames still grade the same
        one = breaker_height_from_profile((swell(0.8, 12.0, 290.0),), WINDOW, 290.0, PROFILE_FIX)
        w = spread_exposure(swell(0.8, 12.0, 290.0), WINDOW)
        expect = (
            breaker_height_over_profile(0.8, 12.0, 0.0, PROFILE_FIX)
            * period_rideability(12.0)
            * math.sqrt(w)
        )
        assert one == pytest.approx(expect, rel=1e-12)

    def test_aligned_swells_add_their_energy_once(self):
        # same bearing = one wave field: the energy adds, but the breaker index is
        # applied to the combined sea ONCE, so the result is below the old sqrt(2) RMS
        one = breaker_height_from_profile((swell(0.8, 12.0, 290.0),), WINDOW, 290.0, PROFILE_FIX)
        two = breaker_height_from_profile(
            (swell(0.8, 12.0, 290.0), swell(0.8, 12.0, 290.0)), WINDOW, 290.0, PROFILE_FIX
        )
        assert two == pytest.approx(one * 2 ** (1 / FIELD_ENERGY_EXP), rel=1e-9)
        assert one < two < one * math.sqrt(2)

    def test_crossing_swells_do_not_add(self):
        # 90 deg apart is two separate seas breaking at two different angles - the
        # surf height is the dominant one's, not the pair's
        one = breaker_height_from_profile((swell(0.8, 12.0, 290.0),), WINDOW, 290.0, PROFILE_FIX)
        crossed = breaker_height_from_profile(
            (swell(0.8, 12.0, 290.0), swell(0.8, 12.0, 340.0)), WINDOW, 290.0, PROFILE_FIX
        )
        assert crossed == pytest.approx(one, rel=1e-9)

    def test_combine_decays_monotonically_with_separation(self):
        heights = [
            breaker_height_from_profile(
                (swell(0.8, 12.0, 290.0), swell(0.8, 12.0, 290.0 + d)), WINDOW, 290.0, PROFILE_FIX
            )
            for d in (0, 10, 20, 30, 40, 50)
        ]
        assert heights == sorted(heights, reverse=True)
        assert heights[-1] == pytest.approx(
            breaker_height_from_profile((swell(0.8, 12.0, 290.0),), WINDOW, 290.0, PROFILE_FIX)
        )

    def test_combine_is_smooth_under_direction_wander(self):
        # Open-Meteo reshuffles partition directions by a few degrees hour to hour
        # (CALIBRATION.md 2026-07-29). A hard cluster threshold made the published
        # height jump ~0.2 m on a 3 deg wander; this taper must not.
        # DEEP_FIX, not PROFILE_FIX: a profile whose shallowest sample is 1.5 m lets the
        # march break in-profile at low incidence and fall through to the breaker index at
        # high incidence, and those two branches disagree by ~0.13 m - a real step, but one
        # in physics.py's march/index handoff, not in the combine under test here. Real
        # GEBCO profiles bottom out around 7-13 m, which is why 97-100% of published hours
        # take the index branch anyway.
        def h(d: float) -> float:
            return breaker_height_from_profile(
                (swell(0.8, 12.0, 290.0), swell(0.75, 12.0, d)), WINDOW, 290.0, DEEP_FIX
            )

        for d in range(290, 340):
            assert abs(h(d + 1) - h(d)) < 0.02

    def test_field_coherence_shape(self):
        assert field_coherence(0.0, 20.0, 20.0) == pytest.approx(1.0)
        assert field_coherence(40.0, 20.0, 20.0) == 0.0  # fans exactly stop overlapping
        assert field_coherence(60.0, 20.0, 20.0) == 0.0  # past the fans
        assert 0.0 < field_coherence(20.0, 20.0, 20.0) < 1.0
        # a broader pair of fans stays coherent further apart
        assert field_coherence(40.0, 35.0, 25.0) > field_coherence(40.0, 20.0, 20.0)


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
    def test_counts_only_what_reaches_the_spot(self):
        # the in-arc swell counts in full; one arriving from behind the coast
        # adds only the sliver of its fan that grazes the arc - never its bulk
        in_arc = energy_in_window((swell(1.0, 10, 290),), WIDE)
        with_behind = energy_in_window((swell(1.0, 10, 290), swell(2.0, 8, 110)), WIDE)
        assert in_arc == pytest.approx(1.0**2 * 10)
        assert in_arc < with_behind < in_arc * 1.05

    def test_empty(self):
        assert energy_in_window((), WINDOW) == 0


class TestEnergyPeriod:
    def test_prefers_peak_period(self):
        p = SwellPartition(height_m=1.0, period_s=5.8, direction_deg=290, peak_period_s=8.4)
        assert energy_period(p) == pytest.approx(0.9 * 8.4)

    def test_falls_back_to_mean_period(self):
        assert energy_period(swell(1.0, 6.0, 290)) == 6.0


class TestEnergyKjPerM:
    def test_scales_with_height_squared_and_period_squared(self):
        p = SwellPartition(height_m=1.5, period_s=5.9, direction_deg=290, peak_period_s=8.4)
        te = 0.9 * 8.4
        assert energy_kj_per_m((p,), WIDE) == pytest.approx(0.98 * 1.5**2 * te**2)

    def test_out_of_window_excluded(self):
        assert energy_kj_per_m((swell(2.0, 12, 100),), WINDOW) == 0

    def test_matches_the_flux_identity(self):
        """E·L = 2·P·Te - the kJ figure and the old 0.49·H²·Te kW/m flux are the same physics."""
        p = swell(1.2, 9.0, 290)
        flux_kw_per_m = 0.49 * p.height_m**2 * p.period_s
        expected = 2 * flux_kw_per_m * p.period_s
        assert energy_kj_per_m((p,), WIDE) == pytest.approx(expected, rel=1e-2)


class TestHeightInWindow:
    def test_rms_combination(self):
        partitions = (swell(0.6, 8, 290), swell(0.8, 10, 300))
        assert height_in_window(partitions, WIDE) == pytest.approx((0.6**2 + 0.8**2) ** 0.5)

    def test_out_of_window_excluded(self):
        assert height_in_window((swell(2.0, 10, 100),), WINDOW) == 0


class TestPeriodQuality:
    def test_reference_period(self):
        assert period_quality(10.0) == 1.0

    def test_windswell_discounted(self):
        assert period_quality(5.0) == pytest.approx(0.5**1.4)  # exp 1.4 (calibration row 2)

    def test_clamps(self):
        assert period_quality(3.0) == 0.3  # floor
        assert period_quality(12.0) == 1.2  # groundswell cap (1.2 clamped)
        assert period_quality(20.0) == 1.2


class TestEffectiveHeight:
    def test_short_period_discounted(self):
        # calibration row 2 (q exp 1.4): 0.66 m @ 5.2 s surfs shin-high ~0.26 m
        h = effective_height_in_window((swell(0.66, 5.2, 290),), WIDE)
        assert h == pytest.approx(0.66 * 0.52**1.4)

    def test_long_period_boosted(self):
        h = effective_height_in_window((swell(1.0, 14.0, 290),), WIDE)
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
        assert wetsuit(19.0) == "spring / 2mm"
        assert wetsuit(18.0) == "3/2"
        assert wetsuit(16.0) == "4/3"
        assert wetsuit(13.0) == "5/4 + boots"
        assert wetsuit(10.0) == "5/4 hooded + gloves"
        assert wetsuit(8.0) == "6/5 hooded"


class TestSpreadExposure:
    """The swell fan (2026-07-29). A partition is not a pencil beam: its energy
    spreads +-20-35 deg about the mean, so a swell whose mean sits outside the
    arc still delivers part of itself. Before this, Pipeline read 0.0-0.1 m with
    a 1.9 m sea offshore while Surfline called 0.3-0.6 m."""

    def test_a_swell_centred_in_a_wide_arc_arrives_whole(self):
        assert spread_exposure(swell(1.0, 12, 290), WIDE) == pytest.approx(1.0)

    def test_a_swell_just_outside_the_arc_still_arrives(self):
        # 20 deg beyond the edge: reduced, but nowhere near zero
        w = spread_exposure(swell(1.0, 8, 360), WINDOW)
        assert 0.1 < w < 0.6

    def test_more_energy_arrives_the_closer_the_mean_is_to_the_arc(self):
        near = spread_exposure(swell(1.0, 8, 350), WINDOW)
        far = spread_exposure(swell(1.0, 8, 30), WINDOW)
        assert near > far

    def test_a_wider_fan_delivers_more_from_outside(self):
        # windsea spreads (35 deg) further than groundswell (20-25), so an
        # equally off-axis windsea leaks more energy into the arc
        windsea = SwellPartition(height_m=1.0, period_s=6.0, direction_deg=5.0, kind="wind")
        groundswell = SwellPartition(height_m=1.0, period_s=12.0, direction_deg=5.0, kind="swell")
        assert spread_exposure(windsea, WINDOW) > spread_exposure(groundswell, WINDOW)

    def test_energy_never_collapses_to_zero_with_a_real_sea_offshore(self):
        """The rule the whole change exists for: a metre offshore cannot read as
        nothing at the spot unless the swell is a fan-width and more off-axis."""
        # Pipeline's arc, and the ENE trade swell that broke it (2026-07-28)
        pipeline_arc = (270.0, 30.0)
        trade = swell(1.9, 8.0, 70.0)
        reaching = height_in_window((trade,), pipeline_arc)
        assert reaching > 0.5, "a 1.9 m sea 40 deg off-axis must still reach the beach"

    def test_energy_and_height_agree_about_what_arrives(self):
        """A row can never show real surf next to 0 kJ (the old hard-window bug)."""
        p = swell(1.5, 9.0, 355.0)  # outside WINDOW, fan still reaching
        assert height_in_window((p,), WINDOW) > 0
        assert energy_kj_per_m((p,), WINDOW) > 0
