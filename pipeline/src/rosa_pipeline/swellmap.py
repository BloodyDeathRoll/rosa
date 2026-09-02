"""SwellMap basin layer (v0.2): animated wave-field frames per region, precomputed.

For each basin box (derived from the spot DB - a spot's lat/lon stays the only place
a location is written down) this fetches GFS-Wave gridded Hs / peak period / primary
direction via the same NOMADS grib-filter path the Stage-3a archive uses, quantizes
each 3-hourly field to bytes, and publishes one compact JSON per region. The web map
colormaps the grids client-side, so the pipeline precomputes DATA (the principle that
matters) without shipping megabytes of rendered PNGs.

Sizing, so nobody re-derives it: ~57 steps x 9 boxes = ~513 filter requests/cycle at
10-30 KB each, seconds of CPU, ~2 MB published. Runs on the existing VM cron.

All-rights-reserved note: this renders NOAA open data with our own pipeline. It must
never fetch, mimic or trace ISRAMAR's imagery (CLAUDE.md legal red lines).
"""

from __future__ import annotations

import json
import math
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar

import httpx

from .geo import dlon180, lon360
from .gfswave import FILTER_URL, RESOLUTION, Box, _is_grib, _lon360, filter_url, pick_cycle
from .publish import write_json_atomic
from .spots import load_spots

