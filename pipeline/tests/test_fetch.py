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


def test_ensemble_that_will_not_attribute_degrades_instead_of_sinking_the_run(capsys):
    """Dream 2026-10-07: a 200 ensemble body that is not JSON, or whose location_id set is
    not 0..n-1, sat outside the degrade guard and sank the batch, marine + weather too."""
    for bad in (
        httpx.Response(200, text="<html>busy</html>"),
        httpx.Response(200, json=[{"location_id": 1}, {"location_id": 1}]),
    ):

        def handler(request: httpx.Request, bad=bad) -> httpx.Response:
            if _is_ensemble(request):
                return bad
            return httpx.Response(200, json=_body({"hourly": {"time": ["2026-07-24T00:00"]}}))

        raws = OpenMeteoSource(transport=httpx.MockTransport(handler)).fetch_many(COORDS)
        assert len(raws) == len(COORDS)
        assert all(r.ensemble is None for r in raws)
        assert all(r.weather["hourly"]["time"] == ["2026-07-24T00:00"] for r in raws)
        assert "horizon proxy only" in capsys.readouterr().err


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
        fetch.fetch_wind_many(COORDS, model="icon_seamless")
    finally:
        fetch.httpx.Client = orig  # type: ignore[attr-defined]
    assert seen == ["gfs_seamless", "icon_seamless"]


def _many_with(handler):
    """Route fetch_*_many's own httpx.Client through a MockTransport (the idiom above)."""
    with_mock = httpx.MockTransport(handler)
    orig = httpx.Client

    class _Client(orig):
        def __init__(self, *a, **kw):
            super().__init__(*a, transport=with_mock, **kw)

    return _Client, orig


def test_batch_bodies_must_be_the_locations_they_were_asked_for():
    """A multi-location response is attributed to buoys by list POSITION and feeds the
    append-only archive. Each body carries the coordinate it answers for: a grid-cell
    snap (well under MAX_GRID_SNAP_DEG) is accepted, a body that sits at another buoy's
    coordinate is refused, and a body with no coordinate (old captures) is let through."""
    coords = [(32.3817, 34.8035), (36.6, -122.0)]

    def body(lat, lon):
        return {"latitude": lat, "longitude": lon, "hourly": {"time": []}}

    def snapped(request):
        return httpx.Response(200, json=[body(32.375, 34.8125), body(36.625, -122.0)])

    def swapped(request):
        return httpx.Response(200, json=[body(36.625, -122.0), body(32.375, 34.8125)])

    def bare(request):
        return httpx.Response(200, json=[{"hourly": {"time": []}}, {"hourly": {"time": []}}])

    for handler, ok in ((snapped, True), (swapped, False), (bare, True)):
        client, orig = _many_with(handler)
        fetch.httpx.Client = client  # type: ignore[attr-defined]
        try:
            if ok:
                assert len(fetch.fetch_marine_waves_many(coords)) == 2
                assert len(fetch.fetch_wind_many(coords)) == 2
            else:
                with pytest.raises(ValueError, match="refusing to attribute it by position"):
                    fetch.fetch_marine_waves_many(coords)
                with pytest.raises(ValueError, match="refusing to attribute it by position"):
                    fetch.fetch_wind_many(coords)
        finally:
            fetch.httpx.Client = orig  # type: ignore[attr-defined]


def test_batch_bodies_are_attributed_by_location_id_not_position():
    """The registry holds buoys closer together than MAX_GRID_SNAP_DEG can tell apart
    (the SoCal Bight CDIP net, ~0.1 deg), so a swapped response between two of them
    passes the coordinate check. Open-Meteo's ``location_id`` (first body omits it) is
    the attribution: a swapped list is put back in request order, an id set that is not
    0..n-1 is refused, and a list with no ids at all is left alone."""
    coords = [(32.868, -117.267), (32.957, -117.279)]  # 46254 / 46266, 0.089 deg apart

    def body(lat, lon, **extra):
        return {"latitude": lat, "longitude": lon, "hourly": {"time": []}, **extra}

    def swapped(request):
        return httpx.Response(
            200,
            json=[body(32.958, -117.292, location_id=1), body(32.875, -117.292)],
        )

    def bad_ids(request):
        return httpx.Response(
            200,
            json=[body(32.875, -117.292, location_id=1), body(32.958, -117.292, location_id=1)],
        )

    client, orig = _many_with(swapped)
    fetch.httpx.Client = client  # type: ignore[attr-defined]
    try:
        for got in (fetch.fetch_marine_waves_many(coords), fetch.fetch_wind_many(coords)):
            assert [b["latitude"] for b in got] == [32.875, 32.958]
    finally:
        fetch.httpx.Client = orig  # type: ignore[attr-defined]

    client, orig = _many_with(bad_ids)
    fetch.httpx.Client = client  # type: ignore[attr-defined]
    try:
        with pytest.raises(ValueError, match="location_id set"):
            fetch.fetch_marine_waves_many(coords)
    finally:
        fetch.httpx.Client = orig  # type: ignore[attr-defined]

    no_ids = [body(1.0, 1.0), body(2.0, 2.0)]
    assert fetch._order_by_location_id(no_ids) is no_ids


