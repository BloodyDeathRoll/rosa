"""Blended wave source - GFS-Wave + ECMWF, our own best_match (fetch-plane plan B).

The A/B verdict this implements (CALIBRATION.md 2026-08-14): a single raw model loses to
Open-Meteo's blend, but a 50/50 GFS-Wave+ECMWF blend reaches parity on Hs, wins direction
at most leads, and wins outright in Portugal. So Rosa blends the two free global grids
itself. Cost model: requests grow with region BOXES and steps, never with spot count -
the O(1)-in-spots property the fetch-plane plan exists for.

What each leg contributes, per hour:

* **GFS-Wave** (NOMADS grib-filter, full schema - the same boxes the archive already
  pulls): the three swell partitions + windsea (the fields the physics eats - ECMWF open
  data has no partitions), plus its total swh/perpw/dirpw as one blend member.
* **ECMWF** (the Stage-3b `ecmwf.py` fetch, reused - ONE fetch serves both this blend and
  the spectral member): total swh/mwd/pp1d as the other member, mwp as the total mean
  period (GFS gridded publishes none). Stops at 240 h - past it the blend degrades to
  GFS-Wave alone, honestly (plan B3; the horizon ceiling already prices that tail low).
* **Open-Meteo, retained**: the weather request (C3 DECIDED 2026-08-26 - OM wins wind
  at every lead before day 4, so it stays) and a LIGHT marine request carrying only
  the SST + tide fallbacks,
  ~1.2 weight/point (Open-Meteo floors each location at weight 1 - see
  quota.MARINE_LIGHT_UNITS_PER_POINT) vs ~7.7 for the full marine+ensemble pair;
  charged against the same daily ledger as the om arm.

The composed ``RawForecast.marine`` uses plain UNSUFFIXED keys, which
``extract._merge_models`` passes through untouched - extract/transform/score need no
changes. ``ensemble`` carries our OWN members (plan
C4): the raw pre-blend GFS totals ride as a one-member ensemble body and extract appends
the ECMWF member - two independent voices, no OM ensemble request. dir_n=2 marks the era.

THE DEFAULT since 2026-08-26 (plan D3, promoted worldwide by product decision -
CALIBRATION.md 2026-08-26). ``run --wave-source om`` is the fallback arm and the
offline-replay arm for the committed OM fixtures.
"""

from __future__ import annotations

import json
import math
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Protocol

import httpx

from .extract import SPECTRAL_JOIN_TOL_H, _nearest_spectral
from .fetch import (
    FORECAST_DAYS,
    MARINE_URL,
    PAST_DAYS,
    WEATHER_HOURLY,
    WEATHER_URL,
    RawForecast,
    fixture_key,
    retrying_get,
)
from .geo import dlon180
from .gfswave import (
    Box,
    _is_grib,
    cluster_boxes,
    filter_url,
    pick_cycle,
)
from .gwam import GwamStep
from .models import SpectralSea

# 3-hourly to the full 16-day horizon - the published table is 3-hourly (TABLE_STEP_H),
# so a finer fetch would be downloaded and thrown away. 129 steps/box/cycle.
BLEND_STEPS: tuple[int, ...] = tuple(range(0, 385, 3))
# Back-reach (OPEN-ITEMS 20, measured on the 2026-08-26 promotion A/B): the OM arm's
# marine request carries past_days=1, so its series reaches back to local midnight at
# any longitude; a GFS cycle's f000 is the cycle time, so without this the far-east
# coasts lost today's first 1-6 table rows (157 of 265 spots, 833 rows fleet-wide). The
# hours before f000 come from the PREVIOUS cycles' f000/f003 - the freshest analysis for
# each 3 h window, the same thing OM's past_days is - back to 24 h, matching PAST_DAYS.
# 8 extra requests per box (+6%); compose_raw's sort + hourly interpolation joins them.
BACK_REACH_H = 24 * PAST_DAYS
BACK_REACH_STEPS: tuple[int, ...] = (0, 3)
# Concurrent grib-filter requests per box. The promotion run (2026-08-26) took 1h42m for
# 1,032 requests fetched one at a time - 5.9 s each, 5% CPU, pure network wait - which
# fits the 6 h cron gap but leaves no slack for more regions. Four in flight is ~40
# requests/min, a third of NOMADS' published 120/min courtesy limit; the archive's
# GFSWaveSource (four workers of its own since 2026-08-29) and the swellmap layers share
# that budget, but they run at different points in the cycle, never alongside. Parsing
# stays on the main thread (pygrib via temp files); a box's responses are a few KB each.
NOMADS_WORKERS = 4


