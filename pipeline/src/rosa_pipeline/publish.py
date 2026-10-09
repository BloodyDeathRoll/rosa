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

ATTRIBUTION = "Weather data by Open-Meteo.com (CC-BY 4.0) · Tides: EOT20 (CC-BY 4.0)"
ATTRIBUTION_ECMWF = "Wave spectra: ECMWF open data (CC-BY 4.0)"
# The promoted arm (2026-08-26): waves are NOAA GFS-Wave (public domain) blended with
# ECMWF open data (CC-BY 4.0); SST is NOAA OISST; weather stays Open-Meteo (plan C3).
ATTRIBUTION_BLEND = (
    "Waves: NOAA GFS-Wave + ECMWF open data (CC-BY 4.0) · Peak periods: DWD GWAM "
    "(CC-BY 4.0) · Weather by Open-Meteo.com (CC-BY 4.0) · Sea temp: NOAA OISST · "
    "Tides: EOT20 (CC-BY 4.0)"
)
TABLE_DAYS = 16
TABLE_STEP_H = 3
OUTLOOK_DAYS = 16


# Tier -> (static fallback ceiling, lead buckets whose measured skill covers it).
# The static numbers are the pre-2026-08-07 hand-set constants; they remain the
# fallback whenever the archive hasn't matured enough distinct hours in a tier.
# Bucket lists cover each tier's day range EXACTLY (day N = leads 24N..24N+24 h):
# tier 0 = days 0-3 = 0-96 h, tier 1 = days 4-9 = 96-240 h, tier 2 = day 10+.
# That is why verify.LEAD_BUCKETS splits at 96 h and 240 h - a tier priced from
# fresher leads than the days it covers would overstate confidence (the day-3
# bug caught in the 2026-08-07 review).
_CEILING_TIERS: tuple[tuple[int | None, float, tuple[str, ...]], ...] = (
    (3, 1.0, ("0-1d", "1-3d", "3-4d")),
    (9, 0.85, ("4-5d", "5-7d", "7-9d")),
    (None, 0.4, ("9d+",)),
)
SKILL_N_FLOOR = 100  # distinct compared hours a tier needs before its measurement is trusted
SKILL_CEILING_MIN = 0.1  # even a terrible measured tier keeps a visible floor


