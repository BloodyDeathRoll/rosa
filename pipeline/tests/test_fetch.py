"""Open-Meteo bills call weight (locations x variables x days) against hourly/daily buckets,
so a large run can be throttled mid-trio. Only the ensemble request is expendable."""

from __future__ import annotations

import httpx
import pytest

from rosa_pipeline import fetch
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


def test_weather_requests_name_the_published_wind_model():
    """The 10 m wind is GFS since 2026-08-30 (fetch.WEATHER_MODEL): the run's weather leg
    and the archive's wind batch both send `models=`, and the A/B member is a different
    model on request. A single model keeps the hourly keys unsuffixed."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(fetch.WEATHER_URL):
            seen.append(request.url.params.get("models", ""))
        return httpx.Response(200, json=_body({"hourly": {"time": ["2026-07-24T00:00"]}}))

    OpenMeteoSource(transport=httpx.MockTransport(handler)).fetch_many(COORDS)
    assert seen == ["gfs_seamless"]

    seen.clear()
    with_mock = httpx.MockTransport(handler)
    orig = httpx.Client

    class _Client(orig):
        def __init__(self, *a, **kw):
            super().__init__(*a, transport=with_mock, **kw)

    fetch.httpx.Client = _Client  # type: ignore[attr-defined]
    try:
        fetch.fetch_wind_many(COORDS)
        fetch.fetch_wind_many(COORDS, model=fetch.WEATHER_AB_MODEL)
    finally:
        fetch.httpx.Client = orig  # type: ignore[attr-defined]
    assert seen == ["gfs_seamless", "icon_seamless"]


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


def test_transient_transport_error_is_retried_not_fatal(capsys, monkeypatch):
    # 2026-08-15: four consecutive fleet captures died on one TLS handshake timeout
    # mid-run - a single transient must cost a retry, never the whole batch
    import rosa_pipeline.fetch as fetch_mod

    monkeypatch.setattr(fetch_mod.time, "sleep", lambda _s: None)  # no real backoff in tests
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


def test_transient_503_is_retried_not_fatal(capsys, monkeypatch):
    # 2026-08-16: a lone 503 on the last of five weather batches killed the 08:20Z cycle
    # after four minutes of successful paced fetching. A transient 5xx must cost a retry.
    import rosa_pipeline.fetch as fetch_mod

    monkeypatch.setattr(fetch_mod.time, "sleep", lambda _s: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="Service Unavailable")
        return httpx.Response(200, json=_body({"hourly": {"time": ["2026-08-16T00:00"]}}))

    src = OpenMeteoSource(transport=httpx.MockTransport(handler), sleep_between_batches_s=0)
    raws = src.fetch_many(COORDS)

    assert len(raws) == len(COORDS)
    assert "503" in capsys.readouterr().err


def test_persistent_503_still_raises(monkeypatch):
    """Bounded, not infinite - a host that is genuinely down must still fail the cycle."""
    import rosa_pipeline.fetch as fetch_mod

    monkeypatch.setattr(fetch_mod.time, "sleep", lambda _s: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    src = OpenMeteoSource(transport=httpx.MockTransport(handler), sleep_between_batches_s=0)
    with pytest.raises(httpx.HTTPStatusError):
        src.fetch_many(COORDS)


def test_minutely_429_on_an_essential_request_is_waited_out(monkeypatch):
    """The minutely cap reopens by itself, so the marine request waits rather than dying."""
    import rosa_pipeline.fetch as fetch_mod

    waits: list[float] = []
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: waits.append(s))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if _is_ensemble(request):
            return httpx.Response(200, json=_body({"hourly": {"time": ["2026-08-16T00:00"]}}))
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                json={"error": True, "reason": "Minutely API request limit exceeded."},
            )
        return httpx.Response(200, json=_body({"hourly": {"time": ["2026-08-16T00:00"]}}))

    src = OpenMeteoSource(transport=httpx.MockTransport(handler), sleep_between_batches_s=0)
    raws = src.fetch_many(COORDS)

    assert len(raws) == len(COORDS)
    assert waits == [fetch_mod._MINUTE_RETRY_WAIT_S]


def test_daily_quota_429_is_not_waited_out(monkeypatch):
    """The daily bucket does not reopen until 00:00Z - the quota guard owns this, not a retry."""
    import rosa_pipeline.fetch as fetch_mod

    waits: list[float] = []
    monkeypatch.setattr(fetch_mod.time, "sleep", lambda s: waits.append(s))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": True, "reason": "Daily API request limit exceeded."}
        )

    src = OpenMeteoSource(transport=httpx.MockTransport(handler), sleep_between_batches_s=0)
    with pytest.raises(httpx.HTTPStatusError):
        src.fetch_many(COORDS)
    assert waits == []


def test_minutely_429_is_retried_when_asked() -> None:
    """The aux legs of the blend fetch pass retry_429=True: a minutely-cap 429 (which
    reopens by itself) must be waited out and retried, not returned to raise_for_status -
    it killed the 2026-08-27T20:20Z and 2026-08-28T02:20Z cycles at 624 spots."""
    calls = {"n": 0}

    class _Resp:
        def __init__(self, status: int, reason: str = "") -> None:
            self.status_code = status
            self._reason = reason

        def json(self) -> dict:
            return {"reason": self._reason}

    class _Client:
        def get(self, url: str, params: dict) -> _Resp:
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(429, "Minutely API request limit exceeded")
            return _Resp(200)

    from unittest.mock import patch

    with patch("rosa_pipeline.fetch.time.sleep") as slept:
        resp = fetch.retrying_get(_Client(), "http://x", {}, retry_429=True)  # type: ignore[arg-type]
    assert resp.status_code == 200 and calls["n"] == 2
    assert slept.called  # waited out the minute bucket rather than hammering
