"""Stage 3a - raw GFS-Wave source: clustering, cycle picking, GRIB parsing, replay,
and the peak-period↔DPD pairing that keeps the A/B honest.

The grib fixture is a REAL NOMADS grib-filter capture (2026-07-23 00z f000, Med box
30-35N / 30-37E, 9.5 KB) - parsing runs fully offline against it."""

from __future__ import annotations

import shutil
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rosa_pipeline.gfswave import (
    Box,
    GFSWaveFixtureSource,
    GFSWaveSource,
    cluster_boxes,
    filter_url,
    parse_grib_points,
    pick_cycle,
)
from rosa_pipeline.observe import BuoyObs
from rosa_pipeline.verify import GFSWAVE_VARIABLES, lead_time_scorecard

FIXTURE = Path(__file__).parent / "fixtures" / "gfswave" / "med_f000.grib2"
# a point inside the fixture box, in open water off the Israeli coast
SEA_POINT = (32.2, 34.55)
# inside the box but deep inland (E Syria) - no wet node within reach
LAND_POINT = (33.0, 36.9)


def test_cluster_boxes_groups_near_and_splits_far() -> None:
    pts = [(32.2, 34.55), (32.8, 34.9), (21.7, -158.1)]  # two Israel, one Hawaii
    boxes = cluster_boxes(pts)
    assert len(boxes) == 2
    (box_a, members_a), (box_b, members_b) = boxes
    assert members_a == [0, 1]
    assert members_b == [2]
    # padding applied; Hawaii longitude expressed 0-360
    assert box_a.bottom < 32.2 and box_a.top > 32.8
    assert 200.0 < box_b.left < 202.0  # -158.1 → 201.9 minus pad


def test_pick_cycle_respects_publication_lag() -> None:
    # 12:00Z: 06z run is ~6 h old → ready; 12z (0 h old) is not on NOMADS yet
    now = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
    assert pick_cycle(now).hour == 6
    # 03:00Z: even 00z (3 h old) isn't ready - fall back to yesterday's 18z
    now = datetime(2026, 7, 23, 3, 0, tzinfo=UTC)
    c = pick_cycle(now)
    assert (c.day, c.hour) == (22, 18)


def test_filter_url_shape() -> None:
    cycle = datetime(2026, 7, 23, 0, tzinfo=UTC)
    url = filter_url(cycle, 6, Box(bottom=30, top=35, left=30, right=37))
    assert "filter_gfswave.pl" in url
    assert "dir=%2Fgfs.20260723%2F00%2Fwave%2Fgridded" in url
    assert "file=gfswave.t00z.global.0p25.f006.grib2" in url
    assert "toplat=35" in url and "bottomlat=30" in url
    assert "leftlon=30" in url and "rightlon=37" in url


def test_parse_grib_points_sea_and_land() -> None:
    valid = datetime(2026, 7, 23, 0, tzinfo=UTC)
    sea, land = parse_grib_points(FIXTURE.read_bytes(), [SEA_POINT, LAND_POINT], valid)
    assert sea is not None
    assert sea.time == valid
    assert sea.hs is not None and 0.0 <= sea.hs < 10.0
    assert sea.tp is not None and 0.0 < sea.tp < 25.0
    assert sea.dir is not None and 0.0 <= sea.dir < 360.0
    assert land is None  # no wet grid node within reach → honest gap, not a land value


def test_fixture_source_replays_by_box_key(tmp_path) -> None:
    # name the capture for the box cluster_boxes derives for the point
    (box, members) = cluster_boxes([SEA_POINT])[0]
    assert members == [0]
    shutil.copy(FIXTURE, tmp_path / f"gfswave_f000_{box.key}.grib2")
    cycle = datetime(2026, 7, 23, 0, tzinfo=UTC)
    src = GFSWaveFixtureSource(tmp_path, cycle=cycle)
    (series,) = src.fetch_series([SEA_POINT])
    assert len(series) == 1
    assert series[0].time == cycle + timedelta(hours=0)
    assert series[0].hs is not None


def _obs(t: datetime, **kw) -> BuoyObs:
    base = dict(hs_m=None, dpd_s=None, apd_s=None, mwd_deg=None, wtmp_c=None)
    base.update(kw)
    return BuoyObs(station="x", time=t, **base)


