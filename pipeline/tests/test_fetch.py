"""Open-Meteo bills call weight (locations x variables x days) against hourly/daily buckets,
so a large run can be throttled mid-trio. Only the ensemble request is expendable."""

from __future__ import annotations

import httpx
import pytest

from rosa_pipeline.fetch import MARINE_BATCH_SIZE, MARINE_URL, OpenMeteoSource

COORDS = [(32.38, 34.80), (9.61, -84.63)]


def _is_ensemble(request: httpx.Request) -> bool:
    """The ensemble hits the marine URL too - it asks for the 3 ensemble variables only."""
    return str(request.url).startswith(MARINE_URL) and "wave_peak_period" not in str(request.url)


def _body(payload: dict) -> list[dict]:
    return [payload for _ in COORDS]


def test_ensemble_429_degrades_instead_of_sinking_the_run(capsys):
    def handler(request: httpx.Request) -> httpx.Response:
        if _is_ensemble(request):
            return httpx.Response(429, text="rate limit")
        return httpx.Response(200, json=_body({"hourly": {"time": ["2026-07-24T00:00"]}}))

    raws = OpenMeteoSource(transport=httpx.MockTransport(handler)).fetch_many(COORDS)

    assert len(raws) == len(COORDS)
    assert all(r.ensemble is None for r in raws)
    assert all(r.marine["hourly"]["time"] == ["2026-07-24T00:00"] for r in raws)
    assert all(r.weather["hourly"]["time"] == ["2026-07-24T00:00"] for r in raws)
    assert "429" in capsys.readouterr().err


def test_marine_429_still_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limit")

    src = OpenMeteoSource(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        src.fetch_many(COORDS)


def test_ensemble_kept_when_the_request_succeeds():
    def handler(request: httpx.Request) -> httpx.Response:
        tag = "ens" if _is_ensemble(request) else "main"
        return httpx.Response(
            200, json=_body({"hourly": {"time": ["2026-07-24T00:00"], "tag": tag}})
        )

    raws = OpenMeteoSource(transport=httpx.MockTransport(handler)).fetch_many(COORDS)

    assert all(r.ensemble["hourly"]["tag"] == "ens" for r in raws)


def test_over_cap_coords_split_into_batches_and_lose_no_point():
    """>MARINE_BATCH_SIZE points must chunk so no batch exceeds the marine host's minute cap,
    while every point still comes back in order."""
    coords = [(float(i), float(-i)) for i in range(MARINE_BATCH_SIZE + 50)]
    marine_request_sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        n = len(request.url.params["latitude"].split(","))
        if str(request.url).startswith(MARINE_URL) and not _is_ensemble(request):
            marine_request_sizes.append(n)
        body = [{"hourly": {"time": ["2026-07-24T00:00"]}} for _ in range(n)]
        return httpx.Response(200, json=body)

    raws = OpenMeteoSource(
        transport=httpx.MockTransport(handler), sleep_between_batches_s=0
    ).fetch_many(coords)

    assert len(raws) == len(coords)
    assert marine_request_sizes == [MARINE_BATCH_SIZE, 50]


def test_transient_transport_error_is_retried_not_fatal(capsys):
    # 2026-08-15: four consecutive fleet captures died on one TLS handshake timeout
    # mid-run - a single transient must cost a retry, never the whole batch
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("handshake timed out", request=request)
        return httpx.Response(200, json=_body({"hourly": {"time": ["2026-08-15T00:00"]}}))

    src = OpenMeteoSource(transport=httpx.MockTransport(handler), sleep_between_batches_s=0)
    raws = src.fetch_many(COORDS)
    assert len(raws) == len(COORDS)
    assert "transport error" in capsys.readouterr().err
