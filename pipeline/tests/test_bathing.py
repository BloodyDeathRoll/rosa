"""bathing.py: source normalisation, the match radius, daily-beats-yearly."""

from types import SimpleNamespace

from rosa_pipeline import bathing


def test_eea_grades_map_best_to_worst():
    site = {"season": 2025, "quality": "1 - Excellent"}
    assert bathing.eea_entry(site)["grade"] == 4
    assert bathing.eea_entry({**site, "quality": "4 - Poor"})["grade"] == 1
    assert bathing.eea_entry({**site, "quality": "0 - Not classified"}) is None
    assert bathing.eea_entry(site)["cadence"] == "yearly"


def test_nsw_forecast_drives_alert_and_cadence():
    base = {
        "latestResultRating": 4,
        "pollutionForecast": "Unlikely",
        "pollutionForecastTimeStamp": "2026-09-26T03:30:00+00:00",
        "latestResultObservationDate": "2026-09-24T10:00:00+10:00",
    }
    e = bathing.nsw_entry(base)
    assert (e["grade"], e["alert"], e["cadence"], e["date"]) == (4, False, "daily", "2026-09-26")
    assert bathing.nsw_entry({**base, "pollutionForecast": "Likely"})["alert"] is True
    assert bathing.nsw_entry({**base, "pollutionForecast": "Possible"})["grade"] == 2
    off = bathing.nsw_entry({**base, "pollutionForecast": "Forecast not available"})
    assert (off["cadence"], off["date"]) == ("sample", "2026-09-24")


def test_match_takes_the_nearest_site_inside_the_radius():
    spots = {"a": SimpleNamespace(lat=38.680, lon=-9.330), "far": SimpleNamespace(lat=0, lon=0)}
    cands = [
        {"site_id": "near", "name": "N", "lat": 38.681, "lon": -9.330},
        {"site_id": "less", "name": "L", "lat": 38.690, "lon": -9.330},
    ]
    out = bathing.match(spots, cands, "nsw", radius_km=2.0)
    assert out["a"]["site_id"] == "near" and "far" not in out


def test_rematch_replaces_its_own_source_and_never_downgrades_daily():
    existing = {
        "x": {"src": "nsw", "site_id": "d"},
        "y": {"src": "eea", "site_id": "old"},
        "gone": {"src": "eea", "site_id": "g"},
    }
    new = {"x": {"src": "eea", "site_id": "e"}, "y": {"src": "eea", "site_id": "new"}}
    merged = bathing.merge_sites(existing, new, "eea")
    assert merged["x"]["src"] == "nsw"
    assert merged["y"]["site_id"] == "new"
    assert "gone" not in merged


def test_a_failed_nsw_request_costs_only_its_spots():
    sites = {
        "a": {"src": "nsw", "site_id": "1"},
        "b": {"src": "eea", "season": 2025, "quality": "1 - Excellent"},
    }

    def boom():
        raise RuntimeError("down")

    out = bathing.pollution_for(["a", "b", "c"], sites, boom)
    assert out["a"] is None and out["b"]["grade"] == 4 and out["c"] is None