def back_reach_plan(cycle: datetime) -> list[tuple[datetime, int]]:
    """(cycle, step) pairs whose valid hours fill ``BACK_REACH_H`` before ``cycle``'s f000,
    oldest first. Pure, so the request plan is testable without NOMADS."""
    plan: list[tuple[datetime, int]] = []
    back = 6
    while back <= BACK_REACH_H:
        prev = cycle - timedelta(hours=back)
        plan.extend((prev, step) for step in BACK_REACH_STEPS)
        back += 6
    plan.sort(key=lambda cs: cs[0] + timedelta(hours=cs[1]))
    return plan


# equal weights, deliberately: tuning bought <=0.005 m out-of-sample on a 5-week archive
# (CALIBRATION.md 2026-08-14 A2). Re-fit when the archive clears A4's >=8 weeks.
W_GFS = 0.5
# a 3-hourly hour joins the nearest 6-hourly ECMWF step within this - extract's own
# rule, imported rather than restated so the two arms can never drift apart
JOIN_TOL_H = SPECTRAL_JOIN_TOL_H
# the light OM legs batch like fetch_marine_waves_many; weight is tiny so one bucket is
# plenty at any batch size we use
AUX_BATCH_SIZE = 100
MARINE_LIGHT_FIELDS = ["sea_surface_temperature", "sea_level_height_msl"]

# the full GFS-Wave partition schema, mapped onto the OM key family extract expects.
# Message order matters: shts/mpts/swdir each appear THREE times in a gridded file
# (partitions 1..3, in file order) - collection below indexes them by appearance.
_GFS_SINGLE = {
    "swh": "swh",
    "perpw": "perpw",
    "dirpw": "dirpw",
    "shww": "windsea_h",
    "mpww": "windsea_p",
    "wvdir": "windsea_d",
}
_GFS_TRIPLE = {"shts": "swell{}_h", "mpts": "swell{}_p", "swdir": "swell{}_d"}

# The four keys extract._partition reads a partition's PEAK period from. GFS-Wave gridded
# publishes none of them - shts/mpts/swdir and shww/mpww/wvdir carry MEAN periods, and the
# only Tp in the file is `perpw`, the whole sea's. So on this arm every SwellPartition
# reaches the transform with peak_period_s=None and both transform.rideability_period and
# transform.energy_period fall back to the mean period. That fallback is not neutral: it is
# the regime CALIBRATION.md 2026-07-30 measured as a 1.6-2x under-call (and the reason
# fetch.TP_MODEL exists on the OM arm at all). Re-measured 2026-08-16 on the committed OM
# fixture + Beit Yanai's real profile: stripping Tp moves 78 of 384 hours' ratings, changes
# 41 buckets, and takes h_break_mid to x0.44 at worst - always DOWN, never up.
#
# Nothing here can repair it: inventing a per-partition Tp from `perpw` would be exactly the
# fabrication rule out (and would move published heights, so pb_0049's A/B gate applies). So
# this REPORTS. It matters because the blend arm's whole purpose is the source A/B that
# gates promotion, and an A/B that carries this offset attributes it to source skill.
_PARTITION_TP_KEYS: tuple[str, ...] = (
    "swell_wave_peak_period",
    "secondary_swell_wave_peak_period",
    "tertiary_swell_wave_peak_period",
    "wind_wave_peak_period",
)


