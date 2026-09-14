"""NDBC + CMEMS observation parsing, the coastal wind-station adapters, and fixture replay."""

from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path

import pytest

from rosa_pipeline.buoys import Buoy
from rosa_pipeline.observe import (
    CMEMSFixtureSource,
    NDBCFixtureSource,
    parse_cmems_nc,
    parse_ndbc_txt,
)

FIX = Path(__file__).resolve().parent / "fixtures" / "verify"

# trailing DEWP/VIS/PTDY/TIDE columns dropped - the parser reads through WTMP (index 14)
SAMPLE = """#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP
#yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC
2026 07 21 07 40 320  5.0  6.0    MM    MM    MM  MM 1012.7  14.2  15.5
2026 07 21 07 20 330  5.0  6.0   1.3    14   7.5 244 1013.0  14.3  15.5
"""


def test_parse_handles_missing_and_values() -> None:
    obs = parse_ndbc_txt(SAMPLE, "46042")
    assert [o.time for o in obs] == [
        datetime(2026, 7, 21, 7, 20, tzinfo=UTC),  # returned oldest-first
        datetime(2026, 7, 21, 7, 40, tzinfo=UTC),
    ]
    wave, met_only = obs
    assert wave.hs_m == 1.3 and wave.dpd_s == 14.0 and wave.apd_s == 7.5 and wave.mwd_deg == 244.0
    assert wave.wtmp_c == 15.5
    # the 07:40 row has no wave data - all wave fields None, met still parsed
    assert met_only.hs_m is None and met_only.apd_s is None and met_only.mwd_deg is None
    assert met_only.wtmp_c == 15.5


def test_parses_the_co_located_wind() -> None:
    """The wind columns share the line with the wave columns and were parsed past until
    2026-08-03. They are the only wind+wave ground truth Rosa has - see open item 4."""
    wave, met_only = parse_ndbc_txt(SAMPLE, "46042")
    assert wave.wdir_deg == 330.0 and wave.wspd_ms == 5.0
    # a row with no waves still carries wind - that is the point of keeping met-only rows
    assert met_only.wdir_deg == 320.0 and met_only.wspd_ms == 5.0


def test_times_are_utc_aware() -> None:
    obs = parse_ndbc_txt(SAMPLE, "x")
    assert all(o.time.tzinfo is UTC for o in obs)


def test_fixture_source_reads_real_capture() -> None:
    buoy = Buoy(id="46042", name="Monterey", lat=36.785, lon=-122.408, source="ndbc")
    obs = NDBCFixtureSource(FIX).fetch(buoy)
    assert len(obs) > 100  # ~2 days of 10-min rows
    assert any(o.hs_m is not None for o in obs)
    assert obs == sorted(obs, key=lambda o: o.time)  # oldest-first


# --- CMEMS in-situ (Copernicus) ------------------------------------------------------
# Portugal's only ground truth. The fixture is one real daily file from the Sines buoy,
# captured 2026-08-03 from the public S3 path (no credentials - see observe.CMEMSSource).

FIX_ROOT = Path(__file__).resolve().parent / "fixtures"
SINES = Buoy(id="Sines-coast-buoy", name="Sines", lat=37.9211, lon=-8.9289, source="cmems")


def test_cmems_fixture_parses_a_real_file() -> None:
    obs = CMEMSFixtureSource(FIX_ROOT).fetch(SINES)
    assert len(obs) == 48  # 30-minute sampling over one day
    assert obs == sorted(obs, key=lambda o: o.time)  # oldest-first, like every source
    assert all(o.station == "Sines-coast-buoy" for o in obs)


def test_cmems_times_decode_from_the_1950_epoch() -> None:
    """TIME is 'days since 1950-01-01'; a wrong epoch silently shifts every pairing by
    decades. Sample times are NOT on the half hour (this buoy reports at :26:44/:56:44),
    so the day and the 30-min spacing are the invariants, not tidy clock times."""
    obs = CMEMSFixtureSource(FIX_ROOT).fetch(SINES)
    assert all(o.time.date() == date(2026, 8, 3) for o in obs)
    assert all(o.time.tzinfo is UTC for o in obs)
    # +-1 s of jitter: TIME is a float64 count of DAYS, so a 30-min step is not exact.
    gaps = [(b.time - a.time).total_seconds() for a, b in pairwise(obs)]
    assert all(abs(g - 1800.0) <= 2.0 for g in gaps)


