"""SwellMap basin layer (v0.2): animated wave-field frames per region, precomputed.

For each basin box (derived from the spot DB - a spot's lat/lon stays the only place
a location is written down) this fetches GFS-Wave gridded Hs / peak period / primary
direction via the same NOMADS grib-filter path the Stage-3a archive uses, quantizes
each 3-hourly field to bytes, and publishes one compact JSON per region. The web map
colormaps the grids client-side, so the pipeline precomputes DATA (the principle that
matters) without shipping megabytes of rendered PNGs.

Sizing, so nobody re-derives it: ~57 steps x 6 boxes = ~342 filter requests/cycle at
10-30 KB each, seconds of CPU, ~2 MB published. Runs on the existing VM cron.

All-rights-reserved note: this renders NOAA open data with our own pipeline. It must
never fetch, mimic or trace ISRAMAR's imagery (CLAUDE.md legal red lines).
"""

from __future__ import annotations

import json
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .gfswave import Box, _is_grib, _lon360, filter_url, pick_cycle
from .spots import load_spots

# One basin box can serve several spot regions (Costa Rica + Nicaragua share a coast).
BASINS: dict[str, tuple[str, ...]] = {
    "israel": ("Israel",),
    "portugal": ("Portugal",),
    "central-america": ("Costa Rica", "Nicaragua"),
    "sri-lanka": ("Sri Lanka",),
    "japan": ("Japan",),
    "philippines": ("Philippines",),
}
BOX_PAD_DEG = 3.0  # sea-room around the spot extent so swell context is visible
STEP_H = 3
HORIZON_H = 168  # 7 days - the scrub range; beyond this confidence is low anyway
REQUEST_GAP_S = 0.15  # NOMADS courtesy

# Quantization (u8, 255 = land/missing): chosen so the round-trip error is far below
# forecast error - 0.1 m in Hs, 2 deg in direction, 0.2 s in period.
HS_SCALE, DIR_SCALE, PER_SCALE = 0.1, 2.0, 0.2
WIND_SCALE = 0.25  # m/s - u8 caps at 63.5 m/s, beyond any real wind
MISSING = 255


@dataclass(frozen=True, slots=True)
class BasinBox:
    name: str
    regions: tuple[str, ...]
    lat0: float  # south
    lat1: float  # north
    lon0: float  # west (-180..180)
    lon1: float  # east


def basin_boxes(spots_dir: Path) -> list[BasinBox]:
    """Basin extents = spot extents + padding, recomputed from the DB every run so
    new spots grow their basin automatically."""
    spots = load_spots(spots_dir)
    out: list[BasinBox] = []
    for name, regions in BASINS.items():
        pts = [(s.lat, s.lon) for s in spots.values() if s.region in regions]
        if not pts:
            continue
        lats = [p[0] for p in pts]
        lons = [p[1] for p in pts]
        out.append(
            BasinBox(
                name=name,
                regions=regions,
                lat0=min(lats) - BOX_PAD_DEG,
                lat1=max(lats) + BOX_PAD_DEG,
                lon0=min(lons) - BOX_PAD_DEG,
                lon1=max(lons) + BOX_PAD_DEG,
            )
        )
    return out


def _quantize(value: float | None, scale: float) -> int:
    if value is None:
        return MISSING
    q = round(value / scale)
    return min(254, max(0, q))


def parse_grib_field(grib_bytes: bytes) -> dict | None:
    """The whole subgrid (not point samples): {lats, lons, hs, per, dir} row-major as
    the file stores it, masked cells (land) -> None."""
    import numpy as np
    import pygrib

    with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
        tf.write(grib_bytes)
        tf.flush()
        grbs = pygrib.open(tf.name)
        fields: dict[str, object] = {}
        lats = lons = None
        for m in grbs:
            if m.shortName in ("swh", "perpw", "dirpw", "ws", "wdir") and m.shortName not in fields:
                fields[m.shortName] = m.values
                if lats is None:
                    lats, lons = m.latlons()
        grbs.close()
    if lats is None or "swh" not in fields:
        return None

    def flat(name: str) -> list[float | None]:
        vals = fields.get(name)
        if vals is None:
            return [None] * lats.size
        arr = np.ma.filled(np.ma.masked_invalid(vals), np.nan)
        return [None if np.isnan(v) else float(v) for v in arr.ravel()]

    def norm_lon(lon: float) -> float:
        # grib-filter works in 0-360; the web draws in -180..180. None of our basins
        # cross the antimeridian, so a plain wrap is safe (Portugal 347.5 -> -12.5).
        return lon - 360.0 if lon > 180.0 else lon

    return {
        "ny": lats.shape[0],
        "nx": lats.shape[1],
        "lat_first": float(lats[0, 0]),
        "lat_last": float(lats[-1, 0]),
        "lon_first": norm_lon(float(lons[0, 0])),
        "lon_last": norm_lon(float(lons[0, -1])),
        "hs": flat("swh"),
        "per": flat("perpw"),
        "dir": flat("dirpw"),
        "wind": flat("ws"),
        "wdir": flat("wdir"),
    }


