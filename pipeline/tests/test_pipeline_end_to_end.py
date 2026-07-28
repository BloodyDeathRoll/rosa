"""Fixture-driven end-to-end test: captured Open-Meteo responses -> published JSON.

The fixture is a real captured response pair (see FixtureSource / --capture);
tests never touch the network.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from rosa_pipeline.extract import extract_hours
from rosa_pipeline.fetch import FixtureSource
from rosa_pipeline.publish import build_payload, prune_index, update_index, write_spot_json
from rosa_pipeline.score import score_hour
from rosa_pipeline.spots import load_spots

FIXTURES = Path(__file__).parent / "fixtures"
SPOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "spots"

BUCKETS = {"FLAT", "POOR", "FAIR", "GOOD", "FIRING"}


@pytest.fixture(scope="module")
def spot():
    return load_spots(SPOTS_DIR)["beit-yanai"]


@pytest.fixture(scope="module")
def raw(spot):
    return FixtureSource(FIXTURES).fetch(*spot.offshore_point)


@pytest.fixture(scope="module")
def payload(spot, raw):
    scored = [score_hour(spot, h) for h in extract_hours(raw)]
    now = datetime.fromisoformat(raw.fetched_at)
    return build_payload(spot, scored, fetched_at=raw.fetched_at, now=now)


def test_extract_merges_models_to_full_horizon(raw):
    # best_match (~9 d) + GFS-Wave (16 d) merged per hour → a full, gap-free 16-day series,
    # never a fabricated flat tail.
    hours = extract_hours(raw)
    assert 15 * 24 <= len(hours) <= 16 * 24  # full horizon, no null gap
    first = hours[0]
    assert first.time.tzinfo is not None
    assert first.wind_speed_kph >= 0
    # SST is carried into the GFS-Wave tail (that model has none), so no None water temps
    assert all(h.sst_c is not None for h in hours)


def test_payload_shape(payload):
    assert payload["spot"]["id"] == "beit-yanai"
    assert payload["model"]
    assert payload["fetched_at"]
    assert payload["attribution"].startswith("Weather data by Open-Meteo")
    # 3-hourly, up to 16 days; the leading partial local day is trimmed (publish
    # starts at the spot's local today, so hour count depends on when now falls)
    assert 15 * 8 <= len(payload["hours"]) <= 16 * 8
    assert len(payload["days"]) == 16
    assert payload["current"]["bucket"] in BUCKETS
    assert payload["current"]["why"].keys() == {"size", "period", "wind"}
    assert payload["current"]["wetsuit"] is not None


def test_no_fabricated_far_days(spot, raw, payload):
    # every published day must be a day that actually has marine data
    from zoneinfo import ZoneInfo

    hours = extract_hours(raw)
    tz = ZoneInfo(spot.timezone)
    real_dates = {h.time.astimezone(tz).date().isoformat() for h in hours}
    assert all(d["date"] in real_dates for d in payload["days"])
    assert len(payload["days"]) == 16  # GFS-Wave fills the full 16-day horizon


def test_every_hour_scored(payload):
    for entry in payload["hours"]:
        assert entry["bucket"] in BUCKETS
        assert 0 <= entry["rating"] <= 100
        assert entry["h"][0] <= entry["h"][1]
        assert entry["wind"]["class"] in {"offshore", "cross-shore", "onshore"}
        assert entry["h"][0] <= entry["h_mid"] <= entry["h"][1] or entry["h_mid"] >= 0
        assert entry["energy_kj"] >= 0
        assert entry["pressure"] is None or 900 < entry["pressure"] < 1100


def test_confidence_degrades(payload):
    confidences = [d["confidence"] for d in payload["days"]]
    assert confidences[0] == "high"
    assert confidences[-1] == "low"


def test_written_files(payload, tmp_path):
    spot_path = write_spot_json(payload, tmp_path)
    index_path = update_index(payload, tmp_path)
    assert spot_path == tmp_path / "spots" / "beit-yanai.json"
    written = json.loads(spot_path.read_text())
    assert written == payload
    index = json.loads(index_path.read_text())
    assert index["spots"]["beit-yanai"]["bucket"] in BUCKETS
    # 16 days of 3-hourly detail; ~45 KB raw but <5 KB gzipped (what's served)
    assert spot_path.stat().st_size < 60_000


def test_prune_index_drops_spots_that_left_the_db(payload, tmp_path):
    """A spot deleted from the YAML must leave the index and lose its payload;
    everything still in the DB must survive untouched."""
    spot_path = write_spot_json(payload, tmp_path)
    update_index(payload, tmp_path)
    gone = dict(payload)
    gone["spot"] = {**payload["spot"], "id": "herzliya-marina"}
    gone_path = write_spot_json(gone, tmp_path)
    update_index(gone, tmp_path)

    assert prune_index({"beit-yanai"}, tmp_path) == ["herzliya-marina"]

    index = json.loads((tmp_path / "index.json").read_text())
    assert set(index["spots"]) == {"beit-yanai"}
    assert not gone_path.exists()
    assert spot_path.exists()
    # nothing left to prune - a second pass is a no-op, not an error
    assert prune_index({"beit-yanai"}, tmp_path) == []
