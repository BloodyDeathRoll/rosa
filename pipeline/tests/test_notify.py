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
