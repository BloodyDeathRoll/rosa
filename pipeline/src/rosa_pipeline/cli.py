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
    render_report,
    summarize,
)
from .fetch import (
    FixtureSource,
    ForecastSource,
    OpenMeteoSource,
    fetch_marine_waves,
    fetch_marine_waves_many,
)
from .gfswave import GFSWaveFixtureSource, GFSWaveSource
from .models import Spot
from .observe import (
    CMEMSFixtureSource,
    CMEMSSource,
    ISRAMARLocalSource,
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
    build_report,
    measure,
)
from .spectra import (
    render_report as render_spectra_report,
)
from .spots import load_spots
from .verify import (
    ECMWF_VARIABLES,
    ENERGY_PERIOD_VARIABLES,
    GFSWAVE_VARIABLES,
    VARIABLES,
    build_scorecard,
    lead_time_scorecard,
    parse_marine_waves,
    render_lead_scorecard,
    render_scorecard,
    skill_payload,
    with_energy_period,
)

# multi-source archive keys: OM rows live at "<buoy>", GFS-Wave at "<buoy>.gfswave",
# ECMWF at "<buoy>.ecmwf"
GFSWAVE_KEY_SUFFIX = ".gfswave"
ECMWF_KEY_SUFFIX = ".ecmwf"
SOURCE_KEY_SUFFIX = {"om": "", "gfswave": GFSWAVE_KEY_SUFFIX, "ecmwf": ECMWF_KEY_SUFFIX}
SOURCE_VARIABLES = {"om": VARIABLES, "gfswave": GFSWAVE_VARIABLES, "ecmwf": ECMWF_VARIABLES}

ARCHIVE_DIR = Path("data/verify/archive")
ISRAMAR_DIR = Path("data/verify/isramar")  # local-only, gitignored (all-rights-reserved)
FEEDBACK_DIR = Path("data/verify/feedback")
BATHY_DIR = Path("data/spots/derived/bathy")  # committed per-spot depth profiles (Stage 2A)


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
        "--ecmwf-fixtures",
        type=Path,
        default=None,
        help="replay captured ECMWF gribs (offline); with --fixtures alone the spectral "
        "member is skipped",
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

    fb = sub.add_parser("feedback", help="record/report surfer 👍👎 vs the published rating")
    fb.add_argument("--report", action="store_true", help="summarise instead of adding")
    fb.add_argument("--markdown", action="store_true", help="with --report: emit CALIBRATION rows")
    fb.add_argument("--spot", help="spot id (required when adding)")
    fb.add_argument("--verdict", choices=["up", "down"], help="👍/👎 (required when adding)")
    fb.add_argument("--observed-bucket", choices=list(BUCKET_ORDER))
    fb.add_argument("--observed-h", type=float, help="observed breaker height midpoint, m")
    fb.add_argument("--observed-phrase")
    fb.add_argument("--note")
    fb.add_argument("--at", help="ISO time of the observation (default: now)")
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
    if args.all:
        targets = list(spots.values())
    else:
        target = spots.get(args.spot)
        if target is None:
            print(f"unknown spot {args.spot!r}; known: {', '.join(sorted(spots))}", file=sys.stderr)
            return 2
        targets = [target]

    source: ForecastSource = (
        FixtureSource(args.fixtures)
        if args.fixtures is not None
        else OpenMeteoSource(capture_dir=args.capture)
    )
    now = datetime.now(UTC)
    # measured horizon ceilings from the verification harness, if `verify --archive`
    # has run and matured past its sample floor; None -> static defaults (2026-08-07)
    skill = load_skill_ceilings(ARCHIVE_DIR.parent / "skill.json")

    # one deep-water sample per unique offshore point; each spot may have its own, so a
    # full run fetches them all in a single batched request (fetch_many) - no throttling.
    groups = group_by_point(targets)
    points = list(groups)
    raws = source.fetch_many(points)

    # ECMWF spectral-lite member (Stage 3b) - guarded: an ECMWF outage must never sink
    # the forecast run. Offline replay (--fixtures) skips it unless --ecmwf-fixtures.
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

    published = 0
    failures: list[tuple[str, Exception]] = []
    for point, raw, spectral in zip(points, raws, spectral_series, strict=True):
        hours = extract_hours(raw, spectral=spectral)
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
                profile = load_profile(spot.id, BATHY_DIR)
                wet_depths = profile.wet_depths_deep_to_shallow() if profile else None
                scored = [score_hour(spot, h, wet_depths) for h in hours]
                payload = build_payload(
                    spot, scored, fetched_at=raw.fetched_at, now=now, skill=skill
                )
                path = write_spot_json(payload, args.out)
                update_index(payload, args.out)
            except Exception as e:
                # repr, not str: losing the exception type on a batch of 199 makes a systemic
                # fault unreadable. The count and the first type are echoed in the summary.
                failures.append((spot.id, e))
                print(f"error: {spot.id}: {e!r}", file=sys.stderr)
                continue
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
    if failures:
        # Still a failed cycle for publish.sh's trap - but only after doing every piece of
        # work that could be done, prune included (it is keyed on the DB, not on this run's
        # output, so a failed spot is never pruned for having failed). A schema break that
        # hits all 199 spots reads as 199 lines plus this summary, not one traceback.
        kinds = ", ".join(sorted({type(e).__name__ for _, e in failures}))
        print(
            f"error: {len(failures)} of {published + len(failures)} spot(s) failed ({kinds}): "
            f"{', '.join(sid for sid, _ in failures)}",
            file=sys.stderr,
        )
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


