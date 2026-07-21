"""Build and write the per-spot JSON payload the frontend renders verbatim."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from astral import Observer
from astral.sun import sun

from .models import ScoredHour, Spot
from .transform import in_window

MODEL_NAME = "open-meteo:best_match (marine + forecast v1)"
ATTRIBUTION = "Weather data by Open-Meteo.com (CC-BY 4.0)"
TABLE_DAYS = 16
TABLE_STEP_H = 3
OUTLOOK_DAYS = 16


def _horizon_ceiling(day_index: int) -> float:
    """Confidence a forecast this far out can earn even if every model agrees — skill
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


def _r(x: float, digits: int = 2) -> float:
    return round(x, digits)


def _daylight(
    spot: Spot, day_hours: list[ScoredHour], date_str: str, tz: ZoneInfo
) -> list[ScoredHour]:
    """Hours between dawn and dusk — the day summary must not be driven by a 1 am land
    breeze nobody can surf. Falls back to all hours if the sun never rises/sets (polar)."""
    try:
        s = sun(Observer(spot.lat, spot.lon), date=date.fromisoformat(date_str), tzinfo=tz)
    except ValueError:
        return day_hours
    lit = [h for h in day_hours if s["dawn"] <= h.hour.time.astimezone(tz) <= s["dusk"]]
    return lit or day_hours


def _day_agreement(day_hours: list[ScoredHour]) -> float | None:
    scores = [s.hour.agreement_score for s in day_hours if s.hour.agreement_score is not None]
    return sum(scores) / len(scores) if scores else None


def _hour_entry(spot: Spot, s: ScoredHour, tz: ZoneInfo) -> dict:
    return {
        "t": s.hour.time.astimezone(tz).isoformat(timespec="minutes"),
        "rating": s.rating,
        "bucket": s.bucket,
        "h": [s.h_break_lo, s.h_break_hi],
        "h_mid": _r(s.h_break_mid, 1),
        "phrase": s.phrase,
        # deep-water wave energy flux of in-window partitions: ~0.49 * sum(H^2 * T) kW/m
        "energy": _r(0.49 * s.energy, 1),
        "pressure": round(s.hour.pressure_msl) if s.hour.pressure_msl is not None else None,
        "air": _r(s.hour.air_c, 1) if s.hour.air_c is not None else None,
        "wind": {
            "kph": _r(s.hour.wind_speed_kph, 1),
            "dir": s.hour.wind_dir_deg,
            "class": s.wind_class,
        },
        "sst": _r(s.hour.sst_c, 1) if s.hour.sst_c is not None else None,
        "swells": [
            {
                "h": _r(p.height_m),
                "period": _r(p.period_s, 1),
                "dir": p.direction_deg,
                "kind": p.kind,
                "in_window": in_window(p.direction_deg, spot.swell_window),
            }
            for p in s.hour.partitions
        ],
    }


def build_payload(spot: Spot, scored: list[ScoredHour], *, fetched_at: str, now: datetime) -> dict:
    tz = ZoneInfo(spot.timezone)

    table_hours = [
        s for s in scored[: TABLE_DAYS * 24] if s.hour.time.astimezone(tz).hour % TABLE_STEP_H == 0
    ]

    by_date: dict[str, list[ScoredHour]] = {}
    for s in scored:
        by_date.setdefault(s.hour.time.astimezone(tz).date().isoformat(), []).append(s)
    sorted_dates = sorted(by_date.items())
    date_index = {date_str: i for i, (date_str, _) in enumerate(sorted_dates)}

    current = next((s for s in scored if s.hour.time >= now), scored[-1])
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

    return {
        "spot": {
            "id": spot.id,
            "name": spot.name,
            "lat": spot.lat,
            "lon": spot.lon,
            "timezone": spot.timezone,
        },
        "model": MODEL_NAME,
        "fetched_at": fetched_at,
        "generated_at": now.isoformat(timespec="seconds"),
        "attribution": ATTRIBUTION,
        "current": current_entry,
        "hours": [_hour_entry(spot, s, tz) for s in table_hours],
        "days": days,
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
        "lat": payload["spot"]["lat"],
        "lon": payload["spot"]["lon"],
        "rating": payload["current"]["rating"],
        "bucket": payload["current"]["bucket"],
        "h": payload["current"]["h"],
        "generated_at": payload["generated_at"],
    }
    path.write_text(json.dumps(index, separators=(",", ":")), encoding="utf-8")
    return path