# One basin box can serve several spot regions (Costa Rica + Nicaragua share a coast).
BASINS: dict[str, tuple[str, ...]] = {
    "israel": ("Israel",),
    "portugal": ("Portugal",),
    "central-america": ("Costa Rica", "Nicaragua", "El Salvador", "Panama"),
    # Mexico gets its own box rather than joining central-america: its spots run from
    # Tijuana to the Oaxaca isthmus, and merging them would stretch one frame over
    # 30 deg of latitude and drown the Central American detail in sea room.
    "mexico": ("Mexico",),
    "sri-lanka": ("Sri Lanka",),
    "japan": ("Japan",),
    "philippines": ("Philippines",),
    "california": ("California",),
    # Oregon + Washington share one Pacific Northwest frame: 900 km of one coastline
    "pacific-northwest": ("Oregon", "Washington"),
    "hawaii": ("Hawaii",),
    "morocco": ("Morocco",),
    "angola": ("Angola",),
    "peru": ("Peru",),
    "maldives": ("Maldives",),
    # Sydney + Byron Bay share one east-Australian frame: same Tasman/Coral Sea swell
    "australia-east": ("Sydney", "Byron Bay", "Gold Coast", "Sunshine Coast"),
    # Perth + Margaret River share one Indian Ocean frame: the same SW groundswell
    "australia-west": ("Perth", "Margaret River"),
    # Bali first; later Indonesian regions (Lombok/Sumbawa, Java, Mentawai) join here
    "indonesia": ("Bali", "Lombok", "Sumbawa", "East Java", "West Java"),
    "french-polynesia": ("French Polynesia",),
    "fiji": ("Fiji",),
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
        # lon extent measured as signed offsets from the first spot (cluster_boxes'
        # idiom, gfswave.py): plain min/max over signed longitudes turns a region
        # straddling the antimeridian (Fiji: +177.2 and -178.8) into a degenerate box
        # covering the ~356 deg the region is NOT in. No committed basin crosses either
        # seam today (nearest is Portugal, lon ~ -13); offsets keep a future one whole.
        seed = lon360(pts[0][1])
        offs = [dlon180(lon360(p[1]), seed) for p in pts]
        west = (seed + min(offs) + 180.0) % 360.0 - 180.0
        east = (seed + max(offs) + 180.0) % 360.0 - 180.0
        if east >= west:
            # The SPOTS do not cross the seam - only the padding would (Fiji reaches
            # 177.95 E, +3 deg of sea-room lands at 180.95 = -179.05 signed, and the
            # box reads inside-out from there: unsliceable, and the published grid
            # comes out with lon_first east of lon_last for the web map to draw
            # backwards). Padding must never INVENT a crossing, so clamp it at the
            # seam; a genuinely straddling region still takes the wrap path below.
            # clamp in SIGNED space, before any wrap: wrapping first would turn
            # 180.95 into -179.05 and min() would keep it.
            lon0, lon1 = max(west - BOX_PAD_DEG, -180.0), min(east + BOX_PAD_DEG, 180.0)
        else:
            lon0 = (seed + min(offs) - BOX_PAD_DEG + 180.0) % 360.0 - 180.0
            lon1 = (seed + max(offs) + BOX_PAD_DEG + 180.0) % 360.0 - 180.0
        if lon1 < lon0:
            # the published signed pair cannot express an antimeridian-crossing box.
            # Do NOT clamp: slice_basin_field treats lon1 < lon0 as unsliceable, the
            # combined pass falls back to this basin's own subregion requests, and
            # fetch_basin_step's 0-360 geometry expresses the box fine - so the basin
            # still publishes correctly. Warn like the gfswave cluster seam does.
            print(
                f"warn: swellmap basin {name!r} crosses the antimeridian "
                f"({lon0:.2f}..{lon1:.2f} signed) - unsliceable from the global file, "
                "it will be fetched with its own subregion requests"
            )
        out.append(
            BasinBox(
                name=name,
                regions=regions,
                lat0=min(lats) - BOX_PAD_DEG,
                lat1=max(lats) + BOX_PAD_DEG,
                lon0=lon0,
                lon1=lon1,
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
    the file stores it, masked cells (land) -> None. A thin view over
    parse_grib_planes: same pygrib pass, but flattened to lists-with-None and lons
    wrapped to -180..180 (basins only; the world path keeps 0-360)."""
    import numpy as np

    parsed = parse_grib_planes(grib_bytes)
    if parsed is None:
        return None
    geom, planes = parsed

    def flat(name: str) -> list[float | None]:
        arr = np.asarray(planes[name], dtype=float)
        return [None if np.isnan(v) else float(v) for v in arr.ravel()]

    def norm_lon(lon: float) -> float:
        # grib-filter works in 0-360; the web draws in -180..180. None of our basins
        # cross the antimeridian, so a plain wrap is safe (Portugal 347.5 -> -12.5).
        return lon - 360.0 if lon > 180.0 else lon

    return {
        "ny": geom["ny"],
        "nx": geom["nx"],
        "lat_first": geom["lat_first"],
        "lat_last": geom["lat_last"],
        "lon_first": norm_lon(geom["lon_first"]),
        "lon_last": norm_lon(geom["lon_last"]),
        "hs": flat("hs"),
        "per": flat("per"),
        "dir": flat("dir"),
        "wind": flat("wind"),
        "wdir": flat("wdir"),
    }


_GEOM_KEYS = ("ny", "nx", "lat_first", "lat_last", "lon_first", "lon_last")


class BasinFrames:
    """Push-driven accumulator for one basin file: feed it `add(step, field)` in step
    order, then ask for `payload()`.

    Push rather than pull so ONE global download can serve every basin in the same
    pass (run_swellmap_all). `build_basin_payload` is the pull-shaped wrapper over
    exactly this, so the per-basin filter path and the sliced path build byte-identical
    frames from the same code."""

    def __init__(self, basin: BasinBox, cycle: datetime) -> None:
        self.basin = basin
        self.cycle = cycle
        self.geom: dict | None = None
        self.frames: list[dict] = []

    def add(self, step: int, field: dict | None) -> None:
        if field is None:
            return
        if self.geom is None:
            self.geom = {k: field[k] for k in _GEOM_KEYS}
        elif (field["ny"], field["nx"]) != (self.geom["ny"], self.geom["nx"]):
            return  # a malformed step must not corrupt the grid geometry
        self.frames.append(
            {
                "t": (self.cycle + timedelta(hours=step)).strftime("%Y-%m-%dT%H:%MZ"),
                "hs": [_quantize(v, HS_SCALE) for v in field["hs"]],
                "per": [_quantize(v, PER_SCALE) for v in field["per"]],
                "dir": [_quantize(v, DIR_SCALE) for v in field["dir"]],
                "wind": [_quantize(v, WIND_SCALE) for v in field["wind"]],
                "wdir": [_quantize(v, DIR_SCALE) for v in field["wdir"]],
            }
        )

    def payload(self) -> dict | None:
        if self.geom is None or not self.frames:
            return None
        return {
            "basin": self.basin.name,
            "regions": list(self.basin.regions),
            "model": "noaa:gfswave.global.0p25",
            "run": self.cycle.strftime("%Y-%m-%dT%H:%MZ"),
            "attribution": "Wave data: NOAA GFS-Wave (WAVEWATCH III)",
            "scales": {
                "hs_m": HS_SCALE,
                "per_s": PER_SCALE,
                "dir_deg": DIR_SCALE,
                "wind_ms": WIND_SCALE,
                "missing": MISSING,
            },
            **self.geom,
            "frames": self.frames,
        }


def build_basin_payload(
    basin: BasinBox,
    cycle: datetime,
    fetch: Callable[[int], bytes | None],
    steps: tuple[int, ...],
) -> dict | None:
    """One region file: geometry + quantized per-step frames. `fetch(step) -> bytes|None`
    so the network (or a fixture) stays injectable. A thin pull-shaped view over
    BasinFrames."""
    acc = BasinFrames(basin, cycle)
    for step in steps:
        raw = fetch(step)
        acc.add(step, parse_grib_field(raw) if raw is not None else None)
    return acc.payload()


def slice_basin_field(geom: dict, planes: dict, basin: BasinBox) -> dict | None:
    """Cut one basin's field out of an already-downloaded GLOBAL plane set, in the exact
    shape `parse_grib_field` returns.

    Both layers read the same five shortNames off the same 0.25 deg global file, so the
    basin layer's ~513 grib-filter subregion requests per cycle were re-downloading data
    the world layer had already fetched. Slicing costs no request at all.

    The row/column window is chosen to COVER the basin box (floor on the leading edge,
    ceil on the trailing one), so the published grid is a superset of what grib-filter's
    subregion returned, never a subset. The payload's own geometry keys are computed from
    the slice that was actually taken, so the file stays self-describing either way.

    Returns None when the box would wrap either seam - the file's 0/360 wrap or the
    antimeridian the SIGNED published grid cannot express. No committed basin crosses
    either, and the caller falls back to the per-basin filter request rather than guess.
    """
    import numpy as np

    ny, nx = geom["ny"], geom["nx"]
    if ny < 2 or nx < 2:
        return None
    dlat = (geom["lat_last"] - geom["lat_first"]) / (ny - 1)
    dlon = (geom["lon_last"] - geom["lon_first"]) / (nx - 1)
    if dlat == 0 or dlon == 0:
        return None

    def span(a: float, b: float, first: float, d: float, n: int) -> tuple[int, int]:
        # a/b in grid order (a reached before b as the index grows)
        i0 = math.floor((a - first) / d)
        i1 = math.ceil((b - first) / d)
        return max(0, min(i0, n - 1)), max(0, min(i1, n - 1))

    # rows run north -> south on the global grid (dlat < 0), so lat1 comes first
    lat_a, lat_b = (basin.lat1, basin.lat0) if dlat < 0 else (basin.lat0, basin.lat1)
    i0, i1 = span(lat_a, lat_b, geom["lat_first"], dlat, ny)
    lon0, lon1 = _lon360(basin.lon0), _lon360(basin.lon1)
    if lon1 < lon0:
        return None  # crosses the 0/360 seam - let the caller fetch this basin directly
    j0, j1 = span(lon0, lon1, geom["lon_first"], dlon, nx)
    if i1 < i0 or j1 < j0:
        return None

    def flat(name: str) -> list[float | None]:
        arr = np.asarray(planes[name], dtype=float)[i0 : i1 + 1, j0 : j1 + 1]
        return [None if np.isnan(v) else float(v) for v in arr.ravel()]

    def norm_lon(lon: float) -> float:
        return lon - 360.0 if lon > 180.0 else lon

    lon_first = norm_lon(geom["lon_first"] + j0 * dlon)
    lon_last = norm_lon(geom["lon_first"] + j1 * dlon)
    if lon_first > lon_last:
        # the window straddles the ANTIMERIDIAN: fine in the file's 0-360 frame, but the
        # published payload is signed (-180..180, what the web map draws in) and would
        # come out with lon_first east of lon_last - a grid the client reads backwards.
        # No committed basin crosses it; the caller fetches this one directly instead.
        return None

    return {
        "ny": i1 - i0 + 1,
        "nx": j1 - j0 + 1,
        "lat_first": geom["lat_first"] + i0 * dlat,
        "lat_last": geom["lat_first"] + i1 * dlat,
        "lon_first": lon_first,
        "lon_last": lon_last,
        "hs": flat("hs"),
        "per": flat("per"),
        "dir": flat("dir"),
        "wind": flat("wind"),
        "wdir": flat("wdir"),
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


_T = TypeVar("_T")


def _resolve_cycle(
    cycle: datetime,
    fetch: Callable[[datetime, int], _T | None],
    first_step: int,
) -> tuple[datetime, _T | None]:
    """Probe `first_step` on `cycle`; if NOMADS has not published that cycle yet, drop
    back one 6 h slot and probe again. Returns the cycle to build on plus the probe's
    result, so the caller never pays for `first_step` twice.

    Mirrors `GFSWaveSource.fetch_series` and `GfsFullSource.fetch_series`, which have
    carried this drop-back since Stage 3a. Without it a late publication costs the
    whole layer its refresh: every step misses, the layer keeps the previous file, and
    the map serves up to ~10 h stale until the next cron slot. Resolved PER basin (and
    once for the world layer) so each published file stays on a single cycle - its own
    `run` stamp then still describes every frame in it.

    A transient miss on `first_step` alone shifts the layer to the older cycle for this
    run. That is the same trade the two in-repo precedents accept: one extra request on
    late days, and a cycle-older map beats no refresh at all.
    """
    got = fetch(cycle, first_step)
    if got is not None:
        return cycle, got
    older = cycle - timedelta(hours=6)
    return older, fetch(older, first_step)


def _write_basin_index(target: Path, spots_dir: Path, index: dict[str, dict]) -> None:
    """Merge this run's basin entries over the previous index and prune basins the spot
    DB no longer has. Shared by the per-basin and the sliced (combined) paths."""
    # merge over the previous index so a skipped basin keeps its entry
    idx_path = target / "index.json"
    prev: dict = {}
    if idx_path.exists():
        try:
            loaded = json.loads(idx_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # a torn index (written non-atomically before write_json_atomic, or
            # damaged any other way) parsed bare crash-looped every later run -
            # after all basins
            # had already been fetched, and before the world layer got to run. A
            # basin skipped this run loses its entry until its next good fetch;
            # degraded, but the map stays alive (same contract as publish._read_index).
            print(f"warn: {idx_path} is unreadable - rebuilding from this run's basins")
        else:
            if isinstance(loaded, dict):
                prev = loaded
    prev.update(index)
    # The DB is the authority on what exists (same rule as publish.prune_index):
    # the merge above only ever upserts, so a basin whose spots left the DB kept
    # its index entry and its <basin>.json forever - both shipping in every CDN
    # deploy. Keyed on basin_boxes(spots_dir), NOT on this run's output, so a
    # basin merely skipped for a failed fetch keeps serving its previous file.
    known = {b.name for b in basin_boxes(spots_dir)}
    for stale in sorted(set(prev) - known):
        del prev[stale]
        (target / f"{stale}.json").unlink(missing_ok=True)
        print(f"swellmap: pruned basin {stale!r} - no longer in the DB")
    write_json_atomic(idx_path, prev)


def _publish_basin(
    target: Path, basin: BasinBox, payload: dict | None, index: dict[str, dict]
) -> bool:
    """Write one basin file and record its index entry. Returns whether it was written -
    a basin whose fetch produced nothing keeps its previous file and its old entry."""
    if payload is None:
        print(f"warn: swellmap {basin.name}: no frames fetched - keeping previous file")
        return False
    write_json_atomic(target / f"{basin.name}.json", payload)
    index[basin.name] = {
        "regions": payload["regions"],
        "run": payload["run"],
        "frames": len(payload["frames"]),
        "bbox": [basin.lat0, basin.lon0, basin.lat1, basin.lon1],
    }
    print(f"swellmap {basin.name}: {len(payload['frames'])} frames")
    return True


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

            def fetch_at(cyc: datetime, step: int, _b: BasinBox = basin) -> bytes | None:
                raw = fetch_basin_step(client, cyc, step, _b)
                time.sleep(REQUEST_GAP_S)
                return raw

            b_cycle, first = _resolve_cycle(cycle, fetch_at, steps[0])
            if b_cycle != cycle:
                print(
                    f"swellmap {basin.name}: {cycle:%Y-%m-%dT%H}Z not on NOMADS yet - "
                    f"falling back to {b_cycle:%Y-%m-%dT%H}Z"
                )

            def fetch(
                step: int,
                _b: BasinBox = basin,
                _c: datetime = b_cycle,
                _first: bytes | None = first,
            ) -> bytes | None:
                # steps[0] was already paid for by the probe above
                return _first if step == steps[0] else fetch_at(_c, step, _b)

            payload = build_basin_payload(basin, b_cycle, fetch, steps)
            if _publish_basin(target, basin, payload, index):
                written.append(basin.name)
    if written:
        _write_basin_index(target, spots_dir, index)
    return written


# ---------------------------------------------------------------------------
# World layer: the whole globe, one PNG per timestep.
#
# JSON dies at global scale (65k cells x 5 fields x 57 frames ≈ 28 MB/cycle even
# at 1 deg), so the quantized planes are packed into an 8-bit grayscale PNG
# instead: five field planes (hs, per, dir, wind, wdir) stacked vertically, so
# one image is (5*ny) x nx. PNG's Up filter + zlib love smooth geophysical
# fields - a 0.5 deg world frame lands around 60-120 KB. The client fetches
# frames lazily while scrubbing and decodes via an offscreen canvas.
# ---------------------------------------------------------------------------

WORLD_SUBSAMPLE = 2  # GFS-Wave global native 0.25 deg -> published 0.5 deg
WORLD_PLANES = ("hs", "per", "dir", "wind", "wdir")
_WORLD_VARS = ("HTSGW", "PERPW", "DIRPW", "WIND", "WDIR")  # grib-filter var names
_PLANE_SCALES = {
    "hs": HS_SCALE,
    "per": PER_SCALE,
    "dir": DIR_SCALE,
    "wind": WIND_SCALE,
    "wdir": DIR_SCALE,
}


def world_filter_url(cycle: datetime, step: int) -> str:
    """Whole-globe grib-filter request, explicit variables only (all_var on the
    full grid would ship every swell partition - several times the bytes)."""
    from urllib.parse import quote

    d = quote(f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/wave/gridded", safe="")
    f = f"gfswave.t{cycle:%H}z.global.{RESOLUTION}.f{step:03d}.grib2"
    var = "&".join(f"var_{v}=on" for v in _WORLD_VARS)
    return (
        f"{FILTER_URL}?dir={d}&file={f}&{var}&subregion="
        f"&toplat=90&leftlon=0&rightlon=360&bottomlat=-90"
    )


def parse_grib_planes(grib_bytes: bytes) -> tuple[dict, dict] | None:
    """The single pygrib pass: (geometry, {name: 2-D float array, NaN = land/missing}).
    Longitudes stay as the file stores them (0-360 for the global grid) - the world
    client handles the wrap; parse_grib_field wraps them for the basins."""
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
    geom = {
        "ny": int(lats.shape[0]),
        "nx": int(lats.shape[1]),
        "lat_first": float(lats[0, 0]),
        "lat_last": float(lats[-1, 0]),
        "lon_first": float(lons[0, 0]),
        "lon_last": float(lons[0, -1]),
    }
    grib_to_plane = {"swh": "hs", "perpw": "per", "dirpw": "dir", "ws": "wind", "wdir": "wdir"}
    planes: dict[str, object] = {}
    for short, name in grib_to_plane.items():
        vals = fields.get(short)
        if vals is None:
            planes[name] = np.full((geom["ny"], geom["nx"]), np.nan)
        else:
            planes[name] = np.ma.filled(np.ma.masked_invalid(vals), np.nan).astype(float)
    return geom, planes


def _quantize_plane(arr: object, scale: float) -> object:
    """Vectorized _quantize: NaN -> 255, else round(v/scale) clipped to 0..254."""
    import numpy as np

    q = np.round(np.asarray(arr, dtype=float) / scale)
    q = np.clip(q, 0, 254)
    q = np.where(np.isnan(np.asarray(arr, dtype=float)), MISSING, q)
    return q.astype(np.uint8)


def png_gray(width: int, height: int, pixels: bytes) -> bytes:
    """Minimal 8-bit grayscale PNG encoder (pure zlib, no imaging dependency).
    Uses the Up filter on every scanline - near-optimal for smooth fields."""
    import struct
    import zlib

    import numpy as np

    img = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width)
    up = img - np.vstack([np.zeros((1, width), np.uint8), img[:-1]])  # uint8 wraps = Up filter
    filtered = np.concatenate([np.full((height, 1), 2, np.uint8), up], axis=1)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)  # bit depth 8, grayscale
    idat = zlib.compress(filtered.tobytes(), 9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _subsample_geom(geom: dict, k: int) -> dict:
    ny, nx = geom["ny"], geom["nx"]
    dlat = (geom["lat_last"] - geom["lat_first"]) / (ny - 1)
    dlon = (geom["lon_last"] - geom["lon_first"]) / (nx - 1)
    ny2 = (ny + k - 1) // k
    nx2 = (nx + k - 1) // k
    return {
        "ny": ny2,
        "nx": nx2,
        "lat_first": geom["lat_first"],
        "lat_last": geom["lat_first"] + (ny2 - 1) * dlat * k,
        "lon_first": geom["lon_first"],
        "lon_last": geom["lon_first"] + (nx2 - 1) * dlon * k,
    }


class WorldFrames:
    """Push-driven accumulator for the global layer - the twin of BasinFrames, so the
    combined pass can feed one downloaded step to the world and every basin at once."""

    def __init__(self, cycle: datetime, world_dir: Path) -> None:
        self.cycle = cycle
        self.world_dir = world_dir
        self.geom: dict | None = None
        self.frames: list[dict] = []
        self.maxes = {"hs": 0.0, "per": 0.0, "wind": 0.0, "energy": 0.0}
        world_dir.mkdir(parents=True, exist_ok=True)

    def add(self, step: int, got: tuple[dict, dict] | None) -> None:
        import numpy as np

        if got is None:
            return
        raw_geom, planes = got
        sub = {n: np.asarray(planes[n])[::WORLD_SUBSAMPLE, ::WORLD_SUBSAMPLE] for n in WORLD_PLANES}
        sgeom = _subsample_geom(raw_geom, WORLD_SUBSAMPLE)
        if self.geom is None:
            self.geom = sgeom
        elif (sgeom["ny"], sgeom["nx"]) != (self.geom["ny"], self.geom["nx"]):
            return  # malformed step must not corrupt the grid geometry
        geom = self.geom
        q = {n: _quantize_plane(sub[n], _PLANE_SCALES[n]) for n in WORLD_PLANES}
        stacked = np.concatenate([q[n] for n in WORLD_PLANES], axis=0)
        png = png_gray(geom["nx"], geom["ny"] * len(WORLD_PLANES), stacked.tobytes())
        # cycle-scoped name: writing over the previous run's f000.png meant a run
        # killed mid-way left the OLD world.json (atomic, so it survives) labelling
        # NEW-cycle pixels with the old run's timestamps - every file parses fine,
        # the map just lies about which run it shows. New names per cycle keep the
        # surviving metadata pointing at its own frames; run_swellmap_world prunes
        # unreferenced frames after the new world.json lands.
        name = f"{self.cycle:%Y%m%d%H}-f{step:03d}.png"
        (self.world_dir / name).write_bytes(png)
        self.frames.append(
            {"t": (self.cycle + timedelta(hours=step)).strftime("%Y-%m-%dT%H:%MZ"), "png": name}
        )
        # fixed per-run ramp scale, computed here so the client never scans frames
        m = self.maxes
        hs, per, wind = sub["hs"], sub["per"], sub["wind"]
        m["hs"] = max(m["hs"], float(np.nanmax(hs)) if np.isfinite(hs).any() else 0.0)
        m["per"] = max(m["per"], float(np.nanmax(per)) if np.isfinite(per).any() else 0.0)
        if np.isfinite(wind).any():
            m["wind"] = max(m["wind"], float(np.nanmax(wind)) * 1.94384)  # knots
        energy = 0.49 * hs**2 * (0.9 * per)  # kW/m, Te = 0.9*Tp - mirrors the client
        if np.isfinite(energy).any():
            m["energy"] = max(m["energy"], float(np.nanmax(energy)))

    def meta(self) -> dict | None:
        if self.geom is None or not self.frames:
            return None
        return {
            "model": "noaa:gfswave.global.0p25",
            "grid_deg": 0.25 * WORLD_SUBSAMPLE,
            "run": self.cycle.strftime("%Y-%m-%dT%H:%MZ"),
            "attribution": "Wave data: NOAA GFS-Wave (WAVEWATCH III)",
            "scales": {
                "hs_m": HS_SCALE,
                "per_s": PER_SCALE,
                "dir_deg": DIR_SCALE,
                "wind_ms": WIND_SCALE,
                "missing": MISSING,
            },
            "planes": list(WORLD_PLANES),
            "max": {k: round(v, 2) for k, v in self.maxes.items()},
            **self.geom,
            "frames": self.frames,
        }


def build_world_frames(
    cycle: datetime,
    fetch_planes: Callable[[int], tuple[dict, dict] | None],
    steps: tuple[int, ...],
    world_dir: Path,
) -> dict | None:
    """Fetch every step, write one PNG per good step into `world_dir`, return the
    world.json metadata (or None if nothing at all arrived). `fetch_planes` is
    injectable so tests feed synthetic arrays instead of the network. A thin
    pull-shaped view over WorldFrames."""
    acc = WorldFrames(cycle, world_dir)
    for step in steps:
        acc.add(step, fetch_planes(step))
    return acc.meta()


def run_swellmap_all(
    spots_dir: Path,
    out_dir: Path,
    now: datetime | None = None,
) -> tuple[list[str], int]:
    """Publish BOTH layers off one download per step. Returns (basin names, world frames).

    The two layers read the same five shortNames off the same 0.25 deg global GFS-Wave
    file, so running them separately fetched everything twice: ~513 grib-filter subregion
    requests for the basins (9 x 57, each behind a REQUEST_GAP_S courtesy sleep) on top of
    the world layer's 57 global ones. Here the global step is downloaded once and every
    basin is cut out of it with `slice_basin_field` - ~10x fewer requests on NOMADS and
    several minutes off the VM cron, which is the shared-infrastructure etiquette this
    module's docstring already commits to.

    A basin the slice cannot serve (the 0/360 seam - no committed basin crosses it) is
    fetched with its own subregion request, so no basin silently loses its layer. The
    per-basin path stays the only route for `--basin` and `--skip-world` runs, which have
    no global download to slice from.
    """
    cycle = pick_cycle(now or datetime.now(UTC))
    steps = tuple(range(0, HORIZON_H + 1, STEP_H))
    target = out_dir / "swellmap"
    target.mkdir(parents=True, exist_ok=True)
    world_dir = target / "world"
    basins = basin_boxes(spots_dir)
    index: dict[str, dict] = {}
    written: list[str] = []

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:

        def fetch_planes_at(cyc: datetime, step: int) -> tuple[dict, dict] | None:
            try:
                resp = client.get(world_filter_url(cyc, step))
            except httpx.HTTPError:
                return None
            time.sleep(REQUEST_GAP_S)
            if resp.status_code != 200 or not _is_grib(resp.content):
                return None
            return parse_grib_planes(resp.content)

        run_cycle, first = _resolve_cycle(cycle, fetch_planes_at, steps[0])
        if run_cycle != cycle:
            print(
                f"swellmap: {cycle:%Y-%m-%dT%H}Z not on NOMADS yet - "
                f"falling back to {run_cycle:%Y-%m-%dT%H}Z"
            )

        world = WorldFrames(run_cycle, world_dir)
        accs = {b.name: BasinFrames(b, run_cycle) for b in basins}
        unsliceable: list[BasinBox] = []
        for step in steps:
            got = first if step == steps[0] else fetch_planes_at(run_cycle, step)
            world.add(step, got)
            if got is None:
                continue
            geom, planes = got
            for b in basins:
                if b in unsliceable:
                    continue
                field = slice_basin_field(geom, planes, b)
                if field is None and accs[b.name].geom is None:
                    # geometry the slicer will not guess at - this basin needs its own
                    # subregion requests; decided once, on the first good step. Keyed on
                    # "no frame accepted yet", NOT on step == steps[0]: f000 itself can be
                    # the missing step (the exact gap _resolve_cycle anticipates), and the
                    # first GOOD step then arrives with a later number - the old test never
                    # matched and the basin lost its refresh with only the generic
                    # "keeping previous file" warning to show for it.
                    unsliceable.append(b)
                    continue
                accs[b.name].add(step, field)

        for b in basins:
            if b in unsliceable:
                continue
            if _publish_basin(target, b, accs[b.name].payload(), index):
                written.append(b.name)

        if unsliceable:
            print(
                "swellmap: fetching "
                + ", ".join(b.name for b in unsliceable)
                + " directly - outside the global slice"
            )
            for basin in unsliceable:

                def fetch(step: int, _b: BasinBox = basin, _c: datetime = run_cycle):
                    raw = fetch_basin_step(client, _c, step, _b)
                    time.sleep(REQUEST_GAP_S)
                    return raw

                if _publish_basin(
                    target, basin, build_basin_payload(basin, run_cycle, fetch, steps), index
                ):
                    written.append(basin.name)

    if written:
        _write_basin_index(target, spots_dir, index)
    return written, _write_world(target, world_dir, world.meta())


def _prune_world_frames(world_dir: Path, keep: set[str]) -> None:
    """Drop frames the just-published world.json does not reference (previous
    cycles', plus any orphans a killed run left) - they would otherwise ship in
    every CDN deploy forever. Only called after the new metadata is on disk, so
    a reader always finds every frame its world.json names."""
    for p in world_dir.glob("*.png"):
        if p.name not in keep:
            p.unlink(missing_ok=True)


def run_swellmap_world(out_dir: Path, now: datetime | None = None) -> int:
    """Fetch + publish the global layer. Returns the number of frames written.
    Never fatal: a total outage keeps the previous world.json serving."""
    cycle = pick_cycle(now or datetime.now(UTC))
    steps = tuple(range(0, HORIZON_H + 1, STEP_H))
    target = out_dir / "swellmap"
    world_dir = target / "world"

    with httpx.Client(timeout=120.0, follow_redirects=True) as client:

        def fetch_planes_at(cyc: datetime, step: int) -> tuple[dict, dict] | None:
            try:
                resp = client.get(world_filter_url(cyc, step))
            except httpx.HTTPError:
                return None
            time.sleep(REQUEST_GAP_S)
            if resp.status_code != 200 or not _is_grib(resp.content):
                return None
            return parse_grib_planes(resp.content)

        w_cycle, first = _resolve_cycle(cycle, fetch_planes_at, steps[0])
        if w_cycle != cycle:
            print(
                f"swellmap world: {cycle:%Y-%m-%dT%H}Z not on NOMADS yet - "
                f"falling back to {w_cycle:%Y-%m-%dT%H}Z"
            )

        def fetch_planes(step: int) -> tuple[dict, dict] | None:
            # steps[0] was already paid for by the probe above
            return first if step == steps[0] else fetch_planes_at(w_cycle, step)

        meta = build_world_frames(w_cycle, fetch_planes, steps, world_dir)
    return _write_world(target, world_dir, meta)


def _write_world(target: Path, world_dir: Path, meta: dict | None) -> int:
    """Publish world.json + prune the frames it no longer names. Returns frames written."""
    if meta is None:
        print("warn: swellmap world: no frames fetched - keeping previous files")
        return 0
    write_json_atomic(target / "world.json", meta)
    _prune_world_frames(world_dir, {f["png"] for f in meta["frames"]})
    print(f"swellmap world: {len(meta['frames'])} frames @ {meta['grid_deg']:g} deg")
    return len(meta["frames"])
