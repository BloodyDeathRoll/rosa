"""rosa-pipeline CLI.

Run from the repo root so the default data paths resolve:
    uv run --project pipeline rosa-pipeline run --spot beit-yanai
    uv run --project pipeline rosa-pipeline run --all
    uv run --project pipeline rosa-pipeline verify --buoy 46042
    uv run --project pipeline rosa-pipeline verify --near beit-yanai

`run --all` samples each spot's own offshore point and publishes it. Every unique point
is fetched in a single batched request (fetch_many), so a full 40-spot run is 2 requests.

`verify` scores the offshore model at a buoy against that buoy's observations (roadmap
Stage 0) - the accuracy backbone. Israel has no NDBC buoy in range; `--near` says so
honestly (its truth is ISRAMAR, local-only, plus the surfer 👍👎 loop).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from . import quota
from .archive import FileArchiveStore, rows_from_model, rows_from_spectral
from .bathymetry import (
    BathymetrySource,
    FixtureBathymetrySource,
    OpenTopoDataSource,
    build_profile,
    load_profile,
)
from .buoys import Buoy, load_all_buoys, nearest_buoys
from .ecmwf import ARCHIVE_PARAMS, EcmwfFixtureSource, EcmwfSource, EcmwfWaves
from .extract import extract_hours
from .feedback import (
    BUCKET_ORDER,
    FeedbackRecord,
    bucket_delta,
    markdown_rows,
    predicted_from_payload,
    records_from_rows,
    render_report,
    summarize,
)
from .fetch import (
    WEATHER_AB_MODEL,
    WEATHER_MODEL,
    FixtureSource,
    ForecastSource,
    OpenMeteoSource,
    fetch_marine_waves,
    fetch_marine_waves_many,
    fetch_wind_many,
)
from .gfswave import GFSWaveFixtureSource, GFSWaveSource
from .models import Spot
from .observe import (
    CMEMSFixtureSource,
    CMEMSSource,
    IMSFixtureSource,
    IMSSource,
    ISRAMARLocalSource,
    MetarFixtureSource,
    MetarSource,
    NDBCFixtureSource,
    NDBCSource,
)
from .publish import (
    build_payload,
    load_skill_ceilings,
    prune_index,
    update_index,
    write_spot_json,
)
from .score import score_hour
from .spectra import (
    NDBCSpectraSource,
    SpectraFixtureSource,
    SpectraReport,
    build_report,
    measure,
    spread_payload,
)
from .spectra import (
    render_report as render_spectra_report,
)
from .spots import load_spots
from .stations import Station, load_stations
from .transform import spread_exposure
from .verify import (
    BIAS_PROFILE_MAX_LEAD_H,
    ECMWF_VARIABLES,
    ENERGY_PERIOD_VARIABLES,
    GFSWAVE_VARIABLES,
    STATION_VARIABLES,
    VARIABLES,
    _station_pairs,
    build_scorecard,
    fit_diurnal_correction,
    join_wind,
    lead_time_scorecard,
    merge_bias_profiles,
    parse_marine_waves,
    render_bias_profile,
    render_diurnal_fit,
    render_lead_scorecard,
    render_pooled_lead,
    render_scorecard,
    skill_payload,
    station_bias_profile,
    wind_points,
    with_energy_period,
)

# multi-source archive keys: OM rows live at "<buoy>", GFS-Wave at "<buoy>.gfswave",
# ECMWF at "<buoy>.ecmwf"
GFSWAVE_KEY_SUFFIX = ".gfswave"
ECMWF_KEY_SUFFIX = ".ecmwf"
SOURCE_KEY_SUFFIX = {"om": "", "gfswave": GFSWAVE_KEY_SUFFIX, "ecmwf": ECMWF_KEY_SUFFIX}
SOURCE_VARIABLES = {"om": VARIABLES, "gfswave": GFSWAVE_VARIABLES, "ecmwf": ECMWF_VARIABLES}
# coastal-station archive keys: the published wind model (fetch.WEATHER_MODEL, GFS since
# 2026-08-30) lives at "<station>", the A/B member (fetch.WEATHER_AB_MODEL, ICON - the
# best_match model it replaced) at "<station>.icon". Same observations score both.
STATION_AB_KEY_SUFFIX = ".icon"
STATION_WIND_MODELS = {"gfs": "", "icon": STATION_AB_KEY_SUFFIX}

ARCHIVE_DIR = Path("data/verify/archive")
# coastal wind stations (rosa_pipeline.stations): the registry is committed, the archive of
# the model's wind at each station is VM-local like the buoy archive, one file per station
STATIONS_DIR = Path("data/stations")
STATIONS_ARCHIVE_DIR = Path("data/verify/stations")
ISRAMAR_DIR = Path("data/verify/isramar")  # local-only, gitignored (all-rights-reserved)
FEEDBACK_DIR = Path("data/verify/feedback")
BATHY_DIR = Path("data/spots/derived/bathy")  # committed per-spot depth profiles (Stage 2A)
TIDE_DIR = Path("data/spots/derived/tide")  # committed per-spot EOT20 constants (plan C1)
TIDE_GRIDS = Path("data/tide-src/ocean_tides")  # local EOT20 grids (gitignored, 2.1 GB)

# A shoaling wave cannot break at an arbitrary multiple of the sea that made it. Nothing
# between breaker_height_from_profile and the CDN inspects the MAGNITUDE of h_break - by
# design, the transform is the authority - but Rosa precomputes and serves static JSON, so
# a bad number ships to every client for a whole cycle with no request-time backend to catch
# it. This is the only place it can be seen. It WARNS, never clamps: no payload key, no
# rating moves, so it sits outside pb_0049's A/B gate.
# Measured on LIVE fleet data, across both swell regimes - and 3.0 was wrong.
# The committed capture is one Mediterranean point: short-period windswell, fleet-wide max
# ratio 2.012, nothing above 3. A live `run --all` (199 spots, 16,961 published hours with a
# usable sea) put 19 hours over 3 - every one of them a long-period Pacific groundswell on
# Central America (Tp 14.9-17.9 s), e.g. puerto-sandino 1.30 m from a 0.40 m sea at Tp 17.5 s.
# That is what a 17 s groundswell DOES when it shoals; the Med capture simply contains no
# example of it. Live p99.9 is 2.95 and the true maximum is 3.25, so 4.0 clears real physics
# with headroom while still catching the defect class this exists for - the 2026-08-15
# refraction singularity produced 8x-57x (up to 192.7 m from a 4.0 m swell).
# Re-derive this from a live fleet run, never from the fixture capture alone.
IMPLAUSIBLE_BREAK_RATIO = 4.0
# ...and below this the ratio is meaningless (see onjuku above): 0.04/0.02 is arithmetic, not
# a physics failure. The finding this guards against produces tens of metres, not centimetres.
IMPLAUSIBLE_BREAK_FLOOR_M = 0.5

# A few broken spots must not withhold the forecast from every other one. On 2026-08-28
# three shallow-profile spots raised the same ValueError, `run --all` returned 1, and
# publish.sh's ERR trap killed the cycle - so 621 healthy spots plus six freshly seeded
# regions sat off the CDN for a day over 3 failures. Same lesson as the archive coupling
# (OPEN-ITEMS 9): aborting turned one loss into many.
#
# So a run that failed only a small share of the fleet exits EXIT_PARTIAL instead of 1.
# publish.sh deploys on it and raises the admin alert; the failed spots keep serving their
# previous payload (prune is keyed on the DB, not on this run's output). Above the share, or
# with nothing published at all, it is still a hard failure - a schema break hits every spot
# and must never reach the CDN.
#
# 5% is deliberately far below any systemic fault (those are ~100%) and far above the
# handful of bad bathy profiles this exists for: 31 of 624 spots. It is a fleet-health
# threshold, not a tuned knob - widen it only with a reason written down here.
EXIT_PARTIAL = 4
PARTIAL_FAILURE_MAX_SHARE = 0.05


def _implausible_break_hours(spot: Spot, scored: list) -> list[tuple[str, float, float]]:
    """(iso hour, h_break_mid, largest in-window partition height) for every scored hour whose
    breaker height exceeds IMPLAUSIBLE_BREAK_RATIO x the sea that produced it. Report only."""
    out = []
    for s in scored:
        if s.h_break_mid < IMPLAUSIBLE_BREAK_FLOOR_M:
            continue
        # "in window" here is spread_exposure > 0, NOT the hard in_window() bearing test:
        # breaker_height_from_profile weights every partition by sqrt(spread_exposure), so a
        # train whose fan clips the window still delivers energy. Using the hard test as the
        # denominator undercounts the sea and fires on 42 perfectly sound hours.
        # Unweighted height, deliberately: the bound asks what the LARGEST train that reaches
        # this spot at all could possibly break as, so it must not be discounted first.
        seas = [
            p.height_m
            for p in s.hour.partitions
            if p.height_m > 0 and spread_exposure(p, spot.swell_window) > 0
        ]
        if not seas:
            continue
        largest = max(seas)
        if s.h_break_mid > IMPLAUSIBLE_BREAK_RATIO * largest:
            out.append((s.hour.time.isoformat(), s.h_break_mid, largest))
    return out


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rosa-pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="fetch, score and publish spot forecasts")
    which = run.add_mutually_exclusive_group(required=True)
    which.add_argument("--spot", help="spot id, e.g. beit-yanai")
    which.add_argument("--all", action="store_true", help="publish every spot in the DB")
    run.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    run.add_argument("--out", type=Path, default=Path("data/out"))
    run.add_argument(
        "--fixtures", type=Path, default=None, help="replay captured responses (offline)"
    )
    run.add_argument("--capture", type=Path, default=None, help="capture raw responses to this dir")
    run.add_argument(
        "--skill",
        type=Path,
        default=ARCHIVE_DIR.parent / "skill.json",
        help="measured horizon ceilings to publish (default data/verify/skill.json, "
        "written by `verify --archive --write-skill`). Point it at a candidate file to "
        "run the same-input A/B a ceiling change needs - CALIBRATION.md's rule - without "
        "touching the VM's real one; /dev/null (or any missing path) forces the static "
        "fallback, which is the A/B's control arm",
    )
    run.add_argument(
        "--bathy-dir",
        type=Path,
        default=BATHY_DIR,
        help="per-spot depth profiles to score against (default the committed set). Point "
        "it at a candidate cut to run the same-input A/B a bathymetry source swap needs - "
        "CALIBRATION.md's tuning rule - without touching the committed profiles",
    )
    run.add_argument(
        "--quota-state",
        type=Path,
        default=None,
        help="daily Open-Meteo budget ledger (default data/verify/quota.json, VM-local and "
        "gitignored). The minute cap is handled inside fetch.py; this guards the DAY cap, "
        "which an ad-hoc fleet run on top of the cron's four exhausted on 2026-08-15",
    )
    run.add_argument(
        "--ignore-quota",
        action="store_true",
        help="fetch even when today's budget is spent (still records the spend). For the "
        "operator who knows the allowance changed - not for the cron",
    )
    run.add_argument(
        "--ecmwf-fixtures",
        type=Path,
        default=None,
        help="replay captured ECMWF gribs (offline); with --fixtures alone the spectral "
        "member is skipped",
    )
    run.add_argument(
        "--tide-source",
        choices=["om", "eot20"],
        default="eot20",
        help="eot20 (default since 2026-08-15): tide synthesised locally from the "
        "committed per-spot EOT20 constants - zero quota, and it fills the day-10-16 "
        "tail the OM field leaves null. Flipped on its same-input fleet A/B "
        "(CALIBRATION.md 2026-08-15: 199 spots, max rating delta 1, 3 bucket-change "
        "hours, 10,283 tail hours gained tide). om: the pre-flip Open-Meteo field - "
        "kept as the fallback arm and for A/B replays",
    )
    run.add_argument(
        "--wave-source",
        choices=["om", "blend"],
        default="blend",
        help="blend (default since 2026-08-26): the GFS-Wave+ECMWF 50/50 blend "
        "(fetch-plane plan B), PROMOTED worldwide - waves come from global files "
        "downloaded once per cycle, so spot count no longer costs marine quota; weather "
        "+ SST/tide fallback still ride light OM requests. With --fixtures, expects "
        "gfsfull_*.grib2 + weather_*/marine_light_*.json captures in the fixtures dir. "
        "om: the per-spot Open-Meteo path - the fallback arm and the A/B replay arm "
        "(the committed OM fixtures replay through it)",
    )

    verify = sub.add_parser("verify", help="score the offshore model against buoy observations")
    target = verify.add_mutually_exclusive_group(required=True)
    target.add_argument("--buoy", help="buoy id from the registry, e.g. 46042")
    target.add_argument("--near", help="spot id - score the nearest in-range buoy(s)")
    target.add_argument(
        "--all-buoys",
        action="store_true",
        help="score every registered buoy (the scheduled fleet skill pass). ISRAMAR "
        "buoys are skipped: their data is manual-calibration-only (legal red line)",
    )
    target.add_argument(
        "--stations",
        action="store_true",
        help="score the model's 10 m wind against every coastal wind station "
        "(data/stations, METAR + IMS) by lead, plus a pooled fleet card. Needs --archive",
    )
    target.add_argument("--station", help="one station id (ICAO or IMS id); needs --archive")
    verify.add_argument(
        "--bias-profile",
        action="store_true",
        help="with --stations --archive: break the SAME pairs the lead card scores down "
        "by solar hour and by observed wind sector instead of by lead. The pooled bias at "
        "these stations is ~0, which a diurnal error would hide - this is the measurement "
        "OPEN-ITEMS 25 step 3 asks for before any correction is chosen",
    )
    verify.add_argument(
        "--wind-model",
        choices=sorted(STATION_WIND_MODELS),
        default="gfs",
        help="with --stations/--station: which archived wind model to score - gfs (the "
        "published model since 2026-08-30) or icon (the A/B member, best_match's ICON "
        "before that). Same METAR/IMS observations either way",
    )
    verify.add_argument("--stations-dir", type=Path, default=STATIONS_DIR)
    verify.add_argument("--stations-archive-dir", type=Path, default=STATIONS_ARCHIVE_DIR)
    verify.add_argument("--buoys-dir", type=Path, default=Path("data/buoys"))
    verify.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    verify.add_argument("--radius-km", type=float, default=150.0, help="--near search radius")
    verify.add_argument("--limit", type=int, default=1, help="--near: max buoys to score")
    verify.add_argument("--tol-min", type=int, default=30, help="model/obs time-match tolerance")
    verify.add_argument("--isramar-dir", type=Path, default=ISRAMAR_DIR)
    verify.add_argument(
        "--archive",
        action="store_true",
        help="score archived forecasts by lead time (instead of the live nowcast)",
    )
    verify.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    verify.add_argument(
        "--write-skill",
        action="store_true",
        help="with --archive: persist the lead-bucket Hs scorecard as skill.json, the "
        "measured horizon ceilings run --all publishes fleet-wide. Opt-in on purpose: "
        "it should only be written from a run covering the full buoy fleet, not the "
        "single-buoy spot checks",
    )
    verify.add_argument(
        "--spectra",
        action="store_true",
        help="validate the Stage-3b assumptions against the buoy's measured spectra "
        "(consistency proxy vs Qp, parametric spread vs sigma from r1)",
    )
    verify.add_argument(
        "--write-spread",
        action="store_true",
        help="with --spectra: persist the per-station, per-class measured spread as "
        "spread.json. Recording only - nothing reads it yet; NDBC realtime2 keeps ~45 "
        "days, so a window not written down cannot be re-pooled later",
    )
    verify.add_argument(
        "--source",
        choices=["om", "gfswave", "ecmwf"],
        default="om",
        help="with --archive: which archived source to score (Stage 3a/3b A/B). "
        "gfswave/ecmwf pair their peak period with buoy DPD",
    )
    verify.add_argument("--fixtures", type=Path, default=None, help="replay marine json (offline)")
    verify.add_argument("--obs-fixtures", type=Path, default=None, help="replay NDBC txt (offline)")
    verify.add_argument("--capture", type=Path, default=None, help="capture responses to this dir")

    archive = sub.add_parser(
        "archive", help="append the current forecast at buoys to the lead-time archive"
    )
    archive.add_argument("--buoy", help="one buoy id; default = every buoy in the registry")
    archive.add_argument("--buoys-dir", type=Path, default=Path("data/buoys"))
    archive.add_argument("--isramar-dir", type=Path, default=ISRAMAR_DIR)
    archive.add_argument("--archive-dir", type=Path, default=ARCHIVE_DIR)
    archive.add_argument(
        "--wave-source",
        choices=["om", "gfswave", "ecmwf", "both", "all"],
        default="all",
        help="which offshore sources to archive (Stage 3a/3b multi-source A/B; "
        "default all = om + gfswave + ecmwf, both = om + gfswave)",
    )
    archive.add_argument("--fixtures", type=Path, default=None, help="replay marine json (offline)")
    archive.add_argument(
        "--gfs-fixtures", type=Path, default=None, help="replay captured gribs (offline)"
    )
    archive.add_argument(
        "--ecmwf-fixtures", type=Path, default=None, help="replay captured ECMWF gribs (offline)"
    )
    archive.add_argument("--capture", type=Path, default=None, help="capture responses to this dir")
    archive.add_argument(
        "--stations-dir",
        type=Path,
        default=STATIONS_DIR,
        help="coastal wind-station registry; the model's 10 m wind is archived at each "
        "station (an empty or missing dir skips the arm)",
    )
    archive.add_argument("--stations-archive-dir", type=Path, default=STATIONS_ARCHIVE_DIR)
    archive.add_argument(
        "--wind-fixtures",
        type=Path,
        default=None,
        help="replay weather_<station>.json bodies for the station arm (offline)",
    )

    stations = sub.add_parser(
        "stations", help="coastal wind-station registry tools (data/stations/*.yaml)"
    )
    stations.add_argument(
        "--discover",
        choices=["metar", "ims"],
        required=True,
        help="print a registry yaml of every station within --radius-km of a spot: metar "
        "reads aviationweather.gov's worldwide cache (no key); ims reads the IMS station "
        "list (IMS_API_TOKEN) and keeps stations with a wind channel",
    )
    stations.add_argument("--radius-km", type=float, default=25.0)
    stations.add_argument("--spots-dir", type=Path, default=Path("data/spots"))

    fb = sub.add_parser("feedback", help="record/report surfer 👍👎 vs the published rating")
    fb.add_argument("--report", action="store_true", help="summarise instead of adding")
    fb.add_argument("--markdown", action="store_true", help="with --report: emit CALIBRATION rows")
    fb.add_argument("--spot", help="spot id (required when adding)")
    fb.add_argument("--verdict", choices=["up", "down"], help="👍/👎 (required when adding)")
    fb.add_argument("--observed-bucket", choices=list(BUCKET_ORDER))
    fb.add_argument("--observed-h", type=float, help="observed breaker height midpoint, m")
    fb.add_argument("--observed-phrase")
    fb.add_argument("--note")
    fb.add_argument(
        "--at",
        help="ISO time of the observation WITH a UTC offset, e.g. 2026-09-07T09:00+03:00 "
        "(default: now). A bare time is refused: payload hours are spot-local, so a naive "
        "value read as UTC would grade the session against the wrong forecast hour.",
    )
    fb.add_argument("--out", type=Path, default=Path("data/out"), help="published payload dir")
    fb.add_argument("--feedback-dir", type=Path, default=FEEDBACK_DIR)

    bathy = sub.add_parser(
        "bathy", help="sample each spot's shore-normal seabed depth profile (Stage 2A)"
    )
    which_b = bathy.add_mutually_exclusive_group(required=True)
    which_b.add_argument("--spot", help="spot id, e.g. beit-yanai")
    which_b.add_argument("--all", action="store_true", help="every spot in the DB")
    bathy.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    bathy.add_argument("--out", type=Path, default=BATHY_DIR, help="derived profile output dir")
    bathy.add_argument(
        "--fixtures", type=Path, default=None, help="replay a captured elevations map (offline)"
    )
    bathy.add_argument(
        "--capture", type=Path, default=None, help="capture the elevations map to this dir"
    )
    bathy.add_argument(
        "--sleep", type=float, default=1.0, help="seconds between spots (OpenTopoData rate limit)"
    )
    bathy.add_argument(
        "--source",
        choices=["opentopo", "local"],
        default="local",
        help="which GEBCO grid to cut from. local (default since 2026-09-11): the GEBCO "
        "2024 grid on disk, offline and uncapped - what every committed profile is cut "
        "with. opentopo: gebco2020 through the point API, the pre-swap source, kept for "
        "A/B only. It reads the NE Brazil shelf as 0 m for km and smooths reefs and "
        "headlands away (OPEN-ITEMS 17/23); never mix it into the committed set",
    )
    bathy.add_argument(
        "--grid",
        type=Path,
        default=None,
        help="path to the local GEBCO grid (default data/bathy/GEBCO_2024.nc, gitignored)",
    )

    sdb_p = sub.add_parser(
        "sdb",
        help="sample CMEMS coastal SDB along each spot's ray and report where it disagrees "
        "with the committed GEBCO profile (OPEN-ITEMS 23). --apply patches the profiles, "
        "which MOVES PUBLISHED HEIGHTS - see the tuning rule in CLAUDE.md",
    )
    which_s = sdb_p.add_mutually_exclusive_group(required=True)
    which_s.add_argument("--spot", help="spot id, e.g. cokes")
    which_s.add_argument("--all", action="store_true", help="every spot in the DB")
    sdb_p.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    sdb_p.add_argument("--bathy-dir", type=Path, default=BATHY_DIR)
    sdb_p.add_argument(
        "--apply",
        action="store_true",
        help="write the merged profiles. NOT the default: this is a source swap that moves "
        "published heights, so it needs a same-input A/B and a CALIBRATION.md entry first",
    )
    sdb_p.add_argument(
        "--min-delta", type=float, default=1.0, help="ignore disagreements below this (m)"
    )
    sdb_p.add_argument(
        "--max-quality",
        type=int,
        default=None,
        help="Quality_indicator ceiling, 0 (highly reliable) to 4 (unknown); default 2",
    )
    sdb_p.add_argument("--cache", type=Path, default=None, help="on-disk chunk cache dir")
    sdb_p.add_argument("--fixtures", type=Path, default=None, help="replay a captured SDB map")
    sdb_p.add_argument("--capture", type=Path, default=None, help="write an SDB fixture here")

    atl_p = sub.add_parser(
        "atl24",
        help="grade the committed profiles (and CMEMS SDB) against ICESat-2 ATL24 lidar. "
        "REPORTS ONLY - never writes a profile",
    )
    which_a = atl_p.add_mutually_exclusive_group(required=True)
    which_a.add_argument("--spot", help="spot id; the box is drawn around it")
    which_a.add_argument("--region", help="region stem, e.g. maldives")
    atl_p.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    atl_p.add_argument("--bathy-dir", type=Path, default=BATHY_DIR)
    atl_p.add_argument(
        "--radius-m", type=float, default=150.0, help="pair a ray point with photons inside this"
    )
    atl_p.add_argument("--pad-deg", type=float, default=0.05, help="box padding around the spots")
    atl_p.add_argument("--cache", type=Path, default=None, help="cache the photon pull here")
    atl_p.add_argument(
        "--sdb", action="store_true", help="also score CMEMS SDB at the same ray points"
    )
    atl_p.add_argument("--sdb-cache", type=Path, default=None, help="SDB chunk cache dir")

    tide_p = sub.add_parser(
        "tide",
        help="extract per-spot EOT20 tide constants (fetch-plane plan C1; needs the "
        "local grids). Writes committed constants; NOTHING consumes them until the "
        "switch lands with its same-input A/B - see CALIBRATION.md 2026-08-14",
    )
    which_t = tide_p.add_mutually_exclusive_group(required=True)
    which_t.add_argument("--spot", help="spot id, e.g. beit-yanai")
    which_t.add_argument("--all", action="store_true", help="every spot in the DB")
    tide_p.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    tide_p.add_argument("--grids", type=Path, default=TIDE_GRIDS, help="EOT20 ocean_tides dir")
    tide_p.add_argument("--out", type=Path, default=TIDE_DIR, help="constants output dir")
    tide_p.add_argument(
        "--verify",
        type=Path,
        default=None,
        metavar="OUT_DIR",
        help="also compare synthesis against the OM tide series in this published "
        "payload dir (e.g. data/out) - corr / offset / demeaned rmse per spot",
    )

    horizon = sub.add_parser(
        "horizon", help="derive a spot's swell_window from coastline geometry (reports only)"
    )
    which_h = horizon.add_mutually_exclusive_group(required=True)
    which_h.add_argument("--spot", help="spot id, e.g. santa-teresa")
    which_h.add_argument("--all", action="store_true", help="every spot in the DB")
    horizon.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    horizon.add_argument(
        "--fixtures", type=Path, default=None, help="replay a captured elevations map (offline)"
    )
    horizon.add_argument(
        "--capture", type=Path, default=None, help="capture the elevations map to this dir"
    )
    horizon.add_argument(
        "--sleep", type=float, default=1.0, help="seconds between spots (OpenTopoData rate limit)"
    )

    notify = sub.add_parser(
        "notify", help="send grouped swell-alert Web Pushes for new events (VM cron step)"
    )
    notify.add_argument("--out", type=Path, default=Path("data/out"), help="published payload dir")
    notify.add_argument(
        "--state",
        type=Path,
        default=Path("data/verify/push-state.json"),
        help="sent-event bookkeeping (VM-local, gitignored)",
    )
    notify.add_argument(
        "--subs-url", default=None, help="push API admin endpoint (default: $PUSH_SUBS_URL)"
    )
    notify.add_argument(
        "--vapid-key",
        type=Path,
        default=None,
        help="VAPID private key PEM (default: $VAPID_PRIVATE_KEY)",
    )
    notify.add_argument(
        "--vapid-sub", default=None, help="VAPID contact claim (default: $VAPID_SUB)"
    )
    notify.add_argument("--dry-run", action="store_true", help="plan and print, send nothing")

    alert = sub.add_parser(
        "alert", help="push an ops alert to the admin devices (publish.sh failure trap)"
    )
    alert.add_argument("--message", required=True, help="alert body text")
    alert.add_argument(
        "--subs",
        type=Path,
        default=Path.home() / "rosa-push" / "admin-subs.json",
        help="admin device subscription snapshot (VM-local)",
    )
    alert.add_argument(
        "--vapid-key",
        type=Path,
        default=None,
        help="VAPID private key PEM (default: $VAPID_PRIVATE_KEY)",
    )
    alert.add_argument(
        "--vapid-sub", default=None, help="VAPID contact claim (default: $VAPID_SUB)"
    )

    exp = sub.add_parser(
        "experiment",
        help="Stage-2E: grade candidate rideability transforms against the calibration frames",
    )
    exp.add_argument(
        "--frames",
        type=Path,
        default=Path("data/calibration/frames.yaml"),
        help="machine-readable eye frames distilled from docs/CALIBRATION.md",
    )
    exp.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    exp.add_argument("--bathy-dir", type=Path, default=BATHY_DIR)

    sm = sub.add_parser(
        "swellmap", help="publish animated wave-field frames per basin (SwellMap v0.2)"
    )
    sm.add_argument("--spots-dir", type=Path, default=Path("data/spots"))
    sm.add_argument("--out", type=Path, default=Path("data/out"))
    sm.add_argument("--basin", default=None, help="single basin name (default: all)")
    layer = sm.add_mutually_exclusive_group()
    layer.add_argument(
        "--skip-world", action="store_true", help="basins only - skip the global PNG layer"
    )
    layer.add_argument(
        "--world-only", action="store_true", help="global PNG layer only - skip the basins"
    )
    return parser


def group_by_point(spots: list[Spot]) -> dict[tuple[float, float], list[Spot]]:
    groups: dict[tuple[float, float], list[Spot]] = {}
    for spot in spots:
        groups.setdefault(spot.offshore_point, []).append(spot)
    return groups


def _cmd_run(args: argparse.Namespace) -> int:
    spots = load_spots(args.spots_dir)
    bathy_dir = getattr(args, "bathy_dir", None) or BATHY_DIR
    if args.all:
        targets = list(spots.values())
    else:
        target = spots.get(args.spot)
        if target is None:
            print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
            return 2
        targets = [target]

    now = datetime.now(UTC)
    # measured horizon ceilings from the verification harness, if `verify --archive`
    # has run and matured past its sample floor; None -> static defaults (2026-08-07).
    # Overridable (--skill) so the same-input A/B that CALIBRATION.md requires before any
    # ceiling change can be run offline against a candidate skill.json: skill.json and the
    # archive are gitignored VM-only state, which is exactly what left the 2026-08-12
    # partial-tier proposal unmeasurable and therefore deferred.
    skill = load_skill_ceilings(args.skill)

    # one deep-water sample per unique offshore point; each spot may have its own, so a
    # full run fetches them all in a single batched request (fetch_many) - no throttling.
    groups = group_by_point(targets)
    points = list(groups)

    # Daily-quota guard (rosa_pipeline.quota), live path only - a fixture replay costs
    # nothing and has to stay runnable on a spent day. This sits ahead of EVERY fetch,
    # including ECMWF's: a run that is going to be refused should not spend someone else's
    # bandwidth on the way to refusing. The spend is recorded BEFORE the fetch, not after:
    # a run that dies mid-fleet has still spent real vendor quota, and a ledger that only
    # counts clean exits under-counts exactly on the bad days - on 2026-08-16 that let a
    # fifth fleet run through into a certain daily-cap 429. Pre-charging can only ever
    # over-count (a refused-or-crashed run's partial spend is rounded up to a full one),
    # which errs toward refusing - the failure mode that costs a stale-but-serving payload
    # instead of a failed cycle.
    # The blend arm is charged too: its marine-light aux leg (SST + tide) rides the same
    # marine host at ~1.21 units/point (see quota.MARINE_LIGHT_UNITS_PER_POINT), and a
    # live blend run is by definition an ad-hoc run on top of the cron's four - the
    # scenario this guard exists for. Only the weights differ between the arms.
    om_arm = getattr(args, "wave_source", "om") != "blend"
    ledger: quota.Ledger | None = None
    if args.fixtures is None:
        ledger = quota.Ledger.load(args.quota_state)
        planned = (
            quota.marine_units(len(points)) if om_arm else quota.marine_light_units(len(points))
        )
        if not ledger.affords(planned) and not args.ignore_quota:
            print(ledger.refusal(planned), file=sys.stderr)
            return quota.EXIT_QUOTA_EXHAUSTED
        ledger.record(planned)

    # ECMWF spectral-lite member (Stage 3b) - guarded: an ECMWF outage must never sink
    # the forecast run. Offline replay (--fixtures) skips it unless --ecmwf-fixtures.
    # Fetched BEFORE the wave source because the blend arm reuses this same series as
    # its ECMWF blend member - one ECMWF fetch per run, never one per leg.
    spectral_series = [[] for _ in points]
    ecmwf_src: EcmwfWaves | None = None
    if args.ecmwf_fixtures is not None:
        ecmwf_src = EcmwfFixtureSource(args.ecmwf_fixtures)
    elif args.fixtures is None:
        ecmwf_src = EcmwfSource(capture_dir=args.capture)
    if ecmwf_src is not None:
        try:
            spectral_series = ecmwf_src.fetch_series(points)
        except Exception as e:
            print(f"warn: ecmwf spectral member skipped: {e}", file=sys.stderr)

    if getattr(args, "wave_source", "om") == "blend":
        # fetch-plane plan B: the A/B arm. Not promoted - see blend.py's module docstring.
        from .blend import (
            BlendedSource,
            GfsFullFixtureSource,
            GfsFullSource,
            fetch_aux_many,
            fixture_aux_many,
        )
        from .gwam import GwamFixtureSource, GwamSource
        from .oisst import OisstFixtureSource, OisstSource

        if args.fixtures is not None:
            blend_src = BlendedSource(
                gfs=GfsFullFixtureSource(args.fixtures),
                aux=lambda coords: fixture_aux_many(coords, args.fixtures),
                sst=OisstFixtureSource(args.fixtures),
                tp=GwamFixtureSource(args.fixtures),
            )
        else:
            blend_src = BlendedSource(
                gfs=GfsFullSource(capture_dir=args.capture),
                aux=lambda coords: fetch_aux_many(coords, capture_dir=args.capture),
                sst=OisstSource(capture_dir=args.capture),
                tp=GwamSource(capture_dir=args.capture),
            )
        raws = blend_src.fetch_many(points, ecmwf_series=spectral_series)
    else:
        source: ForecastSource = (
            FixtureSource(args.fixtures)
            if args.fixtures is not None
            else OpenMeteoSource(capture_dir=args.capture)
        )
        raws = source.fetch_many(points)

    published = 0
    implausible = 0
    stale_profiles = 0
    stale_tides = 0
    no_profile = 0
    failures: list[tuple[str, Exception]] = []
    tide_by_point: dict = {}
    if getattr(args, "tide_source", "om") == "eot20":
        from .tide import load_constants

        for point, group_spots in groups.items():
            # constants are extracted AT the offshore point, so any spot in the group
            # carries the same water - load by the first spot's id
            try:
                c = load_constants(TIDE_DIR, group_spots[0].id)
            except Exception as e:
                # A torn/hand-edited committed constants file must cost this point its
                # EOT20 tide - the OM column stands in, exactly as when the file is
                # missing - never the whole fleet run. This preload sat outside every
                # guard, so one unreadable JSON stranded all 199 spots before the first
                # publish (the per-spot-guard rule, one loop further out).
                c = None
                print(
                    f"warn: EOT20 constants for {group_spots[0].id} are unreadable "
                    f"({e!r}) - OM tide stands in at this point",
                    file=sys.stderr,
                )
            else:
                if c is None:
                    print(
                        f"warn: no EOT20 constants for {group_spots[0].id} - "
                        "OM tide stands in at this point",
                        file=sys.stderr,
                    )
                # ...and check the constants still belong to this point. Exactly the
                # rot DepthProfile.matches_spot is checked for a loop further in, for
                # exactly the same reason: `data/spots/derived/tide/*.json` is committed
                # state whose only guard is test_spots.py, and the VM cron is
                # `git pull` -> `run --all` with no CI in between - so a pin move or an
                # `offshore_bearing`/`offshore_km` edit pushed without a local pytest
                # publishes 4x/day off constants sampled where the spot used to be
                # (2026-08-27: 18 CA/OR/WA spots stale, `bandon` 12 km off).
                # It costs more here than on the bathy ray: since 2026-08-15 eot20 is the
                # DEFAULT arm and owns the whole column - extract_hours synthesises
                # tide_m for every hour from it and ignores the OM field, publish prints
                # it, and score_hour shifts the depth profile by it before the march, so
                # a stale set moves published breaker heights at macro-tidal spots.
                # WARNS, never substitutes: swapping in the OM column or dropping the
                # tide would move published heights fleet-wide, which is a pb_0049
                # tuning change, not a code fix.
                elif not c.matches_spot(group_spots[0]):
                    stale_tides += 1
                    print(
                        f"warn: {group_spots[0].id}: committed EOT20 tide constants no "
                        f"longer match the spot (sampled at {c.origin[0]}, {c.origin[1]}; "
                        f"the spot's offshore point is now {point[0]}, {point[1]}) - "
                        f"re-run `tide --spot {group_spots[0].id}`",
                        file=sys.stderr,
                    )
            tide_by_point[point] = c
    for point, raw, spectral in zip(points, raws, spectral_series, strict=True):
        try:
            hours = extract_hours(raw, spectral=spectral, tide_constants=tide_by_point.get(point))
        except Exception as e:
            # Per-POINT guard, one loop outside the per-spot one: a body that parses as
            # JSON but lacks the hourly schema (a capture torn mid-write, an old-schema
            # fixture, a per-location error object in a batched response) raised here
            # bare and stranded every LATER point's spots unpublished - the ghost-card
            # failure mode again. Damage, not a dry cell: count the point's spots as
            # failures so the cycle still exits 1 for publish.sh's trap.
            for spot in groups[point]:
                failures.append((spot.id, e))
            ids = ", ".join(s.id for s in groups[point])
            print(f"error: point {point} ({ids}): {e!r} - skipped", file=sys.stderr)
            continue
        if not hours:
            # a derived point that landed on a dry grid cell - skip its spots, keep going
            ids = ", ".join(s.id for s in groups[point])
            print(f"warning: no forecast at point {point} - skipping {ids}", file=sys.stderr)
            continue
        for spot in groups[point]:
            # Per-spot failure must not sink the batch. Every other step in this command is
            # already guarded this way (the ECMWF member above, the dry-cell skip above, the
            # gfswave/ecmwf archive members below); this loop was the one that ran bare. The
            # batch IS the product - there is no request-time backend - so a spot that never
            # gets written silently serves its previous payload, and an unguarded raise here
            # strands every spot after it AND skips prune_index, which is exactly how removed
            # spots shipped as ghost cards from 2026-07-23 to 2026-08-02.
            try:
                profile = load_profile(spot.id, bathy_dir)
                # ...and check the ray still belongs to this spot. DepthProfile.matches_spot
                # exists for exactly this and nothing on the publish path asked it: a profile
                # goes stale when the pin moves or `shore_normal` is re-cut without a new
                # `bathy` sweep, and the depths then describe a different piece of seabed -
                # the Fishermen Bay failure (102 deg out, 69% of hours at 0.0-0.1 m). The
                # committed suite catches it (test_spots.py), but there is no CI: the VM cron
                # is `git pull` -> `run --all`, so a YAML edit pushed without a local pytest
                # publishes 4x/day off the old ray with nothing said.
                # WARNS, never substitutes: dropping or swapping the depths would move
                # published heights fleet-wide, which is a pb_0049 tuning change. Fires on
                # nothing in the DB as it stands (265/265 profiles match, 2026-08-16).
                if profile is not None and not profile.matches_spot(spot):
                    stale_profiles += 1
                    print(
                        f"warn: {spot.id}: committed bathy profile no longer matches the "
                        f"spot (cast from {profile.origin_lat}, {profile.origin_lon} aiming "
                        f"{profile.bearing_seaward_deg:.1f} deg; spot is at {spot.lat}, "
                        f"{spot.lon} aiming {spot.shore_normal:.1f} deg) - re-run "
                        f"`bathy --spot {spot.id}`",
                        file=sys.stderr,
                    )
                wet_samples = profile.wet_samples_deep_to_shallow() if profile else None
                if profile is None:
                    no_profile += 1
                scored = [score_hour(spot, h, wet_samples) for h in hours]
                payload = build_payload(
                    spot,
                    scored,
                    fetched_at=raw.fetched_at,
                    now=now,
                    skill=skill,
                    wave_source=getattr(args, "wave_source", "om"),
                    model_run=raw.model_run,
                )
                path = write_spot_json(payload, args.out)
                update_index(payload, args.out)
            except Exception as e:
                # repr, not str: losing the exception type on a batch of 199 makes a systemic
                # fault unreadable. The count and the first type are echoed in the summary.
                failures.append((spot.id, e))
                print(f"error: {spot.id}: {e!r}", file=sys.stderr)
                continue
            for iso, h_mid, sea in _implausible_break_hours(spot, scored):
                print(
                    f"warn: {spot.id} {iso}: h_break_mid {h_mid:.2f} m from a {sea:.2f} m sea",
                    file=sys.stderr,
                )
                implausible += 1
            current = payload["current"]
            published += 1
            print(
                f"{spot.id}: {current['bucket']} {current['rating']}/100 · {current['phrase']} "
                f"· wind {current['wind']['class']} {current['wind']['kph']} kph → {path}"
            )
    if published == 0:
        print("no spots published", file=sys.stderr)
        return 1
    if args.all:
        # the DB is the authority on what exists - prune anything it no longer lists.
        # Guarded by published > 0 above so a failed run can never empty the index,
        # and keyed on the DB (not this run's output) so a spot skipped for a dry
        # grid cell keeps its last payload instead of vanishing.
        removed = prune_index(set(spots), args.out)
        if removed:
            print(f"pruned {len(removed)} spot(s) no longer in the DB: {', '.join(removed)}")
    if stale_profiles:
        # beside the failure summary like the implausible-break count: the cycle published,
        # but its bathymetry is describing seabed the spots have moved away from.
        print(
            f"warn: {stale_profiles} spot(s) published off a bathy profile cast from "
            "superseded coordinates - re-cut them with `bathy` (see warn lines above)",
            file=sys.stderr,
        )
    if stale_tides:
        # beside the stale-profile summary, and for the same reason: the cycle published,
        # but its tide - and every breaker height the tide shifted - describes water the
        # spots have moved away from.
        print(
            f"warn: {stale_tides} offshore point(s) published off EOT20 constants sampled "
            "at superseded coordinates - re-cut them with `tide` (see warn lines above)",
            file=sys.stderr,
        )
    if no_profile:
        print(
            f"warn: {no_profile} spot(s) published without a bathy profile (q(T) fallback) "
            "- cut them with `bathy --spot <id>`",
            file=sys.stderr,
        )
    if implausible:
        # beside the failure summary, not inside it: a run that publishes an implausible
        # height still publishes, so this is a signal to read - not a failed cycle.
        print(
            f"warn: {implausible} published hour(s) broke above "
            f"{IMPLAUSIBLE_BREAK_RATIO:.0f}x their in-window sea (see warn lines above)",
            file=sys.stderr,
        )
    dropped = len(targets) - published - len(failures)
    if dropped:
        # The per-point "no forecast at point" skip, summarised - every other partial
        # outcome of this command already is (implausible, stale_profiles, failures), and
        # this is the only one that costs a spot its refresh outright. Derived rather than
        # counted: a spot ends this loop published, failed, or skipped, never two of them.
        #
        # Worth a line because "a dry grid cell" is not the only way in. Both wave sources
        # turn a total outage into an EMPTY SERIES rather than an exception
        # (blend.GfsFullSource._get and ecmwf._get_step return None on every non-200 and
        # every httpx error - the shape _warn_member_empty was added to `archive` for), so
        # one NOMADS box out for a cycle empties `extract_hours` for every spot in it. Boxes
        # cluster by region (gfswave.CLUSTER_SPAN_DEG = 20 deg), so the unit of loss is a
        # coast. Those spots keep serving their previous payload, up to 6 h stale by the next
        # cron slot, and until now the cycle said only "published N" and exited 0.
        # Exit code deliberately unchanged: a partial cycle is a signal to read, not a
        # failure, and publish.sh's trap keys on the code.
        print(
            f"warn: {dropped} of {len(targets)} spot(s) published nothing - their offshore "
            "point returned no forecast hours (see the 'no forecast at point' lines above). "
            "A dry grid cell does this; so does a wave-source box that was out this cycle, "
            "which empties the series rather than raising. They keep serving their previous "
            "payload.",
            file=sys.stderr,
        )
    if failures:
        # Still a failed cycle for publish.sh's trap - but only after doing every piece of
        # work that could be done, prune included (it is keyed on the DB, not on this run's
        # output, so a failed spot is never pruned for having failed). A schema break that
        # hits all 199 spots reads as 199 lines plus this summary, not one traceback.
        attempted = published + len(failures)
        kinds = ", ".join(sorted({type(e).__name__ for _, e in failures}))
        print(
            f"error: {len(failures)} of {attempted} spot(s) failed ({kinds}): "
            f"{', '.join(sid for sid, _ in failures)}",
            file=sys.stderr,
        )
        if len(failures) / attempted <= PARTIAL_FAILURE_MAX_SHARE:
            print(
                f"warn: publishing the other {published} spot(s) anyway - "
                f"{len(failures)}/{attempted} is under the "
                f"{PARTIAL_FAILURE_MAX_SHARE:.0%} fleet-failure share. The failed spots keep "
                "serving their previous payload; fix them before they go stale.",
                file=sys.stderr,
            )
            return EXIT_PARTIAL
        return 1
    return 0


def _obs_for(buoy: Buoy, args: argparse.Namespace):
    if buoy.source == "isramar":
        # never fetched - reads the local manual-import csv only (all-rights-reserved)
        return ISRAMARLocalSource(args.isramar_dir).fetch(buoy)
    if buoy.source == "cmems":
        if getattr(args, "obs_fixtures", None) is not None:
            return CMEMSFixtureSource(args.obs_fixtures).fetch(buoy)
        return CMEMSSource(capture_dir=args.capture).fetch(buoy)
    if getattr(args, "obs_fixtures", None) is not None:
        return NDBCFixtureSource(args.obs_fixtures).fetch(buoy)
    return NDBCSource(capture_dir=args.capture).fetch(buoy)


def _with_measured_energy_period(
    buoy: Buoy, obs: list, args: argparse.Namespace, variables: tuple
) -> tuple[list, tuple]:
    """Enrich observations with Tm-1,0 from the station's spectra, for a like-for-like
    period comparison against Open-Meteo (which serves Tm-1,0, not APD/Tm02).

    Falls back to the labelled APD pairing - loudly - whenever the station publishes no
    spectra, so a scorecard is never silently built on the definitional +2 s offset."""
    reason = ""
    if buoy.source != "ndbc":
        reason = f"source {buoy.source!r} publishes no spectra"
    else:
        try:
            src = (
                SpectraFixtureSource(args.obs_fixtures)
                if args.obs_fixtures is not None
                else NDBCSpectraSource(capture_dir=args.capture)
            )
            measures = [m for m in (measure(s) for s in src.fetch(buoy)) if m]
        except (OSError, httpx.HTTPError) as exc:
            measures, reason = [], f"spectra unavailable ({type(exc).__name__})"
        if not reason and not measures:
            reason = "station publishes no spectral files"
        if not reason:
            enriched = with_energy_period(obs, measures, tol_min=args.tol_min)
            if any(o.tm_m10_s is not None for o in enriched):
                return enriched, ENERGY_PERIOD_VARIABLES
            reason = "no spectrum within tolerance of any observation"
    print(f"{buoy.id}: period vs APD - {reason}", file=sys.stderr)
    return obs, variables


def _model_for(buoy: Buoy, args: argparse.Namespace, marine: dict | None = None):
    """Nowcast model series for one buoy. ``marine`` short-circuits the per-buoy fetch
    with a body a fleet batch already pulled (fetch_marine_waves_many) - same response
    shape, so capture files and parse_marine_waves are unaffected either way."""
    if marine is None:
        if args.fixtures is not None:
            marine = json.loads(
                (args.fixtures / f"marine_{buoy.id}.json").read_text(encoding="utf-8")
            )
        else:
            marine = fetch_marine_waves(buoy.lat, buoy.lon)
    if args.fixtures is None and args.capture is not None:
        args.capture.mkdir(parents=True, exist_ok=True)
        (args.capture / f"marine_{buoy.id}.json").write_text(json.dumps(marine), encoding="utf-8")
    return parse_marine_waves(marine)


def _station_obs_for(station: Station, args: argparse.Namespace):
    fixtures = getattr(args, "obs_fixtures", None)
    if station.source == "ims":
        if fixtures is not None:
            return IMSFixtureSource(fixtures).fetch(station)
        return IMSSource(capture_dir=args.capture).fetch(station)
    if fixtures is not None:
        return MetarFixtureSource(fixtures).fetch(station)
    return MetarSource(capture_dir=args.capture).fetch(station)


def _cmd_verify_stations(args: argparse.Namespace) -> int:
    """Lead-time wind skill at the coastal stations - the per-station cards and one pooled
    fleet card. Wind only: STATION_VARIABLES. Degrades per station like the buoy pass."""
    if not args.archive:
        print("--stations/--station score the archive only: add --archive", file=sys.stderr)
        return 2
    stations = load_stations(args.stations_dir)
    if args.station:
        st = stations.get(str(args.station))
        if st is None:
            print(
                f"unknown station {args.station!r}; known: {', '.join(sorted(stations))}",
                file=sys.stderr,
            )
            return 2
        targets = [st]
    else:
        targets = sorted(stations.values(), key=lambda s: s.id)
    if not targets:
        print(f"no stations registered under {args.stations_dir}")
        return 0
    store = FileArchiveStore(args.stations_archive_dir)
    wind_model = getattr(args, "wind_model", "gfs")
    key_suffix = STATION_WIND_MODELS[wind_model]
    print(f"wind model: {wind_model} (archive key '<station>{key_suffix}')")
    cards: list[dict] = []
    profiles: list[dict] = []
    all_pairs: list = []
    scored = 0
    failures: list[tuple[str, Exception]] = []
    for st in targets:
        rows = store.read(st.id + key_suffix)
        if not rows:
            print(
                f"{st.id}: no archived {wind_model} wind yet - "
                "the archive arm fills this each cycle"
            )
            continue
        try:
            obs = _station_obs_for(st, args)
            by_lead = lead_time_scorecard(
                rows, obs, tol_min=args.tol_min, variables=STATION_VARIABLES
            )
        except Exception as e:
            if args.station:
                raise
            failures.append((st.id, e))
            print(f"{st.id}: FAILED ({e}) - left out of this station pass", file=sys.stderr)
            continue
        print(render_lead_scorecard(st, by_lead, kind="station"))
        cards.append(by_lead)
        if getattr(args, "bias_profile", False):
            profiles.append(station_bias_profile(rows, obs, lon=st.lon, tol_min=args.tol_min))
            all_pairs.extend(
                _station_pairs(
                    rows,
                    obs,
                    lon=st.lon,
                    tol_min=args.tol_min,
                    max_lead_h=BIAS_PROFILE_MAX_LEAD_H,
                )
            )
        scored += 1
    if not args.station:
        print(
            render_pooled_lead(
                cards,
                f"pooled coastal wind skill ({wind_model}) - {scored} of {len(targets)} station(s)",
            )
        )
    if profiles:
        print()
        print(
            render_bias_profile(
                merge_bias_profiles(profiles),
                f"pooled ({wind_model}, {len(profiles)} station(s))",
            )
        )
        print()
        table, stats = fit_diurnal_correction(sorted(all_pairs))
        print(render_diurnal_fit(table, stats, f"pooled ({wind_model})"))
    if failures:
        kinds = ", ".join(sorted({type(e).__name__ for _, e in failures}))
        print(
            f"error: {len(failures)} of {len(targets)} station(s) failed ({kinds}): "
            f"{', '.join(sid for sid, _ in failures)}",
            file=sys.stderr,
        )
    return 1 if failures and not scored else 0


def _cmd_verify(args: argparse.Namespace) -> int:
    if getattr(args, "stations", False) or getattr(args, "station", None):
        return _cmd_verify_stations(args)
    buoys = load_all_buoys(args.buoys_dir, args.isramar_dir)

    targets: list[tuple[Buoy, float | None]]
    if getattr(args, "all_buoys", False):
        targets = []
        for b in sorted(buoys.values(), key=lambda b: b.id):
            if b.source == "isramar":
                # legal red line (CLAUDE.md): ISRAMAR data is all-rights-reserved,
                # manual validation during calibration only - a scheduled fleet
                # pass must never read it
                print(f"{b.id}: skipped - ISRAMAR obs are manual-calibration-only")
                continue
            targets.append((b, None))
    elif args.buoy:
        buoy = buoys.get(str(args.buoy))
        if buoy is None:
            print(f"unknown buoy {args.buoy!r}; known: {', '.join(sorted(buoys))}", file=sys.stderr)
            return 2
        targets = [(buoy, None)]
    else:
        spots = load_spots(args.spots_dir)
        spot = spots.get(args.near)
        if spot is None:
            print(f"unknown spot {args.near!r}", file=sys.stderr)
            return 2
        near = nearest_buoys(spot.lat, spot.lon, buoys, radius_km=args.radius_km, limit=args.limit)
        if not near:
            print(
                f"no buoy within {args.radius_km:.0f} km of {spot.name} - "
                "no open wave truth here.\n  (eastern-Med spots are validated via "
                "ISRAMAR, local-only, + the surfer 👍👎 loop)"
            )
            return 0
        targets = list(near)

    # Fleet nowcast: one comma-joined Open-Meteo request for every buoy instead of a
    # fresh TCP+TLS handshake per station - the shape _cmd_archive's fleet branch
    # already uses (15 calls/cycle -> 1, one response to guard instead of fifteen coin
    # flips). --buoy/--near keep the per-buoy path on purpose: there a single station's
    # failure IS the answer the operator asked for. A batch that fails costs every
    # buoy's nowcast instead of one, so it is recorded per buoy and reported by the
    # existing per-buoy guard below, exactly as _cmd_archive does it.
    batched: dict[str, dict | Exception] = {}
    if (
        getattr(args, "all_buoys", False)
        and not args.archive
        and not args.spectra
        and args.fixtures is None
    ):
        try:
            marines = fetch_marine_waves_many([(b.lat, b.lon) for b, _ in targets])
        except Exception as e:
            batched = {b.id: e for b, _ in targets}
            print(
                f"error: open-meteo batch failed ({e!r}) - no buoy scores this pass",
                file=sys.stderr,
            )
        else:
            batched = {b.id: m for (b, _), m in zip(targets, marines, strict=True)}

    # per-buoy lead scorecards for the om (published-model) source, persisted as
    # skill.json after the loop - the harness output publish's horizon ceilings read
    skill_by_lead: list[dict] = []
    skill_buoys: list[str] = []
    # --spectra reports, persisted as spread.json on request
    spread_reports: list[SpectraReport] = []
    # what the pass actually managed, so it can say so at the end (the run --all /
    # archive / bathy --all summary shape). `scored` counts buoys that produced a
    # card; a buoy skipped on purpose (non-NDBC under --spectra) is neither.
    scored = 0
    failures: list[tuple[str, Exception]] = []
    for buoy, dist in targets:
        try:
            if args.spectra:
                # measured-spectra validation needs NDBC spectral files, which only NDBC has.
                # Inside the guard, not before it: this branch does its own live NDBC fetch,
                # so `--all-buoys --spectra` used to lose every later station to the first
                # station's outage - the one fleet loop in this command still running bare.
                if buoy.source != "ndbc":
                    print(
                        f"{buoy.id}: no public spectral files for source {buoy.source!r} - skipped"
                    )
                    continue
                src = (
                    SpectraFixtureSource(args.obs_fixtures)
                    if args.obs_fixtures is not None
                    else NDBCSpectraSource(capture_dir=args.capture)
                )
                specs = src.fetch(buoy)
                if not specs:
                    print(f"{buoy.id}: no spectral files published - met-only or non-spectral buoy")
                    continue
                report = build_report(specs)
                spread_reports.append(report)
                print(render_spectra_report(buoy, report))
                scored += 1
                continue
            # Decided already: with the fleet nowcast batch gone this buoy cannot be
            # scored, so raise BEFORE the observation and spectra fetches below. Those
            # are two live requests per buoy (NDBC realtime2 + the spectral files that
            # `_with_measured_energy_period` pulls) whose results the batch failure has
            # made unusable - 30 requests across the fleet, spent to produce the same
            # FAILED line either way.
            prefetched = batched.get(buoy.id)
            if isinstance(prefetched, Exception):
                raise prefetched  # the batch's failure, reported as this buoy's
            obs = _obs_for(buoy, args)
            source = args.source if args.archive else "om"
            variables = SOURCE_VARIABLES[source]
            if source == "om":
                # like-for-like period: Open-Meteo serves Tm-1,0, the met file only APD (Tm02)
                obs, variables = _with_measured_energy_period(buoy, obs, args, variables)
            if args.archive:
                key = buoy.id + SOURCE_KEY_SUFFIX[args.source]
                rows = FileArchiveStore(args.archive_dir).read(key)
                by_lead = lead_time_scorecard(
                    rows,
                    obs,
                    tol_min=args.tol_min,
                    variables=variables,
                )
                print(render_lead_scorecard(buoy, by_lead))
                if source == "om":
                    skill_by_lead.append(by_lead)
                    skill_buoys.append(buoy.id)
            else:
                model = _model_for(buoy, args, marine=prefetched)
                scores = build_scorecard(model, obs, tol_min=args.tol_min, variables=variables)
                print(render_scorecard(buoy, dist, scores))
            scored += 1
        except Exception as e:
            # the fleet pass degrades per buoy (same philosophy as run --all per
            # spot): one obs outage drops that buoy from this skill measurement
            # instead of killing the cycle's whole pass. A targeted run still
            # raises - there a failure is the answer the operator asked for.
            if not getattr(args, "all_buoys", False):
                raise
            failures.append((buoy.id, e))
            print(f"{buoy.id}: FAILED ({e}) - left out of this skill pass", file=sys.stderr)
    if skill_by_lead and getattr(args, "write_skill", False):
        # Opt-in (--write-skill), because this file is FLEET-WIDE state: run --all
        # feeds it to every spot's ceiling, and the deploy README's single-buoy spot
        # check (`verify --buoy 46042 --archive`) must not silently clobber a
        # full-fleet measurement with one Pacific station's skill. Sits next to the
        # archive dir (data/verify/skill.json), never inside it - the archive holds
        # append-only forecast rows, this is derived and rewritable. Written via
        # tmp+replace so a killed run can't leave the torn file load_skill_ceilings
        # then has to throw away.
        skill_path = args.archive_dir.parent / "skill.json"
        skill_path.parent.mkdir(parents=True, exist_ok=True)
        payload = skill_payload(
            skill_by_lead,
            generated=datetime.now(UTC).isoformat(timespec="seconds"),
            buoy_ids=skill_buoys,
        )
        tmp = skill_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
        tmp.replace(skill_path)
        print(f"skill: wrote {skill_path} (buoys: {', '.join(sorted(skill_buoys))})")
    elif skill_by_lead:
        print("skill: not persisted (pass --write-skill to update the published ceilings)")
    elif getattr(args, "write_skill", False):
        # --write-skill only ever collects the om source (the model run --all publishes);
        # a Stage-3a/3b A/B pass asks for it and would otherwise get scorecards, no
        # skill.json and not one word about why. Say what did not happen.
        why = (
            f"--source {args.source!r} is an A/B member, not the published model"
            if args.archive and args.source != "om"
            else "no archived om scorecards in this pass"
        )
        print(f"skill: nothing to persist - {why}", file=sys.stderr)
    if getattr(args, "write_spread", False):
        # Opt-in and recording-only. The harness already builds these numbers every run
        # and then prints them away; this is the step that lets a window survive NDBC's
        # ~45-day realtime2 horizon. Nothing consumes spread.json - making the measured
        # spread SCORE is a calibration change (CALIBRATION.md + a Stage-0 A/B), not
        # this. Sits beside skill.json in data/verify, same tmp+replace idiom, since
        # both are derived and rewritable rather than append-only archive rows.
        if not spread_reports:
            why = (
                "no station published usable spectra"
                if args.spectra
                else "--write-spread needs --spectra"
            )
            print(f"spread: nothing to persist - {why}", file=sys.stderr)
        else:
            spread_path = args.archive_dir.parent / "spread.json"
            spread_path.parent.mkdir(parents=True, exist_ok=True)
            payload = spread_payload(
                spread_reports,
                generated=datetime.now(UTC).isoformat(timespec="seconds"),
            )
            tmp = spread_path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
            tmp.replace(spread_path)
            print(f"spread: wrote {spread_path} ({len(spread_reports)} station(s))")
    if failures:
        # Say what was lost, the way _cmd_run / _cmd_archive / _cmd_bathy do - and only
        # after every buoy that could be scored has been, skill.json included. Without
        # this a fleet pass that lost stations left N scattered FAILED lines and no
        # count, so nothing downstream could tell "one dead buoy" from "the whole pass".
        kinds = ", ".join(sorted({type(e).__name__ for _, e in failures}))
        print(
            f"error: {len(failures)} of {len(targets)} buoy(s) failed ({kinds}): "
            f"{', '.join(bid for bid, _ in failures)}",
            file=sys.stderr,
        )
    # A pass that scored SOMETHING is a degraded pass, not a failed one: dropping a dead
    # station and measuring the rest is the documented contract (see the per-buoy guard
    # above, pinned by test_cli.py::test_verify_all_buoys_fleet_pass). A pass that scored
    # NOTHING measured nothing - a total obs outage, or the fleet nowcast batch failing -
    # and until now exited 0, which is why publish.sh's own
    #   || echo "warn: skill measurement failed - published ceilings stay as-is"
    # could never fire and the published ceilings could go stale in silence.
    return 1 if failures and not scored else 0


def _archive_om_rows(
    store: FileArchiveStore, args: argparse.Namespace, now: datetime, buoy: Buoy, model
) -> int:
    """Archive one buoy's om rows; returns how many, so the arm can total them."""
    rows = rows_from_model(now, model)
    store.append(buoy.id, rows)
    stamp = now.isoformat(timespec="seconds")
    print(
        f"{buoy.id}: archived {len(rows)} forecast rows @ {stamp}"
        f" → {args.archive_dir / (buoy.id + '.jsonl')}"
    )
    return len(rows)


