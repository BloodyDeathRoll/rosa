"""Buoy-observation layer: ground truth for the verification harness (roadmap Stage 0).

Mirrors ``fetch.py``: a live source that can capture responses, and a fixture source that
replays them so tests never touch the network. NDBC is the first adapter (public domain);
CMEMS in-situ (Copernicus, free/open, attribution required) is the second and is the only
non-US network - it is what gives Portugal any ground truth at all. ISRAMAR stays
local-validation-only (all-rights-reserved) - it must never be committed or shipped.

Parses the NDBC ``realtime2/<id>.txt`` standard-meteorological file. Wave columns:
    WDIR = wind direction (deg, FROM)    -> wdir_deg
    WSPD = wind speed (m/s)              -> wspd_ms
    WVHT = significant wave height (m)   -> hs_m
    DPD  = dominant (peak) period (s)    -> dpd_s
    APD  = average period (s), i.e. Tm02 -> apd_s   (NOT the model's mean period - see
                                           verify.py: Open-Meteo serves Tm-1,0)
    MWD  = direction at the dominant      -> mwd_deg   (a PEAK direction despite the
           period, DPD (deg, from)                     name - NDBC measurement
                                                       descriptions; see verify.py)
    WTMP = water temperature (degC)      -> wtmp_c
Missing values are the literal "MM". Rows are newest-first; we return oldest-first.

The wind columns sit on the same line as the wave columns and were parsed past until
2026-08-03. They are the only co-located wind+wave ground truth Rosa has: whether a wind
term belongs in the OFFSHORE input (an Open-Meteo Hs bias, fittable from thousands of buoy
hours) or purely in the NEARSHORE transform (fittable only from eyes) is not answerable
without them. See docs/CALIBRATION.md 2026-08-03 and open item 4.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import httpx

from .buoys import Buoy
from .stations import Station

NDBC_REALTIME = "https://www.ndbc.noaa.gov/data/realtime2"


@dataclass(frozen=True, slots=True)
class BuoyObs:
    station: str
    time: datetime  # tz-aware UTC
    hs_m: float | None
    dpd_s: float | None
    apd_s: float | None
    mwd_deg: float | None
    wtmp_c: float | None
    # Tm-1,0 (m-1/m0) measured from the station's own spectrum - not in the standard-met
    # file, filled in by verify.with_energy_period() where spectra are published.
    tm_m10_s: float | None = None
    # co-located wind, same line of the same file (see module docstring)
    wdir_deg: float | None = None  # direction the wind blows FROM
    wspd_ms: float | None = None  # m/s, as NDBC reports it - not kph
    # gust, m/s - only the coastal wind stations report it (METAR wgst, IMS WSmax);
    # None on every buoy row. Nothing scores it yet; recorded so it CAN be.
    gust_ms: float | None = None


def _num(token: str, damaged: list[str] | None = None) -> float | None:
    """A whitespace-column value, or None if missing/unreadable.

    "MM" is NDBC's documented missing marker. Anything else that will not parse is
    treated as missing TOO, rather than raised: `parse_ndbc_txt` already skips a row
    whose date is unreadable, and a value has no better claim to sink the file than a
    date does. Unguarded, one stray token cost the caller every good row in a ~45-day
    realtime2 file - and a buoy that stops contributing is a buoy the lead-time
    scorecard, and so the published confidence ceiling, quietly stops measuring.
    Matches `_csv_num` below, which has always read an unparseable value as missing."""
    if token == "MM":
        return None
    try:
        return float(token)
    except ValueError:
        # loud, not silent - the caller reports how many it dropped (records_from_rows
        # and _iter_payloads keep the same contract for their own damaged rows)
        if damaged is not None:
            damaged.append(token)
        return None


def _csv_num(parts: list[str], i: int) -> float | None:
    """A comma-column value, or None if absent/blank/placeholder."""
    if i >= len(parts) or parts[i] in ("", "-", "MM"):
        return None
    try:
        return float(parts[i])
    except ValueError:
        return None


def parse_ndbc_txt(text: str, station: str) -> list[BuoyObs]:
    """Parse an NDBC standard-met file into observations, oldest-first.

    Rows with no wave height at all (WVHT missing) are still kept - the harness filters;
    a buoy that reports only met is simply unusable for wave scoring, not an error here."""
    obs: list[BuoyObs] = []
    damaged: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if len(f) < 15:
            continue
        try:
            yr, mo, dy, hr, mn = (int(f[i]) for i in range(5))
            t = datetime(yr, mo, dy, hr, mn, tzinfo=UTC)
        except ValueError:
            continue
        obs.append(
            BuoyObs(
                station=station,
                time=t,
                hs_m=_num(f[8], damaged),
                dpd_s=_num(f[9], damaged),
                apd_s=_num(f[10], damaged),
                mwd_deg=_num(f[11], damaged),
                wtmp_c=_num(f[14], damaged),
                wdir_deg=_num(f[5], damaged),
                wspd_ms=_num(f[6], damaged),
            )
        )
    if damaged:
        shown = ", ".join(sorted(set(damaged))[:5])
        print(
            f"warn: {station}: {len(damaged)} unreadable value(s) read as missing ({shown}) "
            f"- {len(obs)} row(s) kept"
        )
    obs.sort(key=lambda o: o.time)
    return obs


class ObservationSource(Protocol):
    def fetch(self, buoy: Buoy) -> list[BuoyObs]: ...


class NDBCSource:
    def __init__(self, capture_dir: Path | None = None, timeout_s: float = 30.0) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s

    def fetch(self, buoy: Buoy) -> list[BuoyObs]:
        url = f"{NDBC_REALTIME}/{buoy.id}.txt"
        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.get(url)
            resp.raise_for_status()
        text = resp.text
        if self.capture_dir is not None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            (self.capture_dir / f"ndbc_{buoy.id}.txt").write_text(text, encoding="utf-8")
        return parse_ndbc_txt(text, buoy.id)


class NDBCFixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, buoy: Buoy) -> list[BuoyObs]:
        path = self.fixtures_dir / f"ndbc_{buoy.id}.txt"
        return parse_ndbc_txt(path.read_text(encoding="utf-8"), buoy.id)


CMEMS_IBI = (
    "https://s3.waw3-1.cloudferro.com/mdl-native-03/native"
    "/INSITU_IBI_PHYBGCWAV_DISCRETE_MYNRT_013_033"
    "/cmems_obs-ins_ibi_phybgcwav_mynrt_na_irr_202311/latest"
)
# OceanSITES QC convention: 0 no-QC, 1 good, 2 probably-good, 3 bad-correctable, 4 bad,
# 9 missing. CMEMS's own guidance is to use 1 and 2; anything else is dropped.
CMEMS_GOOD_QC = (1, 2)


def parse_cmems_nc(data: bytes, station: str) -> list[BuoyObs]:
    """Parse one CMEMS in-situ daily NetCDF4 file into observations, oldest-first.

    Variable mapping (CMEMS name -> BuoyObs field), chosen to pair LIKE-FOR-LIKE with the
    NDBC adapter so the two networks can share one scorecard:
        VHM0  significant wave height (m)   -> hs_m
        VTM02 mean period, Tm02 (s)         -> apd_s   (same definition as NDBC's APD)
        VTPK  peak period (s)               -> dpd_s   (same definition as NDBC's DPD)
        TEMP  sea temperature (degC)        -> wtmp_c

    DIRECTION IS A KNOWN MISMATCH, deliberately not hidden: these files carry VMDR (mean
    direction) only sometimes, and VPED (direction at the spectral PEAK) always. NDBC's MWD
    is the direction at the dominant period - a PEAK direction (NDBC's measurement
    descriptions, checked 2026-09-13; this said "a mean" until then). So VPED is the
    like-for-like with NDBC and VMDR is not. We still prefer VMDR and fall back to VPED:
    switching moves scorecards and is not done here (CALIBRATION.md 2026-09-13). The
    peak-vs-mean offset is the one already documented for ISRAMAR - a known bias, not an
    error. Never pool direction rows across NDBC and CMEMS stations. Never read a
    direction score across sources without checking which one this station supplied.

    No wind: these platforms publish waves only, so wdir_deg/wspd_ms stay None (unlike NDBC,
    where wind shares the line - see the module docstring and open item 4).

    Values are (time, depth) arrays; the first QC-good depth level wins per timestamp."""
    import io

    import h5py
    import numpy as np

    obs: list[BuoyObs] = []
    with h5py.File(io.BytesIO(data), "r") as f:
        if "TIME" not in f or "VHM0" not in f:
            return []
        # TIME is days since the CF epoch below; the files state it in TIME.units.
        times = np.asarray(f["TIME"][:], dtype="float64")
        epoch = datetime(1950, 1, 1, tzinfo=UTC)

        def column(name: str) -> np.ndarray | None:
            """QC-filtered values per timestamp, NaN where unusable."""
            if name not in f:
                return None
            vals = np.asarray(f[name][:], dtype="float64")
            fill = f[name].attrs.get("_FillValue")
            if fill is not None:
                vals = np.where(np.isclose(vals, float(np.ravel(fill)[0])), np.nan, vals)
            qc_name = f"{name}_QC"
            if qc_name in f:
                qc = np.asarray(f[qc_name][:])
                vals = np.where(np.isin(qc, CMEMS_GOOD_QC), vals, np.nan)
            if vals.ndim == 1:
                return vals
            # (time, depth) -> first non-NaN depth level per timestamp
            out = np.full(vals.shape[0], np.nan)
            for i, row in enumerate(vals):
                ok = row[~np.isnan(row)]
                if ok.size:
                    out[i] = ok[0]
            return out

        hs = column("VHM0")
        tm02 = column("VTM02")
        tpk = column("VTPK")
        direction = column("VMDR")
        if direction is None or np.all(np.isnan(direction)):
            direction = column("VPED")
        temp = column("TEMP")

        def at(arr: np.ndarray | None, i: int) -> float | None:
            if arr is None or i >= arr.shape[0]:
                return None
            v = arr[i]
            return None if np.isnan(v) else float(v)

        for i, day in enumerate(times):
            if not np.isfinite(day):
                continue
            obs.append(
                BuoyObs(
                    station=station,
                    time=epoch + timedelta(days=float(day)),
                    hs_m=at(hs, i),
                    dpd_s=at(tpk, i),
                    apd_s=at(tm02, i),
                    mwd_deg=at(direction, i),
                    wtmp_c=at(temp, i),
                )
            )
    obs.sort(key=lambda o: o.time)
    return obs


class CMEMSSource:
    """Copernicus Marine in-situ waves. Public S3, no credentials (verified 2026-08-04).

    One file per platform per day, so a window of recent days is stitched together. Today's
    file may not exist yet, and a platform can simply miss a day - both are normal and are
    skipped, never raised, so one gap can't fail a whole verify run."""

    def __init__(
        self, capture_dir: Path | None = None, timeout_s: float = 30.0, days: int = 3
    ) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s
        self.days = days

    def fetch(self, buoy: Buoy) -> list[BuoyObs]:
        today = datetime.now(UTC).date()
        obs: list[BuoyObs] = []
        with httpx.Client(timeout=self.timeout_s) as client:
            for back in range(self.days, -1, -1):
                stamp = (today - timedelta(days=back)).strftime("%Y%m%d")
                name = f"IR_TS_MO_{buoy.id}_{stamp}.nc"
                resp = client.get(f"{CMEMS_IBI}/{stamp}/{name}")
                if resp.status_code == 404:
                    continue  # day not published (yet) - normal
                resp.raise_for_status()
                if self.capture_dir is not None:
                    self.capture_dir.mkdir(parents=True, exist_ok=True)
                    (self.capture_dir / f"cmems_{name}").write_bytes(resp.content)
                obs.extend(parse_cmems_nc(resp.content, buoy.id))
        obs.sort(key=lambda o: o.time)
        return obs


class CMEMSFixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, buoy: Buoy) -> list[BuoyObs]:
        obs: list[BuoyObs] = []
        for path in sorted(self.fixtures_dir.glob(f"cmems_IR_TS_MO_{buoy.id}_*.nc")):
            obs.extend(parse_cmems_nc(path.read_bytes(), buoy.id))
        obs.sort(key=lambda o: o.time)
        return obs


def parse_isramar_csv(text: str, station: str) -> list[BuoyObs]:
    """Parse a manual-import ISRAMAR csv into observations, oldest-first.

    Columns: ``time_utc, hs_m, period_s, dir_deg[, wtmp_c]`` - blank/`-`/`MM` = missing,
    `#` lines ignored. NOTE: ISRAMAR usually displays *peak* period; it's stored in the
    period slot the harness compares to the model's MEAN wave_period, so expect the same
    peak-vs-mean offset seen at NDBC (a known, documented bias, not an error)."""
    obs: list[BuoyObs] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            t = datetime.fromisoformat(parts[0])
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=UTC)
        obs.append(
            BuoyObs(
                station=station,
                time=t,
                hs_m=_csv_num(parts, 1),
                dpd_s=None,
                apd_s=_csv_num(parts, 2),
                mwd_deg=_csv_num(parts, 3),
                wtmp_c=_csv_num(parts, 4),
            )
        )
    obs.sort(key=lambda o: o.time)
    return obs


