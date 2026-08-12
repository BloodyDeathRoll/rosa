"""NDBC + CMEMS observation parsing and fixture replay."""

from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import pairwise
from pathlib import Path

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