def _model_for(buoy: Buoy, args: argparse.Namespace):
    if args.fixtures is not None:
        marine = json.loads((args.fixtures / f"marine_{buoy.id}.json").read_text(encoding="utf-8"))
    else:
        marine = fetch_marine_waves(buoy.lat, buoy.lon)
        if args.capture is not None:
            args.capture.mkdir(parents=True, exist_ok=True)
            (args.capture / f"marine_{buoy.id}.json").write_text(
                json.dumps(marine), encoding="utf-8"
            )
    return parse_marine_waves(marine)


def _cmd_verify(args: argparse.Namespace) -> int:
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

    # per-buoy lead scorecards for the om (published-model) source, persisted as
    # skill.json after the loop - the harness output publish's horizon ceilings read
    skill_by_lead: list[dict] = []
    skill_buoys: list[str] = []
    for buoy, dist in targets:
        if args.spectra:
            # measured-spectra validation needs NDBC spectral files, which only NDBC has
            if buoy.source != "ndbc":
                print(f"{buoy.id}: no public spectral files for source {buoy.source!r} - skipped")
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
            print(render_spectra_report(buoy, build_report(specs)))
            continue
        try:
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
                model = _model_for(buoy, args)
                scores = build_scorecard(model, obs, tol_min=args.tol_min, variables=variables)
                print(render_scorecard(buoy, dist, scores))
        except Exception as e:
            # the fleet pass degrades per buoy (same philosophy as run --all per
            # spot): one obs outage drops that buoy from this skill measurement
            # instead of killing the cycle's whole pass. A targeted run still
            # raises - there a failure is the answer the operator asked for.
            if not getattr(args, "all_buoys", False):
                raise
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
    return 0