def partition_peak_period_gap(raw: RawForecast) -> int:
    """How many partition slots in this composed forecast carry no peak period.

    Counts filled partition-height slots whose matching ``*_peak_period`` column is absent
    or null - i.e. the partitions that will reach ``transform`` keyed on a mean period.
    Report only; returns 0 for a source that does publish per-partition Tp."""
    hourly = raw.marine.get("hourly", {})
    gap = 0
    for tp_key in _PARTITION_TP_KEYS:
        h_key = tp_key.replace("_peak_period", "_height")
        heights = hourly.get(h_key)
        if not heights:
            continue
        tps = hourly.get(tp_key)
        for i, h in enumerate(heights):
            if h is None or h <= 0:
                continue
            if tps is None or i >= len(tps) or tps[i] is None:
                gap += 1
    return gap


@dataclass(frozen=True, slots=True)
class GfsSea:
    """One GFS-Wave step at one point - totals plus the partition set."""

    time: datetime
    fields: dict  # keys per _GFS_SINGLE/_GFS_TRIPLE values; missing -> absent


def parse_gfs_full(
    grib_bytes: bytes, points: list[tuple[float, float]], valid: datetime
) -> list[GfsSea | None]:
    """Sample the full wave schema at each point's nearest wet node (one step's bytes)."""
    import numpy as np
    import pygrib

    fields: dict[str, tuple] = {}
    counts: dict[str, int] = {}
    with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
        tf.write(grib_bytes)
        tf.flush()
        grbs = pygrib.open(tf.name)
        for m in grbs:
            sn = m.shortName
            if sn in _GFS_SINGLE:
                key = _GFS_SINGLE[sn]
                if key in fields:
                    continue
            elif sn in _GFS_TRIPLE:
                idx = counts.get(sn, 0) + 1
                counts[sn] = idx
                if idx > 3:
                    continue
                key = _GFS_TRIPLE[sn].format(idx)
            else:
                continue
            fields[key] = (m.values, *m.latlons())
        grbs.close()

    out: list[GfsSea | None] = []
    for lat, lon in points:
        lon360 = lon % 360.0
        got: dict[str, float] = {}
        for key, (vals, glats, glons) in fields.items():
            d2 = (glats - lat) ** 2 + dlon180(np.mod(glons, 360.0), lon360) ** 2
            if hasattr(vals, "mask") and vals.mask is not np.ma.nomask:
                d2 = np.where(vals.mask, np.inf, d2)
            idx = np.unravel_index(np.argmin(d2), d2.shape)
            if d2[idx] > 0.6**2:  # gfswave.NEAREST_MAX_DEG
                continue
            got[key] = round(float(vals[idx]), 3)
        out.append(GfsSea(time=valid, fields=got) if "swh" in got else None)
    return out


class GfsFullWaves(Protocol):
    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[GfsSea]]: ...


class GfsFullSource:
    """Live NOMADS fetch, full schema: one grib-filter request per (box x step); every
    point in the box is sampled from the same download. Identical download pattern to
    the archive's GFSWaveSource - only the parse differs."""

    def __init__(
        self,
        capture_dir: Path | None = None,
        steps: tuple[int, ...] = BLEND_STEPS,
        timeout_s: float = 60.0,
    ) -> None:
        self.capture_dir = capture_dir
        self.steps = steps
        self.timeout_s = timeout_s

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[GfsSea]]:
        series: list[list[GfsSea]] = [[] for _ in points]
        cycle = pick_cycle(datetime.now(UTC))
        with (
            httpx.Client(timeout=self.timeout_s) as client,
            ThreadPoolExecutor(max_workers=NOMADS_WORKERS) as pool,
        ):
            for box, members in cluster_boxes(points):
                pts = [points[i] for i in members]
                # The first step is probed ALONE: it decides the cycle (drop back 6 h when
                # NOMADS has not published yet), and every other request depends on it.
                cyc = cycle
                first = self._get(client, cyc, self.steps[0], box)
                if first is None:
                    cyc = cyc - timedelta(hours=6)  # cycle not on NOMADS yet
                    first = self._get(client, cyc, self.steps[0], box)
                # The rest of the forecast plus the hours BEFORE f000 from the previous
                # cycles (OPEN-ITEMS 20) go through the pool; each miss is skipped on its
                # own - a purged old cycle costs its 3 h window, never the forecast.
                # Back-reach captures use a distinct prefix so the fixture source's
                # `gfsfull_f*` glob keeps replaying the forecast alone.
                wanted: list[tuple[datetime, int, bool]] = [
                    *((cyc, step, False) for step in self.steps[1:]),
                    *((prev, step, True) for prev, step in back_reach_plan(cyc)),
                ]
                fetched = pool.map(lambda w, b=box: self._get(client, w[0], w[1], b), wanted)
                for (run, step, back), data in zip(
                    [(cyc, self.steps[0], False), *wanted], [first, *fetched], strict=True
                ):
                    if data is None:
                        continue
                    if self.capture_dir is not None:
                        self.capture_dir.mkdir(parents=True, exist_ok=True)
                        prefix = f"gfsfull_p{run:%Y%m%d%H}" if back else "gfsfull"
                        (self.capture_dir / f"{prefix}_f{step:03d}_{box.key}.grib2").write_bytes(
                            data
                        )
                    valid = run + timedelta(hours=step)
                    for i, sea in zip(members, parse_gfs_full(data, pts, valid), strict=True):
                        if sea is not None:
                            series[i].append(sea)
        return series

    def _get(self, client: httpx.Client, cycle: datetime, step: int, box: Box) -> bytes | None:
        try:
            resp = client.get(filter_url(cycle, step, box))
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or not _is_grib(resp.content):
            return None
        return resp.content


