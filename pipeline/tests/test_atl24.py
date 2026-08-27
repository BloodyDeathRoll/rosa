"""ICESat-2 ATL24 validation harness. Offline: the SlideRule wire format is built in-test."""

import math
import struct

import pytest

from rosa_pipeline import atl24
from rosa_pipeline.atl24 import Photon, pair, profile_points, score
from rosa_pipeline.bathymetry import DepthProfile, DepthSample


def _record(name: str, payload: bytes) -> bytes:
    raw = name.encode() + b"\0"
    return struct.pack(">HHI", 2, len(raw), len(payload)) + raw + payload


def _except(msg: str) -> bytes:
    return _record("exceptrec", b"\0" * 8 + msg.encode() + b"\0")


def test_split_records_walks_the_stream_exactly():
    blob = _except("hello") + _record("arrowrec.data", b"PAR1body PAR1")
    got = atl24._split_records(blob)
    assert [n for n, _ in got] == ["exceptrec", "arrowrec.data"]
    assert got[1][1] == b"PAR1body PAR1"


def test_split_records_rejects_an_unknown_framing_version():
    """Fail loudly rather than walk off into garbage: a version bump would otherwise be
    read as a nonsense length and produce silent nonsense photons."""
    with pytest.raises(ValueError, match="version"):
        atl24._split_records(struct.pack(">HHI", 9, 1, 0) + b"\0")


def test_messages_surface_sliderules_own_explanation():
    """When a box comes back empty the server says why ('resources exceeded maximum
    allowed: 341 > 300'). Losing that line turns a documented limit into a mystery."""
    blob = _except("query response truncated: ATL24 resources exceeded maximum allowed: 341 > 300")
    assert "341 > 300" in atl24._messages(blob)[0]


def _data(chunk: bytes) -> bytes:
    """An arrowrec.data record: 128-byte preamble, then this slice of the Parquet file."""
    return _record("arrowrec.data", b"\x00" * atl24._ARROW_PREAMBLE + chunk)


def test_one_parquet_file_is_reassembled_from_many_records():
    """SlideRule caps a payload at 32 MiB and splits ONE Parquet file across records - the
    Maldivian north took four, 129 MB. Reading each record as a complete file (the obvious
    first guess) fails on exactly the boxes worth measuring: the middle records carry no
    PAR1 at all, so they look empty, and the first looks corrupt."""
    blob = _except("progress") + _data(b"PAR1head") + _data(b"middle") + _data(b"tailPAR1")
    assert atl24._parquet_blob(blob) == b"PAR1headmiddletailPAR1"


def test_a_single_record_answer_still_works():
    assert atl24._parquet_blob(_data(b"PAR1body PAR1")) == b"PAR1body PAR1"


def test_no_data_records_means_no_photons_not_an_error():
    assert atl24._parquet_blob(_except("nothing here")) is None


def test_a_tile_with_no_photons_is_empty_not_broken():
    """Most tiles of a country-sized box have no lidar at all - ICESat-2 flies fixed repeat
    tracks - and they come back as preamble only. Raising would abort the sweep on the
    normal case."""
    assert atl24._parquet_blob(_data(b"")) is None


def test_a_half_written_parquet_still_raises():
    """Empty is fine; corrupt is not. Silently dropping bytes that are not a Parquet file
    would lose real photons and read as 'no coverage here'."""
    with pytest.raises(ValueError, match="corrupt, not empty"):
        atl24._parquet_blob(_data(b"PAR1rows-but-no-footer"))


def test_wkb_point_decodes_lon_then_lat():
    """SlideRule ships coordinates as WKB, and WKB is (x, y) = (lon, lat). Swapping them
    puts every Maldivian photon in Somalia."""
    blob = b"\x01" + struct.pack("<I", 1) + struct.pack("<dd", 73.5567, 4.3966)
    lon, lat = atl24._wkb_point(blob)
    assert (round(lon, 4), round(lat, 4)) == (73.5567, 4.3966)


def test_wkb_point_rejects_a_non_point_geometry():
    with pytest.raises(ValueError, match="WKB point"):
        atl24._wkb_point(b"\x01" + struct.pack("<I", 3) + struct.pack("<dd", 0.0, 0.0))


def _profile(depths):
    return DepthProfile(
        spot_id="reef",
        bearing_seaward_deg=90.0,
        samples=tuple(
            DepthSample(dist_km=0.25 * (i + 1), lat=4.0 + i / 10000, lon=73.0, depth_m=z)
            for i, z in enumerate(depths)
        ),
        origin_lat=4.0,
        origin_lon=73.0,
    )


def test_profile_points_keeps_the_deep_samples():
    """The whole finding is that GEBCO reads 280 m where the lidar sees 5 m. Filtering the
    source's deep readings before pairing would hide exactly that and flatter GEBCO."""
    pts = profile_points(_profile([280.0, 5.0, float("nan")]))
    assert [p[2] for p in pts] == [280.0, 5.0]  # NaN dropped, 280 kept


def test_pair_uses_the_median_photon_not_the_nearest():
    """One ICESat-2 photon carries real per-photon noise; a source is graded on the seabed."""
    pts = [(4.0, 73.0, 10.0)]
    photons = [Photon(4.0, 73.0, 99.0), Photon(4.00001, 73.0, 5.0), Photon(4.00002, 73.0, 5.5)]
    assert pair(pts, photons, radius_m=150.0) == [(10.0, 5.5)]


def test_pair_drops_points_with_no_photon_in_range():
    """ICESat-2 flies fixed repeat tracks, so most ray points have no lidar. That is the
    normal case, not an error."""
    assert pair([(4.0, 73.0, 10.0)], [Photon(4.5, 73.0, 5.0)], radius_m=150.0) == []


def test_score_bias_is_signed():
    """CALIBRATION.md's first method rule: a metric that cannot show sign cannot show a
    bias. Positive means the source reads DEEPER than the lidar."""
    deep = score("deep", [(12.0, 5.0), (10.0, 5.0)])
    shallow = score("shallow", [(2.0, 5.0), (0.0, 5.0)])
    assert deep.bias_m > 0 and shallow.bias_m < 0


def test_score_maths():
    s = score("x", [(6.0, 5.0), (2.0, 5.0)])  # errors +1, -3
    assert s.n == 2
    assert s.bias_m == pytest.approx(-1.0)
    assert s.mae_m == pytest.approx(2.0)
    assert s.rmse_m == pytest.approx(math.sqrt(5.0))
    assert s.worse_than_5m == 0


def test_score_counts_the_gross_misses():
    assert score("x", [(280.0, 5.0), (6.0, 5.0)]).worse_than_5m == 1


def test_score_of_nothing_is_empty_not_a_crash():
    """A box with no lidar coverage must report n=0, not divide by zero - the harness is
    run over regions that may have none."""
    s = score("x", [])
    assert s.n == 0 and math.isnan(s.rmse_m)
    assert "n=     0" in s.as_row()


def test_truncated_stream_is_its_own_error():
    """A 20 MB ATL24 answer does get cut short mid-body. Keeping the short payload would
    hand pyarrow a headless Parquet file and blame the schema for a network problem, so
    the overrun is detected and typed - fetch_photons retries on it."""
    blob = struct.pack(">HHI", 2, 5, 999) + b"data\0" + b"only-a-few"
    with pytest.raises(atl24.TruncatedStream, match="declares 999 bytes"):
        atl24._split_records(blob)