def _archive_om_rows(
    store: FileArchiveStore, args: argparse.Namespace, now: datetime, buoy: Buoy, model
) -> None:
    rows = rows_from_model(now, model)
    store.append(buoy.id, rows)
    stamp = now.isoformat(timespec="seconds")
    print(
        f"{buoy.id}: archived {len(rows)} forecast rows @ {stamp}"
        f" → {args.archive_dir / (buoy.id + '.jsonl')}"
    )


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
                _archive_om_rows(store, args, now, buoy, model)
        else:
            # fleet live run: one comma-joined request for all buoys instead of one
            # request (fresh TCP+TLS) per buoy - 15 calls/cycle -> 1, and one
            # response to guard instead of fifteen coin flips
            try:
                marines = fetch_marine_waves_many([(b.lat, b.lon) for b in targets])
            except Exception as e:
                failures.extend((b.id, e) for b in targets)
                print(
                    f"error: open-meteo batch failed ({e!r}) - om rows left out of "
                    "this archive run",
                    file=sys.stderr,
                )
            else:
                for buoy, marine in zip(targets, marines, strict=True):
                    try:
                        if args.capture is not None:
                            args.capture.mkdir(parents=True, exist_ok=True)
                            (args.capture / f"marine_{buoy.id}.json").write_text(
                                json.dumps(marine), encoding="utf-8"
                            )
                        model = parse_marine_waves(marine)
                    except Exception as e:
                        failures.append((buoy.id, e))
                        print(
                            f"error: {buoy.id}: {e!r} - left out of this archive run",
                            file=sys.stderr,
                        )
                        continue
                    _archive_om_rows(store, args, now, buoy, model)
    if args.wave_source in ("gfswave", "both", "all"):
        # Stage 3a A/B member. Guarded so a NOMADS outage never breaks OM archiving.
        try:
            src = (
                GFSWaveFixtureSource(args.gfs_fixtures)
                if args.gfs_fixtures is not None
                else GFSWaveSource(capture_dir=args.capture)
            )
            points = [(b.lat, b.lon) for b in targets]
            for buoy, series in zip(targets, src.fetch_series(points), strict=True):
                rows = rows_from_model(now, series)
                key = buoy.id + GFSWAVE_KEY_SUFFIX
                store.append(key, rows)
                print(
                    f"{buoy.id}: archived {len(rows)} gfswave rows"
                    f" → {args.archive_dir / (key + '.jsonl')}"
                )
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
            for buoy, series in zip(targets, esrc.fetch_series(points), strict=True):
                rows = rows_from_spectral(now, series)
                key = buoy.id + ECMWF_KEY_SUFFIX
                store.append(key, rows)
                print(
                    f"{buoy.id}: archived {len(rows)} ecmwf rows"
                    f" → {args.archive_dir / (key + '.jsonl')}"
                )
        except Exception as e:
            print(f"warn: ecmwf archive skipped: {e}", file=sys.stderr)
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


def _cmd_feedback(args: argparse.Namespace) -> int:
    store = FileArchiveStore(args.feedback_dir)
    if args.report:
        records = [FeedbackRecord.from_row(r) for r in store.read("feedback")]
        print(render_report(summarize(records)))
        if args.markdown and records:
            print("\n" + markdown_rows(records))
        return 0

    if not args.spot or not args.verdict:
        print("adding feedback needs --spot and --verdict (or use --report)", file=sys.stderr)
        return 2
    payload_path = args.out / "spots" / f"{args.spot}.json"
    if not payload_path.exists():
        print(f"no published forecast at {payload_path} - run the pipeline first", file=sys.stderr)
        return 2
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    at = datetime.fromisoformat(args.at) if args.at else datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)

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
        width = ((derived[1] - derived[0]) % 360) or 360
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

    source: BathymetrySource = (
        FixtureBathymetrySource.from_file(args.fixtures / "bathy_elevations.json")
        if args.fixtures is not None
        else OpenTopoDataSource(capture_dir=args.capture)
    )

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
    from .swellmap import basin_boxes, run_swellmap, run_swellmap_world

    if args.world_only and args.basin is not None:
        # The two filters together select nothing: --basin narrows the basin layer, which
        # --world-only skips outright. Left to run, this fetched nothing, printed nothing and
        # returned 1 - which publish.sh's failure trap reads as a broken cycle, not a typo.
        print("swellmap: --world-only selects no basin - drop --basin", file=sys.stderr)
        return 2

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
    if not args.skip_world and args.basin is None:
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
    send_notifications(
        out_dir=args.out,
        state_path=args.state,
        subs_url=subs_url,
        admin_secret=admin_secret,
        vapid_private_key=vapid_key,
        vapid_sub=vapid_sub,
        dry_run=args.dry_run,
        feedback_dir=FEEDBACK_DIR,
    )
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
    if args.command == "feedback":
        return _cmd_feedback(args)
    if args.command == "bathy":
        return _cmd_bathy(args)
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