class GfsFullFixtureSource:
    """Replay captured full-schema gribs; ``valid`` stamped from a fixed cycle."""

    def __init__(self, fixtures_dir: Path, cycle: datetime | None = None) -> None:
        self.fixtures_dir = fixtures_dir
        self.cycle = cycle or datetime(2026, 8, 14, 0, tzinfo=UTC)

    def fetch_series(self, points: list[tuple[float, float]]) -> list[list[GfsSea]]:
        series: list[list[GfsSea]] = [[] for _ in points]
        for box, members in cluster_boxes(points):
            for path in sorted(self.fixtures_dir.glob(f"gfsfull_f*_{box.key}.grib2")):
                step = int(path.name.split("_f")[1][:3])
                valid = self.cycle + timedelta(hours=step)
                pts = [points[i] for i in members]
                for i, sea in zip(
                    members, parse_gfs_full(path.read_bytes(), pts, valid), strict=True
                ):
                    if sea is not None:
                        series[i].append(sea)
        return series


# ---------------------------------------------------------------------------
# the transitional Open-Meteo legs (weather unchanged; marine cut to SST + tide)
# ---------------------------------------------------------------------------


def fetch_aux_many(
    coords: list[tuple[float, float]],
    *,
    capture_dir: Path | None = None,
    timeout_s: float = 30.0,
) -> list[tuple[dict, dict]]:
    """(weather_body, marine_light_body) per point, batched comma-joined."""
    out: list[tuple[dict, dict]] = []
    if not coords:
        return out
    with httpx.Client(timeout=timeout_s) as client:
        for i in range(0, len(coords), AUX_BATCH_SIZE):
            batch = coords[i : i + AUX_BATCH_SIZE]
            lat_s = ",".join(f"{lat:g}" for lat, _ in batch)
            lon_s = ",".join(f"{lon:g}" for _, lon in batch)
            # retrying_get, same as the OM arm's batches: a lone 503 on a weather
            # batch killed the 2026-08-16 08:20Z cycle, and these two legs run AFTER
            # the GFS/ECMWF downloads - a transient here throws all of that away.
            # retry_429=True since 2026-08-28: these legs are ESSENTIAL to the cycle
            # (the whole run dies at raise_for_status below), and the DB growth to 624
            # spots pushed the burst past the MINUTELY cap - the 20:20Z and 02:20Z
            # cycles both died on the same aux weather batch ~64 min in. Only the
            # minutely-cap 429 is retried (fetch._retry_wait_s); hourly/daily still
            # fail fast, which is rosa_pipeline.quota's job.
            wresp = retrying_get(
                client,
                WEATHER_URL,
                {
                    "latitude": lat_s,
                    "longitude": lon_s,
                    "hourly": ",".join(WEATHER_HOURLY),
                    "forecast_days": FORECAST_DAYS,
                    "past_days": PAST_DAYS,
                },
                retry_429=True,
            )
            wresp_ok = wresp.raise_for_status().json()
            mresp = retrying_get(
                client,
                MARINE_URL,
                {
                    "latitude": lat_s,
                    "longitude": lon_s,
                    "hourly": ",".join(MARINE_LIGHT_FIELDS),
                    "forecast_days": FORECAST_DAYS,
                    "past_days": PAST_DAYS,
                },
                retry_429=True,
            )
            mresp_ok = mresp.raise_for_status().json()
            wb = [wresp_ok] if isinstance(wresp_ok, dict) else list(wresp_ok)
            mb = [mresp_ok] if isinstance(mresp_ok, dict) else list(mresp_ok)
            if len(wb) != len(batch) or len(mb) != len(batch):
                raise ValueError("open-meteo returned a different location count")
            for (lat, lon), w, m in zip(batch, wb, mb, strict=True):
                if capture_dir is not None:
                    capture_dir.mkdir(parents=True, exist_ok=True)
                    key = fixture_key(lat, lon)
                    (capture_dir / f"weather_{key}.json").write_text(json.dumps(w))
                    (capture_dir / f"marine_light_{key}.json").write_text(json.dumps(m))
                out.append((w, m))
    return out