def test_cmems_maps_periods_like_for_like_with_ndbc() -> None:
    """VTM02 is Tm02 (= NDBC APD) and VTPK is the peak (= NDBC DPD). Swapping them would
    put a ~+2 s offset into the scorecard and read as a model bias."""
    obs = [o for o in CMEMSFixtureSource(FIX_ROOT).fetch(SINES) if o.apd_s and o.dpd_s]
    assert obs, "fixture should carry both periods"
    # Peak >= mean in the overwhelming majority, but NOT always: a near-flat spectrum can
    # invert it (1 row of 48 here, 5.0 s vs 5.3 s). Asserting "always" fails on real data;
    # asserting the bulk still catches the two periods being swapped, which would invert
    # the relationship wholesale and inject a ~+2 s offset that reads as a model bias.
    inverted = [o for o in obs if o.dpd_s < o.apd_s]
    assert len(inverted) / len(obs) < 0.1
    median_peak = sorted(o.dpd_s for o in obs)[len(obs) // 2]
    median_mean = sorted(o.apd_s for o in obs)[len(obs) // 2]
    assert median_peak > median_mean + 1.0
    assert all(0.0 < o.hs_m < 20.0 for o in obs if o.hs_m is not None)


def test_cmems_publishes_no_wind() -> None:
    """These platforms are wave-only; wind must stay None rather than default to 0."""
    obs = CMEMSFixtureSource(FIX_ROOT).fetch(SINES)
    assert all(o.wdir_deg is None and o.wspd_ms is None for o in obs)


def test_cmems_drops_qc_rejected_values() -> None:
    """Only OceanSITES flags 1/2 are usable. Flip every VHM0 flag to 4 (bad) and the
    heights must vanish while the timestamps stay."""
    import io

    import h5py

    raw = (FIX_ROOT / "cmems_IR_TS_MO_Sines-coast-buoy_20260803.nc").read_bytes()
    buf = io.BytesIO(raw)
    with h5py.File(buf, "r+") as f:
        f["VHM0_QC"][:] = 4
    obs = parse_cmems_nc(buf.getvalue(), "Sines-coast-buoy")
    assert len(obs) == 48
    assert all(o.hs_m is None for o in obs)
    assert any(o.apd_s is not None for o in obs)  # other variables untouched


# --- coastal wind stations (2026-08-29) -------------------------------------------------


def test_metar_fixture_parses_the_real_capture() -> None:
    """metar_LLBG.json is a live aviationweather.gov capture (2026-08-29, 24 h). Speeds
    arrive in knots and are stored as m/s; the rows come newest-first and leave oldest-first."""
    from rosa_pipeline.observe import KT_TO_MS, MetarFixtureSource
    from rosa_pipeline.stations import Station

    obs = MetarFixtureSource(FIX).fetch(Station("LLBG", "Ben Gurion", 32.011, 34.887, "metar"))
    assert len(obs) == 48
    assert all(a.time < b.time for a, b in pairwise(obs))
    assert obs[-1].time == datetime(2026, 8, 29, 19, 0, tzinfo=UTC)
    assert obs[-1].wspd_ms == pytest.approx(12 * KT_TO_MS)
    assert obs[-1].wdir_deg == 260.0
    assert obs[-1].hs_m is None and obs[-1].gust_ms is None


def test_metar_variable_wind_keeps_speed_drops_direction() -> None:
    from rosa_pipeline.observe import KT_TO_MS, parse_metar_json

    rows = [
        {"reportTime": "2026-08-29T10:00:00.000Z", "wdir": "VRB", "wspd": 3, "wgst": None},
        {"reportTime": "2026-08-29T09:00:00.000Z", "wdir": 250, "wspd": 8, "wgst": 15},
        {"reportTime": "2026-08-29T08:00:00.000Z", "wdir": None, "wspd": None},  # no wind group
    ]
    obs = parse_metar_json(rows, "X")
    assert [o.time.hour for o in obs] == [9, 10]
    assert obs[1].wdir_deg is None and obs[1].wspd_ms == pytest.approx(3 * KT_TO_MS)
    assert obs[0].gust_ms == pytest.approx(15 * KT_TO_MS)


def test_ims_parse_applies_the_winter_time_rule() -> None:
    """Shape per IMS's API_Explanation_en.pdf (data[].datetime + channels[]{name,value,
    valid,status}); NOT a live capture - the API needs a token. The doc's own rule: the
    stamp is always UTC+2 whatever suffix it carries, so 10:00+03:00 is 08:00Z, not 07:00Z."""
    from rosa_pipeline.observe import parse_ims_json

    body = {
        "stationId": 178,
        "data": [
            {
                "datetime": "2026-08-29T10:00:00+03:00",
                "channels": [
                    {"id": 1, "name": "WS", "value": 5.2, "valid": True, "status": 1},
                    {"id": 2, "name": "WD", "value": 289, "valid": True, "status": 1},
                    {"id": 3, "name": "WSmax", "value": 8.1, "valid": True, "status": 1},
                ],
            },
            {
                "datetime": "2026-08-29T09:50:00+03:00",
                "channels": [
                    {"id": 1, "name": "WS", "value": 99.0, "valid": False, "status": 1},
                    {"id": 2, "name": "WD", "value": 300, "valid": True, "status": 2},
                    {"id": 4, "name": "TD", "value": 30.1, "valid": True, "status": 1},
                ],
            },
        ],
    }
    obs = parse_ims_json(body, "178")
    assert len(obs) == 1  # the second row has no valid wind channel at all
    assert obs[0].time == datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
    assert obs[0].wspd_ms == 5.2 and obs[0].wdir_deg == 289.0 and obs[0].gust_ms == 8.1


def test_ims_source_refuses_without_a_token(monkeypatch) -> None:
    from rosa_pipeline.observe import IMS_TOKEN_ENV, IMSSource
    from rosa_pipeline.stations import Station

    monkeypatch.delenv(IMS_TOKEN_ENV, raising=False)
    with pytest.raises(RuntimeError, match=IMS_TOKEN_ENV):
        IMSSource().fetch(Station("178", "Tel Aviv Coast", 32.06, 34.76, "ims"))


def test_ims_source_asks_past_today_because_to_is_exclusive(monkeypatch) -> None:
    """Measured live 2026-09-14: from=to=today is an empty 204 and to=tomorrow returns
    today's rows, so the request must end the day AFTER today - on IMS's UTC+2 calendar,
    which at 23:00Z is already the next UTC day."""
    import httpx

    from rosa_pipeline import observe
    from rosa_pipeline.stations import Station

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 14, 23, 0, tzinfo=UTC)

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    real_client = httpx.Client
    monkeypatch.setattr(observe, "datetime", Frozen)
    monkeypatch.setattr(
        observe.httpx,
        "Client",
        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
    )
    observe.IMSSource(token="t", days=8).fetch(Station("178", "TA", 32.06, 34.76, "ims"))
    assert seen[0].url.params["from"] == "2026/09/07"
    assert seen[0].url.params["to"] == "2026/09/16"
    assert seen[0].headers["Authorization"] == "ApiToken t"


def test_ims_source_reads_a_204_as_no_readings(monkeypatch) -> None:
    """A station with nothing in the range answers 204 and an empty body (live,
    2026-09-14) - that is zero readings, not a JSON error."""
    import httpx

    from rosa_pipeline import observe
    from rosa_pipeline.stations import Station

    real_client = httpx.Client
    monkeypatch.setattr(
        observe.httpx,
        "Client",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(204)), **kw
        ),
    )
    assert observe.IMSSource(token="t").fetch(Station("45", "Z", 32.57, 34.95, "ims")) == []
