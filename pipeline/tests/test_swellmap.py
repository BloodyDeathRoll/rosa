"""SwellMap basin layer - offline against the captured Med GRIB fixture."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rosa_pipeline.swellmap import (
    BASINS,
    MISSING,
    WORLD_PLANES,
    WORLD_SUBSAMPLE,
    BasinBox,
    BasinFrames,
    _quantize,
    _quantize_plane,
    _resolve_cycle,
    basin_boxes,
    build_basin_payload,
    build_world_frames,
    parse_grib_field,
    parse_grib_planes,
    png_gray,
    slice_basin_field,
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


# --- late-NOMADS cycle fallback (2026-08-17 proposal) --------------------------
# The layer used to pick pick_cycle(now) and never retry an older one, so a late
# publication cost the whole refresh: every step missed, the previous file kept
# serving, and the map went up to ~10 h stale until the next cron slot.

CYC = datetime(2026, 8, 23, 12, tzinfo=UTC)


def test_resolve_cycle_keeps_the_current_cycle_when_step_0_is_there():
    asked: list[tuple[datetime, int]] = []

    def fetch(cyc, step):
        asked.append((cyc, step))
        return b"GRIB-payload"

    cycle, first = _resolve_cycle(CYC, fetch, 0)
    assert cycle == CYC
    assert first == b"GRIB-payload"
    assert asked == [(CYC, 0)]  # no speculative second request on a normal day


def test_resolve_cycle_drops_back_six_hours_when_nomads_is_late():
    late = CYC - timedelta(hours=6)

    def fetch(cyc, step):
        return b"older" if cyc == late else None

    cycle, first = _resolve_cycle(CYC, fetch, 0)
    assert cycle == late
    assert first == b"older"


def test_resolve_cycle_gives_up_after_one_drop_back():
    asked: list[datetime] = []

    def fetch(cyc, step):
        asked.append(cyc)
        return None

    _cycle, first = _resolve_cycle(CYC, fetch, 0)
    assert first is None
    assert asked == [CYC, CYC - timedelta(hours=6)]  # exactly one extra request


def test_fallback_stamps_frames_on_the_cycle_it_actually_fetched():
    """A basin that fell back must label its frames with the OLDER cycle - the file
    carries one `run` stamp, so a mixed-cycle payload would lie about its own age."""
    late = CYC - timedelta(hours=6)
    steps = (0, 3)

    def fetch_at(cyc, step):
        return GRIB if cyc == late else None

    cycle, first = _resolve_cycle(CYC, fetch_at, steps[0])

    def fetch(step):
        return first if step == steps[0] else fetch_at(cycle, step)

    basin = BasinBox(name="med", regions=("Israel",), lat0=30.0, lon0=32.0, lat1=34.0, lon1=36.0)
    payload = build_basin_payload(basin, cycle, fetch, steps)
    assert payload is not None
    assert payload["frames"][0]["t"] == "2026-08-23T06:00Z"
    assert payload["frames"][1]["t"] == "2026-08-23T09:00Z"


# --- basins sliced out of the global planes (2026-08-17 proposal) -------------
# Both layers read the same five shortNames off the same 0.25 deg global file, so the
# basin layer's ~513 subregion requests per cycle re-downloaded what the world layer
# already had. The risk the proposal named is off-by-one in the lat/lon subsetting.


def _synthetic_globe(ny=21, nx=40, lat0=90.0, dlat=-9.0, lon0=0.0, dlon=9.0):
    """A coarse whole-globe grid whose cell values encode their own (row, col)."""
    import numpy as np

    geom = {
        "ny": ny,
        "nx": nx,
        "lat_first": lat0,
        "lat_last": lat0 + (ny - 1) * dlat,
        "lon_first": lon0,
        "lon_last": lon0 + (nx - 1) * dlon,
    }
    idx = np.arange(ny)[:, None] * 1000 + np.arange(nx)[None, :]
    planes = {n: idx.astype(float) for n in ("hs", "per", "dir", "wind", "wdir")}
    return geom, planes


def test_slice_covers_the_basin_box_and_reports_its_own_geometry():
    geom, planes = _synthetic_globe()
    basin = BasinBox(name="b", regions=("R",), lat0=0.0, lat1=27.0, lon0=18.0, lon1=45.0)
    f = slice_basin_field(geom, planes, basin)
    assert f is not None
    # the window must CONTAIN the box, never clip inside it
    assert f["lat_first"] >= basin.lat1 and f["lat_last"] <= basin.lat0
    assert f["lon_first"] <= basin.lon0 and f["lon_last"] >= basin.lon1
    assert f["ny"] * f["nx"] == len(f["hs"])
    # row-major, and the values still name the global cells they came from
    top_left = f["hs"][0]
    assert top_left == (90.0 - f["lat_first"]) / 9.0 * 1000 + f["lon_first"] / 9.0


def test_slice_matches_the_grid_geometry_the_payload_would_publish():
    geom, planes = _synthetic_globe()
    basin = BasinBox(name="b", regions=("R",), lat0=-18.0, lat1=18.0, lon0=90.0, lon1=126.0)
    f = slice_basin_field(geom, planes, basin)
    assert f is not None
    dlat = (f["lat_last"] - f["lat_first"]) / (f["ny"] - 1)
    dlon = (f["lon_last"] - f["lon_first"]) / (f["nx"] - 1)
    assert dlat == -9.0 and dlon == 9.0  # native spacing preserved, no resampling


def test_slice_wraps_lon_to_signed_like_parse_grib_field():
    geom, planes = _synthetic_globe()
    # Portugal-ish: 347.5 deg east on the 0-360 grid must publish as negative
    basin = BasinBox(name="pt", regions=("Portugal",), lat0=36.0, lat1=42.0, lon0=-13.0, lon1=-8.0)
    f = slice_basin_field(geom, planes, basin)
    assert f is not None
    assert f["lon_first"] < 0 and f["lon_last"] < 0


def test_slice_refuses_a_seam_crossing_box_instead_of_guessing():
    geom, planes = _synthetic_globe()
    # antimeridian: 170E..170W is contiguous in the file's 0-360 frame (170..190) but
    # cannot be published as a signed lon_first < lon_last grid
    anti = BasinBox(name="x", regions=("R",), lat0=-9.0, lat1=9.0, lon0=170.0, lon1=-170.0)
    assert slice_basin_field(geom, planes, anti) is None
    # 0/360 seam: Greenwich-crossing box, refused before any index arithmetic
    seam = BasinBox(name="y", regions=("R",), lat0=-9.0, lat1=9.0, lon0=-10.0, lon1=10.0)
    assert slice_basin_field(geom, planes, seam) is None


def test_slice_marks_land_as_none_like_the_grib_parser():
    import numpy as np

    geom, planes = _synthetic_globe()
    planes = {k: v.copy() for k, v in planes.items()}
    for v in planes.values():
        v[5, 5] = np.nan
    basin = BasinBox(name="b", regions=("R",), lat0=-90.0, lat1=90.0, lon0=0.0, lon1=179.0)
    f = slice_basin_field(geom, planes, basin)
    assert f is not None
    assert f["hs"][5 * f["nx"] + 5] is None


def test_sliced_frames_equal_the_pull_path_on_the_real_fixture():
    """The two paths must build the same frame - same accumulator, same quantization."""
    geom, planes = parse_grib_planes(GRIB)
    med = BasinBox(name="med", regions=("Israel",), lat0=30.0, lat1=34.0, lon0=32.0, lon1=36.0)
    field = slice_basin_field(geom, planes, med)
    assert field is not None
    acc = BasinFrames(med, CYC)
    acc.add(0, field)
    pushed = acc.payload()
    pulled = build_basin_payload(med, CYC, lambda step: GRIB, (0,))
    assert pushed is not None and pulled is not None
    # the slice is a window on the fixture's own subgrid, so it is a subset, not equal;
    # what must match is the frame SHAPE and the quantization contract
    assert pushed["frames"][0].keys() == pulled["frames"][0].keys()
    assert pushed["scales"] == pulled["scales"]
    assert pushed["run"] == pulled["run"]
    assert pushed["ny"] * pushed["nx"] == len(pushed["frames"][0]["hs"])


# --- seam-safe basin extents (2026-08-31) -------------------------------------------------

_FIJI_YAML = """\
spots:
  - id: test-fiji-w
    name: Test Fiji W
    lat: -17.8
    lon: 177.2
    timezone: Pacific/Fiji
    offshore_direction: 250
    swell_window: [180, 300]
    height_coeff: 1.0
    break_type: reef
    ideal: {wind_dir: [45, 135], size_m: [0.6, 2.5]}
  - id: test-fiji-e
    name: Test Fiji E
    lat: -18.1
    lon: -178.8
    timezone: Pacific/Fiji
    offshore_direction: 110
    swell_window: [0, 120]
    height_coeff: 1.0
    break_type: reef
    ideal: {wind_dir: [225, 315], size_m: [0.6, 2.5]}