def fixture_aux_many(
    coords: list[tuple[float, float]], fixtures_dir: Path
) -> list[tuple[dict, dict]]:
    out = []
    for lat, lon in coords:
        key = fixture_key(lat, lon)
        w = json.loads((fixtures_dir / f"weather_{key}.json").read_text())
        m = json.loads((fixtures_dir / f"marine_light_{key}.json").read_text())
        out.append((w, m))
    return out


# ---------------------------------------------------------------------------
# composition
# ---------------------------------------------------------------------------


def _wavg(a: float | None, b: float | None, w: float = W_GFS) -> float | None:
    if a is not None and b is not None:
        return round(w * a + (1 - w) * b, 3)
    return a if a is not None else b


def _circ(a: float | None, b: float | None, w: float = W_GFS) -> float | None:
    if a is None or b is None:
        return a if a is not None else b
    x = w * math.cos(math.radians(a)) + (1 - w) * math.cos(math.radians(b))
    y = w * math.sin(math.radians(a)) + (1 - w) * math.sin(math.radians(b))
    # round BEFORE the wrap: rounding after can hand back 360.0 (a hair under wraps to
    # 359.99..., rounds up) and a bearing of exactly 360 is not a value the schema has
    return round(math.degrees(math.atan2(y, x)), 1) % 360.0


# fill hourly between consecutive samples this far apart or closer - covers the
# native 3-hourly steps and the 6-hourly reduced sets fixtures use
INTERP_MAX_GAP_H = 6.0


def _tp_at(series: list[GwamStep], t: datetime, attr: str) -> float | None:
    """A GWAM peak period at hour ``t``: exact step, else linear between the two steps
    that bracket it when they are INTERP_MAX_GAP_H or closer and both carry a value.
    Anything else is None - a peak is never extrapolated past the last step (174 h) or
    across a purged one. Open-Meteo's hourly gwam column was the same 3-hourly model
    interpolated, so this is the shape the transform was calibrated on."""
    if not series:
        return None
    before = None
    for s in series:
        if s.time == t:
            v = getattr(s, attr)
            return round(v, 2) if v is not None else None
        if s.time < t:
            before = s
            continue
        # first step past t
        if before is None:
            return None
        gap_h = (s.time - before.time).total_seconds() / 3600.0
        a, b = getattr(before, attr), getattr(s, attr)
        if gap_h > INTERP_MAX_GAP_H or a is None or b is None:
            return None
        w = (t - before.time).total_seconds() / 3600.0 / gap_h
        return round(a + (b - a) * w, 2)
    return None