def test_gfswave_scoring_pairs_peak_period_with_dpd() -> None:
    """perpw is a PEAK period: it must score against the buoy's DPD, never APD -
    pairing mean-vs-dominant would fabricate a phantom bias."""
    valid = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    rows = [
        {
            "run": (valid - timedelta(hours=6)).isoformat(),
            "valid": valid.isoformat(),
            "hs": None,
            "tp": 12.0,
            "dir": None,
        },
    ]
    # buoy: dominant period 12 s (matches), average period 7 s (would read +5 s hot)
    obs = [_obs(valid, dpd_s=12.0, apd_s=7.0)]
    by_lead = lead_time_scorecard(rows, obs, tol_min=30, variables=GFSWAVE_VARIABLES)
    assert by_lead["0-1d"]["tp"].n == 1
    assert abs(by_lead["0-1d"]["tp"].bias) < 1e-9  # paired with DPD → no phantom bias


BUOYS_YAML = """\
buoys:
  - id: "TEST1"
    name: "Test - off Beit Yanai"
    lat: 32.2
    lon: 34.55
    source: ndbc
"""


def test_cli_archive_gfswave_writes_suffixed_key(tmp_path) -> None:
    """`archive --wave-source gfswave` appends <buoy>.gfswave.jsonl from replayed gribs
    and never touches the OM key."""
    import json

    from rosa_pipeline.cli import main

    buoys_dir = tmp_path / "buoys"
    buoys_dir.mkdir()
    (buoys_dir / "test.yaml").write_text(BUOYS_YAML, encoding="utf-8")
    gfs_dir = tmp_path / "gribs"
    gfs_dir.mkdir()
    (box, _members) = cluster_boxes([SEA_POINT])[0]
    shutil.copy(FIXTURE, gfs_dir / f"gfswave_f000_{box.key}.grib2")
    archive_dir = tmp_path / "archive"

    rc = main(
        [
            "archive",
            "--buoys-dir",
            str(buoys_dir),
            "--archive-dir",
            str(archive_dir),
            "--wave-source",
            "gfswave",
            "--gfs-fixtures",
            str(gfs_dir),
            "--isramar-dir",
            str(tmp_path / "no-isramar"),
            # ...and an empty station registry: `--gfs-fixtures` is a PARTIAL replay,
            # which `_archive_stations` treats as live by design (cli.py:1342 - only the
            # OM arm's own `--fixtures` means offline). Without this the test loads
            # data/stations and fires a real fetch_wind_many at api.open-meteo.com; the
            # arm's guard turns the failure into a warn, so the assertions below never
            # noticed and the suite just paid retrying_get's 10 s + 20 s backoff.
            "--stations-dir",
            str(tmp_path / "no-stations"),
        ]
    )
    assert rc == 0
    gfs_rows = [
        json.loads(line) for line in (archive_dir / "TEST1.gfswave.jsonl").read_text().splitlines()
    ]
    assert len(gfs_rows) == 1
    assert gfs_rows[0]["hs"] is not None and gfs_rows[0]["tp"] is not None
    assert not (archive_dir / "TEST1.jsonl").exists()  # OM key untouched in gfswave-only mode


class _StubNomads(GFSWaveSource):
    """GFSWaveSource with the network swapped for a fixed grib. ``miss_first_step``
    replays NOMADS not having published the cycle yet, which the live loop answers by
    dropping the whole box back one cycle."""

    def __init__(self, data: bytes, *, miss_first_step: bool = False, **kw) -> None:
        super().__init__(**kw)
        self._data = data
        self._miss_first_step = miss_first_step
        self._lock = threading.Lock()
        self.cycles: list[datetime] = []

    def _get(self, client, cycle: datetime, step: int, box: Box) -> bytes | None:
        with self._lock:
            self.cycles.append(cycle)
        if self._miss_first_step and step == self.steps[0] and len(self.cycles) == 1:
            return None
        return self._data


def test_live_fetch_returns_steps_in_order_under_concurrency() -> None:
    """The step downloads fan out across WORKERS threads and finish in any order; each
    point's series must still come back ascending in time, as the serial loop left it."""
    steps = tuple(range(0, 49, 6))  # 9 steps - more than one WORKERS-sized chunk
    src = _StubNomads(FIXTURE.read_bytes(), steps=steps)
    (series,) = src.fetch_series([SEA_POINT])
    cycle = src.cycles[0]
    assert [wp.time for wp in series] == [cycle + timedelta(hours=s) for s in steps]


def test_live_fetch_drops_the_box_back_a_cycle_when_the_first_step_is_missing() -> None:
    """The first step is probed alone precisely so this decision is made before the rest
    fan out - every step of the box must then be stamped from the older cycle."""
    steps = (0, 6, 12, 18, 24)
    src = _StubNomads(FIXTURE.read_bytes(), miss_first_step=True, steps=steps)
    (series,) = src.fetch_series([SEA_POINT])
    picked, used = src.cycles[0], src.cycles[1]
    assert used == picked - timedelta(hours=6)
    assert [wp.time for wp in series] == [used + timedelta(hours=s) for s in steps]
