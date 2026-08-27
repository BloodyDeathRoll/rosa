"""ICESat-2 ATL24 - measured seafloor, used to GRADE a bathymetry source. Reports, never applies.

ATL24 (NSIDC, DOI 10.5067/ATLAS/ATL24.001) is NASA's classified photon bathymetry: ICESat-2's
green laser reaches the seafloor in clear water, and ATL24 publishes the refraction-corrected
depth of every photon it classified as bottom return. ~11 m footprint, ~40 m depth ceiling,
CC0 with citation requested - the cleanest licence of anything in this area.

**This is a harness, not a data source, and the distinction is the whole point.** ICESat-2
flies a 91-day exact-repeat orbit, so its coverage is a fixed set of narrow ground tracks: over
the Male atolls the nearest bathymetry photon sits 0.9-4.0 km from most named breaks, and there
is no gridded ATL24 derivative. It can never fill a spot's ray. What it CAN do is settle which
of two disagreeing grids is telling the truth about the nearshore, which is exactly the open
question in docs/OPEN-ITEMS.md items 17 and 23.

So this module scores; it does not write profiles. Same discipline as ``horizon`` and the cam
tools (CLAUDE.md standing prohibitions): it reports, a human reads it, and any change to the
committed DB is a separate, deliberate step with its own A/B.

Access: SlideRule Earth (https://slideruleearth.io) serves ATL24 subsets with **no
authentication**, which is why this needs no Earthdata login. It answers in SlideRule's own
record framing - a length-prefixed stream whose payload is a Parquet file - and this module
parses that framing directly rather than taking the 400 MB ``sliderule`` client (which pulls
geopandas/shapely/pyarrow) into the pipeline. ``pyarrow`` is a DEV dependency only: the cron
forecast path never imports this module.
"""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path

import httpx

from .bathymetry import DepthProfile

SLIDERULE_ATL24_URL = "https://sliderule.slideruleearth.io/source/atl24x"
CITATION = "ICESat-2 ATL24 (NASA/NSIDC, doi:10.5067/ATLAS/ATL24.001), subset via SlideRule Earth"

# SlideRule frames every record as: version(u16) type-name-length(u16) payload-length(u32),
# then the NUL-terminated type name, then the payload. Verified against a live response
# 2026-08-27: 254 `exceptrec` progress records, one `arrowrec.meta`, one `arrowrec.data`.
_REC_HEADER = ">HHI"
_REC_VERSION = 2
_PARQUET_MAGIC = b"PAR1"
# Each arrowrec.data payload opens with a fixed 128-byte preamble before its slice of the
# Parquet file. Measured against live responses 2026-08-27, single- and multi-record alike.
_ARROW_PREAMBLE = 128


@dataclass(frozen=True, slots=True)
class Photon:
    """One classified seafloor return. ``depth_m`` is positive down, like DepthSample."""

    lat: float
    lon: float
    depth_m: float


@dataclass(frozen=True, slots=True)
class Score:
    """How well one depth source matches the lidar. Bias is signed ON PURPOSE.

    CALIBRATION.md's first method rule: a skill metric that cannot show sign cannot show a
    bias. ``bias_m`` > 0 means the source reads DEEPER than the lidar.
    """

    source: str
    n: int
    bias_m: float
    mae_m: float
    rmse_m: float
    worse_than_5m: int

    def as_row(self) -> str:
        pct = 100.0 * self.worse_than_5m / self.n if self.n else 0.0
        return (
            f"{self.source:28s} n={self.n:6d}  bias {self.bias_m:+7.2f}  "
            f"mae {self.mae_m:6.2f}  rmse {self.rmse_m:6.2f}  |err|>5 m {pct:5.1f}%"
        )


# -- fetch --------------------------------------------------------------------------------


class TruncatedStream(ValueError):
    """The response ended mid-record. A 20 MB ATL24 answer is one long HTTP body and it does
    get cut short; the declared payload length then overruns the data. Worth its own type
    because the fix is to ask again, not to give up on the box - and because silently
    keeping the short payload would hand pyarrow a headless Parquet file and blame the
    schema for a network problem."""


