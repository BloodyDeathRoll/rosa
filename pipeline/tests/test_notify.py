"""Swell-alert planning: grouping (one swell = one push), favorites filter,
sent-state tolerance, payload loading. Pure functions — no network."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rosa_pipeline.notify import (
    SpotEvent,
    endpoint_hash,
    event_key,
    group_events,
    load_spot_events,
    load_state,
    mark_sent,
    plan_notifications,
    save_state,
    sent_for,
)

NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)


def ev(
    spot_id: str,
    *,
    region: str | None = "Israel",
    peak_off_h: float = 24.0,
    direction: float | None = 295.0,
    rating: int = 62,
    h_peak: float = 1.6,
    name: str | None = None,
) -> SpotEvent:
    peak = NOW + timedelta(hours=peak_off_h)
    return SpotEvent(
        spot_id=spot_id,
        spot_name=name or spot_id,
        region=region,
        start=peak - timedelta(hours=12),
        peak=peak,
        end=peak + timedelta(hours=14),
        h_peak=h_peak,
        direction_deg=direction,
        rating=rating,
        bucket="GOOD",
    )


class TestGrouping:
    def test_adjacent_spots_one_group(self):
        # the requirement: 20 spots on one coast, one swell -> ONE group
        events = [ev(f"spot-{i}", peak_off_h=24 + i * 0.2, direction=295 + i) for i in range(20)]
        assert len(group_events(events)) == 1

    def test_regions_split(self):
        groups = group_events([ev("a"), ev("b", region="Costa Rica")])
        assert len(groups) == 2

    def test_peaks_far_apart_split(self):
        groups = group_events([ev("a"), ev("b", peak_off_h=24 + 20)])
        assert len(groups) == 2

    def test_directions_far_apart_split(self):
        groups = group_events([ev("a", direction=290.0), ev("b", direction=120.0)])
        assert len(groups) == 2

    def test_direction_wraparound_groups(self):
        groups = group_events([ev("a", direction=350.0), ev("b", direction=15.0)])
        assert len(groups) == 1

    def test_none_direction_groups_by_time(self):
        groups = group_events([ev("a", direction=None), ev("b")])
        assert len(groups) == 1

    def test_chained_cluster_stays_single(self):
        # a->b close, b->c close, a->c further: still one physical swell
        events = [
            ev("a", peak_off_h=24, direction=280.0),
            ev("b", peak_off_h=32, direction=300.0),
            ev("c", peak_off_h=40, direction=320.0),
        ]
        assert len(group_events(events)) == 1


class TestPlanning:
    def test_one_push_per_group_named_for_best_favorite(self):
        events = [
            ev("beit-yanai", rating=68, name="Beit Yanai"),
            ev("sidna-ali", rating=55, name="Sidna Ali (Herzliya)"),
            ev("dromi", rating=61, name="Dromi (Herzliya)"),
        ]
        plans = plan_notifications(
            group_events(events), ["beit-yanai", "sidna-ali", "dromi"], set(), NOW
        )
        assert len(plans) == 1
        n = plans[0]
        assert n.title == "New swell — Israel"
        assert "Beit Yanai" in n.body
        assert "+2 more spots" in n.body
        assert n.url.endswith(f"#/spot/beit-yanai?ev={events[0].peak.date().isoformat()}")
        assert set(n.keys) == {event_key(e) for e in events}

    def test_non_favorited_group_skipped(self):
        plans = plan_notifications(group_events([ev("a")]), ["other-spot"], set(), NOW)
        assert plans == []

    def test_already_peaked_skipped(self):
        plans = plan_notifications(group_events([ev("a", peak_off_h=-2)]), ["a"], set(), NOW)
        assert plans == []

    def test_sent_key_skipped(self):
        e = ev("a")
        plans = plan_notifications(group_events([e]), ["a"], {event_key(e)}, NOW)
        assert plans == []

    def test_sent_tolerance_absorbs_peak_drift(self):
        # yesterday's send recorded peak date D; today the model drifted the peak to D+1
        e_sent = ev("a", peak_off_h=24)
        e_drifted = ev("a", peak_off_h=24 + 26)  # crosses midnight vs e_sent
        assert e_sent.peak.date() != e_drifted.peak.date()
        plans = plan_notifications(
            group_events([e_drifted]), ["a"], {event_key(e_sent)}, NOW
        )
        assert plans == []

    def test_group_sent_via_any_member_suppresses_all(self):
        # the swell was announced from spot a; spot b joining the group later
        # must not re-notify
        a, b = ev("a"), ev("b")
        plans = plan_notifications(group_events([a, b]), ["b"], {event_key(a)}, NOW)
        assert plans == []

    def test_singleton_body_has_no_more_suffix(self):
        plans = plan_notifications(group_events([ev("a")]), ["a"], set(), NOW)
        assert len(plans) == 1
        assert "more spot" not in plans[0].body
        assert "WNW" in plans[0].body
        assert "Good" in plans[0].body  # display word, not the raw bucket

    def test_no_region_falls_back_to_spot_name(self):
        plans = plan_notifications(
            group_events([ev("a", region=None, name="Lonely Reef")]), ["a"], set(), NOW
        )
        assert plans[0].title == "New swell — Lonely Reef"


class TestState:
    def test_roundtrip_and_prune(self, tmp_path: Path):
        path = tmp_path / "state.json"
        sent: dict[str, str] = {}
        mark_sent(sent, "abc", ("a:2026-07-24",), NOW)
        sent["abc|old:2026-01-01"] = (NOW - timedelta(days=60)).isoformat()
        save_state(path, sent, NOW)
        loaded = load_state(path)
        assert "abc|a:2026-07-24" in loaded
        assert "abc|old:2026-01-01" not in loaded  # pruned past the TTL
        assert sent_for(loaded, "abc") == {"a:2026-07-24"}
        assert sent_for(loaded, "zzz") == set()

    def test_load_state_missing_or_corrupt(self, tmp_path: Path):
        assert load_state(tmp_path / "nope.json") == {}
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        assert load_state(bad) == {}

    def test_endpoint_hash_stable(self):
        h = endpoint_hash("https://fcm.googleapis.com/fcm/send/xyz")
        assert h == endpoint_hash("https://fcm.googleapis.com/fcm/send/xyz")
        assert len(h) == 16


class TestLoad:
    def test_load_spot_events(self, tmp_path: Path):
        spots = tmp_path / "spots"
        spots.mkdir()
        payload = {
            "spot": {"id": "beit-yanai", "name": "Beit Yanai", "region": "Israel"},
            "events": [
                {
                    # already over -> dropped
                    "start": "2026-07-20T21:00+03:00",
                    "peak": "2026-07-21T11:00+03:00",
                    "end": "2026-07-22T08:00+03:00",
                    "h_peak": 1.1,
                    "dir": 300.0,
                    "rating": 55,
                    "bucket": "GOOD",
                },
                {
                    "start": "2026-07-24T21:00+03:00",
                    "peak": "2026-07-25T11:00+03:00",
                    "end": "2026-07-26T08:00+03:00",
                    "h_peak": 1.6,
                    "dir": 295.0,
                    "rating": 62,
                    "bucket": "GOOD",
                },
            ],
        }
        (spots / "beit-yanai.json").write_text(json.dumps(payload))
        (spots / "flat-spot.json").write_text(
            json.dumps({"spot": {"id": "flat-spot", "name": "Flat"}, "events": []})
        )
        events = load_spot_events(tmp_path, NOW)
        assert len(events) == 1
        e = events[0]
        assert e.spot_id == "beit-yanai"
        assert e.region == "Israel"
        assert e.h_peak == 1.6
        assert e.peak.isoformat() == "2026-07-25T11:00:00+03:00"


# ---------------------------------------------------------------- feedback


from zoneinfo import ZoneInfo  # noqa: E402

from rosa_pipeline.notify import (  # noqa: E402
    FeedbackCandidate,
    feedback_key,
    feedback_payload,
    load_feedback_candidates,
    plan_feedback_push,
)

IL = ZoneInfo("Asia/Jerusalem")
# 2026-07-23 19:00 Israel — inside the evening ask window
EVENING = datetime(2026, 7, 23, 16, 0, tzinfo=UTC)


def cand(spot_id: str, *, rating: int = 62, date: str = "2026-07-23") -> FeedbackCandidate:
    return FeedbackCandidate(
        spot_id=spot_id,
        spot_name=spot_id,
        date=date,
        rating=rating,
        bucket="GOOD",
        h=(0.6, 0.9),
        at=f"{date}T09:00+03:00",
        predicted={"rating": rating, "bucket": "GOOD", "h": [0.6, 0.9], "phrase": "waist-high"},
    )


def _payload_dir(tmp_path: Path, rating_max: int, date: str = "2026-07-23") -> Path:
    spots = tmp_path / "spots"
    spots.mkdir(exist_ok=True)
    payload = {
        "spot": {"id": "zvulun", "name": "Zvulun (Herzliya)", "timezone": "Asia/Jerusalem"},
        "days": [{"date": date, "rating_max": rating_max, "bucket": "GOOD", "h_max": [0.6, 0.9]}],
        "hours": [
            {"t": f"{date}T09:00+03:00", "rating": rating_max, "bucket": "GOOD",
             "h": [0.6, 0.9], "phrase": "waist-high"},
            {"t": f"{date}T15:00+03:00", "rating": 40, "bucket": "FAIR",
             "h": [0.4, 0.6], "phrase": "knee-high"},
        ],
    }
    (spots / "zvulun.json").write_text(json.dumps(payload))
    return tmp_path


class TestFeedbackCandidates:
    def test_good_day_in_evening_window(self, tmp_path: Path):
        cands = load_feedback_candidates(_payload_dir(tmp_path, 62), EVENING)
        assert len(cands) == 1
        c = cands[0]
        assert c.spot_id == "zvulun"
        assert c.date == "2026-07-23"
        assert c.at == "2026-07-23T09:00+03:00"  # the best-rated hour = the session graded
        assert c.predicted["bucket"] == "GOOD"

    def test_below_good_day_skipped(self, tmp_path: Path):
        assert load_feedback_candidates(_payload_dir(tmp_path, 45), EVENING) == []

    def test_outside_evening_window_skipped(self, tmp_path: Path):
        noon = datetime(2026, 7, 23, 9, 0, tzinfo=UTC)  # 12:00 Israel
        assert load_feedback_candidates(_payload_dir(tmp_path, 62), noon) == []


class TestFeedbackPlanning:
    def test_one_ask_best_favorite(self):
        got = plan_feedback_push([cand("a", rating=55), cand("b", rating=70)], ["a", "b"], set())
        assert got is not None
        n, c = got
        assert c.spot_id == "b"
        assert n.title == "How was b today?"
        assert n.keys == (feedback_key("b", "2026-07-23"),)

    def test_non_favorite_skipped(self):
        assert plan_feedback_push([cand("a")], ["other"], set()) is None

    def test_one_per_day_even_across_spots(self):
        # yesterday's cycle asked about spot a; a later cycle the same evening
        # must not ask about spot b
        sent = {feedback_key("a", "2026-07-23")}
        assert plan_feedback_push([cand("a"), cand("b")], ["a", "b"], sent) is None

    def test_payload_carries_actions_and_row(self):
        n, c = plan_feedback_push([cand("a")], ["a"], set())
        p = feedback_payload(n, c)
        assert [a["action"] for a in p["actions"]] == ["up", "down"]
        assert p["feedback"]["spot"] == "a"
        assert p["feedback"]["source"] == "push"
        assert p["feedback"]["predicted"]["bucket"] == "GOOD"


class TestFeedbackPull:
    def test_merge_dedupes_by_id(self, tmp_path: Path, monkeypatch):
        from rosa_pipeline import notify as mod
        from rosa_pipeline.archive import FileArchiveStore

        store = FileArchiveStore(tmp_path)
        store.append(
            "feedback", [{"id": "feedback/x.json", "spot": "a", "at": "t", "verdict": "up"}]
        )

        class FakeResp:
            def raise_for_status(self):
                pass

            def json(self):
                return [
                    {"id": "feedback/x.json", "spot": "a", "at": "t", "verdict": "up"},
                    {"id": "feedback/y.json", "spot": "b", "at": "t", "verdict": "down"},
                ]

        deleted = {}

        class FakeHttpx:
            @staticmethod
            def get(url, headers=None, timeout=None):
                return FakeResp()

            @staticmethod
            def request(method, url, headers=None, json=None, timeout=None):
                deleted.update(json or {})
                return FakeResp()

        monkeypatch.setitem(__import__("sys").modules, "httpx", FakeHttpx)
        fresh = mod.pull_feedback("https://x/api/feedback", "s", tmp_path)
        assert fresh == 1  # only y was new
        rows = store.read("feedback")
        assert [r["id"] for r in rows] == ["feedback/x.json", "feedback/y.json"]
        assert set(deleted["ids"]) == {"feedback/x.json", "feedback/y.json"}  # both pruned
