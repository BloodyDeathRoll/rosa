"""clarity.py: nearest clear pixel, cloud walk-back, and the once-a-day cache."""

import json
from datetime import date

import httpx
import numcodecs
import numpy as np

from rosa_pipeline import clarity


def _blosc(arr: np.ndarray) -> bytes:
    return numcodecs.Blosc().encode(np.ascontiguousarray(arr))


def _store(zsd_by_t: dict[int, float | None], lat: float, lon: float, n: int = 3):
    """A fake ARCO store: n days; day t has value zsd_by_t[t] one pixel off (lat, lon)
    or all fill (cloud). Counts chunk requests."""
    i, j = clarity._pixel(lat, lon)
    i += 1  # the clear pixel sits one cell north of the spot
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        rel = req.url.path.split("timeChunked.zarr/")[1]
        calls.append(rel)
        if rel == ".zmetadata":
            meta = {"metadata": {"ZSD/.zarray": {"shape": [n, 4320, 8640]}}}
            return httpx.Response(200, json=meta)
        if rel.startswith("time/"):
            days = np.full(clarity.TIME_CHUNK, np.nan, dtype="<f4")
            for t in range(n):
                days[t] = (date(2026, 9, 22 + t) - clarity.EPOCH).days
            return httpx.Response(200, content=_blosc(days))
        t, by, bx = (int(x) for x in rel.split("/")[1].split("."))
        arr = np.full(clarity.CHUNK, clarity.FILL, dtype="<f4")
        v = zsd_by_t.get(t)
        if v is not None and (by, bx) == (i // clarity.CHUNK[0], j // clarity.CHUNK[1]):
            arr[i % clarity.CHUNK[0], j % clarity.CHUNK[1]] = v
        return httpx.Response(200, content=_blosc(arr))

    return httpx.MockTransport(handler), calls


def test_takes_the_newest_clear_day_and_says_which(tmp_path):
    lat, lon = 38.68, -9.33
    transport, _ = _store({0: 4.0, 1: 5.0, 2: None}, lat, lon)  # newest day is cloud
    src = clarity.CmemsClaritySource(tmp_path, transport=transport, today=date(2026, 9, 26))
    assert src.fetch([(lat, lon)]) == [{"zsd_m": 5.0, "date": "2026-09-23"}]


def test_nothing_in_reach_is_none(tmp_path):
    transport, _ = _store({}, 38.68, -9.33)
    src = clarity.CmemsClaritySource(tmp_path, transport=transport, today=date(2026, 9, 26))
    assert src.fetch([(38.68, -9.33)]) == [None]


def test_second_cycle_of_the_day_reads_the_cache_not_the_store(tmp_path):
    lat, lon = 38.68, -9.33
    transport, calls = _store({2: 7.0}, lat, lon)
    today = date(2026, 9, 26)
    clarity.CmemsClaritySource(tmp_path, transport=transport, today=today).fetch([(lat, lon)])
    n = len(calls)
    again = clarity.CmemsClaritySource(tmp_path, transport=transport, today=today)
    assert again.fetch([(lat, lon)]) == [{"zsd_m": 7.0, "date": "2026-09-24"}]
    assert len(calls) == n  # zero requests


def test_a_failed_fetch_falls_back_to_the_newest_cached_day(tmp_path):
    (tmp_path / "2026-09-25.json").write_text(
        json.dumps({clarity._key(38.68, -9.33): {"zsd_m": 3.0, "date": "2026-09-23"}})
    )
    down = httpx.MockTransport(lambda r: httpx.Response(503))
    src = clarity.CmemsClaritySource(tmp_path, transport=down, today=date(2026, 9, 26))
    assert src.fetch([(38.68, -9.33)]) == [{"zsd_m": 3.0, "date": "2026-09-23"}]