def _is_replay(args: argparse.Namespace) -> bool:
    """Was `archive` asked to replay captured responses instead of fetching? True when any
    of its "(offline)" fixture flags is set - the wave members each honour their own, and
    this is what lets the arms that have no flag of their own honour them too."""
    return any(
        getattr(args, name, None) is not None
        for name in ("fixtures", "gfs_fixtures", "ecmwf_fixtures")
    )


def _warn_member_empty(member: str, rows: int, targets: list, noun: str = "buoy") -> None:
    """An A/B member that archived NOTHING at any buoy has to say so, once, on stderr.

    The per-step fetchers turn every non-200 and every httpx error into a missing step
    (ecmwf._get_step, gfswave._get), so a total outage is not an exception - it is an
    empty series, which archives 0 rows per buoy and returns a clean exit. The existing
    `warn: <member> archive skipped` line only fires when something RAISES, so the one
    failure mode that costs the whole cycle's rows for this member is the one that says
    the least. The archive is append-only and cannot be back-filled, so those hours are
    gone; the A/B scorecard just gets quieter. Same shape as _cmd_run's `implausible` /
    `stale_profiles` summaries: a signal to read, never a failed cycle - the essential
    OM archive still decides the exit code."""
    if targets and rows == 0:
        print(
            f"warn: {member} archived 0 rows at all {len(targets)} {noun}(s) - the member "
            "fetched nothing this cycle (outage or a moved endpoint); these hours cannot "
            "be back-filled",
            file=sys.stderr,
        )