# GFS-Wave's wind-sea field and its swell partitions are NOT always disjoint: at some
# cells the same wave system is written into BOTH `shww/mpww/wvdir` and a `shts/mpts/swdir`
# slot, so the partition set carries more energy than the `swh` it partitions. Handed
# through unchanged the transform then breaks one wave twice - Poleg on 2026-08-30 published
# 1.4-2.1 m against a 1.6 m swell both Surfline and the OM arm agreed on.
#
# Measured on the 2026-08-27 00Z cycle over 350 grid cells carrying both a wind sea and a
# swell partition (Israel, California, Sri Lanka, Portugal, Japan, Peru x f024/f078/f120):
#   - 6 cells (1.7%) RMS to >1.25x their own swh. In EVERY one the wind sea and swell 1 are
#     one system written twice - median |dir_ww - dir_sw1| 1.7 deg, |dT|/T 0.002, h ratio 0.99.
#   - the 328 cells that do close sit median 63.7 deg and 53% of period apart, and NOT ONE
#     falls inside the thresholds below.
# The separation is clean, which is what makes this de-duplication rather than the partition
# SCALING docs/ALGORITHM.md forbids: no height is changed and no energy is invented - one of
# two identical copies is dropped, and a sea that is genuinely bimodal is never touched.
#
# The wind-sea copy is the one dropped, for three reasons: the swell slots are POSITIONAL
# (extract indexes swell 1/2/3 in order, so blanking slot 1 under a filled slot 2 would
# misread the rest), the swell copy carries GWAM's `pp1ds` while the wind-sea copy carries
# `pp1dw` - 2.2 s against a measured 8.4 s mean at Poleg, plainly the wrong spectrum - and
# these systems are too long for their wind to have raised them (6.7 m/s supports ~5 s, not
# 8.4 s), so `swell` is the honest label.
DEDUPE_DIR_DEG = 20.0
DEDUPE_PERIOD_FRAC = 0.15


def drop_duplicate_windsea(fields: dict) -> dict:
    """Blank GFS's wind-sea partition when it restates a swell partition.

    Returns `fields` untouched unless the duplicate is present, so the common path keeps
    the source's own numbers verbatim."""
    h_w, d_w, p_w = (fields.get(k) for k in ("windsea_h", "windsea_d", "windsea_p"))
    if not h_w or d_w is None or not p_w:
        return fields
    for n in (1, 2, 3):
        h_s, d_s, p_s = (fields.get(f"swell{n}_{k}") for k in ("h", "d", "p"))
        if not h_s or d_s is None or not p_s:
            continue
        if abs((d_w - d_s + 180.0) % 360.0 - 180.0) > DEDUPE_DIR_DEG:
            continue
        if abs(p_w - p_s) / p_s > DEDUPE_PERIOD_FRAC:
            continue
        return {k: v for k, v in fields.items() if not k.startswith("windsea_")}
    return fields


def _interp_hourly(gfs: list[GfsSea]) -> list[GfsSea]:
    """Expand a 3-hourly GFS series to hourly by linear (circular for bearings)
    interpolation between consecutive steps.

    Needed for correctness, not cosmetics: publish keeps only WHOLE local days, and a
    3-hourly UTC series contains a local-midnight hour only in timezones whose offset
    is a multiple of 3 h - Hawaii (UTC-10) and Sri Lanka (UTC+5:30) published ZERO days
    from the raw steps (caught by the 2026-08-14 smoke). Open-Meteo interpolates its
    3-hourly models to hourly the same way; a key missing at either endpoint stays
    missing in the filled hours rather than being invented."""
    if not gfs:
        return gfs
    out: list[GfsSea] = []
    for a, b in pairwise(gfs):
        out.append(a)
        gap_h = (b.time - a.time).total_seconds() / 3600.0
        if not 1.0 < gap_h <= INTERP_MAX_GAP_H:
            continue
        shared = set(a.fields) & set(b.fields)
        for k in range(1, round(gap_h)):
            frac = k / gap_h
            f: dict[str, float] = {}
            for key in shared:
                va, vb = a.fields[key], b.fields[key]
                if key.endswith("_d") or key == "dirpw":
                    f[key] = _circ(va, vb, w=1.0 - frac)
                else:
                    f[key] = round(va + (vb - va) * frac, 3)
            out.append(GfsSea(time=a.time + timedelta(hours=k), fields=f))
    out.append(gfs[-1])
    return out


