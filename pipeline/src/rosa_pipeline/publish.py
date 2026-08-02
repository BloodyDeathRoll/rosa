"""Build and write the per-spot JSON payload the frontend renders verbatim."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun

from .events import detect_events
from .models import ScoredHour, Spot, SpotCam
from .spectral import consistency_score, missed_swells, parametric_spread_deg
from .transform import energy_kj_per_m, in_window, partition_closure

MODEL_NAME = "open-meteo:best_match (marine + forecast v1)"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC-BY 4.0)"
ATTRIBUTION_ECMWF = "Wave spectra: ECMWF open data (CC-BY 4.0)"
TABLE_DAYS = 16
TABLE_STEP_H = 3
OUTLOOK_DAYS = 16


def _horizon_ceiling(day_index: int) -> float:
    """Confidence a forecast this far out can earn even if every model agrees - skill
    degrades with lead time, and the day 10+ tail is GFS-Wave-only."""
    if day_index <= 3:
        return 1.0
    if day_index <= 9:
        return 0.85
    return 0.4


def _confidence(day_index: int, agreement_score: float | None) -> tuple[str, float]:
    """Combine multi-model agreement with the horizon ceiling → (label, 0-1 score).
    No ensemble (agreement None) → fall back to the horizon proxy alone."""
    ceiling = _horizon_ceiling(day_index)
    base = agreement_score if agreement_score is not None else ceiling
    score = min(base, ceiling)
    label = "high" if score >= 0.7 else "medium" if score >= 0.45 else "low"
    return label, round(score, 2)


def _cam_entry(cam: SpotCam) -> dict:
    return {
        "yt": cam.youtube_id,
        "by": cam.by,
        "by_url": cam.by_url,
        **({"note": cam.note} if cam.note else {}),
        **({"label": cam.label} if cam.label else {}),
    }


def _r(x: float, digits: int = 2) -> float:
    return round(x, digits)


def _daylight(
    spot: Spot, day_hours: list[ScoredHour], date_str: str, tz: ZoneInfo
) -> list[ScoredHour]:
    """Hours between dawn and dusk - the day summary must not be driven by a 1 am land
    breeze nobody can surf. Falls back to all hours if the sun never rises/sets (polar)."""
    try:
        s = sun(Observer(spot.lat, spot.lon), date=date.fromisoformat(date_str), tzinfo=tz)
    except ValueError:
        return day_hours
    lit = [h for h in day_hours if s["dawn"] <= h.hour.time.astimezone(tz) <= s["dusk"]]
    return lit or day_hours


def _covers_day(day_hours: list[ScoredHour], tz: ZoneInfo) -> bool:
    """Does this day's data actually span the local day? A published day has to
    reach from around midnight to late evening; anything shorter is the model
    horizon cutting a day in half, and would show a range read off a few hours
    with no daypart bars at all. Tolerant of the 3-hourly grid and of offsets
    that aren't whole hours (Asia/Colombo is +05:30)."""
    hours = [s.hour.time.astimezone(tz).hour for s in day_hours]
    return bool(hours) and min(hours) <= 1 and max(hours) >= 21


def _day_agreement(day_hours: list[ScoredHour]) -> float | None:
    scores = [s.hour.agreement_score for s in day_hours if s.hour.agreement_score is not None]
    return sum(scores) / len(scores) if scores else None


def _spectral_entry(s: ScoredHour) -> dict | None:
    """ECMWF spectral-lite block (Stage 3b): consistency 0-100 + any missed swells.
    Omitted entirely when the member wasn't joined to this hour (beyond its 240 h
    horizon, or the fetch failed) - an absent key is honest, a fabricated one isn't."""
    sea = s.hour.spectral
    if sea is None:
        return None
    out: dict = {}
    consistency = consistency_score(sea)
    if consistency is not None:
        out["consistency"] = consistency
    missed = [
        {
            "t": [m.period_lo_s, m.period_hi_s],
            "h": _r(m.height_m, 1),
            # deep-water energy FLUX of the unaccounted band, kW per metre of crest
            # (mid-band period) - a different quantity to the hour's energy_kj, hence the unit
            # in the key: nothing here should ever be read as interchangeable with it
            "energy_kw": _r(0.49 * m.height_m**2 * (m.period_lo_s + m.period_hi_s) / 2.0, 1),
        }
        for m in missed_swells(sea, s.hour.partitions)
    ]
    if missed:
        out["missed"] = missed
    return out or None