def _archive_stations(args: argparse.Namespace, now: datetime) -> None:
    """The coastal-station arm: the model's 10 m wind at every registered station, one
    weather-host request for the whole registry (2 vars, ~1 unit/point - ~90 units a
    cycle at 90 stations, not charged to the marine ledger, same choice as the buoy
    archive). Guarded top to bottom: this is evidence, and it must never sink the
    essential buoy archive or fail the cycle."""
    stations = load_stations(args.stations_dir)
    if not stations:
        return
    if args.wind_fixtures is None and args.fixtures is not None:
        # The OM arm's own fixture flag (`--fixtures`) means this run is offline for the
        # marine side. A partial replay (`--gfs-fixtures` or `--ecmwf-fixtures` only) is
        # live by construction - the OM arm still fetches, so the station arm should too.
        # Skipping is the honest answer only when the OM arm itself is offline.
        print(
            "warn: station arm skipped - this is a fixture replay (offline) and "
            "--wind-fixtures was not given",
            file=sys.stderr,
        )
        return
    targets = sorted(stations.values(), key=lambda s: s.id)
    store = FileArchiveStore(args.stations_archive_dir)
    coords = [(st.lat, st.lon) for st in targets]
    ab_bodies: list[dict | None]
    try:
        if args.wind_fixtures is not None:
            bodies = [
                json.loads(
                    (args.wind_fixtures / f"weather_{st.id}.json").read_text(encoding="utf-8")
                )
                for st in targets
            ]
            ab_bodies = []
            for st in targets:
                f = args.wind_fixtures / f"weather_{st.id}{STATION_AB_KEY_SUFFIX}.json"
                ab_bodies.append(json.loads(f.read_text(encoding="utf-8")) if f.exists() else None)
        else:
            bodies = fetch_wind_many(coords, model=WEATHER_MODEL)
            # the A/B member is the more expendable of the two: lose it, keep the
            # published model's rows
            try:
                ab_bodies = list(fetch_wind_many(coords, model=WEATHER_AB_MODEL))
            except Exception as e:
                print(
                    f"warn: station {WEATHER_AB_MODEL} batch failed ({e!r}) - "
                    "A/B member skipped this run",
                    file=sys.stderr,
                )
                ab_bodies = [None] * len(targets)
    except Exception as e:
        print(f"warn: station wind batch failed ({e!r}) - station arm skipped", file=sys.stderr)
        return
    total = 0
    for st, body, ab in zip(targets, bodies, ab_bodies, strict=True):
        try:
            if args.capture is not None and args.wind_fixtures is None:
                args.capture.mkdir(parents=True, exist_ok=True)
                (args.capture / f"weather_{st.id}.json").write_text(
                    json.dumps(body), encoding="utf-8"
                )
                if ab is not None:
                    (args.capture / f"weather_{st.id}{STATION_AB_KEY_SUFFIX}.json").write_text(
                        json.dumps(ab), encoding="utf-8"
                    )
            rows = rows_from_model(now, wind_points(body))
            store.append(st.id, rows)
            total += len(rows)
            n_ab = 0
            if ab is not None:
                ab_rows = rows_from_model(now, wind_points(ab))
                store.append(st.id + STATION_AB_KEY_SUFFIX, ab_rows)
                n_ab = len(ab_rows)
            print(
                f"{st.id}: archived {len(rows)} wind rows ({WEATHER_MODEL})"
                f" + {n_ab} ({WEATHER_AB_MODEL})"
                f" → {args.stations_archive_dir / (st.id + '.jsonl')}"
            )
        except Exception as e:
            print(f"warn: {st.id}: {e!r} - station left out of this run", file=sys.stderr)
    # Same silent shape as the wave members: the batch guard above catches a raise, but a
    # 200 that parses to no hours archives 0 rows at every station and returns cleanly -
    # 89 lines of "archived 0 wind rows" and no summary. Only the published model is
    # totalled: the A/B member has its own warn on the one path that can empty it.
    _warn_member_empty(WEATHER_MODEL, total, targets, noun="station")