def _split_records(blob: bytes) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    off = 0
    while off + 8 <= len(blob):
        version, type_len, payload_len = struct.unpack_from(_REC_HEADER, blob, off)
        if version != _REC_VERSION:
            raise ValueError(f"SlideRule record version {version} at byte {off}, expected 2")
        name = blob[off + 8 : off + 8 + type_len].split(b"\0")[0].decode()
        start = off + 8 + type_len
        end = start + payload_len
        if end > len(blob):
            raise TruncatedStream(
                f"record {name!r} declares {payload_len} bytes but only "
                f"{len(blob) - start} arrived ({len(blob)} bytes total)"
            )
        out.append((name, blob[start:end]))
        off = end
    return out


def _messages(blob: bytes) -> list[str]:
    """SlideRule's own progress/error lines. When a request comes back empty these say why,
    so they are surfaced rather than swallowed behind a generic parse failure."""
    out: list[str] = []
    for name, payload in _split_records(blob):
        if name == "exceptrec":
            out.append(payload[8:].split(b"\0")[0].decode(errors="replace"))
    return out


def _parquet_blob(blob: bytes) -> bytes | None:
    """The single Parquet file the stream carries, or None when the tile had no photons.

    SlideRule caps an ``arrowrec.data`` payload at 32 MiB and splits ONE Parquet file
    across as many records as it needs - the Maldivian north took four, 129 MB in total.
    Each payload opens with a 128-byte preamble; the file is the concatenation of what
    follows. Treating each record as a complete file (the obvious reading, and the first
    one written here) fails on exactly the boxes worth measuring: the middle records carry
    no PAR1 at all, so they look "empty", and the first looks corrupt.

    A tile with no photons yields either no ``arrowrec.data`` at all or preamble-only
    records. Over a country-sized box most tiles are empty - ICESat-2 flies fixed repeat
    tracks - so that must return None, not raise.
    """
    parts = [payload for name, payload in _split_records(blob) if name == "arrowrec.data"]
    if not parts:
        return None
    joined = b"".join(p[_ARROW_PREAMBLE:] for p in parts)
    if not joined:
        return None
    if not (joined.startswith(_PARQUET_MAGIC) and joined.endswith(_PARQUET_MAGIC)):
        raise ValueError(
            f"reassembled {len(parts)} arrowrec.data record(s) into {len(joined)} bytes that "
            "are not a Parquet file (expected PAR1 at both ends) - corrupt, not empty"
        )
    return joined


def _fetch_box(
    south: float,
    west: float,
    north: float,
    east: float,
    timeout_s: float,
    transport: httpx.BaseTransport | None,
    attempts: int = 3,
) -> tuple[list[Photon], list[str]]:
    body = {
        "parms": {
            "poly": [
                {"lat": south, "lon": west},
                {"lat": south, "lon": east},
                {"lat": north, "lon": east},
                {"lat": north, "lon": west},
                {"lat": south, "lon": west},
            ],
            "srt": -1,  # dynamic surface type; ATL24 is bathymetry-classified already
        }
    }
    last: TruncatedStream | None = None
    with httpx.Client(timeout=timeout_s, transport=transport) as client:
        for _ in range(attempts):
            resp = client.post(SLIDERULE_ATL24_URL, json=body)
            resp.raise_for_status()
            blob = resp.content
            try:
                parquet = _parquet_blob(blob)
                photons: list[Photon] = [] if parquet is None else _parse_parquet(parquet)
            except TruncatedStream as e:
                last = e
                continue
            return photons, _messages(blob)
    raise last  # every attempt came back short - that is worth failing on