def _hour_entry(spot: Spot, s: ScoredHour, tz: ZoneInfo) -> dict:
    entry = {
        "t": s.hour.time.astimezone(tz).isoformat(timespec="minutes"),
        "rating": s.rating,
        "bucket": s.bucket,
        "h": [s.h_break_lo, s.h_break_hi],
        "h_mid": _r(s.h_break_mid, 1),
        "phrase": s.phrase,
        # deep-water wave energy of in-window partitions, kJ per metre of crest (the unit
        # surf forecasts quote); keyed on the energy period Te, not the mean period
        "energy_kj": round(energy_kj_per_m(s.hour.partitions, spot.swell_window)),
        "pressure": round(s.hour.pressure_msl) if s.hour.pressure_msl is not None else None,
        "air": _r(s.hour.air_c, 1) if s.hour.air_c is not None else None,
        "wind": {
            "kph": _r(s.hour.wind_speed_kph, 1),
            "dir": s.hour.wind_dir_deg,
            "class": s.wind_class,
        },
        "sst": _r(s.hour.sst_c, 1) if s.hour.sst_c is not None else None,
        # tide / total water level rel. MSL, m (Stage 2D) - real series replacing the web mock
        "tide": _r(s.hour.tide_m, 2) if s.hour.tide_m is not None else None,
        "swells": [
            {
                "h": _r(p.height_m),
                "period": _r(p.period_s, 1),
                "peak_period": _r(p.peak_period_s, 1) if p.peak_period_s is not None else None,
                "dir": p.direction_deg,
                "kind": p.kind,
                "in_window": in_window(p.direction_deg, spot.swell_window),
                # assumed directional spread by partition class - modeled, not observed
                # (see payload spectral_meta); replaced by measured spread at Stage 4
                "spread": round(parametric_spread_deg(p)),
            }
            for p in s.hour.partitions
        ],
    }
    # fraction of the source's own sea the four partition fields account for. Diagnostic:
    # nothing downstream scores on it (docs/CALIBRATION.md 2026-07-30). Omitted rather than
    # published as null when the source gave no total, to keep the payload small.
    closure = partition_closure(s.hour.partitions, s.hour.total_hs_m)
    if closure is not None:
        entry["closure"] = _r(closure, 2)
    spectral = _spectral_entry(s)
    if spectral is not None:
        entry["spectral"] = spectral
    return entry


def build_payload(spot: Spot, scored: list[ScoredHour], *, fetched_at: str, now: datetime) -> dict:
    tz = ZoneInfo(spot.timezone)

    # The fetch reaches one day back (fetch.PAST_DAYS) so the series covers local
    # midnight at any longitude; publish from the spot's local today so every day
    # shown is complete, without shipping a stale full yesterday. Events below
    # still see the whole series - history only steadies their baseline.
    today_local = now.astimezone(tz).date()
    visible = [s for s in scored if s.hour.time.astimezone(tz).date() >= today_local]
    if not visible:  # stale run older than a day - publish what exists, honestly
        visible = scored

    # ...and drop the trailing day when the model horizon lands mid-day: east of
    # UTC the last local day can hold a couple of pre-dawn hours, which render as
    # a day with no dayparts and a range read off two hours. Half a day is not a
    # forecast - cut it rather than show it. (The leading day can't be partial:
    # the fetch reaches a day back, so local midnight is always covered.)
    day_of = lambda s: s.hour.time.astimezone(tz).date().isoformat()  # noqa: E731
    by_date: dict[str, list[ScoredHour]] = {}
    for s in visible:
        by_date.setdefault(day_of(s), []).append(s)
    complete = {d: hrs for d, hrs in by_date.items() if _covers_day(hrs, tz)}
    if complete:  # never strip everything - a spot with no full day still reports
        by_date = complete
        visible = [s for s in visible if day_of(s) in by_date]

    table_hours = [
        s for s in visible[: TABLE_DAYS * 24] if s.hour.time.astimezone(tz).hour % TABLE_STEP_H == 0
    ]

    sorted_dates = sorted(by_date.items())
    date_index = {date_str: i for i, (date_str, _) in enumerate(sorted_dates)}

    current = next((s for s in visible if s.hour.time >= now), visible[-1])
    current_entry = _hour_entry(spot, current, tz)
    current_entry["wetsuit"] = current.wetsuit
    current_entry["why"] = {
        "size": _r(current.size_score, 1),
        "period": _r(current.period_score, 1),
        "wind": _r(current.wind_score, 1),
    }
    cur_date = current.hour.time.astimezone(tz).date().isoformat()
    cur_label, cur_score = _confidence(date_index.get(cur_date, 0), current.hour.agreement_score)
    current_entry["confidence"] = {
        "label": cur_label,
        "score": cur_score,
        "models": current.hour.n_models,
    }

    days = []
    for day_index, (date_str, day_hours) in enumerate(sorted_dates[:OUTLOOK_DAYS]):
        best = max(_daylight(spot, day_hours, date_str, tz), key=lambda s: s.rating)
        label, score = _confidence(day_index, _day_agreement(day_hours))
        days.append(
            {
                "date": date_str,
                "rating_max": best.rating,
                "bucket": best.bucket,
                "h_max": [best.h_break_lo, best.h_break_hi],
                "confidence": label,
                "confidence_score": score,
            }
        )

    has_spectral = any(s.hour.spectral is not None for s in scored)
    # swell events (CLAUDE.md spec): >= 12 h of >= 2x-baseline energy, GOOD+ at peak -
    # the alerts/swell-stories seed; local-time ISO like every other timestamp here
    events = [
        {
            "start": e.start.astimezone(tz).isoformat(timespec="minutes"),
            "peak": e.peak.astimezone(tz).isoformat(timespec="minutes"),
            "end": e.end.astimezone(tz).isoformat(timespec="minutes"),
            "h_peak": e.peak_height_m,
            "dir": e.direction_deg,
            "rating": e.peak_rating,
            "bucket": e.peak_bucket,
        }
        for e in detect_events(scored)
    ]
    return {
        "spot": {
            "id": spot.id,
            "name": spot.name,
            "region": spot.region,
            "tide_best": spot.tide_best,
            "lat": spot.lat,
            "lon": spot.lon,
            "timezone": spot.timezone,
            # Embeddable live cams + their credit; keys omitted entirely when the spot
            # has none. `cams` carries every angle; `cam` stays as the first one for
            # single-cam consumers (map card still).
            **(
                {
                    "cam": _cam_entry(spot.cams[0]),
                    "cams": [_cam_entry(c) for c in spot.cams],
                }
                if spot.cams
                else {}
            ),
        },
        "model": MODEL_NAME,
        "fetched_at": fetched_at,
        "generated_at": now.isoformat(timespec="seconds"),
        "attribution": (f"{ATTRIBUTION} · {ATTRIBUTION_ECMWF}" if has_spectral else ATTRIBUTION),
        # transparency labels for the Stage-3b fields ("why this rating" principle):
        # swell spread is a per-class assumption until validated against buoy spectra
        "spectral_meta": {
            "member": "ecmwf-ifs-0p25 (open data)" if has_spectral else None,
            "spread": "parametric (modeled)",
        },
        "current": current_entry,
        "hours": [_hour_entry(spot, s, tz) for s in table_hours],
        "days": days,
        "events": events,
    }