def _cmd_archive(args: argparse.Namespace) -> int:
    buoys = load_all_buoys(args.buoys_dir, args.isramar_dir)
    if args.buoy:
        buoy = buoys.get(str(args.buoy))
        if buoy is None:
            print(f"unknown buoy {args.buoy!r}; known: {', '.join(sorted(buoys))}", file=sys.stderr)
            return 2
        targets = [buoy]
    else:
        targets = list(buoys.values())

    store = FileArchiveStore(args.archive_dir)
    now = datetime.now(UTC)
    failures: list[tuple[str, Exception]] = []
    om_total = 0
    om_batch_failed = False
    if args.wave_source in ("om", "both", "all"):
        # Failure must not sink the fleet run (same philosophy as run --all per spot
        # and verify --all-buoys per buoy): the archive is append-only and can never
        # be back-filled, so an unguarded Open-Meteo hiccup cost every later buoy
        # this run's rows for ALL sources - the guarded gfswave/ecmwf members below
        # never even started. A targeted --buoy run still raises: there the failure
        # is the answer the operator asked for.
        if args.buoy or args.fixtures is not None:
            # targeted or fixture-fed: per-buoy fetch (fixtures are per-buoy files;
            # nothing to batch)
            for buoy in targets:
                try:
                    model = _model_for(buoy, args)
                except Exception as e:
                    if args.buoy:
                        raise
                    failures.append((buoy.id, e))
                    print(
                        f"error: {buoy.id}: {e!r} - left out of this archive run",
                        file=sys.stderr,
                    )
                    continue
                if args.fixtures is None:
                    # live targeted run: same wind join as the fleet path (plan C3
                    # evidence); guarded - wind is decision data, waves are the spine
                    try:
                        [wind] = fetch_wind_many([(buoy.lat, buoy.lon)])
                        model = join_wind(model, wind)
                    except Exception as e:
                        print(
                            f"warn: {buoy.id}: wind fetch failed ({e!r}) - archiving without wind",
                            file=sys.stderr,
                        )
                om_total += _archive_om_rows(store, args, now, buoy, model)
        else:
            # fleet live run: one comma-joined request for all buoys instead of one
            # request (fresh TCP+TLS) per buoy - 15 calls/cycle -> 1, and one
            # response to guard instead of fifteen coin flips
            try:
                marines = fetch_marine_waves_many([(b.lat, b.lon) for b in targets])
            except Exception as e:
                om_batch_failed = True
                failures.extend((b.id, e) for b in targets)
                print(
                    f"error: open-meteo batch failed ({e!r}) - om rows left out of "
                    "this archive run",
                    file=sys.stderr,
                )
            else:
                # 10 m wind for the same points, one weather-host request (plan C3
                # evidence). Guarded separately: wind is the decision data, waves are
                # the archive's spine - a weather-host hiccup must cost wind columns
                # for this run, never the wave rows.
                winds: list[dict] = []
                try:
                    winds = fetch_wind_many([(b.lat, b.lon) for b in targets])
                except Exception as e:
                    print(
                        f"warn: open-meteo wind batch failed ({e!r}) - om rows archive "
                        "without wind this run",
                        file=sys.stderr,
                    )
                for bi, (buoy, marine) in enumerate(zip(targets, marines, strict=True)):
                    try:
                        if args.capture is not None:
                            args.capture.mkdir(parents=True, exist_ok=True)
                            (args.capture / f"marine_{buoy.id}.json").write_text(
                                json.dumps(marine), encoding="utf-8"
                            )
                        model = parse_marine_waves(marine)
                        if bi < len(winds):
                            model = join_wind(model, winds[bi])
                    except Exception as e:
                        failures.append((buoy.id, e))
                        print(
                            f"error: {buoy.id}: {e!r} - left out of this archive run",
                            file=sys.stderr,
                        )
                        continue
                    om_total += _archive_om_rows(store, args, now, buoy, model)
        if not om_batch_failed:
            # The om arm raises on a total outage (it calls raise_for_status), and the
            # branch above already says so - but a 200 that parses to no hours is the
            # other half of the shape _warn_member_empty exists for: 15 lines each
            # saying "archived 0 rows" and a clean exit. Suppressed when the batch
            # already errored, so the loud path stays one line, like the members below.
            #
            # `om_batch_failed` only covers the fleet-live branch; the per-buoy branch
            # (--buoy / --fixtures) records its own loud path in `failures` instead. So
            # count only the buoys this arm actually GOT to archive: a replay whose
            # bodies are all missing already prints one error line per buoy and a
            # failure summary, and must not also be told an outage emptied a member it
            # never asked anything of. _warn_member_empty no-ops on an empty list, and
            # a partial failure now names the buoys it really covers rather than "all N".
            failed_ids = {bid for bid, _ in failures}
            _warn_member_empty("om", om_total, [b for b in targets if b.id not in failed_ids])
    if args.wave_source in ("gfswave", "both", "all"):
        # Stage 3a A/B member. Guarded so a NOMADS outage never breaks OM archiving.
        try:
            src = (
                GFSWaveFixtureSource(args.gfs_fixtures)
                if args.gfs_fixtures is not None
                else GFSWaveSource(capture_dir=args.capture)
            )
            points = [(b.lat, b.lon) for b in targets]
            total = 0
            for buoy, series in zip(targets, src.fetch_series(points), strict=True):
                rows = rows_from_model(now, series)
                total += len(rows)
                key = buoy.id + GFSWAVE_KEY_SUFFIX
                store.append(key, rows)
                print(
                    f"{buoy.id}: archived {len(rows)} gfswave rows"
                    f" → {args.archive_dir / (key + '.jsonl')}"
                )
            _warn_member_empty("gfswave", total, targets)
        except Exception as e:  # A/B member must never sink the essential archive
            print(f"warn: gfswave archive skipped: {e}", file=sys.stderr)
    if args.wave_source in ("ecmwf", "all"):
        # Stage 3b member - hs + peak period (pp1d ↔ DPD) + direction. Same guard.
        try:
            esrc: EcmwfWaves = (
                EcmwfFixtureSource(args.ecmwf_fixtures, params=ARCHIVE_PARAMS)
                if args.ecmwf_fixtures is not None
                else EcmwfSource(capture_dir=args.capture, params=ARCHIVE_PARAMS)
            )
            points = [(b.lat, b.lon) for b in targets]
            total = 0
            for buoy, series in zip(targets, esrc.fetch_series(points), strict=True):
                rows = rows_from_spectral(now, series)
                total += len(rows)
                key = buoy.id + ECMWF_KEY_SUFFIX
                store.append(key, rows)
                print(
                    f"{buoy.id}: archived {len(rows)} ecmwf rows"
                    f" → {args.archive_dir / (key + '.jsonl')}"
                )
            _warn_member_empty("ecmwf", total, targets)
        except Exception as e:
            print(f"warn: ecmwf archive skipped: {e}", file=sys.stderr)
    # coastal wind stations - after every buoy member, and never able to fail the run.
    # The arm guards every FETCH it makes, but its first two statements (the registry
    # load and the archive store) sit outside every try, and `load_stations` raises on a
    # duplicate id, a missing id/name/lat/lon, a bad coordinate or unparseable YAML -
    # and data/stations/*.yaml is regenerated by `stations --discover metar` after every
    # spot-DB change, with the IMS rows hand-maintained beside it. Escaping here bypassed
    # the exit contract below (0 clean / 1 some buoy failed) and reported an already-
    # complete essential archive as a crashed cycle. Same shape as the gfswave/ecmwf
    # members' guards: warn, and let the archive keep its own answer.
    try:
        _archive_stations(args, now)
    except Exception as e:
        print(f"warn: station arm skipped: {e!r}", file=sys.stderr)
    if failures:
        # still a failed cycle for the cron trap - but only after archiving every
        # buoy and member that could be archived (mirrors _cmd_run's summary)
        kinds = ", ".join(sorted({type(e).__name__ for _, e in failures}))
        print(
            f"error: {len(failures)} of {len(targets)} buoy(s) failed ({kinds}): "
            f"{', '.join(bid for bid, _ in failures)}",
            file=sys.stderr,
        )
        return 1
    return 0


