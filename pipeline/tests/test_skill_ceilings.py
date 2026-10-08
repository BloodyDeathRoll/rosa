"""Measured horizon ceilings (2026-08-07): the last hand-set numbers in the
confidence chain become derivable from the shipped verification harness.

verify --archive --write-skill persists skill.json (per lead bucket: n over
DISTINCT compared hours, bias, mae, rmse, scatter index, plus the contributing
buoy ids); publish.load_skill_ceilings maps each tier's n-weighted scatter index
onto a ceiling (1 - SI, clamped), falls back to the pre-existing static
constants whenever a tier's sample count is under SKILL_N_FLOOR, and clamps the
result monotone non-increasing across tiers. The payload publishes which source
(and which buoys) the ceiling came from.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rosa_pipeline.publish import (
    _CEILING_TIERS,
    SKILL_N_FLOOR,
    _horizon_ceiling,
    load_skill_ceilings,
)
from rosa_pipeline.verify import LEAD_BUCKETS, VarScore, merge_var_scores, skill_payload


def _vs(n: int, *, rmse: float = 0.2, si: float | None = 0.2) -> VarScore:
    return VarScore("hs", "Sig. wave height", "m", n, 0.05, 0.15, rmse, si)


def _skill_file(tmp_path: Path, buckets: dict) -> Path:
    p = tmp_path / "skill.json"
    p.write_text(json.dumps({"generated": "2026-08-07T00:00:00+00:00", "buckets": buckets}))
    return p


def test_static_defaults_without_skill_file(tmp_path: Path) -> None:
    assert load_skill_ceilings(tmp_path / "absent.json") is None
    # and the ceiling function keeps the documented constants
    assert _horizon_ceiling(0) == 1.0
    assert _horizon_ceiling(9) == 0.85
    assert _horizon_ceiling(10) == 0.4


def test_tier_buckets_cover_exactly_the_days_they_price() -> None:
    # day N = leads [24N, 24N+24); a tier priced from fresher (or older) leads than
    # the days it covers misstates confidence - the day-3 bug of the 2026-08-07 review
    ranges = {label: (lo, hi) for label, lo, hi in LEAD_BUCKETS}
    prev_max = -1
    for max_day, _static, labels in _CEILING_TIERS:
        lo = min(ranges[lb][0] for lb in labels)
        hi = max(ranges[lb][1] for lb in labels)
        # buckets are contiguous within the tier
        assert sorted(ranges[lb] for lb in labels) == [ranges[lb] for lb in labels]
        assert lo == (prev_max + 1) * 24.0
        assert hi == (max_day + 1) * 24.0 if max_day is not None else hi == float("inf")
        prev_max = max_day if max_day is not None else prev_max
    # day 3 specifically: priced by tier 0, whose buckets end at 96 h = day 3's last lead
    assert _horizon_ceiling(3, {0: 0.5, 1: 0.85, 2: 0.4}) == 0.5


def test_measured_tier_maps_scatter_index_to_ceiling(tmp_path: Path) -> None:
    n = SKILL_N_FLOOR  # exactly at the floor counts as matured
    path = _skill_file(
        tmp_path,
        {
            "0-1d": {"n": n, "scatter_index": 0.15},
            "1-3d": {"n": n, "scatter_index": 0.25},
            # far tiers not matured -> fall back (then monotone-clamped, below)
            "4-5d": {"n": 3, "scatter_index": 0.4},
            "9d+": {"n": 0},
        },
    )
    ceilings, source = load_skill_ceilings(path)
    # tier 0: n-weighted SI = 0.2 -> ceiling 0.8 (was a hand-set 1.0)
    assert abs(_horizon_ceiling(2, ceilings) - 0.8) < 1e-9
    # tier 1 fell back to static 0.85, then clamped to tier 0's 0.8: confidence
    # must not RISE with lead time while far tiers are still maturing
    assert abs(_horizon_ceiling(5, ceilings) - 0.8) < 1e-9
    # tier 2's static 0.4 already sits below - untouched
    assert _horizon_ceiling(12, ceilings) == 0.4
    assert source.startswith("measured")


def test_ceilings_are_monotone_even_when_far_tier_measures_better(tmp_path: Path) -> None:
    n = SKILL_N_FLOOR
    path = _skill_file(
        tmp_path,
        {
            "0-1d": {"n": n, "scatter_index": 0.3},  # tier 0 measured: 0.7
            "5-7d": {"n": n, "scatter_index": 0.1},  # tier 1 measured "better": 0.9
        },
    )
    ceilings, _source = load_skill_ceilings(path)
    assert abs(_horizon_ceiling(1, ceilings) - 0.7) < 1e-9
    assert abs(_horizon_ceiling(6, ceilings) - 0.7) < 1e-9  # clamped, not 0.9


def test_all_tiers_under_floor_reads_as_static(tmp_path: Path) -> None:
    path = _skill_file(tmp_path, {"0-1d": {"n": 5, "scatter_index": 0.9}})
    ceilings, source = load_skill_ceilings(path)
    assert _horizon_ceiling(0, ceilings) == 1.0  # not degraded by 5 samples
    assert source.startswith("static defaults")


def test_corrupt_skill_file_is_static_not_fatal(tmp_path: Path, capsys) -> None:
    p = tmp_path / "skill.json"
    p.write_text("{ torn")
    assert load_skill_ceilings(p) is None
    # a torn file IS damage and must still say so
    assert "unreadable" in capsys.readouterr().out


def test_empty_skill_file_is_the_ab_control_arm_and_stays_quiet(tmp_path: Path, capsys) -> None:
    # `run --skill /dev/null` is the documented control arm: static ceilings, and no
    # warning, because a scary line in one arm is what gets an A/B disbelieved
    for body in ("", "   \n"):
        p = tmp_path / "skill.json"
        p.write_text(body)
        assert load_skill_ceilings(p) is None
        assert capsys.readouterr().out == ""
    assert load_skill_ceilings(Path("/dev/null")) is None
    assert capsys.readouterr().out == ""


def test_malformed_buckets_are_static_not_fatal(tmp_path: Path) -> None:
    # parseable-but-wrong shapes must read as "no measurement", never abort a
    # publish cycle (load_skill_ceilings runs before _cmd_run's per-spot guard)
    assert load_skill_ceilings(_skill_file(tmp_path, {"0-1d": {"scatter_index": 0.2}})) is None
    assert (
        load_skill_ceilings(_skill_file(tmp_path, {"0-1d": {"n": None, "scatter_index": 0.2}}))
        is None
    )
    p = tmp_path / "skill.json"
    p.write_text(json.dumps({"generated": "x", "buckets": "not-a-dict"}))
    assert load_skill_ceilings(p) is None


def test_measured_source_names_its_buoys(tmp_path: Path) -> None:
    p = tmp_path / "skill.json"
    p.write_text(
        json.dumps(
            {
                "generated": "2026-08-07T00:00:00+00:00",
                "buoy_ids": ["46042", "Leixoes-coast-buoy"],
                "buckets": {"0-1d": {"n": SKILL_N_FLOOR, "scatter_index": 0.2}},
            }
        )
    )
    _ceilings, source = load_skill_ceilings(p)
    # a fleet-wide ceiling measured at two buoys says so in the payload's provenance
    assert "46042" in source and "Leixoes-coast-buoy" in source


def test_merge_var_scores_is_n_weighted() -> None:
    merged = merge_var_scores([_vs(100, si=0.1), _vs(300, si=0.3)])
    assert merged.n == 400
    assert abs(merged.scatter_index - 0.25) < 1e-9  # (100*0.1 + 300*0.3)/400
    assert merge_var_scores([_vs(0)]) is None  # empty buckets merge to None, not zeros


def test_merge_var_scores_refuses_to_pool_two_period_pairings() -> None:
    """The fleet loop picks the period pairing PER BUOY (Energy period where a spectrum is
    published, APD elsewhere), so a pool of buoy cards can hold both. Their ~2 s
    definitional offset must never be n-weighted into one bias under whichever label
    sorted first - verify.py's docstring forbids calibrating against exactly that."""
    from rosa_pipeline.verify import APD_FALLBACK_LABEL

    energy = VarScore("tp", "Energy period", "s", 100, 0.5, 1.0, 1.2, 0.1)
    apd = VarScore("tp", APD_FALLBACK_LABEL, "s", 100, 2.7, 2.8, 3.0, 0.3)
    with pytest.raises(ValueError, match=r"Energy period.*Mean per\. vs APD"):
        merge_var_scores([energy, apd])
    # an n=0 cell carries no samples, so its label cannot poison the pool
    assert merge_var_scores([energy, VarScore("tp", APD_FALLBACK_LABEL, "s", 0, 0, 0, 0, 0)])
    assert merge_var_scores([energy, energy]).n == 200