def test_marine_429_still_raises(monkeypatch):
    """...and the retries it takes on the way are RECORDED, not served.

    "rate limit" is not JSON and names no bucket, so since 2026-08-31 the essential marine
    request is unclassifiable and `_retry_wait_s` lets the quota ledger arbitrate: with the
    day's budget unspent it waits `_MINUTE_RETRY_WAIT_S` before each of the two retries.
    That is 130 s of real `time.sleep` inside one unit test - two thirds of the whole
    suite's wall-clock - and nothing here ever asserted on it. Asserting on the waits
    instead pins the classification (the thing this test is about) and gives the seconds
    back."""
    waits: list[float] = []
    monkeypatch.setattr(fetch.time, "sleep", waits.append)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limit")

    src = OpenMeteoSource(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        src.fetch_many(COORDS)
    # two retries, both on the minutely-cap wait the ledger arbitration grants
    assert waits == [fetch._MINUTE_RETRY_WAIT_S, fetch._MINUTE_RETRY_WAIT_S]


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


# --- 429 classification beyond the vendor's exact wording (2026-08-31) --------------------


def test_retry_after_header_is_honored_on_a_429_whatever_the_body_says():
    """An explicit Retry-After is the server's own answer - it wins over the body text."""
    resp = httpx.Response(
        429, headers={"Retry-After": "7"}, json={"error": True, "reason": "brand new wording"}
    )
    assert fetch._retry_wait_s(resp, 0) == 7.0
    capped = httpx.Response(429, headers={"Retry-After": "9000"}, text="")
    assert fetch._retry_wait_s(capped, 0) == fetch._RETRY_AFTER_CAP_S


def test_unclassifiable_429_is_retried_once_when_the_ledger_has_room(monkeypatch):
    """No header, no readable reason: if today's budget still has room the daily bucket
    cannot be what tripped, so treat it as the minutely cap instead of reverting to the
    2026-08-28 dead-cycle mode the day Open-Meteo rewords its error body."""
    monkeypatch.setenv("ROSA_OM_DAILY_BUDGET", "9400")
    resp = httpx.Response(429, text="Too Many Requests")  # non-JSON body
    assert fetch._retry_wait_s(resp, 0) == fetch._MINUTE_RETRY_WAIT_S


def test_unclassifiable_429_is_not_retried_when_the_budget_is_spent(monkeypatch):
    monkeypatch.setenv("ROSA_OM_DAILY_BUDGET", "0")
    resp = httpx.Response(429, text="Too Many Requests")
    assert fetch._retry_wait_s(resp, 0) is None


def test_named_other_bucket_429_still_skips_the_ledger(monkeypatch):
    """A 429 that names a non-minutely bucket is never retried, budget or no budget -
    only the UNclassifiable case consults the ledger."""
    monkeypatch.setenv("ROSA_OM_DAILY_BUDGET", "9400")
    resp = httpx.Response(429, json={"error": True, "reason": "Hourly API request limit"})
    assert fetch._retry_wait_s(resp, 0) is None


def test_unclassifiable_429_from_an_unmetered_host_ignores_the_marine_ledger(monkeypatch):
    """The ledger meters the marine host only. A spent marine budget says nothing about the
    weather host's daily bucket (never booked there), so an unclassifiable weather 429 still
    gets its one minute wait - and a marine one is still refused."""
    monkeypatch.setenv("ROSA_OM_DAILY_BUDGET", "0")
    resp = httpx.Response(429, text="Too Many Requests")
    assert fetch._retry_wait_s(resp, 0, fetch.WEATHER_URL) == fetch._MINUTE_RETRY_WAIT_S
    assert fetch._retry_wait_s(resp, 0, fetch.MARINE_URL) is None


def test_wind_archive_asks_the_self_hosted_open_meteo_first(monkeypatch, capsys):
    """2026-10-08: the station/buoy wind archive rides the same self-hosted Open-Meteo as
    the weather leg; on any failure there it asks the public API, never failing on it."""
    coords = [(32.3817, 34.8035), (36.6, -122.0)]
    monkeypatch.setenv(fetch.WEATHER_URL_ENV, "http://127.0.0.1:8080/v1/forecast")
    hosts: list[str] = []

    def body(lat, lon):
        return {"latitude": lat, "longitude": lon, "hourly": {"time": []}}

    def up(request):
        hosts.append(request.url.host)
        return httpx.Response(200, json=[body(32.375, 34.8125), body(36.625, -122.0)])

    def down_here(request):
        hosts.append(request.url.host)
        if request.url.host == "127.0.0.1":
            return httpx.Response(503, text="starting")
        return httpx.Response(200, json=[body(32.375, 34.8125), body(36.625, -122.0)])

    for handler, want in ((up, ["127.0.0.1"]), (down_here, ["127.0.0.1", "api.open-meteo.com"])):
        hosts.clear()
        client, orig = _many_with(handler)
        fetch.httpx.Client = client  # type: ignore[attr-defined]
        try:
            assert len(fetch.fetch_wind_many(coords)) == 2
        finally:
            fetch.httpx.Client = orig  # type: ignore[attr-defined]
        assert hosts == want
    assert "self-hosted weather failed for 2 wind point(s)" in capsys.readouterr().err


# --- the marine API from the self-hosted Open-Meteo, off unless ROSA_MARINE_URL (2026-10-08) ---


def test_buoy_marine_batch_asks_the_self_hosted_copy_first(monkeypatch, capsys):
    """The archive's fleet request rides the self-hosted /v1/marine; a refusal OR a batch
    that will not attribute there falls back to marine-api.open-meteo.com, never fails."""
    coords = [(32.3817, 34.8035), (36.6, -122.0)]
    monkeypatch.setenv(fetch.MARINE_URL_ENV, "http://127.0.0.1:8080/v1/marine")
    hosts: list[str] = []

    def body(lat, lon):
        return {"latitude": lat, "longitude": lon, "hourly": {"time": []}}

    good = [body(32.375, 34.8125), body(36.625, -122.0)]
    swapped = [body(36.625, -122.0), body(32.375, 34.8125)]

    def make(local):
        def handler(request):
            hosts.append(request.url.host)
            return local if request.url.host == "127.0.0.1" else httpx.Response(200, json=good)

        return handler

    cases = (
        (httpx.Response(200, json=good), ["127.0.0.1"]),
        (httpx.Response(503, text="starting"), ["127.0.0.1", "marine-api.open-meteo.com"]),
        (httpx.Response(200, json=swapped), ["127.0.0.1", "marine-api.open-meteo.com"]),
    )
    for local, want in cases:
        hosts.clear()
        client, orig = _many_with(make(local))
        fetch.httpx.Client = client  # type: ignore[attr-defined]
        try:
            assert len(fetch.fetch_marine_waves_many(coords)) == 2
        finally:
            fetch.httpx.Client = orig  # type: ignore[attr-defined]
        assert hosts == want
    assert "self-hosted marine failed for 2 buoy(s)" in capsys.readouterr().err


def test_om_arm_marine_and_ensemble_ask_the_self_hosted_copy_first(monkeypatch, capsys):
    monkeypatch.setenv(fetch.MARINE_URL_ENV, "http://127.0.0.1:8080/v1/marine")
    seen: list[str] = []
    ok = _body({"hourly": {"time": ["2026-07-24T00:00"]}})

    def up(request):
        seen.append(request.url.host)
        return httpx.Response(200, json=ok)

    raws = OpenMeteoSource(transport=httpx.MockTransport(up)).fetch_many(COORDS)
    assert len(raws) == len(COORDS) and all(r.ensemble is not None for r in raws)
    # marine + ensemble from the box, weather from the weather host as before
    assert seen == ["127.0.0.1", "api.open-meteo.com", "127.0.0.1"]

    seen.clear()

    def down_here(request):
        seen.append(request.url.host)
        if request.url.host == "127.0.0.1":
            return httpx.Response(500, text="down")
        return httpx.Response(200, json=ok)

    raws = OpenMeteoSource(transport=httpx.MockTransport(down_here)).fetch_many(COORDS)
    assert len(raws) == len(COORDS)
    assert seen.count("marine-api.open-meteo.com") == 2  # marine + ensemble fell back
    assert "self-hosted marine failed for an om-arm batch" in capsys.readouterr().err


def test_marine_ignores_the_self_hosted_path_when_unset(monkeypatch):
    monkeypatch.delenv(fetch.MARINE_URL_ENV, raising=False)
    hosts: list[str] = []

    def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(200, json={"hourly": {"time": []}})

    client, orig = _many_with(handler)
    fetch.httpx.Client = client  # type: ignore[attr-defined]
    try:
        fetch.fetch_marine_waves(1.0, 1.0)
    finally:
        fetch.httpx.Client = orig  # type: ignore[attr-defined]
    assert hosts == ["marine-api.open-meteo.com"]
