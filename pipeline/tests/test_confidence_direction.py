"""Direction axis of ensemble agreement (2026-08-07): fetched bearings finally read.

The ensemble request always fetched wave_direction per member; nothing consumed
it. The member fan (widest pairwise bearing gap) is now measured and recorded on
Agreement.dir_span_deg as a DIAGNOSTIC. It does not score: penalising on it needs
a CALIBRATION.md entry first (the 2026-08-07 review found the proposed tolerance
borrowed a per-partition constant for a total-sea quantity). These tests pin both
halves: the span is measured right, and the score is untouched by it.
"""

from __future__ import annotations

from rosa_pipeline.confidence import (
    agreement_from_heights,
    agreement_from_members,
    direction_span_deg,
    member_directions_at,
)


def test_member_direction_extraction_tracks_height_members() -> None:
    hourly = {
        "time": ["t0"],
        "wave_height_ewam": [1.0],
        "wave_height_gwam": [1.2],
        "wave_direction_ewam": [350.0],
        "wave_direction_gwam": [10.0],
    }
    assert member_directions_at(hourly, 0) == [350.0, 10.0]
    # a height member with no direction column contributes no bearing
    hourly["wave_height_meteofrance_wam"] = [1.1]
    assert member_directions_at(hourly, 0) == [350.0, 10.0]


def test_direction_span_is_circular() -> None:
    assert direction_span_deg([350.0, 10.0]) == 20.0  # wraps through 360, not 340
    assert direction_span_deg([270.0]) is None  # need >=2 bearings
    assert direction_span_deg([]) is None
    assert direction_span_deg([0.0, 90.0, 180.0]) == 180.0  # widest pair, not adjacent


def test_span_is_recorded_on_agreement() -> None:
    a = agreement_from_members([1.4, 1.4], [100.0, 130.0])
    assert a.dir_span_deg == 30.0
    assert agreement_from_members([1.4, 1.4], [100.0]).dir_span_deg is None


def test_direction_never_scores() -> None:
    # diagnostic only until calibrated: even a fully opposed fan leaves the
    # calibrated Hs score untouched
    fanned = agreement_from_members([1.4, 1.4], [0.0, 180.0])
    assert fanned.score == agreement_from_heights([1.4, 1.4]).score == 1.0


def test_heights_only_callers_are_unchanged() -> None:
    # fixtures captured before wave_direction was read must score exactly as before
    a = agreement_from_heights([1.0, 2.0])
    assert a.dir_span_deg is None
    assert abs(a.score - (1 - (0.5 / 1.5) / 0.6)) < 1e-9