def test_skill_payload_covers_every_bucket_and_carries_provenance() -> None:
    by_lead = {label: {"hs": _vs(10)} for label, _lo, _hi in LEAD_BUCKETS}
    out = skill_payload([by_lead], generated="2026-08-07T00:00:00+00:00", buoy_ids=["46042"])
    assert set(out["buckets"]) == {label for label, _lo, _hi in LEAD_BUCKETS}
    assert out["buckets"]["0-1d"]["n"] == 10
    assert out["variable"] == "hs"
    assert out["buoy_ids"] == ["46042"]


def test_measured_source_names_only_buoys_with_compared_hours(tmp_path: Path) -> None:
    """A registered buoy that paired zero hours (a wave-silent station) contributed
    nothing to the ceiling, so the published provenance must not name it."""
    reporting = {label: {"hs": _vs(SKILL_N_FLOOR)} for label, _lo, _hi in LEAD_BUCKETS}
    silent = {label: {"hs": _vs(0)} for label, _lo, _hi in LEAD_BUCKETS}
    out = skill_payload(
        [reporting, silent],
        generated="2026-09-30T00:00:00+00:00",
        buoy_ids=["A-reporting", "B-silent"],
    )
    assert out["buoy_ids"] == ["A-reporting", "B-silent"]  # the pass reached both
    assert out["buoy_hours"]["B-silent"] == 0
    p = tmp_path / "skill.json"
    p.write_text(json.dumps(out))
    _ceilings, source = load_skill_ceilings(p)
    assert "A-reporting" in source and "B-silent" not in source


def test_provenance_names_the_measured_card(tmp_path: Path) -> None:
    """OPEN-ITEMS 37a: skill.json says which forecast its numbers measure (the shipped
    blend since 2026-10-08), and the published ceiling_source repeats it; a file
    without the key (written before) reads exactly as it always did."""
    buckets = {lb: {"n": SKILL_N_FLOOR, "scatter_index": 0.2} for lb, _a, _b in LEAD_BUCKETS}
    p = tmp_path / "skill.json"
    p.write_text(json.dumps({"generated": "g", "source": "blend", "buckets": buckets}))
    _ceilings, why = load_skill_ceilings(p)
    assert why.startswith("measured (verify skill.json g, blend card, buoys:")
    p.write_text(json.dumps({"generated": "g", "buckets": buckets}))
    _ceilings, why = load_skill_ceilings(p)
    assert why.startswith("measured (verify skill.json g, buoys:")