METAR_CACHE_URL = "https://aviationweather.gov/data/cache/metars.cache.csv.gz"


def _cmd_stations(args: argparse.Namespace) -> int:
    """Print a station registry yaml: every station within --radius-km of any spot."""
    import csv
    import gzip
    import io

    from .buoys import haversine_km
    from .observe import IMS_API, ims_token

    spots = list(load_spots(args.spots_dir).values())

    def near(lat: float, lon: float) -> tuple[int, str] | None:
        hits = [(haversine_km(s.lat, s.lon, lat, lon), s.region) for s in spots]
        hits = [(d, r) for d, r in hits if d <= args.radius_km]
        return (len(hits), min(hits)[1]) if hits else None

    found: list[tuple[str, str, float, float, str, int, str]] = []
    with httpx.Client(timeout=60.0) as client:
        if args.discover == "metar":
            resp = client.get(METAR_CACHE_URL)
            resp.raise_for_status()
            text = gzip.decompress(resp.content).decode("utf-8", errors="replace")
            coords: dict[str, tuple[float, float]] = {}
            for row in csv.reader(io.StringIO(text)):
                # columns: raw_text, station_id, observation_time, latitude, longitude, ...
                if len(row) < 5 or not row[1] or row[1] == "station_id":
                    continue
                try:
                    coords[row[1]] = (float(row[3]), float(row[4]))
                except ValueError:
                    continue
            hits = {k: n for k, (la, lo) in coords.items() if (n := near(la, lo))}
            names: dict[str, str] = {}
            ids = sorted(hits)
            for i in range(0, len(ids), 40):
                chunk = ids[i : i + 40]
                r = client.get(
                    "https://aviationweather.gov/api/data/metar",
                    params={"ids": ",".join(chunk), "format": "json", "hours": 2},
                )
                r.raise_for_status()
                for ob in r.json():
                    names.setdefault(ob["icaoId"], str(ob.get("name") or ob["icaoId"]))
            for k in ids:
                la, lo = coords[k]
                n, region = hits[k]
                found.append((k, names.get(k, k), la, lo, "metar", n, region))
        else:
            token = ims_token()
            if not token:
                print("IMS_API_TOKEN not set (mail ims@ims.gov.il for one)", file=sys.stderr)
                return 2
            r = client.get(f"{IMS_API}/stations", headers={"Authorization": f"ApiToken {token}"})
            r.raise_for_status()
            for st in r.json():
                loc = st.get("location") or {}
                monitors = st.get("monitors") or []
                if not st.get("active", True) or not any(m.get("name") == "WS" for m in monitors):
                    continue
                try:
                    la, lo = float(loc["latitude"]), float(loc["longitude"])
                except (KeyError, TypeError, ValueError):
                    continue
                if n := near(la, lo):
                    found.append(
                        (
                            str(st["stationId"]),
                            str(st.get("name") or st["stationId"]),
                            la,
                            lo,
                            "ims",
                            n[0],
                            n[1],
                        )
                    )
    print("stations:")
    for sid, name, la, lo, source, n, region in sorted(found):
        name = name.replace('"', "")
        print(
            f'  - {{ id: "{sid}", name: "{name}", lat: {la}, lon: {lo}, source: {source} }}'
            f"  # {region}, {n} spot(s) within {args.radius_km:g} km"
        )
    print(f"# {len(found)} station(s)", file=sys.stderr)
    return 0