"""


def test_basin_boxes_seed_offsets_are_a_noop_for_every_committed_basin():
    """The signed-offset extent (cluster_boxes idiom) must reproduce the old plain
    min/max box for every committed basin - none has SPOTS crossing a seam today.
    Padding is clamped at the antimeridian (Fiji's +3 deg of sea-room would otherwise
    land at 180.95), so the expected edge is the padded one capped at +/-180."""
    from rosa_pipeline.spots import load_spots
    from rosa_pipeline.swellmap import BOX_PAD_DEG

    spots = load_spots(SPOTS_DIR)
    boxes = basin_boxes(SPOTS_DIR)
    assert boxes
    for b in boxes:
        lons = [s.lon for s in spots.values() if s.region in b.regions]
        assert b.lon0 == pytest.approx(max(min(lons) - BOX_PAD_DEG, -180.0), abs=1e-9)
        assert b.lon1 == pytest.approx(min(max(lons) + BOX_PAD_DEG, 180.0), abs=1e-9)
        assert b.lon0 < b.lon1


def test_padding_never_invents_an_antimeridian_crossing():
    """Fiji's easternmost spot is at 177.95 E: inside the seam, but +3 deg of padding
    is not. The box must clamp at 180 rather than wrap to -179.05, which would make it
    unsliceable AND publish a grid whose lon_first sits east of its lon_last."""
    from rosa_pipeline.spots import load_spots

    spots = load_spots(SPOTS_DIR)
    [fiji] = [b for b in basin_boxes(SPOTS_DIR) if b.name == "fiji"]
    east = max(s.lon for s in spots.values() if s.region in fiji.regions)
    assert east < 180.0
    assert fiji.lon1 == pytest.approx(180.0)
    assert fiji.lon0 < fiji.lon1


def test_basin_box_across_the_antimeridian_stays_local_and_warns(tmp_path, monkeypatch, capsys):
    """Fiji-shaped region (+177.2 and -178.8): the old min/max gave lon0=-181.8,
    lon1=+180.2 - a box covering the ~356 deg the region is NOT in. The offset extent
    keeps it 10 deg wide; the signed pair cannot express it (lon1 < lon0), which routes
    it to the per-basin direct fetch whose 0-360 box CAN."""
    import rosa_pipeline.swellmap as swellmap
    from rosa_pipeline.gfswave import _lon360

    (tmp_path / "fiji.yaml").write_text(_FIJI_YAML, encoding="utf-8")
    monkeypatch.setattr(swellmap, "BASINS", {"fiji": ("Fiji",)})
    [b] = swellmap.basin_boxes(tmp_path)
    assert b.lon0 == pytest.approx(174.2)
    assert b.lon1 == pytest.approx(-175.8)
    assert b.lon1 < b.lon0  # slice_basin_field returns None for this - direct fetch
    assert _lon360(b.lon0) < _lon360(b.lon1)  # ...and fetch_basin_step's box is valid
    assert "crosses the antimeridian" in capsys.readouterr().out