def build_basin_payload(
    basin: BasinBox,
    cycle: datetime,
    fetch: Callable[[int], bytes | None],
    steps: tuple[int, ...],
) -> dict | None:
    """One region file: geometry + quantized per-step frames. `fetch(step) -> bytes|None`
    so the network (or a fixture) stays injectable."""
    frames: list[dict] = []
    geom: dict | None = None
    for step in steps:
        raw = fetch(step)
        if raw is None:
            continue
        field = parse_grib_field(raw)
        if field is None:
            continue
        if geom is None:
            geom = {
                k: field[k] for k in ("ny", "nx", "lat_first", "lat_last", "lon_first", "lon_last")
            }
        elif (field["ny"], field["nx"]) != (geom["ny"], geom["nx"]):
            continue  # a malformed step must not corrupt the grid geometry
        frames.append(
            {
                "t": (cycle + timedelta(hours=step)).strftime("%Y-%m-%dT%H:%MZ"),
                "hs": [_quantize(v, HS_SCALE) for v in field["hs"]],
                "per": [_quantize(v, PER_SCALE) for v in field["per"]],
                "dir": [_quantize(v, DIR_SCALE) for v in field["dir"]],
                "wind": [_quantize(v, WIND_SCALE) for v in field["wind"]],
                "wdir": [_quantize(v, DIR_SCALE) for v in field["wdir"]],
            }
        )
    if geom is None or not frames:
        return None
    return {
        "basin": basin.name,
        "regions": list(basin.regions),
        "model": "noaa:gfswave.global.0p25",
        "run": cycle.strftime("%Y-%m-%dT%H:%MZ"),
        "attribution": "Wave data: NOAA GFS-Wave (WAVEWATCH III)",
        "scales": {
            "hs_m": HS_SCALE,
            "per_s": PER_SCALE,
            "dir_deg": DIR_SCALE,
            "wind_ms": WIND_SCALE,
            "missing": MISSING,
        },
        **geom,
        "frames": frames,
    }


def fetch_basin_step(
    client: httpx.Client, cycle: datetime, step: int, basin: BasinBox
) -> bytes | None:
    box = Box(
        bottom=basin.lat0,
        top=basin.lat1,
        left=_lon360(basin.lon0),
        right=_lon360(basin.lon1),
    )
    try:
        resp = client.get(filter_url(cycle, step, box))
    except httpx.HTTPError:
        return None
    if resp.status_code != 200 or not _is_grib(resp.content):
        return None
    return resp.content


def run_swellmap(
    spots_dir: Path,
    out_dir: Path,
    now: datetime | None = None,
    basins: list[BasinBox] | None = None,
) -> list[str]:
    """Fetch + publish every basin. Returns the basin names written. A basin whose
    fetch fails entirely is skipped (the old file keeps serving), never fatal."""
    cycle = pick_cycle(now or datetime.now(UTC))
    steps = tuple(range(0, HORIZON_H + 1, STEP_H))
    target = out_dir / "swellmap"
    target.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    index: dict[str, dict] = {}
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for basin in basins if basins is not None else basin_boxes(spots_dir):

            def fetch(step: int, _b: BasinBox = basin) -> bytes | None:
                raw = fetch_basin_step(client, cycle, step, _b)
                time.sleep(REQUEST_GAP_S)
                return raw

            payload = build_basin_payload(basin, cycle, fetch, steps)
            if payload is None:
                print(f"warn: swellmap {basin.name}: no frames fetched - keeping previous file")
                continue
            (target / f"{basin.name}.json").write_text(
                json.dumps(payload, separators=(",", ":")), encoding="utf-8"
            )
            written.append(basin.name)
            index[basin.name] = {
                "regions": payload["regions"],
                "run": payload["run"],
                "frames": len(payload["frames"]),
                "bbox": [basin.lat0, basin.lon0, basin.lat1, basin.lon1],
            }
            print(f"swellmap {basin.name}: {len(payload['frames'])} frames")
    if written:
        # merge over the previous index so a skipped basin keeps its entry
        idx_path = target / "index.json"
        prev = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
        prev.update(index)
        idx_path.write_text(json.dumps(prev, separators=(",", ":")), encoding="utf-8")
    return written