def _cmd_feedback(args: argparse.Namespace) -> int:
    store = FileArchiveStore(args.feedback_dir)
    if args.report:
        records = records_from_rows(store.read("feedback"))
        print(render_report(summarize(records)))
        from .feedback import render_wind_fit, wind_fit

        print(render_wind_fit(wind_fit(records)))
        if args.markdown and records:
            print("\n" + markdown_rows(records))
        return 0

    if not args.spot or not args.verdict:
        print("adding feedback needs --spot and --verdict (or use --report)", file=sys.stderr)
        return 2
    if args.at:
        try:
            at = datetime.fromisoformat(args.at)
        except ValueError:
            print(f"--at {args.at!r} is not an ISO time", file=sys.stderr)
            return 2
        if at.tzinfo is None:
            # Every payload hour is spot-local ISO and a surfer's clock is local too, so a
            # naive value has no honest reading: stamped UTC it graded a Maldives dawn
            # session against the 14:00 forecast. Refuse rather than guess.
            print(
                f"--at {args.at!r} has no UTC offset - write it like 2026-09-07T09:00+03:00",
                file=sys.stderr,
            )
            return 2
    else:
        at = datetime.now(UTC)
    payload_path = args.out / "spots" / f"{args.spot}.json"
    if not payload_path.exists():
        print(f"no published forecast at {payload_path} - run the pipeline first", file=sys.stderr)
        return 2
    payload = json.loads(payload_path.read_text(encoding="utf-8"))

    predicted = predicted_from_payload(payload, at)
    observed: dict = {}
    if args.observed_bucket:
        observed["bucket"] = args.observed_bucket
    if args.observed_h is not None:
        observed["h_mid"] = args.observed_h
    if args.observed_phrase:
        observed["phrase"] = args.observed_phrase
    if args.note:
        observed["note"] = args.note

    record = FeedbackRecord(
        spot=args.spot,
        at=at,
        verdict=args.verdict,
        predicted=predicted,
        observed=observed,
        source="cli",
    )
    store.append("feedback", [record.to_row()])

    icon = "👍" if args.verdict == "up" else "👎"
    delta = bucket_delta(predicted.get("bucket"), observed.get("bucket"))
    drift = f" · bucket {delta:+d} vs observed" if delta is not None else ""
    print(
        f"{icon} {args.spot}: Rosa said {predicted.get('bucket')} {predicted.get('rating')} "
        f"({predicted.get('phrase')}){drift} → recorded"
    )
    return 0