def compose_raw(
    gfs: list[GfsSea],
    ecmwf: list[SpectralSea],
    weather: dict,
    marine_light: dict,
    fetched_at: str,
    sst_daily: float | None = None,
    tp: list[GwamStep] | None = None,
) -> RawForecast:
    """One point's blended ``RawForecast``, in the unsuffixed shape extract passes through.

    Time base = the GFS steps interpolated to hourly (the only leg carrying partitions);
    each hour blends in the nearest ECMWF step within JOIN_TOL_H. Tide is looked up from
    the light OM marine body BY TIMESTAMP, so a missing hour is None, never misaligned.
    SST: ``sst_daily`` (OISST, plan C2 - intra-day drift ~0.1 C, below model error) fills
    every hour when present; the OM light value is the per-hour fallback.
    ``tp`` (DWD GWAM, docs/rosa-peak-period-plan.md): the primary swell's and the wind
    sea's PEAK period per hour, the two columns extract._partition reads a peak from -
    what the OM arm's gwam join supplied. None past 174 h and for secondaries, as there."""
    gfs = _interp_hourly(sorted(gfs, key=lambda g: g.time))
    tp_series = sorted(tp or [], key=lambda s: s.time)
    sp_series = sorted(ecmwf, key=lambda s: s.time)
    sp_times = [s.time for s in sp_series]
    ml = marine_light.get("hourly", {})
    ml_index = {t: i for i, t in enumerate(ml.get("time", []))}

    cols: dict[str, list] = {
        k: []
        for k in (
            "time",
            "wave_height",
            "wave_direction",
            "wave_period",
            "wave_peak_period",
            "wind_wave_height",
            "wind_wave_direction",
            "wind_wave_period",
            "wind_wave_peak_period",
            "swell_wave_height",
            "swell_wave_direction",
            "swell_wave_period",
            "swell_wave_peak_period",
            "secondary_swell_wave_height",
            "secondary_swell_wave_direction",
            "secondary_swell_wave_period",
            "tertiary_swell_wave_height",
            "tertiary_swell_wave_direction",
            "tertiary_swell_wave_period",
            "sea_surface_temperature",
            "sea_level_height_msl",
        )
    }
    # plan C4: the blend arm's confidence members are its OWN two models - the raw
    # (pre-blend) GFS totals ride as a one-member ensemble body here, and extract
    # appends the ECMWF member exactly as it does on the OM arm. Two independent
    # voices; the blended total itself is NOT a member (it is not independent).
    ens_hs: list = []
    ens_dir: list = []
    for g in gfs:
        t_iso = g.time.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")
        f = drop_duplicate_windsea(g.fields)
        sp = _nearest_spectral(g.time, sp_series, sp_times)
        cols["time"].append(t_iso)
        ens_hs.append(f.get("swh"))
        ens_dir.append(f.get("dirpw"))
        cols["wave_height"].append(_wavg(f.get("swh"), sp.swh if sp else None))
        cols["wave_direction"].append(_circ(f.get("dirpw"), sp.mwd if sp else None))
        # total mean period exists only on the ECMWF side (GFS gridded has none);
        # None past 240 h - the per-partition periods the physics eats are GFS's own
        cols["wave_period"].append(round(sp.mwp, 2) if sp and sp.mwp is not None else None)
        cols["wave_peak_period"].append(_wavg(f.get("perpw"), sp.pp1d if sp else None))
        cols["wind_wave_height"].append(f.get("windsea_h"))
        cols["wind_wave_direction"].append(f.get("windsea_d"))
        cols["wind_wave_period"].append(f.get("windsea_p"))
        # GWAM's peaks ride on the partitions GFS actually publishes: a peak with no
        # partition under it is dropped, so extract never sees a Tp for an empty slot
        cols["wind_wave_peak_period"].append(
            _tp_at(tp_series, g.time, "windsea_tp") if f.get("windsea_h") else None
        )
        cols["swell_wave_peak_period"].append(
            _tp_at(tp_series, g.time, "swell_tp") if f.get("swell1_h") else None
        )
        for n, prefix in (
            (1, "swell_wave"),
            (2, "secondary_swell_wave"),
            (3, "tertiary_swell_wave"),
        ):
            cols[f"{prefix}_height"].append(f.get(f"swell{n}_h"))
            cols[f"{prefix}_direction"].append(f.get(f"swell{n}_d"))
            cols[f"{prefix}_period"].append(f.get(f"swell{n}_p"))
        j = ml_index.get(t_iso)
        om_sst = None
        if (
            (arr := ml.get("sea_surface_temperature")) is not None
            and j is not None
            and j < len(arr)
        ):
            om_sst = arr[j]
        cols["sea_surface_temperature"].append(sst_daily if sst_daily is not None else om_sst)
        arr = ml.get("sea_level_height_msl")
        cols["sea_level_height_msl"].append(
            arr[j] if arr is not None and j is not None and j < len(arr) else None
        )

    ensemble = {
        "hourly": {
            "time": cols["time"],
            "wave_height_ncep_gfswave016": ens_hs,
            "wave_direction_ncep_gfswave016": ens_dir,
        }
    }
    return RawForecast(
        fetched_at=fetched_at,
        marine={"hourly": cols},
        weather=weather,
        # plan C4: our own members, no OM ensemble request - GFS here, ECMWF appended
        # by extract from the spectral series. dir_n reports the 2-member era honestly.
        ensemble=ensemble,
    )