def load_skill_ceilings(path: Path) -> tuple[dict[int, float], str] | None:
    """Measured horizon ceilings from ``verify --archive``'s skill.json, or None.

    Maps each tier's n-weighted scatter index onto a ceiling (1 - SI, clamped):
    SI is rmse relative to the observed mean, so "typically 20% off" reads as "at
    most 0.8 confident" - crude, monotone, and auditable against the harness.
    A tier whose buckets hold fewer than SKILL_N_FLOOR distinct hours falls back
    to the static constant; with the archive's no-backfill rule the far tiers
    ship on fallback for their first weeks, deliberately. Ceilings are then
    clamped monotone non-increasing across tiers: near leads mature first, so a
    measured tier 0 below a still-static tier 1 would otherwise publish day 5 at
    HIGHER confidence than tomorrow - skill never improves with lead. Second
    element is the provenance string the payload publishes, naming the buoys the
    measurement came from AND the lead buckets that actually cleared the floor:
    the archive matures nearest-first and cannot be back-filled, so a tier can
    read "measured" off one matured bucket beside two still-empty ones. Naming
    the leads is what lets a reader re-run ``verify --archive`` and reproduce
    exactly what the string claims, at the lead they are looking at. The whole
    body is guarded: skill.json is derived, rewritable state written
    non-atomically, so a torn or malformed file must read as "no measurement"
    (static defaults), never abort a publish cycle."""
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            # An EMPTY file is "no measurement", not damage, and must not warn:
            # `run --skill /dev/null` is the documented A/B control arm (its help text
            # says so), and /dev/null reads as "". skill.json itself is written
            # tmp+replace, so zero bytes is not a failure mode it has. A control-arm run
            # whose log carries a line that reads like a fault is a run that gets
            # disbelieved or re-done - and both arms being auditable is the whole point.
            return None
        skill = json.loads(text)
        buckets = skill["buckets"]
        ceilings: dict[int, float] = {}
        matured: list[str] = []  # lead buckets scored on their own, for the provenance
        for tier_i, (_max_day, static, labels) in enumerate(_CEILING_TIERS):
            entries = [buckets.get(lb) or {} for lb in labels]
            n = sum(int(e.get("n") or 0) for e in entries)
            # a bucket past the floor implies its tier is too (the tier's n is the sum),
            # so this can never claim a lead inside a tier that fell back to static
            matured.extend(
                lb
                for lb, e in zip(labels, entries, strict=True)
                if e.get("scatter_index") is not None and int(e.get("n") or 0) >= SKILL_N_FLOOR
            )
            sis = [
                (float(e["scatter_index"]), int(e["n"]))
                for e in entries
                if e.get("scatter_index") is not None
            ]
            weight = sum(w for _, w in sis)
            if n < SKILL_N_FLOOR or not sis or weight <= 0:
                # weight == 0: every bucket that carries a scatter_index has n == 0 while
                # the tier's summed n clears the floor - a shape the writer never emits
                # (merge_var_scores drops n == 0) but a hand-edited or damaged file can.
                # It is "no measurement", not a ZeroDivisionError before the per-spot guard.
                ceilings[tier_i] = static
                continue
            si = sum(v * w for v, w in sis) / weight
            ceilings[tier_i] = max(SKILL_CEILING_MIN, min(1.0, 1.0 - si))
        for tier_i in range(1, len(_CEILING_TIERS)):
            ceilings[tier_i] = min(ceilings[tier_i], ceilings[tier_i - 1])
        generated = skill.get("generated", "?")
        # which forecast was measured (blend since 2026-10-08); older files carry no key
        card = f", {skill['source']} card" if isinstance(skill.get("source"), str) else ""
        ids = skill.get("buoy_ids") or []
        hours = skill.get("buoy_hours")
        if isinstance(hours, dict):
            # name only the buoys the measurement came from (older files lack the key)
            ids = [b for b in ids if int(hours.get(b) or 0) > 0]
        buoys = ", ".join(ids) or "unknown buoys"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        # AttributeError: a bucket map that parsed as a non-dict (.get on a str)
        if path.exists():
            print(f"warn: {path} is unreadable - static ceilings this run")
        return None
    if all(ceilings[i] == static for i, (_d, static, _l) in enumerate(_CEILING_TIERS)):
        # nothing matured past the floor - identical to defaults, say so honestly
        return ceilings, (
            f"static defaults (skill.json {generated}: no tier past n>={SKILL_N_FLOOR})"
        )
    leads = ",".join(matured) if matured else f"none past n>={SKILL_N_FLOOR}"
    return ceilings, (
        f"measured (verify skill.json {generated}{card}, buoys: {buoys}, leads: {leads})"
    )


def _horizon_ceiling(day_index: int, ceilings: dict[int, float] | None = None) -> float:
    """Confidence a forecast this far out can earn even if every model agrees - skill
    degrades with lead time, and the day 10+ tail is GFS-Wave-only. ``ceilings``
    (2026-08-07) substitutes measured per-tier values derived from the shipped
    verification harness; None keeps the static constants."""
    for tier_i, (max_day, static, _labels) in enumerate(_CEILING_TIERS):
        if max_day is None or day_index <= max_day:
            return ceilings[tier_i] if ceilings is not None else static
    return _CEILING_TIERS[-1][1]  # unreachable - the last tier is open-ended


def _confidence(
    day_index: int,
    agreement_score: float | None,
    ceilings: dict[int, float] | None = None,
) -> tuple[str, float]:
    """Combine multi-model agreement with the horizon ceiling → (label, 0-1 score).
    No ensemble (agreement None) → fall back to the horizon proxy alone.

    Closure deliberately does NOT feed this (2026-08-07 review): capping on
    closure² is the honest option ALGORITHM.md sketches, but shipping it is a
    fleet-wide confidence change (7.5% of published hours leave "high") and so
    needs a Stage-0 A/B and a CALIBRATION.md entry first - plus a small-Hs guard,
    since at calm hours closure dips are quantisation noise, not missing sea."""
    ceiling = _horizon_ceiling(day_index, ceilings)
    base = agreement_score if agreement_score is not None else ceiling
    score = min(base, ceiling)
    label = "high" if score >= 0.7 else "medium" if score >= 0.45 else "low"
    return label, round(score, 2)


