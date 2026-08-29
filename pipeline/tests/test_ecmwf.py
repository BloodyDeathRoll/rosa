"""Stage 3b - ECMWF open-data wave member: cycle picking, index parsing, range
coalescing, GRIB parsing, replay, and the archive/verify wiring.

Both fixtures are REAL captures (2026-07-22 00z step 0): ``wave-fc.index`` is the full
13-param index, ``ecmwf_f000.grib2`` is the swh + pp1d + mp2 + mwp + h1012 messages
(4.4 MB, byte-ranged; mwd deliberately absent) - parsing runs fully offline against
real global masked fields."""

from __future__ import annotations

import shutil
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rosa_pipeline.ecmwf import (
    DEFAULT_PARAMS,
    EcmwfFixtureSource,
    EcmwfSource,
    coalesce,
    data_url,
    index_url,
    parse_grib_points,
    parse_index,
    pick_cycle,
)

FIXTURES = Path(__file__).parent / "fixtures" / "ecmwf"
GRIB = FIXTURES / "ecmwf_f000.grib2"
INDEX = FIXTURES / "wave-fc.index"
# open water off the Israeli coast / deep inland (E Syria) - no wet node within reach
SEA_POINT = (32.2, 34.55)
LAND_POINT = (33.0, 36.9)


def test_pick_cycle_uses_only_full_horizon_cycles() -> None:
    # 10:00Z: 00z (10 h old, fully published) is the pick - 06z never qualifies
    assert pick_cycle(datetime(2026, 7, 23, 10, 0, tzinfo=UTC)).hour == 0
    # 22:00Z: 12z is 10 h old → ready
    assert pick_cycle(datetime(2026, 7, 23, 22, 0, tzinfo=UTC)).hour == 12
    # 08:00Z: 00z is only 8 h old → fall back to yesterday's 12z
    c = pick_cycle(datetime(2026, 7, 23, 8, 0, tzinfo=UTC))
    assert (c.day, c.hour) == (22, 12)


def test_urls_shape() -> None:
    cycle = datetime(2026, 7, 22, 0, tzinfo=UTC)
    assert index_url(cycle, 0) == (
        "https://data.ecmwf.int/forecasts/20260722/00z/ifs/0p25/wave/"
        "20260722000000-0h-wave-fc.index"
    )
    assert data_url(cycle, 144).endswith("/20260722000000-144h-wave-fc.grib2")


def test_parse_index_and_coalesce_single_range() -> None:
    """Our 11 params sit nearly contiguous in the file - the ~0.5 MB wmb gap is bridged,
    the trailing cdww is excluded, and the whole step is ONE range request."""
    spans = parse_index(INDEX.read_text(encoding="utf-8"), DEFAULT_PARAMS)
    assert len(spans) == 11
    ranges = coalesce(spans)
    assert len(ranges) == 1
    start, end = ranges[0]
    assert start == 0  # h1012 is the first message
    assert end == 8771155 + 909494 - 1  # ...through the end of mwp, before cdww


def test_coalesce_splits_on_large_gaps() -> None:
    assert coalesce([(0, 10), (2_000_000, 10)]) == [(0, 9), (2_000_000, 2_000_009)]


def test_parse_grib_points_sea_land_and_missing_params() -> None:
    valid = datetime(2026, 7, 22, 0, tzinfo=UTC)
    sea, land = parse_grib_points(GRIB.read_bytes(), [SEA_POINT, LAND_POINT], valid)
    assert sea is not None
    assert sea.time == valid
    # summer Med windsea: modest height, short periods, Tp >= Tm-1,0 >= Tm02
    assert sea.swh is not None and 0.0 < sea.swh < 5.0
    assert sea.mwp is not None and 0.0 < sea.mwp < 10.0
    assert sea.mp2 is not None and sea.pp1d is not None
    assert sea.pp1d >= sea.mwp >= sea.mp2
    # h1012 present (near-zero - no 10-12 s energy in the summer Med)
    bands = dict(sea.bands)
    assert "h1012" in bands and 0.0 <= bands["h1012"] < 0.5
    # a param not in the fixture bytes (mwd) is honestly None, not fabricated
    assert sea.mwd is None
    assert land is None  # no wet node within reach