def _sdb_source(args: argparse.Namespace):
    from .sdb import MAX_QUALITY_FLAG, CmemsSdbSource, FixtureSdbSource

    if args.fixtures is not None:
        return FixtureSdbSource.from_file(args.fixtures)
    return CmemsSdbSource(
        cache_dir=args.cache,
        max_quality=(
            MAX_QUALITY_FLAG if getattr(args, "max_quality", None) is None else args.max_quality
        ),
    )


def _cmd_sdb(args: argparse.Namespace) -> int:
    """Sample CMEMS coastal SDB along each committed ray and report the disagreement.

    Reporting is the point. --apply exists because the operator will eventually want the
    merged profiles for an A/B arm, but it is off by default: patching a ray point changes
    h_break, and CLAUDE.md's tuning rule says a change that moves published numbers needs a
    same-input A/B on the shipped harness plus a CALIBRATION.md entry in the SAME change.
    """
    from .bathymetry import load_profile
    from .sdb import ATTRIBUTION, merge_profile

    spots = load_spots(args.spots_dir)
    if args.all:
        targets = list(spots.values())
    else:
        target = spots.get(args.spot)
        if target is None:
            print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
            return 2
        targets = [target]

    source = _sdb_source(args)
    captured: list[tuple[float, float]] = []
    n_profiles = n_patched = n_points = 0
    deltas: list[float] = []
    for spot in targets:
        profile = load_profile(spot.id, args.bathy_dir)
        if profile is None:
            print(f"warn: {spot.id}: no committed profile - run `bathy` first", file=sys.stderr)
            continue
        points = [(s.lat, s.lon) for s in profile.samples]
        captured.extend(points)
        readings = source.readings(points)
        merged, patched = merge_profile(profile, readings, min_delta_m=args.min_delta)
        n_profiles += 1
        n_points += sum(1 for r in readings if r is not None)
        if not patched:
            continue
        n_patched += 1
        for ps in patched:
            was = "none" if ps.was_m is None else f"{ps.was_m:.1f}"
            if ps.was_m is not None:
                deltas.append(ps.was_m - ps.now_m)
            print(
                f"{spot.id:24s} {ps.dist_km:5.2f} km  gebco {was:>7s} m -> sdb "
                f"{ps.now_m:6.1f} m  (quality {ps.quality})"
            )
        if args.apply:
            path = args.bathy_dir / f"{spot.id}.json"
            path.write_text(json.dumps(merged.to_dict(), indent=2) + "\n", encoding="utf-8")

    if args.capture is not None:
        source.capture(captured, args.capture)
        print(f"captured {len(captured)} SDB points -> {args.capture}")
    print(
        f"\n{n_profiles} profile(s); SDB had a gated reading at {n_points} ray point(s); "
        f"{n_patched} profile(s) disagree by more than {args.min_delta} m"
    )
    if deltas:
        deltas.sort()
        mid = len(deltas) // 2
        median = deltas[mid] if len(deltas) % 2 else 0.5 * (deltas[mid - 1] + deltas[mid])
        print(f"median gebco-minus-sdb over the patched points: {median:+.1f} m")
    print(ATTRIBUTION)
    if not args.apply and n_patched:
        print("nothing written - re-run with --apply once the A/B says the swap is right")
    return 0


def _cmd_atl24(args: argparse.Namespace) -> int:
    """Grade depth sources against ICESat-2 lidar. Reports, never writes - same discipline
    as `horizon` and the cam tools (CLAUDE.md standing prohibitions)."""
    from . import atl24
    from .bathymetry import load_profile

    spots = load_spots(args.spots_dir)
    if args.region:
        want = args.region.replace("-", " ").lower()
        targets = [s for s in spots.values() if s.region.lower() == want]
        if not targets:
            regions = sorted({s.region for s in spots.values()})
            print(f"unknown region {args.region!r}; known: {', '.join(regions)}", file=sys.stderr)
            return 2
    else:
        target = spots.get(args.spot)
        if target is None:
            print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
            return 2
        targets = [target]

    pad = args.pad_deg
    south = min(s.lat for s in targets) - pad
    north = max(s.lat for s in targets) + pad
    west = min(s.lon for s in targets) - pad
    east = max(s.lon for s in targets) + pad
    print(f"ATL24 box {south:.3f},{west:.3f} .. {north:.3f},{east:.3f} for {len(targets)} spot(s)")
    photons = atl24.fetch_photons(
        south, west, north, east, cache=args.cache, on_note=lambda m: print(f"  {m}")
    )
    print(f"{len(photons)} classified seafloor photon(s)")
    if not photons:
        print("no lidar coverage in this box - ICESat-2 flies fixed repeat tracks, so this is")
        print("an expected outcome, not a failure. Nothing can be graded here.")
        return 0

    # build the spatial index ONCE: it is O(photons) to build and 9 cells to query, where
    # a bare list is a 5-million-photon scan per ray point
    index = atl24.PhotonIndex(photons, args.radius_m)
    gebco_pairs: list[tuple[float, float]] = []
    sdb_pairs: list[tuple[float, float]] = []
    source = (
        _sdb_source(argparse.Namespace(fixtures=None, cache=args.sdb_cache)) if args.sdb else None
    )
    reached = 0
    for spot in targets:
        profile = load_profile(spot.id, args.bathy_dir)
        if profile is None:
            continue
        points = atl24.profile_points(profile)
        pairs = atl24.pair(points, index, radius_m=args.radius_m)
        if pairs:
            reached += 1
        gebco_pairs.extend(pairs)
        if source is not None:
            readings = source.readings([(lat, lon) for lat, lon, _ in points])
            sdb_points = [
                (lat, lon, r.depth_m)
                for (lat, lon, _), r in zip(points, readings, strict=True)
                if r is not None
            ]
            sdb_pairs.extend(atl24.pair(sdb_points, index, radius_m=args.radius_m))

    print(
        f"{reached} of {len(targets)} spot(s) had a ray point within "
        f"{args.radius_m:.0f} m of a photon\n"
    )
    print(atl24.score(profile_source_label(args), gebco_pairs).as_row())
    if source is not None:
        print(atl24.score("CMEMS coastal SDB 100 m", sdb_pairs).as_row())
    print(f"\n{atl24.CITATION}")
    return 0


def profile_source_label(args: argparse.Namespace) -> str:
    """The committed profiles are GEBCO unless `sdb --apply` has patched them."""
    return "committed profile (gebco2020)"


def _cmd_horizon(args: argparse.Namespace) -> int:
    """Report the geometry-derived swell window next to the one in the YAML. Deliberately does
    NOT apply: per CLAUDE.md's coordinate authority ladder a derived value ranks below a human's
    eyes, and the cam sweep already taught this repo what unattended --apply costs."""
    import time

    from .horizon import scan_horizon

    spots = load_spots(args.spots_dir)
    if args.all:
        targets = list(spots.values())
    else:
        target = spots.get(args.spot)
        if target is None:
            print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
            return 2
        targets = [target]

    source: BathymetrySource = (
        FixtureBathymetrySource.from_file(args.fixtures / "bathy_elevations.json")
        if args.fixtures is not None
        else OpenTopoDataSource(capture_dir=args.capture)
    )

    changed = 0
    for i, spot in enumerate(targets):
        try:
            scan = scan_horizon(source, spot)
        except Exception as exc:
            # ValueError is a per-spot geometry verdict - always report and move on.
            # Anything else (an OpenTopoData hiccup, mid-sweep) must not abort a
            # rate-limited ~1 s/spot sweep either - but a targeted single-spot run
            # still raises: there the failure is the answer the operator asked for
            # (the verify --all-buoys rule).
            if not args.all and not isinstance(exc, ValueError):
                raise
            print(f"{spot.id}: ⚠ {exc}", file=sys.stderr)
            continue
        cur = spot.swell_window
        derived = scan.window
        same = abs(cur[0] - derived[0]) < 2.5 and abs(cur[1] - derived[1]) < 2.5
        changed += not same
        # A window narrower than this is almost certainly an artifact rather than a sheltered
        # spot - no open beach sees less. Flagged, never suppressed: the caller decides.
        # No `or 360` here: `window_from_open_bearings` clips both sides to
        # +-MAX_INCIDENCE_DEG, so a derived arc is never wider than 180 deg and a width of
        # 0 is never a full circle - it is the degenerate window the scan returns when the
        # shore normal's own bearing is open and both neighbours are blocked. Reading that
        # 0 as 360 turned the worst possible result into the widest one and silenced the
        # only NARROW review gate standing between a derived arc and the spot DB.
        width = (derived[1] - derived[0]) % 360
        flag = "" if same else "   <- differs"
        if width < 90:
            flag += f"   ⚠ NARROW {width:.0f} deg - review before adopting"
        print(
            f"{spot.id}: yaml [{cur[0]:.0f}, {cur[1]:.0f}] vs derived "
            f"[{derived[0]:.0f}, {derived[1]:.0f}] (shore normal {scan.shore_normal:.0f}){flag}"
        )
        if args.fixtures is None and i < len(targets) - 1 and args.sleep > 0:
            time.sleep(args.sleep)
    print(f"{changed} of {len(targets)} spot(s) differ - edit the YAML by hand to adopt")
    return 0