def fetch_photons(
    south: float,
    west: float,
    north: float,
    east: float,
    cache: Path | None = None,
    timeout_s: float = 600.0,
    transport: httpx.BaseTransport | None = None,
    max_depth: int = 4,
    on_note=None,
) -> list[Photon]:
    """Every ATL24 seafloor photon in the box. Slow (tens of seconds) - cache it.

    SlideRule refuses a request that would touch more than 300 ATL24 granules, and a box
    the length of the Maldives needs 341. Rather than make the caller pre-tile, split the
    box in half on its long axis and recurse - the refusal is a documented server limit
    with a machine-readable message, not an outage, so retrying the same box is pointless.
    """
    if cache is not None and cache.exists():
        return [Photon(*row) for row in json.loads(cache.read_text(encoding="utf-8"))]

    def note(msg: str) -> None:
        if on_note is not None:
            on_note(msg)

    def gather(s: float, w: float, n: float, e: float, depth: int) -> list[Photon]:
        photons, msgs = _fetch_box(s, w, n, e, timeout_s, transport)
        too_many = [m for m in msgs if "exceeded maximum allowed" in m]
        if photons or not too_many:
            if not photons and msgs:
                note(msgs[-1])
            return photons
        if depth >= max_depth:
            note(f"{msgs[-1]} - and the box is already split {max_depth} deep; giving up")
            return []
        if (n - s) >= (e - w):
            mid = 0.5 * (n + s)
            note(f"box {s:.2f}..{n:.2f} lat is too large for one request; splitting at {mid:.2f}")
            return gather(s, w, mid, e, depth + 1) + gather(mid, w, n, e, depth + 1)
        mid = 0.5 * (e + w)
        note(f"box {w:.2f}..{e:.2f} lon is too large for one request; splitting at {mid:.2f}")
        return gather(s, w, n, mid, depth + 1) + gather(s, mid, n, e, depth + 1)

    photons = gather(south, west, north, east, 0)
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps([[p.lat, p.lon, p.depth_m] for p in photons], separators=(",", ":")),
            encoding="utf-8",
        )
    return photons


CLASS_BATHYMETRY = 40  # ATL24 class_ph value for a classified seafloor return


def _wkb_point(blob: bytes) -> tuple[float, float]:
    """(lon, lat) from a WKB point. SlideRule returns geometry as WKB, not x/y columns."""
    little = blob[0] == 1
    fmt = "<I" if little else ">I"
    geom_type = struct.unpack_from(fmt, blob, 1)[0]
    if geom_type != 1:
        raise ValueError(f"expected a WKB point (type 1), got type {geom_type}")
    return struct.unpack_from("<dd" if little else ">dd", blob, 5)


def _parse_parquet(data: bytes) -> list[Photon]:
    """pyarrow is a dev dependency: the forecast path never reaches this module.

    Schema verified against a live response 2026-08-27. Coordinates arrive as WKB in
    ``geometry`` (there are no x/y columns), and ``ortho_h`` is the refraction-corrected
    seafloor height above the geoid - negative under water, so depth is its negation.
    """
    import io

    import pyarrow.parquet as pq

    table = pq.read_table(io.BytesIO(data))
    names = set(table.column_names)
    for required in ("geometry", "ortho_h"):
        if required not in names:
            raise ValueError(f"ATL24 response is missing {required!r}: {sorted(names)}")
    geoms = table.column("geometry").to_pylist()
    hs = table.column("ortho_h").to_pylist()
    classes = (
        table.column("class_ph").to_pylist()
        if "class_ph" in names
        else [CLASS_BATHYMETRY] * len(hs)
    )
    out: list[Photon] = []
    for geom, h, cls in zip(geoms, hs, classes, strict=True):
        if cls != CLASS_BATHYMETRY or h is None or not math.isfinite(h) or h >= 0:
            continue  # keep classified seafloor returns that are actually under water
        lon, lat = _wkb_point(bytes(geom))
        out.append(Photon(lat, lon, -float(h)))
    return out