class ISRAMARLocalSource:
    """ISRAMAR truth, MANUAL-IMPORT ONLY - Rosa never fetches ISRAMAR.

    ISRAMAR data is all-rights-reserved and its download endpoints are robots-disallowed, so
    there is no automated fetch here by design (CLAUDE.md red line: manual validation during
    calibration; partnership before any integration). The operator reads the ISRAMAR real-time
    display and pastes rows into ``data/verify/isramar/<station>.csv`` - gitignored, never
    shipped, never committed. This just reads that local file."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def fetch(self, buoy: Buoy) -> list[BuoyObs]:
        path = self.root / f"{buoy.id}.csv"
        if not path.exists():
            return []
        return parse_isramar_csv(path.read_text(encoding="utf-8"), buoy.id)


# ---------------------------------------------------------------------------------------
# Coastal wind stations (rosa_pipeline.stations, 2026-08-29). Both adapters return BuoyObs
# with the wave fields None and only wdir/wspd/gust set, so the lead-time harness scores
# them with the wind pairing (verify.STATION_VARIABLES) and nothing else.

METAR_API = "https://aviationweather.gov/api/data/metar"
# aviationweather.gov caps one response at 400 reports whatever the id list, so the source
# asks per station; 240 h is ~8 days at a half-hourly field, which covers every lead bucket
# the buoy harness scores (the valid hour must fall in the obs window, not the run time).
METAR_HOURS = 240
KT_TO_MS = 0.514444


def _kt(v: object) -> float | None:
    """A METAR speed field (knots, int) as m/s; None for missing or a non-number."""
    return float(v) * KT_TO_MS if isinstance(v, (int, float)) else None


def parse_metar_json(data: list[dict], station: str) -> list[BuoyObs]:
    """Parse aviationweather.gov's ``format=json`` METAR list, oldest-first.

    ``wspd``/``wgst`` are knots; ``wdir`` is degrees FROM, or the literal "VRB" when the
    wind is light and variable - kept as a speed with no direction (the harness pairs
    speed and direction separately, so a directionless row still scores speed). Reports
    with no wind group at all are dropped - a station that publishes none is not truth."""
    obs: list[BuoyObs] = []
    for r in data:
        ws = _kt(r.get("wspd"))
        if ws is None:
            continue
        raw_t = r.get("reportTime") or ""
        try:
            t = datetime.fromisoformat(raw_t.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            continue
        wd = r.get("wdir")
        obs.append(
            BuoyObs(
                station=station,
                time=t,
                hs_m=None,
                dpd_s=None,
                apd_s=None,
                mwd_deg=None,
                wtmp_c=None,
                wdir_deg=float(wd) if isinstance(wd, (int, float)) else None,
                wspd_ms=ws,
                gust_ms=_kt(r.get("wgst")),
            )
        )
    obs.sort(key=lambda o: o.time)
    return obs


class MetarSource:
    def __init__(
        self, capture_dir: Path | None = None, timeout_s: float = 30.0, hours: int = METAR_HOURS
    ) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s
        self.hours = hours

    def fetch(self, station: Station) -> list[BuoyObs]:
        with httpx.Client(timeout=self.timeout_s) as client:
            resp = client.get(
                METAR_API, params={"ids": station.id, "format": "json", "hours": self.hours}
            )
            resp.raise_for_status()
        if self.capture_dir is not None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            (self.capture_dir / f"metar_{station.id}.json").write_text(resp.text, encoding="utf-8")
        return parse_metar_json(resp.json(), station.id)


class MetarFixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, station: Station) -> list[BuoyObs]:
        path = self.fixtures_dir / f"metar_{station.id}.json"
        return parse_metar_json(json.loads(path.read_text(encoding="utf-8")), station.id)


IMS_API = "https://api.ims.gov.il/v1/envista"
IMS_ATTEMPTS = 5
IMS_TOKEN_ENV = "IMS_API_TOKEN"
# The API doc (ims.gov.il, API_Explanation_en.pdf): "The observation date is always in
# Israel winter time (UTC + 2), and not as mentioned in the output datetime +03:00". So the
# suffix on the wire is ignored and this fixed offset applied instead.
IMS_FIXED_OFFSET = timedelta(hours=2)
IMS_GOOD_STATUS = 1  # channel status: 1 = correct, 2 = incorrect


def parse_ims_json(body: dict, station: str) -> list[BuoyObs]:
    """Parse an Envista ``/stations/{id}/data`` body, oldest-first.

    Rows are ``{"datetime": ..., "channels": [{"name","value","valid","status"}, ...]}``.
    Channels read: WS (m/s), WD (deg FROM), WSmax (gust, m/s). A channel that is not
    ``valid`` or whose status is not 1 is treated as missing, never as a value."""
    obs: list[BuoyObs] = []
    for r in body.get("data") or []:
        raw_t = str(r.get("datetime") or "")
        try:
            naive = datetime.fromisoformat(raw_t).replace(tzinfo=None)
        except ValueError:
            continue
        t = (naive - IMS_FIXED_OFFSET).replace(tzinfo=UTC)
        vals: dict[str, float] = {}
        for ch in r.get("channels") or []:
            if not ch.get("valid", False) or ch.get("status") != IMS_GOOD_STATUS:
                continue
            v = ch.get("value")
            if isinstance(v, (int, float)):
                vals[str(ch.get("name"))] = float(v)
        if "WS" not in vals and "WD" not in vals:
            continue
        obs.append(
            BuoyObs(
                station=station,
                time=t,
                hs_m=None,
                dpd_s=None,
                apd_s=None,
                mwd_deg=None,
                wtmp_c=None,
                wdir_deg=vals.get("WD"),
                wspd_ms=vals.get("WS"),
                gust_ms=vals.get("WSmax"),
            )
        )
    obs.sort(key=lambda o: o.time)
    return obs


def ims_token() -> str | None:
    return os.environ.get(IMS_TOKEN_ENV) or None


class IMSSource:
    """IMS Envista 10-minute data, ``from``/``to`` date range (calendar days, ``to`` exclusive)."""

    def __init__(
        self,
        token: str | None = None,
        capture_dir: Path | None = None,
        timeout_s: float = 30.0,
        days: int = 8,
        retry_wait_s: float = 10.0,
    ) -> None:
        self.token = token if token is not None else ims_token()
        self.retry_wait_s = retry_wait_s
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s
        self.days = days

    def fetch(self, station: Station) -> list[BuoyObs]:
        if not self.token:
            raise RuntimeError(f"{IMS_TOKEN_ENV} not set - IMS stations need a token")
        # Both dates are IMS's own UTC+2 calendar, and ``to`` is EXCLUSIVE on the wire
        # (measured 2026-09-14: from=to=today is an empty 204, to=tomorrow returns today's
        # rows) - so ``to=today`` silently dropped the freshest day.
        today = (datetime.now(UTC) + IMS_FIXED_OFFSET).date()
        start = today - timedelta(days=self.days)
        end = today + timedelta(days=1)
        with httpx.Client(timeout=self.timeout_s) as client:
            # IMS intermittently answers 200 with a Hebrew HTML error page instead of
            # JSON - a different station each pass, the same station fine seconds later
            # (measured 2026-09-26: 10 of 21 IMS stations lost in one verify pass; 3 tries
            # 5 + 10 s apart still lost 2 - the outage outlasts seconds). Retry that and
            # 5xx/429 with a widening wait before the station drops out of the pass.
            for attempt in range(IMS_ATTEMPTS):
                resp = client.get(
                    f"{IMS_API}/stations/{station.id}/data",
                    params={"from": start.strftime("%Y/%m/%d"), "to": end.strftime("%Y/%m/%d")},
                    headers={"Authorization": f"ApiToken {self.token}"},
                )
                transient = (
                    resp.status_code == 429
                    or resp.status_code >= 500
                    or (
                        resp.status_code == 200
                        and "json" not in resp.headers.get("content-type", "")
                    )
                )
                if not transient or attempt == IMS_ATTEMPTS - 1:
                    break
                time.sleep(self.retry_wait_s * (attempt + 1))
            resp.raise_for_status()
            if resp.status_code == 200 and "json" not in resp.headers.get("content-type", ""):
                raise RuntimeError(f"IMS answered a non-JSON page {IMS_ATTEMPTS} times")
        # A station with nothing in the range answers 204 with an empty body (ZIKHRON
        # YAAQOV, 2026-09-14) - no readings, not a parse error.
        if resp.status_code == 204:
            return []
        if self.capture_dir is not None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            (self.capture_dir / f"ims_{station.id}.json").write_text(resp.text, encoding="utf-8")
        return parse_ims_json(resp.json(), station.id)


class IMSFixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, station: Station) -> list[BuoyObs]:
        path = self.fixtures_dir / f"ims_{station.id}.json"
        return parse_ims_json(json.loads(path.read_text(encoding="utf-8")), station.id)
