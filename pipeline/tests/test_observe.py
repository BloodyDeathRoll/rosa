"""NDBC observation parsing + fixture replay."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rosa_pipeline.buoys import Buoy
from rosa_pipeline.observe import NDBCFixtureSource, parse_ndbc_txt

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