# -- score --------------------------------------------------------------------------------


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class PhotonIndex:
    """Photons bucketed into a lat/lon grid so a lookup touches 9 cells, not 5 million.

    ATL24 returns millions of photons for a country-sized box (5,068,562 for the Maldives),
    and a ray-point query is a small radius. Scanning the whole list per point is
    O(points x photons) - about 2e9 haversine calls in pure Python for one region, which
    does not finish. The cell is sized to the search radius, so the 3x3 neighbourhood is
    guaranteed to contain every photon within it.
    """

    def __init__(self, photons: list[Photon], radius_m: float) -> None:
        self.radius_m = radius_m
        # a degree of latitude is ~111.32 km everywhere; longitude shrinks with cos(lat),
        # so sizing the cell in latitude degrees keeps it >= the radius in both axes
        self.cell_deg = max(radius_m / 111_320.0, 1e-6)
        self.buckets: dict[tuple[int, int], list[Photon]] = {}
        for p in photons:
            self.buckets.setdefault(self._key(p.lat, p.lon), []).append(p)

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return (math.floor(lat / self.cell_deg), math.floor(lon / self.cell_deg))

    def near(self, lat: float, lon: float) -> list[Photon]:
        i, j = self._key(lat, lon)
        # longitude cells are narrower than the radius away from the equator, so widen the
        # search in x by 1/cos(lat) - at 60 deg that is 2 cells, at the equator 1
        span = max(1, math.ceil(1.0 / max(math.cos(math.radians(lat)), 1e-6)))
        out: list[Photon] = []
        for di in (-1, 0, 1):
            for dj in range(-span, span + 1):
                for p in self.buckets.get((i + di, j + dj), ()):
                    if _haversine_m(lat, lon, p.lat, p.lon) <= self.radius_m:
                        out.append(p)
        return out


def pair(
    points: list[tuple[float, float, float]],
    photons: list[Photon] | PhotonIndex,
    radius_m: float = 150.0,
) -> list[tuple[float, float]]:
    """(source depth, lidar depth) for each point with a photon inside ``radius_m``.

    The lidar side is the MEDIAN of every photon in range, not the nearest one: a single
    ICESat-2 photon carries real per-photon noise, and a source is being graded on the
    seabed, not on one return.

    Pass a ``PhotonIndex`` when scoring more than a handful of points - building it once
    and reusing it is the difference between seconds and hours over a whole region.
    """
    index = photons if isinstance(photons, PhotonIndex) else PhotonIndex(photons, radius_m)
    out: list[tuple[float, float]] = []
    for lat, lon, depth in points:
        if not math.isfinite(depth):
            continue
        near = sorted(p.depth_m for p in index.near(lat, lon))
        if not near:
            continue
        mid = len(near) // 2
        lidar = near[mid] if len(near) % 2 else 0.5 * (near[mid - 1] + near[mid])
        out.append((depth, lidar))
    return out


def score(source: str, pairs: list[tuple[float, float]]) -> Score:
    if not pairs:
        return Score(source, 0, float("nan"), float("nan"), float("nan"), 0)
    errs = [a - b for a, b in pairs]
    n = len(errs)
    return Score(
        source=source,
        n=n,
        bias_m=sum(errs) / n,
        mae_m=sum(abs(e) for e in errs) / n,
        rmse_m=math.sqrt(sum(e * e for e in errs) / n),
        worse_than_5m=sum(1 for e in errs if abs(e) > 5.0),
    )


def profile_points(profile: DepthProfile) -> list[tuple[float, float, float]]:
    """(lat, lon, depth_m) for every sample the source actually produced.

    Deliberately NOT filtered to ATL24's ~40 m ceiling. Dropping the source's deep readings
    would throw away precisely the errors this harness exists to find - a GEBCO sample of
    280 m where the lidar sees 5 m is the finding, and a depth filter would silently hide
    it and hand GEBCO a flattering score. ``pair`` does the limiting instead, by keeping
    only points where the lidar has something to say.
    """
    return [(s.lat, s.lon, s.depth_m) for s in profile.samples if math.isfinite(s.depth_m)]