class BlendedSource:
    """``ForecastSource`` for the blend arm. ``ecmwf_series`` (one list per coord, the
    same series the caller feeds extract's spectral member) is passed to ``fetch_many``
    so ECMWF is fetched ONCE per run, not once per leg."""

    def __init__(
        self,
        gfs: GfsFullWaves,
        aux,  # callable(coords) -> list[(weather_body, marine_light_body)]
        sst=None,  # oisst.SstSource | None (plan C2); OM light value is the fallback
        tp=None,  # gwam.GwamPeaks | None (peak-period plan A); None -> mean-period fallback
    ) -> None:
        self.gfs = gfs
        self.aux = aux
        self.sst = sst
        self.tp = tp

    def fetch(self, lat: float, lon: float) -> RawForecast:
        return self.fetch_many([(lat, lon)])[0]

    def fetch_many(
        self,
        coords: list[tuple[float, float]],
        ecmwf_series: list[list[SpectralSea]] | None = None,
    ) -> list[RawForecast]:
        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        gfs_series = self.gfs.fetch_series(coords)
        sp_series = ecmwf_series if ecmwf_series is not None else [[] for _ in coords]
        aux = self.aux(coords)
        sst_vals: list[float | None] = [None] * len(coords)
        if self.sst is not None:
            try:  # guarded: an NCEI outage must never sink the run - OM value stands in
                sst_vals = self.sst.fetch(coords)
            except Exception as e:
                import sys

                print(f"warn: oisst sst skipped: {e!r}", file=sys.stderr)
        tp_series: list[list[GwamStep]] = [[] for _ in coords]
        if self.tp is not None:
            try:  # guarded: a DWD outage costs the peaks (mean-period fallback), never the run
                tp_series = self.tp.fetch_series(coords)
            except Exception as e:
                import sys

                print(f"warn: gwam peak periods skipped: {e!r}", file=sys.stderr)
        raws = [
            compose_raw(g, sp, w, m, fetched_at, sst_daily=sst_v, tp=tp_v)
            for g, sp, (w, m), sst_v, tp_v in zip(
                gfs_series, sp_series, aux, sst_vals, tp_series, strict=True
            )
        ]
        # ...and say what this arm cannot measure. Once per run, not per point: the gap is a
        # property of the SOURCE SCHEMA, not of any one spot. See _PARTITION_TP_KEYS.
        gap = sum(partition_peak_period_gap(r) for r in raws)
        if gap:
            import sys

            print(
                f"warn: blend arm: {gap} partition slot(s) have no peak period - GFS-Wave "
                "gridded publishes only per-partition MEAN periods, so period_rideability "
                "and energy_period key on the mean (CALIBRATION.md 2026-07-30 measured that "
                "as a 1.6-2x under-call). A blend-vs-om A/B carries this offset on top of "
                "any real source difference.",
                file=sys.stderr,
            )
        return raws
