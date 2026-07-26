"""SwellMap basin layer - offline against the captured Med GRIB fixture."""

from datetime import UTC, datetime
from pathlib import Path

from rosa_pipeline.swellmap import (
    BASINS,
    MISSING,
    BasinBox,
    _quantize,
    basin_boxes,
    build_basin_payload,
    parse_grib_field,
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