def write_spot_json(payload: dict, out_dir: Path) -> Path:
    spots_dir = out_dir / "spots"
    spots_dir.mkdir(parents=True, exist_ok=True)
    path = spots_dir / f"{payload['spot']['id']}.json"
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path


def update_index(payload: dict, out_dir: Path) -> Path:
    """Upsert this spot's summary into index.json (list of all published spots)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.json"
    index: dict = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"spots": {}}
    index["spots"][payload["spot"]["id"]] = {
        "name": payload["spot"]["name"],
        "region": payload["spot"].get("region", ""),
        "lat": payload["spot"]["lat"],
        "lon": payload["spot"]["lon"],
        "rating": payload["current"]["rating"],
        "bucket": payload["current"]["bucket"],
        "h": payload["current"]["h"],
        "generated_at": payload["generated_at"],
        # just video ids: enough for the map card still and the nearby-cams strip
        # without fetching whole payloads. Full credit travels in the spot payload.
        **({"cam": payload["spot"]["cam"]["yt"]} if "cam" in payload["spot"] else {}),
        **(
            {"cams": [c["yt"] for c in payload["spot"]["cams"]]}
            if "cams" in payload["spot"]
            else {}
        ),
    }
    path.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    return path


def prune_index(known_ids: set[str], out_dir: Path) -> list[str]:
    """Drop spots that have left the DB from index.json, and delete their payloads.

    update_index only ever upserts, so a spot removed from data/spots/*.yaml would
    otherwise stay published forever - a ghost card and map pin that no longer has
    a YAML entry behind it. Only a full run may call this: a single-spot run has no
    knowledge of the rest of the index. Returns the ids removed.

    Sweeps the payload DIRECTORY as well as the index, because the two go stale
    independently: an index entry can disappear on its own (a rewritten index, a prune
    that ran before the file landed) and from that moment the payload is invisible to an
    index-driven prune and ships in every prebuilt deploy forever. Four such orphans had
    been riding along since 2026-07-23 and were only found by diffing the output
    directory against the DB (2026-08-02).
    """
    path = out_dir / "index.json"
    spots_dir = out_dir / "spots"

    stale: set[str] = set()
    index: dict | None = None
    if path.exists():
        index = json.loads(path.read_text(encoding="utf-8"))
        stale |= set(index.get("spots", {})) - known_ids
    if spots_dir.is_dir():
        stale |= {p.stem for p in spots_dir.glob("*.json")} - known_ids
    if not stale:
        return []

    for spot_id in sorted(stale):
        if index is not None:
            index.get("spots", {}).pop(spot_id, None)
        (spots_dir / f"{spot_id}.json").unlink(missing_ok=True)
    if index is not None:
        path.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    return sorted(stale)
