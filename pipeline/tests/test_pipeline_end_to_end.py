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
from rosa_pipeline.publish import build_payload, update_index, write_spot_json
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


def test_extract_full_horizon(raw):
    hours = extract_hours(raw)
    assert len(hours) == 16 * 24
    first = hours[0]
    assert first.time.tzinfo is not None
    assert first.wind_speed_kph >= 0


def test_payload_shape(payload):
    assert payload["spot"]["id"] == "beit-yanai"
    assert payload["model"]
    assert payload["fetched_at"]
    assert payload["attribution"].startswith("Weather data by Open-Meteo")
    assert len(payload["hours"]) == 7 * 8  # 7 days, 3-hourly
    assert len(payload["days"]) == 16
    assert payload["current"]["bucket"] in BUCKETS
    assert payload["current"]["why"].keys() == {"size", "period", "wind"}
    assert payload["current"]["wetsuit"] is not None


def test_every_hour_scored(payload):
    for entry in payload["hours"]:
        assert entry["bucket"] in BUCKETS
        assert 0 <= entry["rating"] <= 100
        assert entry["h"][0] <= entry["h"][1]
        assert entry["wind"]["class"] in {"offshore", "cross-shore", "onshore"}


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
    # size sanity: keep the payload lean (spec target ~5 KB; hard cap here)
    assert spot_path.stat().st_size < 40_000
