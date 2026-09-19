"""Multi-model agreement → confidence: metric math, extract wiring, publish combine."""

from __future__ import annotations

from pathlib import Path

from rosa_pipeline.confidence import (
    agreement_from_heights,
    member_heights_at,
    member_suffixes,
)
from rosa_pipeline.extract import extract_hours
from rosa_pipeline.fetch import FixtureSource, RawForecast
from rosa_pipeline.publish import _confidence, build_payload
from rosa_pipeline.score import score_hour
from rosa_pipeline.spots import load_spots

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"


def test_member_discovery_and_extraction() -> None:
    hourly = {
        "time": ["t0", "t1"],
        "wave_height_ewam": [1.0, None],
        "wave_height_gwam": [1.2, 1.3],
        "wave_height_ncep_gfswave016": [0.9, 1.1],
    }
    assert member_suffixes(hourly) == ["ewam", "gwam", "ncep_gfswave016"]
    assert member_heights_at(hourly, 0) == [1.0, 1.2, 0.9]
    assert member_heights_at(hourly, 1) == [1.3, 1.1]  # ewam None dropped


def test_agreement_math() -> None:
    assert agreement_from_heights([1.0, 1.0, 1.0]).score == 1.0  # zero spread → perfect
    assert agreement_from_heights([1.0]) is None  # need ≥2 members
    assert agreement_from_heights([]) is None
    # mean 1.5, pstdev 0.5, cov 0.333, score = 1 - 0.333/0.6
    a = agreement_from_heights([1.0, 2.0])
    assert a.n_models == 2 and abs(a.score - (1 - (0.5 / 1.5) / 0.6)) < 1e-9
    # wild disagreement clamps to 0, never negative
    assert agreement_from_heights([0.1, 5.0]).score == 0.0


def test_publish_confidence_combines_agreement_and_horizon() -> None:
    assert _confidence(0, None) == ("high", 1.0)  # near term, no ensemble → horizon proxy
    assert _confidence(0, 0.5) == ("medium", 0.5)  # agreement drags a day-0 down
    assert _confidence(5, 0.3) == ("low", 0.3)
    assert _confidence(5, None) == ("high", 0.85)  # mid-range horizon proxy
    # day 10+ tail is GFS-only: even perfect agreement is capped low
    assert _confidence(12, 0.95) == ("low", 0.4)
    assert _confidence(12, None) == ("low", 0.4)


def _raw_with_ensemble(members: dict[str, float]) -> RawForecast:
    """Real fixture marine+weather, plus a synthetic constant-value ensemble aligned to it."""
    raw = FixtureSource(FIX).fetch(32.3817, 34.8035)  # beit-yanai offshore point
    times = raw.marine["hourly"]["time"]
    hourly = {"time": times}
    for suffix, value in members.items():
        hourly[f"wave_height_{suffix}"] = [value] * len(times)
    return RawForecast(
        fetched_at=raw.fetched_at,
        marine=raw.marine,
        weather=raw.weather,
        ensemble={"hourly": hourly},
    )


def test_extract_attaches_agreement_from_ensemble() -> None:
    hours = extract_hours(_raw_with_ensemble({"ncep_gfswave016": 1.0, "ewam": 1.0, "gwam": 1.0}))
    assert hours and all(h.agreement_score == 1.0 and h.n_models == 3 for h in hours)
    # no ensemble at all → agreement stays None (graceful, horizon proxy takes over)
    bare = FixtureSource(FIX).fetch(32.3817, 34.8035)
    assert all(h.agreement_score is None and h.n_models == 0 for h in extract_hours(bare))


def test_end_to_end_confidence_in_payload() -> None:
    from datetime import UTC, datetime

    spot = load_spots(ROOT / "data" / "spots")["beit-yanai"]
    raw = _raw_with_ensemble({"ncep_gfswave016": 1.0, "ewam": 1.0, "gwam": 1.0})
    scored = [score_hour(spot, h) for h in extract_hours(raw)]
    payload = build_payload(spot, scored, fetched_at=raw.fetched_at, now=datetime.now(UTC))
    conf = payload["current"]["confidence"]
    assert conf["models"] == 3 and conf["score"] == 1.0 and conf["label"] == "high"
    assert all("confidence" in d and "confidence_score" in d for d in payload["days"])


def test_day_confidence_is_read_off_the_daylight_hours_the_headline_uses() -> None:
    from datetime import UTC, datetime

    spot = load_spots(ROOT / "data" / "spots")["beit-yanai"]
    raw = _raw_with_ensemble({"ncep_gfswave016": 1.0, "ewam": 1.0, "gwam": 1.0})
    # the members go missing in the dead of night (22-01 UTC = 01-04 in Israel)
    for key, col in raw.ensemble["hourly"].items():
        if key != "time":
            for i, t in enumerate(raw.ensemble["hourly"]["time"]):
                if int(t[11:13]) in (22, 23, 0, 1):
                    col[i] = None
    scored = [score_hour(spot, h) for h in extract_hours(raw)]
    assert any(s.hour.n_models == 0 for s in scored)
    payload = build_payload(spot, scored, fetched_at=raw.fetched_at, now=datetime.now(UTC))
    assert payload["days"] and all(d["models"] == 3 for d in payload["days"])