def _cam_entry(cam: SpotCam) -> dict:
    return {
        "yt": cam.youtube_id,
        "by": cam.by,
        "by_url": cam.by_url,
        "ch": cam.channel_id,
        "title": cam.title,
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


def _day_models(day_hours: list[ScoredHour]) -> int:
    """Fewest ensemble members backing any hour handed in - 0 = at least one hour had none.
    The ``days`` loop hands in the daylight hours, the window the headline is read off
    (2026-09-19): one 3 am hour without members no longer zeroes a fully backed day.

    Published so a reader can tell an ensemble-backed confidence from a horizon-proxy one.
    They are not the same claim and the label does not distinguish them: with no ensemble
    ``_confidence`` falls back to the ceiling alone, which is >= the score the same hour
    would have earned WITH members (min(agreement, ceiling)), so a lost ensemble - the
    documented 429 fallback in fetch._fetch_batch - publishes a day at the HIGHEST
    confidence its horizon allows. Changing that score is a tuning change and is not done
    here; saying how many models stood behind it costs one integer per day."""
    return min((s.hour.n_models for s in day_hours), default=0)


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
    # Stage-4 per-hour provenance: which model carried the wave to the handoff point.
    # Omitted (not null) on the shipping path, so payloads outside a modelled region are
    # byte-identical to before.
    if s.nearshore is not None:
        entry["nearshore"] = s.nearshore
    # member bearing fan, deg - diagnostic like closure: nothing scores on it
    # (2026-08-07 revert), but publishing it is what lets a calibration entry
    # derive a direction tolerance from real hours instead of a borrowed
    # constant. Omitted (not null) when <2 member bearings, to keep payloads small.
    if s.hour.dir_span_deg is not None:
        entry["dir_span"] = round(s.hour.dir_span_deg)
        # ...and how many bearings that span covers. The span is the widest PAIRWISE gap,
        # so it grows with the member count on its own (k members = k(k-1)/2 pairs), and
        # the count moves with lead time as shorter-horizon members drop out. Published
        # beside the span because nothing else in the payload carries it: `models` on
        # `current` counts HEIGHT members, and the fan (ECMWF bearing included since
        # 2026-08-11) can be smaller than it when a member's bearing is missing. Without it a
        # calibration entry pooling these hours would read member attrition as direction
        # disagreement.
        entry["dir_n"] = s.hour.n_dir_members
    spectral = _spectral_entry(s)
    if spectral is not None:
        entry["spectral"] = spectral
    return entry


def _tail_from(visible: list, tz) -> str | None:
    """Local-time stamp of the first visible hour served by the GFS-Wave tail."""
    for sc in visible:
        if getattr(sc.hour, "from_tail", False):
            return sc.hour.time.astimezone(tz).isoformat(timespec="minutes")
    return None


def _blend_attribution(has_spectral: bool, has_peak_periods: bool) -> str:
    """Build the blend-arm credit from what the run actually had, not a constant."""
    waves = "Waves: NOAA GFS-Wave"
    if has_spectral:
        waves += " + ECMWF open data (CC-BY 4.0)"
    parts = [waves]
    if has_peak_periods:
        parts.append("Peak periods: DWD GWAM (CC-BY 4.0)")
    parts.append("Weather by Open-Meteo.com (CC-BY 4.0)")
    parts.append("Sea temp: NOAA OISST")
    parts.append("Tides: EOT20 (CC-BY 4.0)")
    return " · ".join(parts)


def build_payload(
    spot: Spot,
    scored: list[ScoredHour],
    *,
    fetched_at: str,
    now: datetime,
    skill: tuple[dict[int, float], str] | None = None,
    wave_source: str = "om",
    model_run: dict | None = None,
) -> dict:
    """``wave_source`` ("om" | "blend") picks the data credit only; nothing scores on it.
    ``model_run`` (blend arm, per point - see blend._model_run) is published beside
    ``fetched_at`` when present: the cycle the numbers came from, which on the blend arm
    Rosa itself chose and may have dropped back 6-12 h from. Provenance only."""
    tz = ZoneInfo(spot.timezone)
    ceilings, ceiling_source = skill if skill is not None else (None, "static defaults")

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
    # ...but TODAY is exempt. The parenthetical above ("the leading day can't be partial")
    # is a premise, not a guarantee: extract_hours drops any hour whose weather record has
    # a null wind - a case its own comment records as observed on the past_days hours - and
    # east of UTC those are precisely the hours covering local midnight. Lose two of them
    # and the leading day fails _covers_day like any other, which deleted today from
    # `days`/`hours` AND pushed `current` (the app's whole first screen) onto tomorrow's
    # 00:00, under a fresh generated_at with nothing saying which day it is. A thin card
    # for today is honest; yesterday's answer relabelled as now is not. Trailing and
    # interior days keep the filter exactly as before.
    leading = min(by_date) if by_date else None
    complete = {d: hrs for d, hrs in by_date.items() if d == leading or _covers_day(hrs, tz)}
    if complete:  # never strip everything - a spot with no full day still reports
        by_date = complete
        visible = [s for s in visible if day_of(s) in by_date]

    table_hours = [
        s for s in visible[: TABLE_DAYS * 24] if s.hour.time.astimezone(tz).hour % TABLE_STEP_H == 0
    ]

    sorted_dates = sorted(by_date.items())

    # Lead in days from the run, NOT the position in the published list. `_horizon_ceiling`
    # is a claim about forecast SKILL at a lead time, and this list has holes in it by
    # construction: the `_covers_day` filter above drops any day the model half-covers.
    # Keyed on position, one dropped mid-series day promoted every later day a whole tier -
    # a day-10, GFS-Wave-only forecast published as 0.85 "high" instead of 0.4 "low".
    def lead_days(date_str: str) -> int:
        return max(0, (date.fromisoformat(date_str) - today_local).days)

    current = next((s for s in visible if s.hour.time >= now), visible[-1])
    current_entry = _hour_entry(spot, current, tz)
    current_entry["wetsuit"] = current.wetsuit
    current_entry["why"] = {
        "size": _r(current.size_score, 1),
        "period": _r(current.period_score, 1),
        "wind": _r(current.wind_score, 1),
    }
    cur_date = current.hour.time.astimezone(tz).date().isoformat()
    cur_label, cur_score = _confidence(lead_days(cur_date), current.hour.agreement_score, ceilings)
    current_entry["confidence"] = {
        "label": cur_label,
        "score": cur_score,
        "models": current.hour.n_models,
    }

    days = []
    for date_str, day_hours in sorted_dates[:OUTLOOK_DAYS]:
        # one window for the headline AND the confidence beside it (CALIBRATION.md 2026-09-19)
        lit = _daylight(spot, day_hours, date_str, tz)
        best = max(lit, key=lambda s: s.rating)
        label, score = _confidence(lead_days(date_str), _day_agreement(lit), ceilings)
        days.append(
            {
                "date": date_str,
                "rating_max": best.rating,
                "bucket": best.bucket,
                "h_max": [best.h_break_lo, best.h_break_hi],
                "confidence": label,
                "confidence_score": score,
                # how many ensemble members stood behind that label (see _day_models);
                # 0 means the horizon proxy alone, which the label cannot say by itself
                "models": _day_models(lit),
            }
        )

    has_spectral = any(s.hour.spectral is not None for s in scored)
    has_peak_periods = any(p.peak_period_s is not None for s in visible for p in s.hour.partitions)
    # swell events (CLAUDE.md spec): >= 12 h of >= 2x-baseline energy, GOOD+ at peak -
    # the alerts/swell-stories seed; local-time ISO like every other timestamp here.
    #
    # DETECTED over the whole series (the trailing baseline needs the history), but only
    # PUBLISHED when the peak lands on a day this payload actually shows. Detecting over
    # `scored` and publishing unfiltered leaked events past both trims above: one peaking
    # on the half-covered tail day - whose h_peak/rating are read off exactly the few
    # hours `_covers_day` had just rejected as too thin to forecast from - and one that
    # finished yesterday, which the web renders as live (notify filters those, the payload
    # did not). Both link to `/spot/<id>?ev=<peak date>`, a day with no card behind it.
    published_dates = {d["date"] for d in days}
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
        if e.peak.astimezone(tz).date().isoformat() in published_dates
    ]
    return {
        "spot": {
            "id": spot.id,
            "name": spot.name,
            "region": spot.region,
            # search-only: the town a break is often known by. Key omitted when unset.
            **({"town": spot.town} if spot.town else {}),
            "tide_best": spot.tide_best,
            # swim mode's shore type; key omitted when unset, so today's output is unchanged
            **({"shore": spot.shore} if spot.shore else {}),
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
        # No `model` key by design (2026-08-14): the payload is stitched per hour from
        # best_match and the GFS-Wave tail, so one constant name was wrong on ~40% of
        # rows, and nothing rendered it. `attribution` carries the data credit.
        # `tail_from` below is the per-hour version, and the only one that is true.
        "fetched_at": fetched_at,
        # First published hour that came from the GFS-Wave tail instead of best_match
        # (extract._merge_models anchors this on wave_height, so it describes the whole
        # hour). The boundary is monotone per point, so one stamp says what a per-hour
        # key would - at one key per payload instead of ~400. None when every visible
        # hour is best_match, or when the source published a single model (fixtures,
        # the blend arm). Display provenance only: nothing scores on it.
        "tail_from": _tail_from(visible, tz),
        # Blend arm: when the model RAN, per point - fetched_at says only when Rosa asked.
        # Omitted (not null) on the OM arm and on fixtures, where the cycle is not known.
        **({"model_run": model_run} if model_run else {}),
        "generated_at": now.isoformat(timespec="seconds"),
        "attribution": _blend_attribution(has_spectral, has_peak_periods)
        if wave_source == "blend"
        else (f"{ATTRIBUTION} · {ATTRIBUTION_ECMWF}" if has_spectral else ATTRIBUTION),
        # transparency labels for the Stage-3b fields ("why this rating" principle):
        # swell spread is a per-class assumption until validated against buoy spectra
        "spectral_meta": {
            "member": "ecmwf-ifs-0p25 (open data)" if has_spectral else None,
            "spread": "parametric (modeled)",
        },
        # where the horizon ceiling came from ("why this rating" principle, 2026-08-07):
        # a reader can regenerate the measured value with `verify --archive` and compare
        "confidence_meta": {"ceiling_source": ceiling_source},
        "current": current_entry,
        "hours": [_hour_entry(spot, s, tz) for s in table_hours],
        "days": days,
        "events": events,
    }


def write_json_atomic(path: Path, obj: dict) -> None:
    """Compact JSON via tmp+replace, so a killed run can't leave a torn file.

    publish.sh ships data/out wholesale to the CDN, so a half-written file would
    serve to every client until the next cycle - and the heal-on-read guards
    (_read_index, notify._iter_payloads, swellmap's index merge) only protect the
    pipeline, not the app. Same idiom as skill.json in cli._cmd_verify."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def write_spot_json(payload: dict, out_dir: Path) -> Path:
    spots_dir = out_dir / "spots"
    spots_dir.mkdir(parents=True, exist_ok=True)
    path = spots_dir / f"{payload['spot']['id']}.json"
    write_json_atomic(path, payload)
    return path


def _index_entry(payload: dict) -> dict:
    return {
        "name": payload["spot"]["name"],
        "region": payload["spot"].get("region", ""),
        # the search index matches name, region, town and id - see web/src/pages/SearchPage.tsx
        **({"town": payload["spot"]["town"]} if payload["spot"].get("town") else {}),
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


def _read_index(out_dir: Path) -> dict:
    """index.json, rebuilt from the payloads on disk when it can't be read.

    index.json has been written atomically since 2026-08-08, so a kill between truncate
    and flush can no longer tear it. The guard stays as defense in depth (disk damage,
    partial CDN syncs, hand edits), because a torn index parsed bare once made every
    spot in ``_cmd_run``'s per-spot guard raise JSONDecodeError, ``published`` stay 0 and
    the cycle return 1 WITHOUT rewriting the file - so the next cycle failed identically
    and the pipeline stayed down until a human deleted it. There is no request-time
    backend to cover that gap.

    Nothing has to be invented to recover: every field the index holds is a copy of one
    already in ``spots/<id>.json``, so the payload directory is the authority and the
    index is a derived cache. A payload that is itself unreadable is skipped - the run
    that publishes it will upsert it back."""
    path = out_dir / "index.json"
    if path.exists():
        try:
            index = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            index = None
        else:
            if isinstance(index, dict) and isinstance(index.get("spots"), dict):
                return index
        print(f"warn: {path} is unreadable - rebuilding it from {out_dir / 'spots'}")

    spots: dict[str, dict] = {}
    for p in sorted((out_dir / "spots").glob("*.json")):
        try:
            spots[p.stem] = _index_entry(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, KeyError, TypeError):
            print(f"warn: {p} is unreadable - left out of the rebuilt index")
    return {"spots": spots}


def update_index(payload: dict, out_dir: Path) -> Path:
    """Upsert this spot's summary into index.json (list of all published spots)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.json"
    index = _read_index(out_dir)
    index["spots"][payload["spot"]["id"]] = _index_entry(payload)
    write_json_atomic(path, index)
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
        index = _read_index(out_dir)  # same self-heal as update_index - never raise here
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
        write_json_atomic(path, index)
    return sorted(stale)