def _cmd_tide(args: argparse.Namespace) -> int:
    from . import tide as tide_mod

    spots = load_spots(args.spots_dir)
    if args.all:
        targets = list(spots.values())
    else:
        target = spots.get(args.spot)
        if target is None:
            print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
            return 2
        targets = [target]
    if not args.grids.is_dir():
        print(
            f"error: EOT20 grids not found at {args.grids} - download once from "
            "SEANOE 10.17882/79489 (ocean_tides, ~2.1 GB)",
            file=sys.stderr,
        )
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    failures: list[tuple[str, Exception]] = []
    for spot in targets:
        try:
            constants = tide_mod.extract_constants(spot.id, spot.offshore_point, args.grids)
        except Exception as e:
            # per-spot guard, the bathy/run --all rule; a targeted --spot run raises
            if not args.all:
                raise
            failures.append((spot.id, e))
            print(f"error: {spot.id}: {e!r} - left out of this sweep", file=sys.stderr)
            continue
        path = tide_mod.save_constants(constants, args.out)
        written += 1
        line = (
            f"{spot.id}: {constants.method} @ ({constants.sample[0]:.3f}, "
            f"{constants.sample[1]:.3f}) sum-amp {tide_mod.amplitude_m(constants):.2f} m → {path}"
        )
        if args.verify is not None:
            line += _tide_verify_suffix(spot.id, constants, args.verify, tide_mod)
        print(line)
    if failures:
        print(f"error: {len(failures)} of {len(targets)} spot(s) failed", file=sys.stderr)
    return 1 if failures else 0


def _tide_verify_suffix(spot_id: str, constants, out_dir: Path, tide_mod) -> str:
    """Compare EOT20 synthesis against the OM tide series a published payload carries.

    A constant offset is EXPECTED and not an error: OM's sea_level_height_msl includes
    non-tidal sea level (seasonal steric height, surge), EOT20 is the astronomical tide
    alone. Shape (corr) and demeaned rmse are the extraction-correctness signals."""
    import statistics
    from datetime import datetime

    payload_path = out_dir / "spots" / f"{spot_id}.json"
    if not payload_path.exists():
        return "  (no published payload to verify against)"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    pairs = [
        (datetime.fromisoformat(h["t"]), h["tide"])
        for h in payload.get("hours", [])
        if h.get("tide") is not None
    ]
    if len(pairs) < 24:
        return "  (payload has no OM tide series)"
    pred = tide_mod.predict(constants, [t for t, _ in pairs])
    om = [v for _, v in pairs]
    mo, mp = statistics.mean(om), statistics.mean(pred)
    dm = [(p - mp) - (o - mo) for p, o in zip(pred, om, strict=True)]
    rmse = (sum(x * x for x in dm) / len(dm)) ** 0.5
    rng = max(om) - min(om)
    corr = statistics.correlation(pred, om) if rng > 0.02 else None
    corr_s = f"{corr:+.3f}" if corr is not None else "n/a (flat)"
    flag = "  ⚠ CHECK" if corr is not None and corr < 0.9 and rmse > 0.1 else ""
    return f"  | vs OM: corr {corr_s} offset {mp - mo:+.2f} m demeaned-rmse {rmse:.3f} m{flag}"


def _cmd_bathy(args: argparse.Namespace) -> int:
    import time

    spots = load_spots(args.spots_dir)
    if args.all:
        targets = list(spots.values())
    else:
        target = spots.get(args.spot)
        if target is None:
            print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
            return 2
        targets = [target]

    source: BathymetrySource
    if args.fixtures is not None:
        source = FixtureBathymetrySource.from_file(args.fixtures / "bathy_elevations.json")
    elif args.source == "local":
        from .bathymetry import LocalGebcoSource

        source = LocalGebcoSource(args.grid)
        args.sleep = 0.0  # a local grid has no rate limit to pace against
    else:
        source = OpenTopoDataSource(capture_dir=args.capture)

    args.out.mkdir(parents=True, exist_ok=True)
    written = 0
    failures: list[tuple[str, Exception]] = []
    for i, spot in enumerate(targets):
        try:
            profile = build_profile(source, spot)
        except Exception as e:
            # Per-spot guard (the run --all rule): the sweep paces itself ~1 s/spot
            # for the OpenTopoData rate limit, so an unguarded hiccup at spot 150
            # threw away minutes of rate-limited work and every later profile. A
            # targeted --spot run still raises - there the failure is the answer.
            if not args.all:
                raise
            failures.append((spot.id, e))
            print(f"error: {spot.id}: {e!r} - left out of this sweep", file=sys.stderr)
            if args.fixtures is None and i < len(targets) - 1 and args.sleep > 0:
                time.sleep(args.sleep)
            continue
        path = args.out / f"{spot.id}.json"
        path.write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")
        written += 1
        warns = []
        if profile.land_samples:
            warns.append(f"{profile.land_samples} land sample(s) - check shore-normal")
        if profile.missing_samples:
            # a hole reads as `nan m` in the numbers above and was otherwise silent -
            # land_samples can't see it, so a whole sweep could hide one in 199 lines
            warns.append(f"{profile.missing_samples} sample(s) with no GEBCO elevation")
        if profile.non_monotone_samples:
            # the geometry the shoaling march's premise depends on, made visible: the ray
            # is ordered by distance, not depth, so a shelf inside the reference is silent
            warns.append(f"{profile.non_monotone_samples} sample(s) deeper than the one before")
        if not profile.deepest_is_reference:
            warns.append("deepest wet sample is not the 18 km reference")
        warn = f"  ⚠ {'; '.join(warns)}" if warns else ""
        print(
            f"{spot.id}: near {profile.nearshore_depth_m:.0f} m → offshore "
            f"{profile.offshore_depth_m:.0f} m (slope {profile.mean_slope_m_per_km:.1f} m/km) "
            f"→ {path}{warn}"
        )
        # OpenTopoData rate-limits to ~1 req/s; skip the wait on replay and after the last spot.
        if args.fixtures is None and i < len(targets) - 1 and args.sleep > 0:
            time.sleep(args.sleep)
    print(f"wrote {written} depth profile(s) → {args.out}")
    if failures:
        # still a failed cycle - but only after sampling every spot that could be
        # (mirrors _cmd_run's summary)
        kinds = ", ".join(sorted({type(e).__name__ for _, e in failures}))
        print(
            f"error: {len(failures)} of {len(targets)} spot(s) failed ({kinds}): "
            f"{', '.join(sid for sid, _ in failures)}",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_experiment(args: argparse.Namespace) -> int:
    from .experiment import load_frames, render_report, run_experiment

    frames = load_frames(args.frames)
    spots = load_spots(args.spots_dir)
    results = run_experiment(frames, spots, args.bathy_dir)
    print(render_report(results))
    return 0


def _cmd_swellmap(args: argparse.Namespace) -> int:
    from .swellmap import basin_boxes, run_swellmap, run_swellmap_all, run_swellmap_world

    if args.world_only and args.basin is not None:
        # The two filters together select nothing: --basin narrows the basin layer, which
        # --world-only skips outright. Left to run, this fetched nothing, printed nothing and
        # returned 1 - which publish.sh's failure trap reads as a broken cycle, not a typo.
        print("swellmap: --world-only selects no basin - drop --basin", file=sys.stderr)
        return 2

    # The default cron shape - both layers, every basin - shares one global download per
    # step instead of fetching the same fields twice (~513 extra NOMADS requests/cycle).
    # The narrowed forms below have no global pass to slice from, so they keep the
    # per-basin filter path.
    if not args.world_only and not args.skip_world and args.basin is None:
        written, world_frames = run_swellmap_all(args.spots_dir, args.out)
        return 0 if (written or world_frames) else 1

    written: list[str] = []
    if not args.world_only:
        basins = basin_boxes(args.spots_dir)
        if args.basin is not None:
            basins = [b for b in basins if b.name == args.basin]
            if not basins:
                print(f"unknown basin {args.basin!r}", file=sys.stderr)
                return 2
        written = run_swellmap(args.spots_dir, args.out, basins=basins)
    world_frames = 0
    if args.skip_world or args.basin is not None:
        # --skip-world is the operator asking for it and owes no message; --basin does,
        # because narrowing the BASIN layer silently dropping the GLOBAL one leaves a log
        # indistinguishable from a full run. Same contract as `skill: nothing to persist`
        # and `spread: nothing to persist` above: say what did not happen.
        if not args.skip_world:
            print(f"swellmap: world layer skipped - --basin {args.basin!r} narrows this run")
    else:
        world_frames = run_swellmap_world(args.out)
    return 0 if (written or world_frames) else 1


def _cmd_notify(args: argparse.Namespace) -> int:
    import os

    from .notify import send_notifications

    subs_url = args.subs_url or os.environ.get("PUSH_SUBS_URL")
    admin_secret = os.environ.get("PUSH_ADMIN_SECRET")
    vapid_key = args.vapid_key or (
        Path(os.environ["VAPID_PRIVATE_KEY"]) if os.environ.get("VAPID_PRIVATE_KEY") else None
    )
    vapid_sub = args.vapid_sub or os.environ.get("VAPID_SUB")
    missing = [
        name
        for name, val in [
            ("PUSH_SUBS_URL/--subs-url", subs_url),
            ("PUSH_ADMIN_SECRET", admin_secret),
            ("VAPID_PRIVATE_KEY/--vapid-key", vapid_key),
            ("VAPID_SUB/--vapid-sub", vapid_sub),
        ]
        if not val
    ]
    if missing:
        print(f"notify: missing {', '.join(missing)}", file=sys.stderr)
        return 2
    assert subs_url and admin_secret and vapid_key and vapid_sub
    failures: list[str] = []
    sent = send_notifications(
        out_dir=args.out,
        state_path=args.state,
        subs_url=subs_url,
        admin_secret=admin_secret,
        vapid_private_key=vapid_key,
        vapid_sub=vapid_sub,
        dry_run=args.dry_run,
        feedback_dir=FEEDBACK_DIR,
        failures=failures,
    )
    if failures and not sent:
        # Same rule as _cmd_verify's `1 if failures and not scored`: pushes were planned
        # and every one of them failed - a rotated VAPID key, pywebpush gone from the
        # venv, the admin API changing shape. Returning 0 here left publish.sh's
        # `notify || echo "warn: notify failed"` unable to fire, so a cycle that
        # delivered nothing read exactly like a quiet one. A partial failure still
        # exits 0 - the per-subscription degrade is the design.
        print(
            f"notify: {len(failures)} failure(s) and nothing sent - "
            + "; ".join(failures[:3])
            + (" ..." if len(failures) > 3 else ""),
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_alert(args: argparse.Namespace) -> int:
    import os

    from .notify import send_alert

    vapid_key = args.vapid_key or (
        Path(os.environ["VAPID_PRIVATE_KEY"]) if os.environ.get("VAPID_PRIVATE_KEY") else None
    )
    vapid_sub = args.vapid_sub or os.environ.get("VAPID_SUB")
    if not vapid_key or not vapid_sub:
        print(
            "alert: missing VAPID_PRIVATE_KEY/--vapid-key or VAPID_SUB/--vapid-sub",
            file=sys.stderr,
        )
        return 2
    if not args.subs.exists():
        print(f"alert: no admin subs snapshot at {args.subs}", file=sys.stderr)
        return 2
    sent = send_alert(args.message, args.subs, vapid_key, vapid_sub)
    print(f"alert: sent to {sent} admin device(s)")
    return 0 if sent else 1


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "archive":
        return _cmd_archive(args)
    if args.command == "stations":
        return _cmd_stations(args)
    if args.command == "feedback":
        return _cmd_feedback(args)
    if args.command == "tide":
        return _cmd_tide(args)
    if args.command == "bathy":
        return _cmd_bathy(args)
    if args.command == "sdb":
        return _cmd_sdb(args)
    if args.command == "atl24":
        return _cmd_atl24(args)
    if args.command == "horizon":
        return _cmd_horizon(args)
    if args.command == "notify":
        return _cmd_notify(args)
    if args.command == "alert":
        return _cmd_alert(args)
    if args.command == "experiment":
        return _cmd_experiment(args)
    if args.command == "swellmap":
        return _cmd_swellmap(args)
    return _cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