def test_consistency_on_real_windsea_reads_lully() -> None:
    """Smoke the proxy on real fields: a short-period summer Med windsea must score in
    the broad/lully half, never as clean groundswell."""
    from rosa_pipeline.spectral import consistency_score

    valid = datetime(2026, 7, 22, 0, tzinfo=UTC)
    (sea,) = parse_grib_points(GRIB.read_bytes(), [SEA_POINT], valid)
    assert sea is not None
    score = consistency_score(sea)
    assert score is not None and 0 <= score <= 60


def test_fixture_source_replays_steps(tmp_path) -> None:
    shutil.copy(GRIB, tmp_path / "ecmwf_f000.grib2")
    cycle = datetime(2026, 7, 22, 0, tzinfo=UTC)
    src = EcmwfFixtureSource(tmp_path, cycle=cycle)
    (series,) = src.fetch_series([SEA_POINT])
    assert len(series) == 1
    assert series[0].time == cycle + timedelta(hours=0)
    assert series[0].mwp is not None


BUOYS_YAML = """\
buoys:
  - id: "TEST1"
    name: "Test - off Beit Yanai"
    lat: 32.2
    lon: 34.55
    source: ndbc
"""


def test_cli_archive_ecmwf_writes_suffixed_key(tmp_path) -> None:
    """`archive --wave-source ecmwf` appends <buoy>.ecmwf.jsonl from replayed gribs and
    never touches the OM or GFS-Wave keys."""
    import json

    from rosa_pipeline.cli import main

    buoys_dir = tmp_path / "buoys"
    buoys_dir.mkdir()
    (buoys_dir / "test.yaml").write_text(BUOYS_YAML, encoding="utf-8")
    grib_dir = tmp_path / "gribs"
    grib_dir.mkdir()
    shutil.copy(GRIB, grib_dir / "ecmwf_f000.grib2")
    archive_dir = tmp_path / "archive"

    rc = main(
        [
            "archive",
            "--buoys-dir",
            str(buoys_dir),
            "--archive-dir",
            str(archive_dir),
            "--wave-source",
            "ecmwf",
            "--ecmwf-fixtures",
            str(grib_dir),
            "--isramar-dir",
            str(tmp_path / "no-isramar"),
        ]
    )
    assert rc == 0
    rows = [
        json.loads(line) for line in (archive_dir / "TEST1.ecmwf.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["hs"] is not None and rows[0]["tp"] is not None
    assert rows[0]["dir"] is None  # mwd absent from the fixture - honest gap
    assert not (archive_dir / "TEST1.jsonl").exists()
    assert not (archive_dir / "TEST1.gfswave.jsonl").exists()


class _StubEcmwf(EcmwfSource):
    """EcmwfSource with the network swapped for a fixed grib. ``miss_first_step``
    replays a cycle that is not fully published, which the live loop answers by dropping
    back 12 h before any other step is fetched."""

    def __init__(self, data: bytes, *, miss_first_step: bool = False, **kw) -> None:
        super().__init__(**kw)
        self._data = data
        self._miss_first_step = miss_first_step
        self._lock = threading.Lock()
        self.cycles: list[datetime] = []

    def _get_step(self, client, cycle: datetime, step: int) -> bytes | None:
        with self._lock:
            self.cycles.append(cycle)
        if self._miss_first_step and step == self.steps[0] and len(self.cycles) == 1:
            return None
        return self._data


def test_live_fetch_returns_steps_in_order_under_concurrency() -> None:
    """Steps download across WORKERS threads and finish in any order; each point's
    series must still come back ascending in time, as the serial loop left it."""
    steps = tuple(range(0, 49, 6))  # 9 steps - more than one WORKERS-sized chunk
    src = _StubEcmwf(GRIB.read_bytes(), steps=steps, params=("swh",))
    (series,) = src.fetch_series([SEA_POINT])
    cycle = src.cycles[0]
    assert [sp.time for sp in series] == [cycle + timedelta(hours=s) for s in steps]


def test_live_fetch_drops_back_a_cycle_when_the_first_step_is_missing() -> None:
    """The first step is fetched alone precisely so this decision is made before the
    rest fan out - every step must then be stamped from the older cycle."""
    steps = (0, 6, 12, 18, 24)
    src = _StubEcmwf(GRIB.read_bytes(), miss_first_step=True, steps=steps, params=("swh",))
    (series,) = src.fetch_series([SEA_POINT])
    picked, used = src.cycles[0], src.cycles[1]
    assert used == picked - timedelta(hours=12)
    assert [sp.time for sp in series] == [used + timedelta(hours=s) for s in steps]
