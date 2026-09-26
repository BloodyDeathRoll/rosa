"""Water clarity: satellite Secchi depth at every spot, once a day (docs/WATER-SOURCES.md).

Source: CMEMS GlobColour ``OCEANCOLOUR_GLO_BGC_L3_NRT_009_101``, dataset
``cmems_obs-oc_glo_bgc-transp_nrt_l3-multi-4km_P1D``, variable ``ZSD`` - Secchi disk depth
in metres, the depth a white disk stays visible from the surface, i.e. how far down you
can see. Daily, 4 km, global, about 2 days behind (measured 2026-09-26: latest day
2026-09-24). A measurement, not a forecast: it is display only and nothing scores on it.

Clouds hide the sea on any given day, so each spot takes its latest clear pixel from the
last ``MAX_LAG_DAYS`` days and the payload says which day that was. Near the shore the
4 km pixels are often masked (land, glint, shallow bottom), so the nearest valid pixel
within ``REACH_PX`` cells is taken - a reading for the water off the beach, not at it.

Cost: the satellite updates once a day, so the result is cached per UTC day in
``cache_dir/<YYYY-MM-DD>.json``; the first cycle of the day samples the store and the
other three read the file. Raw chunks are cached by day under ``cache_dir/chunks/`` so a
new day fetches only that day's chunks. A failed fetch falls back to the newest cached
day, which the published ``date`` makes honest.

Access and licence: the ARCO Zarr store on CloudFerro reads anonymously over HTTP, the
same route ``sdb.py`` uses (convenient rather than guaranteed - the documented route is
the ``copernicusmarine`` toolbox with a free account). Copernicus Marine Service licence:
commercial use and redistribution allowed, attribution REQUIRED (``ATTRIBUTION``), free of
charge to 2028-06-30 - re-verify before then.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from .geo import dlon180

ZARR_URL = (
    "https://s3.waw3-1.cloudferro.com/mdl-arco-time-043/arco/"
    "OCEANCOLOUR_GLO_BGC_L3_NRT_009_101/"
    "cmems_obs-oc_glo_bgc-transp_nrt_l3-multi-4km_P1D_202311/timeChunked.zarr"
)
ATTRIBUTION = (
    "Water clarity: E.U. Copernicus Marine Service Information; https://doi.org/10.48670/moi-00278"
)
VAR = "ZSD"
# Grid geometry, read off the store's .zmetadata 2026-09-26: pixel centres, lat ascending
# from the south pole, 1/24 deg (~4.6 km) steps; chunks are one day x 512 x 1024.
STEP_DEG = 1.0 / 24.0
LAT0 = -90.0 + STEP_DEG / 2.0
LON0 = -180.0 + STEP_DEG / 2.0
GRID = (4320, 8640)
CHUNK = (512, 1024)
TIME_CHUNK = 15
EPOCH = date(1900, 1, 1)  # time axis: days since
FILL = -999.0
MAX_LAG_DAYS = 7
REACH_PX = 3  # ~14 km: the nearest clear pixel off the beach, no further


class ClaritySource(Protocol):
    def fetch(self, points: list[tuple[float, float]]) -> list[dict | None]: ...


def _key(lat: float, lon: float) -> str:
    return f"{lat:.4f},{lon:.4f}"


def _pixel(lat: float, lon: float) -> tuple[int, int]:
    i = round((lat - LAT0) / STEP_DEG)
    j = round((lon - LON0) / STEP_DEG) % GRID[1]
    return i, j


def nearest_valid(get_chunk, lat: float, lon: float, reach: int = REACH_PX) -> float | None:
    """Value of the nearest non-fill pixel within ``reach`` cells (cos-lat weighted), or
    None. ``get_chunk(by, bx)`` returns a CHUNK-shaped array or None (no data there)."""
    ci, cj = _pixel(lat, lon)
    best: tuple[float, float] | None = None
    coslat = math.cos(math.radians(lat))
    for i in range(ci - reach, ci + reach + 1):
        if not 0 <= i < GRID[0]:
            continue
        for jj in range(cj - reach, cj + reach + 1):
            j = jj % GRID[1]  # longitude wraps
            arr = get_chunk(i // CHUNK[0], j // CHUNK[1])
            if arr is None:
                continue
            v = float(arr[i % CHUNK[0], j % CHUNK[1]])
            if not math.isfinite(v) or v <= FILL + 1 or v < 0:
                continue
            plat = LAT0 + i * STEP_DEG
            plon = LON0 + j * STEP_DEG
            d2 = (plat - lat) ** 2 + (coslat * float(dlon180(plon, lon))) ** 2
            if best is None or d2 < best[0]:
                best = (d2, v)
    return None if best is None else best[1]


class CmemsClaritySource:
    """Live store read with a per-day result cache (see module docstring)."""

    def __init__(
        self,
        cache_dir: Path,
        base_url: str = ZARR_URL,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
        today: date | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport
        self._today = today
        self._client: httpx.Client | None = None
        self._chunks: dict[tuple[int, int, int], object] = {}

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_s, transport=self._transport)
        return self._client

    def _decode(self, raw: bytes, dtype: str, shape: tuple[int, ...] | None):
        import numcodecs
        import numpy as np

        arr = np.frombuffer(numcodecs.Blosc().decode(raw), dtype=dtype)
        return arr if shape is None else arr.reshape(shape)

    def _get(self, rel: str) -> bytes | None:
        resp = self._http().get(f"{self.base_url}/{rel}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content

    def _latest_days(self) -> list[tuple[int, date]]:
        """(time index, day) for the store's last MAX_LAG_DAYS days, newest first."""
        meta = json.loads(self._get(".zmetadata") or b"{}")["metadata"]
        n = int(meta[f"{VAR}/.zarray"]["shape"][0])
        out: list[tuple[int, date]] = []
        cache: dict[int, object] = {}
        for t in range(n - 1, max(-1, n - 1 - MAX_LAG_DAYS), -1):
            c = t // TIME_CHUNK
            if c not in cache:
                raw = self._get(f"time/{c}")
                cache[c] = self._decode(raw, "<f4", None) if raw else None
            arr = cache[c]
            if arr is None:
                continue
            v = float(arr[t % TIME_CHUNK])
            if math.isfinite(v):
                out.append((t, EPOCH + timedelta(days=int(v))))
        return out

    def _chunk(self, t: int, by: int, bx: int):
        key = (t, by, bx)
        if key in self._chunks:
            return self._chunks[key]
        path = self.cache_dir / "chunks" / str(t) / f"{by}.{bx}"
        if path.exists():
            raw = path.read_bytes() or None
        else:
            raw = self._get(f"{VAR}/{t}.{by}.{bx}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw or b"")
        arr = self._decode(raw, "<f4", CHUNK) if raw else None
        self._chunks[key] = arr
        return arr

    def _prune(self, keep: set[int]) -> None:
        root = self.cache_dir / "chunks"
        if not root.exists():
            return
        for d in root.iterdir():
            if d.is_dir() and d.name.isdigit() and int(d.name) not in keep:
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()

    def _sample(self, points: list[tuple[float, float]]) -> dict[str, dict | None]:
        days = self._latest_days()
        out: dict[str, dict | None] = {}
        for lat, lon in points:
            found = None
            for t, day in days:
                v = nearest_valid(lambda by, bx, t=t: self._chunk(t, by, bx), lat, lon)
                if v is not None:
                    found = {"zsd_m": round(v, 1), "date": day.isoformat()}
                    break
            out[_key(lat, lon)] = found
        self._prune({t for t, _ in days})
        return out

    def fetch(self, points: list[tuple[float, float]]) -> list[dict | None]:
        if not points:
            return []
        today = self._today or datetime.now(UTC).date()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / f"{today.isoformat()}.json"
        cached: dict[str, dict | None] = {}
        if path.exists():
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                cached = {}
        missing = [p for p in points if _key(*p) not in cached]
        if missing:
            try:
                cached.update(self._sample(missing))
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(cached, separators=(",", ":")), encoding="utf-8")
                tmp.replace(path)
            except Exception as e:
                print(
                    f"warn: clarity fetch failed ({e!r}) - using the newest cache",
                    file=sys.stderr,
                )
                cached = {**self._newest_cache(before=today), **cached}
            finally:
                if self._client is not None:
                    self._client.close()
                    self._client = None
        return [cached.get(_key(*p)) for p in points]

    def _newest_cache(self, before: date) -> dict[str, dict | None]:
        for back in range(1, MAX_LAG_DAYS + 1):
            p = self.cache_dir / f"{(before - timedelta(days=back)).isoformat()}.json"
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except ValueError:
                    continue
        return {}


class ClarityFixtureSource:
    """Offline replay: ``clarity.json`` in the fixtures dir, keyed like the day cache."""

    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, points: list[tuple[float, float]]) -> list[dict | None]:
        path = self.fixtures_dir / "clarity.json"
        if not path.exists():
            return [None] * len(points)
        data = json.loads(path.read_text(encoding="utf-8"))
        return [data.get(_key(*p)) for p in points]
