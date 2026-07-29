"""SwellMap basin layer - offline against the captured Med GRIB fixture."""

from datetime import UTC, datetime
from pathlib import Path

from rosa_pipeline.swellmap import (
    BASINS,
    MISSING,
    WORLD_PLANES,
    WORLD_SUBSAMPLE,
    BasinBox,
    _quantize,
    _quantize_plane,
    basin_boxes,
    build_basin_payload,
    build_world_frames,
    parse_grib_field,
    parse_grib_planes,
    png_gray,
)

FIXTURES = Path(__file__).parent / "fixtures"
SPOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "spots"
GRIB = (FIXTURES / "gfswave" / "med_f000.grib2").read_bytes()


def test_quantize_round_trip_and_missing():
    assert _quantize(None, 0.1) == MISSING
    assert _quantize(0.82, 0.1) == 8  # 0.8 m back - error below display snapping
    assert _quantize(301.0, 2.0) == 150  # 300 deg back
    assert _quantize(1e9, 0.1) == 254  # capped below the missing sentinel


def test_every_spot_region_has_a_basin():
    """A new region file must be claimed by a basin or its users get no map layer."""
    import glob

    import yaml

    covered = {r for regions in BASINS.values() for r in regions}
    for f in glob.glob(str(SPOTS_DIR / "*.yaml")):
        region = yaml.safe_load(Path(f).read_text(encoding="utf-8")).get("region")
        name = region or Path(f).stem.replace("-", " ").title()
        assert name in covered, f"{f}: region {name!r} not in any basin"


def test_basin_boxes_pad_the_spot_extent():
    boxes = {b.name: b for b in basin_boxes(SPOTS_DIR)}
    il = boxes["israel"]
    assert il.lat0 < 31.6 < 33.1 < il.lat1
    assert il.lon0 < 34.5 < 35.1 < il.lon1


def test_parse_grib_field_extracts_wet_and_dry_cells():
    field = parse_grib_field(GRIB)
    assert field is not None
    assert field["nx"] * field["ny"] == len(field["hs"])
    wet = [v for v in field["hs"] if v is not None]
    assert wet, "no wet cells in the Med fixture"
    # wind rides in the same GRIB - the Wind chart costs zero extra requests
    winds = [v for v in field["wind"] if v is not None]
    assert winds and all(0 <= v < 60 for v in winds)
    assert any(v is None for v in field["hs"]), "land must be masked, not zero"
    assert all(0 < v < 20 for v in wet)


def test_build_basin_payload_shape():
    basin = BasinBox("israel", ("Israel",), 28.6, 36.1, 31.5, 38.1)
    cycle = datetime(2026, 7, 23, 6, tzinfo=UTC)
    # two good steps and one outage - the payload must carry on
    payload = build_basin_payload(
        basin, cycle, lambda step: GRIB if step in (0, 3) else None, (0, 3, 6)
    )
    assert payload is not None
    assert [f["t"] for f in payload["frames"]] == ["2026-07-23T06:00Z", "2026-07-23T09:00Z"]
    n = payload["nx"] * payload["ny"]
    for f in payload["frames"]:
        assert len(f["hs"]) == len(f["per"]) == len(f["dir"]) == n
        assert len(f["wind"]) == len(f["wdir"]) == n
        assert all(0 <= v <= 255 for v in f["hs"])
    assert payload["scales"]["hs_m"] == 0.1
    assert payload["scales"]["wind_ms"] == 0.25
    assert "NOAA" in payload["attribution"]


def test_build_basin_payload_total_outage_is_none():
    basin = BasinBox("israel", ("Israel",), 28.6, 36.1, 31.5, 38.1)
    cycle = datetime(2026, 7, 23, 6, tzinfo=UTC)
    assert build_basin_payload(basin, cycle, lambda step: None, (0, 3)) is None


def _decode_png_gray(png: bytes):
    """Reference decoder for the world frames: parse chunks, inflate, undo the
    Up filter. Independent of the encoder so a bug can't cancel itself out."""
    import struct
    import zlib

    import numpy as np

    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    idat = b""
    w = h = None
    while pos < len(png):
        (length,) = struct.unpack(">I", png[pos : pos + 4])
        tag = png[pos + 4 : pos + 8]
        payload = png[pos + 8 : pos + 8 + length]
        if tag == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", payload[:10])
            assert depth == 8 and ctype == 0, "must be 8-bit grayscale"
        elif tag == b"IDAT":
            idat += payload
        pos += 12 + length
    raw = zlib.decompress(idat)
    rows = np.frombuffer(raw, np.uint8).reshape(h, w + 1)
    assert (rows[:, 0] == 2).all(), "every scanline uses the Up filter"
    return w, h, np.add.accumulate(rows[:, 1:], axis=0, dtype=np.uint8)


def test_png_gray_roundtrip():
    import numpy as np

    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, size=(19, 31), dtype=np.uint8)
    w, h, back = _decode_png_gray(png_gray(31, 19, img.tobytes()))
    assert (w, h) == (31, 19)
    assert (back == img).all()


def test_build_world_frames_from_fixture(tmp_path):
    from datetime import UTC, datetime

    import numpy as np

    cycle = datetime(2026, 7, 23, 6, tzinfo=UTC)
    parsed = parse_grib_planes(GRIB)
    assert parsed is not None
    # two good steps and one outage - the run must carry on
    meta = build_world_frames(
        cycle, lambda step: parsed if step in (0, 3) else None, (0, 3, 6), tmp_path
    )
    assert meta is not None
    assert [f["t"] for f in meta["frames"]] == ["2026-07-23T06:00Z", "2026-07-23T09:00Z"]
    assert meta["grid_deg"] == 0.25 * WORLD_SUBSAMPLE
    assert meta["planes"] == list(WORLD_PLANES)
    assert meta["max"]["hs"] > 0 and meta["max"]["energy"] > 0

    # decode a frame and check the hs plane round-trips the quantized subsample
    png = (tmp_path / meta["frames"][0]["png"]).read_bytes()
    w, h, img = _decode_png_gray(png)
    assert (w, h) == (meta["nx"], meta["ny"] * len(WORLD_PLANES))
    _geom, planes = parsed
    want = _quantize_plane(np.asarray(planes["hs"])[::WORLD_SUBSAMPLE, ::WORLD_SUBSAMPLE], 0.1)
    assert (img[: meta["ny"]] == want).all()
    assert (img == MISSING).any(), "land must be encoded as the missing sentinel"


def test_build_world_frames_total_outage_is_none(tmp_path):
    from datetime import UTC, datetime

    cycle = datetime(2026, 7, 23, 6, tzinfo=UTC)
    assert build_world_frames(cycle, lambda step: None, (0, 3), tmp_path) is None


def test_payload_longitudes_are_wrapped_to_signed():
    """Western-hemisphere basins (Portugal, Central America) come back from the
    0-360 grib-filter as e.g. 347.5E; the payload must carry -12.5 or the web
    projects the field a world-copy off-screen (the 2026-07-26 render bug)."""
    basin = BasinBox("israel", ("Israel",), 28.6, 36.1, 31.5, 38.1)
    cycle = datetime(2026, 7, 23, 6, tzinfo=UTC)
    payload = build_basin_payload(basin, cycle, lambda step: GRIB, (0,))
    assert payload is not None
    assert -180.0 <= payload["lon_first"] <= 180.0
    assert -180.0 <= payload["lon_last"] <= 180.0
