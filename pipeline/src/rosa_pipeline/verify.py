"""Forecast-skill scoring against buoy truth (roadmap Stage 0).

Scores the OFFSHORE model field (link 1 of the forecast chain) - significant wave height,
period, and direction - sampled at a buoy against that buoy's observations. Pure functions
over paired series; the CLI wires live/fixture I/O around them.

Two comparison notes baked in:
- Open-Meteo ``wave_period`` is a MEAN period - but "mean period" is not one quantity.
  It is the ENERGY period Tm-1,0 (m-1/m0); the buoy's APD is Tm02 (sqrt(m0/m2)), and
  Tm-1,0 > Tm02 for any real spectrum. Pairing the two manufactures a positive bias
  (+2.67 s fleet-wide vs +0.54 s against Tm-1,0; CALIBRATION.md 2026-07-29). So the
  period pairs with Tm-1,0 measured from the station's own spectrum
  (``ENERGY_PERIOD_VARIABLES``); the APD pairing survives only as a labelled fallback
  for stations that publish no spectra, and must never be calibrated against.
- Direction is circular - errors wrap at ±180°, and scatter-index is undefined for it.
- NDBC's MWD is the direction AT THE DOMINANT PERIOD (NDBC measurement descriptions,
  checked 2026-09-13) - a PEAK direction despite its name. GFS-Wave's dirpw is a peak too,
  so that row is like-for-like; Open-Meteo's wave_direction and ECMWF's mwd are MEANS, so
  their direction rows carry a peak-vs-mean offset in bimodal seas and are not a
  calibratable bias (CALIBRATION.md 2026-09-13).

The nowcast path (compare today's forecast hours to the buoy's recent obs) needs no stored
history and works immediately; the archive path (Stage 0 next increment) extends this to
lead-time skill by replaying forecasts stamped at successive run times.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from .buoys import Buoy
from .observe import BuoyObs
from .spectra import SpectrumMeasures
from .stations import Station

# the APD-paired period label; the renderers footnote it so a reader can never mistake
# this row for a calibratable bias (see module docstring)
APD_FALLBACK_LABEL = "Mean per. vs APD"

# variable key -> (label, unit, model attr, obs attr, circular?)
# FALLBACK pairing: period vs the buoy's APD (Tm02). Definitionally ~2 s hot against
# Open-Meteo's Tm-1,0 - used only where no spectrum is published. Prefer the tuple below.
# 10 m wind vs the buoy's anemometer (plan C3 evidence) - appended to the OM and
# GFS-Wave tuples; n=0 on all pre-2026-08-14 rows, accumulating since. NOT on the ECMWF
# tuple: the open-data wave stream carries no 10 m wind, and an always-empty row on its
# card would read like a measurement.
_WIND_VARIABLES = (
    ("ws", "Wind speed", "m/s", "ws", "wspd_ms", False),
    ("wdir", "Wind direction", "°", "wdir", "wdir_deg", True),
)

VARIABLES = (
    ("hs", "Sig. wave height", "m", "hs", "hs_m", False),
    ("tp", APD_FALLBACK_LABEL, "s", "tp", "apd_s", False),
    ("dir", "Wave direction", "°", "dir", "mwd_deg", True),
    *_WIND_VARIABLES,
)

# PREFERRED pairing for Open-Meteo: like-for-like against the measured energy period.
# Needs obs enriched by with_energy_period().
ENERGY_PERIOD_VARIABLES = (
    ("hs", "Sig. wave height", "m", "hs", "hs_m", False),
    ("tp", "Energy period", "s", "tp", "tm_m10_s", False),
    ("dir", "Wave direction", "°", "dir", "mwd_deg", True),
    *_WIND_VARIABLES,
)

# GFS-Wave archive rows carry a PEAK period (perpw), so tp pairs with the buoy's DPD
# (dominant period), not APD - pairing mean-vs-dominant would fabricate a bias (Stage 3a).
GFSWAVE_VARIABLES = (
    ("hs", "Sig. wave height", "m", "hs", "hs_m", False),
    ("tp", "Peak period", "s", "tp", "dpd_s", False),
    ("dir", "Wave direction", "°", "dir", "mwd_deg", True),
    *_WIND_VARIABLES,
)

# ECMWF archive rows store pp1d - also a peak period, same DPD pairing (Stage 3b).
# No wind: the open-data wave stream does not publish it.
ECMWF_VARIABLES = (
    ("hs", "Sig. wave height", "m", "hs", "hs_m", False),
    ("tp", "Peak period", "s", "tp", "dpd_s", False),
    ("dir", "Wave direction", "°", "dir", "mwd_deg", True),
)

# Coastal wind stations (rosa_pipeline.stations) archive the model's 10 m wind only, so
# their card is the wind pair alone - a wave row against an airport would be nonsense.
STATION_VARIABLES = _WIND_VARIABLES


@dataclass(frozen=True, slots=True)
class WavePoint:
    time: datetime  # tz-aware UTC
    hs: float | None
    tp: float | None
    dir: float | None
    # co-located 10 m wind (fetch-plane plan C3 evidence, 2026-08-14): archived from both
    # sources so the weather-migration decision can be a measurement against the buoys'
    # anemometers. m/s to pair with NDBC WSPD directly. None on pre-2026-08-14 history;
    # GFS carries it in the same wave gribs, OM needs the separate weather-host join
    # (verify.join_wind). Field VERIFIED live before shipping - both sources return values.
    ws: float | None = None
    wdir: float | None = None


@dataclass(frozen=True, slots=True)
class VarScore:
    key: str
    label: str
    unit: str
    n: int
    bias: float
    mae: float
    rmse: float
    scatter_index: float | None  # rmse / mean(obs); None for circular direction


def parse_marine_waves(marine: dict) -> list[WavePoint]:
    """Total sea-state series from an Open-Meteo marine payload (wave_height/period/direction)."""
    hourly = marine["hourly"]
    times = hourly["time"]
    hs = hourly.get("wave_height", [None] * len(times))
    tp = hourly.get("wave_period", [None] * len(times))
    wd = hourly.get("wave_direction", [None] * len(times))
    out: list[WavePoint] = []
    for t, h, p, d in zip(times, hs, tp, wd, strict=True):
        out.append(
            WavePoint(
                time=datetime.fromisoformat(t).replace(tzinfo=UTC),
                hs=h,
                tp=p,
                dir=d,
            )
        )
    return out


def join_wind(model: list[WavePoint], weather: dict) -> list[WavePoint]:
    """Attach OM 10 m wind (m/s) to wave points, matched by exact timestamp.

    ``weather`` is a weather-host body (fetch.fetch_wind_many - requested in m/s).
    Points without a matching hour keep ws/wdir None; never interpolated here."""
    hourly = weather.get("hourly", {})
    times = hourly.get("time", [])
    ws = hourly.get("wind_speed_10m", [])
    wd = hourly.get("wind_direction_10m", [])
    by_time = {
        t: (ws[i] if i < len(ws) else None, wd[i] if i < len(wd) else None)
        for i, t in enumerate(times)
    }
    out: list[WavePoint] = []
    for p in model:
        w = by_time.get(p.time.strftime("%Y-%m-%dT%H:%M"))
        out.append(replace(p, ws=w[0], wdir=w[1]) if w is not None else p)
    return out


def wind_points(weather: dict) -> list[WavePoint]:
    """A weather-host body (fetch.fetch_wind_many, m/s) as wind-only points: the archive
    row shape for a coastal station, where there is no wave field to attach wind to."""
    hourly = weather.get("hourly", {})
    times = hourly.get("time", [])
    ws = hourly.get("wind_speed_10m", [])
    wd = hourly.get("wind_direction_10m", [])
    out: list[WavePoint] = []
    for i, t in enumerate(times):
        out.append(
            WavePoint(
                time=datetime.fromisoformat(t).replace(tzinfo=UTC),
                hs=None,
                tp=None,
                dir=None,
                ws=ws[i] if i < len(ws) else None,
                wdir=wd[i] if i < len(wd) else None,
            )
        )
    return out


def ang_diff(a: float, b: float) -> float:
    """Signed smallest angle a-b in (-180, 180]."""
    return (a - b + 180.0) % 360.0 - 180.0


def _circular_mean_deg(vals: list[float]) -> float:
    """Vector-mean bearing - naive averaging breaks across the 0/360 wrap."""
    s = sum(math.sin(math.radians(v)) for v in vals)
    c = sum(math.cos(math.radians(v)) for v in vals)
    return math.degrees(math.atan2(s, c)) % 360.0


def _collapse_hour(hour_pairs: list[tuple[float, float]], circular: bool) -> tuple[float, float]:
    """Average the archived runs of one valid hour into a single (model, obs) pair.

    The obs side is the same observation repeated (identical valid -> identical
    nearest match), so its mean is a no-op kept for symmetry; the model side is a
    true mean across runs. Direction averages as a vector, not arithmetically.

    Only for callers that need a (model, obs) PAIR per hour and read it linearly - the
    diurnal bias fit (``_station_pairs``). A scorecard must not grade this mean: see
    ``_score_hours``."""
    if len(hour_pairs) == 1:
        return hour_pairs[0]
    ms = [m for m, _ in hour_pairs]
    os_ = [o for _, o in hour_pairs]
    if circular:
        return _circular_mean_deg(ms), _circular_mean_deg(os_)
    return sum(ms) / len(ms), sum(os_) / len(os_)


def _obs_index(obs: list[BuoyObs]) -> tuple[list[BuoyObs], list[datetime]]:
    """Sort once, so ``_nearest_obs`` can bisect instead of rescanning.

    Every parser already returns observations oldest-first (observe.py:103, :230, :263, :311)
    and ``with_energy_period`` preserves input order - but that is an informal invariant, and
    an unsorted source would make the bisect silently return the wrong neighbour where the old
    linear scan was right. Sorting here (once per variable, not once per model point) makes it
    an enforced one instead."""
    ordered = sorted(obs, key=lambda o: o.time)
    return ordered, [o.time for o in ordered]


def _nearest_obs(
    t: datetime, index: tuple[list[BuoyObs], list[datetime]], tol: timedelta
) -> BuoyObs | None:
    """Nearest observation to ``t`` within ``tol``, in O(log n).

    Was a linear scan over every observation, once per (variable, model point): O(V*M*O). That
    is seconds on a nowcast but compounds on ``verify --archive``, where the archive gains
    ~len(model) rows per buoy per run and so gets slower every day the project measures.
    Same two-neighbour pattern already used by ``with_energy_period`` and
    ``extract._nearest_spectral``.

    Tie-breaking is preserved exactly, which takes more care than it looks: the old scan's
    ``gap <= best_gap`` kept the LAST equal-gap observation in list order, and buoy files do
    repeat timestamps. Splitting at ``bisect_right`` puts the last row of the ``<= t`` run at
    ``i - 1`` for free, but ``i`` is the FIRST row of the later run - so walk it to that run's
    last row too. Checking the earlier candidate before the later one then reproduces the
    scan's preference for the later observation when the two are equidistant."""
    ordered, times = index
    i = bisect_right(times, t)
    hi = bisect_right(times, times[i]) - 1 if i < len(times) else i
    best: BuoyObs | None = None
    best_gap = tol
    for j in (i - 1, hi):
        if 0 <= j < len(ordered):
            gap = abs(ordered[j].time - t)
            if gap <= best_gap:
                best, best_gap = ordered[j], gap
    return best


def with_energy_period(
    obs: list[BuoyObs], measures: Sequence[SpectrumMeasures], *, tol_min: int = 30
) -> list[BuoyObs]:
    """Attach each observation's measured energy period Tm-1,0, from the nearest spectrum.

    This is what makes a like-for-like period comparison possible: the standard-met file
    publishes only APD (Tm02), while the model serves Tm-1,0. Observations with no
    spectrum inside ``tol_min`` keep ``tm_m10_s = None`` and simply drop out of period
    scoring - never silently fall back to APD, which is the bias this exists to remove."""
    if not measures:
        return obs
    ordered = sorted(measures, key=lambda m: m.time)
    times = [m.time for m in ordered]
    tol = timedelta(minutes=tol_min)
    out: list[BuoyObs] = []
    for o in obs:
        i = bisect_left(times, o.time)
        best: SpectrumMeasures | None = None
        best_gap = tol
        for j in (i - 1, i):  # times is sorted, so the nearest is one of these two
            if 0 <= j < len(ordered):
                gap = abs(ordered[j].time - o.time)
                if gap <= best_gap:
                    best, best_gap = ordered[j], gap
        out.append(o if best is None else replace(o, tm_m10_s=best.tm_m10_s))
    return out


def pair_series(
    model: list[WavePoint], obs: list[BuoyObs], *, tol_min: int = 30, variables: tuple = VARIABLES
) -> dict[str, list[tuple[float, float]]]:
    """(model, obs) value pairs per variable - each forecast hour matched to the nearest
    observation *that actually reports that variable* within ``tol_min``.

    Matching is per-variable, not per-row: many buoys log met every 10 min but waves only
    every ~30-60 min, so the time-nearest row is often wave-blank. Filtering to rows with
    the field present before the nearest-search is what keeps those hours scorable."""
    tol = timedelta(minutes=tol_min)
    pairs: dict[str, list[tuple[float, float]]] = {key: [] for key, *_ in variables}
    for key, _label, _unit, m_attr, o_attr, _circ in variables:
        # indexed once per variable, outside the model loop
        index = _obs_index([o for o in obs if getattr(o, o_attr) is not None])
        for mp in model:
            mv = getattr(mp, m_attr)
            if mv is None:
                continue
            o = _nearest_obs(mp.time, index, tol)
            if o is not None:
                pairs[key].append((mv, getattr(o, o_attr)))
    return pairs


def _score_var(
    key: str, label: str, unit: str, pairs: list[tuple[float, float]], circular: bool
) -> VarScore:
    n = len(pairs)
    if n == 0:
        return VarScore(key, label, unit, 0, 0.0, 0.0, 0.0, None)
    diffs = [ang_diff(m, o) if circular else (m - o) for m, o in pairs]
    bias = sum(diffs) / n
    mae = sum(abs(d) for d in diffs) / n
    rmse = math.sqrt(sum(d * d for d in diffs) / n)
    si: float | None = None
    if not circular:
        mean_obs = sum(o for _, o in pairs) / n
        si = rmse / mean_obs if mean_obs else None
    return VarScore(key, label, unit, n, bias, mae, rmse, si)


def _score_hours(
    key: str,
    label: str,
    unit: str,
    hours: list[list[tuple[float, float]]],
    circular: bool,
) -> VarScore:
    """Score one comparison per distinct valid hour, from the archived runs covering it.

    n counts HOURS (the 2026-08-07 rule), but each hour's terms are the mean of its runs'
    ERRORS, never the error of its runs' mean. Averaging the forecasts first scored a
    lagged-ensemble mean nobody published: |mean(d)| <= mean(|d|) and mean(d)^2 <= mean(d^2),
    so mae/rmse/scatter-index could only read too small, and by more the wider the bucket
    (4 runs in "0-1d", 24 in "9d+") - two runs 1 m low and 1 m high scored as a perfect
    forecast. bias is linear, so it is the same number either way. An hour covered by one
    run is bit-identical to ``_score_var``."""
    hours = [hp for hp in hours if hp]
    n = len(hours)
    if n == 0:
        return VarScore(key, label, unit, 0, 0.0, 0.0, 0.0, None)
    bias = mae = sq = obs_sum = 0.0
    for hp in hours:
        diffs = [ang_diff(m, o) if circular else (m - o) for m, o in hp]
        k = len(diffs)
        bias += sum(diffs) / k
        mae += sum(abs(d) for d in diffs) / k
        sq += sum(d * d for d in diffs) / k
        obs_sum += sum(o for _, o in hp) / k
    rmse = math.sqrt(sq / n)
    si: float | None = None
    if not circular:
        mean_obs = obs_sum / n
        si = rmse / mean_obs if mean_obs else None
    return VarScore(key, label, unit, n, bias / n, mae / n, rmse, si)


def build_scorecard(
    model: list[WavePoint],
    obs: list[BuoyObs],
    *,
    tol_min: int = 30,
    variables: tuple = VARIABLES,
) -> dict[str, VarScore]:
    pairs = pair_series(model, obs, tol_min=tol_min, variables=variables)
    return {
        key: _score_var(key, label, unit, pairs[key], circular)
        for key, label, unit, _m, _o, circular in variables
    }


# lead-time buckets (hours): label, lo (inclusive), hi (exclusive)
# Bucket edges sit exactly on publish._CEILING_TIERS' day boundaries so every
# ceiling tier is priced from the leads of the days it covers, nothing fresher:
# 7d+ split at 240 h (day 9/10 tier change, and the day-10+ tail is
# GFS-Wave-only); 3-5d split at 96 h (2026-08-07 review) because tier 0 ends at
# day 3 = leads up to 96 h - with a whole 72-120 h bucket, day 3 was priced
# partly from day-4 forecasts and day 4 partly from day-3 ones.
LEAD_BUCKETS: tuple[tuple[str, float, float], ...] = (
    ("0-1d", 0.0, 24.0),
    ("1-3d", 24.0, 72.0),
    ("3-4d", 72.0, 96.0),
    ("4-5d", 96.0, 120.0),
    ("5-7d", 120.0, 168.0),
    ("7-9d", 168.0, 240.0),
    ("9d+", 240.0, float("inf")),
)


def merge_var_scores(scores: list[VarScore]) -> VarScore | None:
    """n-weighted merge of one variable's scores across buoys (for skill.json).

    bias and mae merge exactly (they are n-weighted means); rmse merges exactly
    via the mean of squares; scatter_index has lost its mean_obs so it merges as
    an n-weighted mean of the per-buoy values - approximate, and good enough for
    a ceiling with a sample floor in front of it."""
    scored = [s for s in scores if s.n > 0]
    if not scored:
        return None
    labels = {s.label for s in scored}
    if len(labels) > 1:
        # The label names the PAIRING (Tm-1,0 "Energy period" vs Tm02 APD_FALLBACK_LABEL),
        # and the fleet loop picks it per buoy (_with_measured_energy_period), so a pool of
        # buoy cards can mix both. n-weighting a ~2 s definitional offset into one bias and
        # labelling it after whichever buoy sorted first is the exact number the module
        # docstring forbids calibrating against - fail loudly instead of printing it.
        raise ValueError(
            f"refusing to merge '{scored[0].key}' across different pairings: "
            + ", ".join(sorted(labels))
        )
    n = sum(s.n for s in scored)
    first = scored[0]
    bias = sum(s.bias * s.n for s in scored) / n
    mae = sum(s.mae * s.n for s in scored) / n
    rmse = math.sqrt(sum(s.rmse * s.rmse * s.n for s in scored) / n)
    sis = [(s.scatter_index, s.n) for s in scored if s.scatter_index is not None]
    si = sum(v * w for v, w in sis) / sum(w for _, w in sis) if sis else None
    return VarScore(first.key, first.label, first.unit, n, bias, mae, rmse, si)


def skill_payload(
    per_buoy: list[dict[str, dict[str, VarScore]]],
    *,
    key: str = "hs",
    generated: str,
    buoy_ids: list[str] | None = None,
) -> dict:
    """The lead-bucket skill summary ``verify --archive`` persists for the pipeline.

    One variable (Hs - the axis confidence is calibrated on), merged across buoys,
    one entry per lead bucket. Consumed by publish.load_skill_ceilings; every
    number is straight from lead_time_scorecard, so the ceiling it feeds is
    auditable against the same harness the accuracy claims come from. ``buoy_ids``
    is the provenance the payload carries all the way to the published
    confidence_meta: a fleet-wide ceiling measured at one buoy must say so.
    ``buoy_hours`` (parallel to ``per_buoy``) is each buoy's compared hours summed over
    the lead buckets, so the provenance can name only the buoys the number came from -
    a registered buoy that paired nothing (wave-silent) stays in ``buoy_ids`` only."""
    buckets: dict[str, dict] = {}
    for label, _lo, _hi in LEAD_BUCKETS:
        merged = merge_var_scores([b[label][key] for b in per_buoy if label in b])
        if merged is None:
            buckets[label] = {"n": 0}
            continue
        buckets[label] = {
            "n": merged.n,
            "bias": round(merged.bias, 4),
            "mae": round(merged.mae, 4),
            "rmse": round(merged.rmse, 4),
            "scatter_index": (
                round(merged.scatter_index, 4) if merged.scatter_index is not None else None
            ),
        }
    out = {
        "generated": generated,
        "variable": key,
        "buoys": len(per_buoy),
        "buoy_ids": sorted(buoy_ids or []),
        "buckets": buckets,
    }
    if buoy_ids is not None and len(buoy_ids) == len(per_buoy):
        out["buoy_hours"] = {
            bid: sum(b[label][key].n for label, _lo, _hi in LEAD_BUCKETS if label in b)
            for bid, b in sorted(zip(buoy_ids, per_buoy, strict=True))
        }
    return out


def _bucket_for(lead_h: float, buckets: tuple[tuple[str, float, float], ...]) -> str | None:
    for label, lo, hi in buckets:
        if lo <= lead_h < hi:
            return label
    return None


def lead_time_scorecard(
    rows: list[dict],
    obs: list[BuoyObs],
    *,
    buckets: tuple[tuple[str, float, float], ...] = LEAD_BUCKETS,
    tol_min: int = 30,
    variables: tuple = VARIABLES,
) -> dict[str, dict[str, VarScore]]:
    """Skill by forecast lead time, from archived forecasts vs observations.

    Each archived row (forecast for ``valid``, made at ``run``) is bucketed by lead
    (valid-run) and paired to the nearest observation reporting that variable. Answers
    "does our day-5 forecast still hold up, or is only the nowcast any good?"
    ``variables`` picks the model↔obs pairing (VARIABLES for Open-Meteo mean period,
    GFSWAVE_VARIABLES for GFS-Wave peak period)."""
    tol = timedelta(minutes=tol_min)
    # indexed once per variable, not rescanned per archived row - the archive only grows
    valid_obs = {
        o_attr: _obs_index([o for o in obs if getattr(o, o_attr) is not None])
        for *_head, o_attr, _circ in variables
    }
    # The archive appends the whole horizon 4x/day, so one valid hour is archived
    # once per run and several of those rows land inside the same lead bucket.
    # Pairing each row independently counted the same (hour, observation)
    # comparison once per archived run - n was inflated 3.7-27.8x and the standard
    # error the headline accuracy claim rests on was overstated by ~sqrt(that)
    # (2026-08-07 Dream review). Collapse to one comparison per distinct valid
    # hour per bucket: every run still contributes signal, but n counts what a
    # reader assumes it counts - independent compared hours. The collapse averages
    # the runs' ERRORS, not their forecasts (_score_hours): the mean of several
    # runs is a forecast nobody published, and it always scores better than they did.
    grouped: dict[str, dict[str, dict[str, list[tuple[float, float]]]]] = {
        label: {key: {} for key, *_ in variables} for label, _lo, _hi in buckets
    }
    # Observations only reach as far back as the source keeps them (NDBC realtime2
    # ~45 days, CMEMS 3), but the archive is append-only and grows forever. A row
    # whose valid hour lies outside the obs window can never pair with anything, so
    # skip it before the per-variable bisect instead of searching for nothing - the
    # pass then scales with the obs window rather than with archive age. Empty obs
    # pairs nothing anywhere, so skipping every row is the same result, faster.
    obs_times = [o.time for o in obs]
    window = (min(obs_times) - tol, max(obs_times) + tol) if obs_times else None
    for row in rows:
        valid = datetime.fromisoformat(row["valid"])
        if window is None or not window[0] <= valid <= window[1]:
            continue
        run = datetime.fromisoformat(row["run"])
        lead_h = (valid - run).total_seconds() / 3600.0
        label = _bucket_for(lead_h, buckets)
        if label is None:
            continue
        for key, _label, _unit, _m_attr, o_attr, _circ in variables:
            mv = row.get(key)
            if mv is None:
                continue
            o = _nearest_obs(valid, valid_obs[o_attr], tol)
            if o is not None:
                grouped[label][key].setdefault(row["valid"], []).append((mv, getattr(o, o_attr)))
    return {
        label: {
            key: _score_hours(key, lbl, unit, list(grouped[label][key].values()), circ)
            for key, lbl, unit, _m, _o, circ in variables
        }
        for label, _lo, _hi in buckets
    }


def _apd_footnote(*scorecards: dict[str, VarScore]) -> list[str]:
    """The warning that has to travel with any APD-paired period row."""
    used = any(s.label == APD_FALLBACK_LABEL and s.n for card in scorecards for s in card.values())
    if not used:
        return []
    return [
        "  * period scored against APD (Tm02); the model serves Tm-1,0, so this row reads",
        "    ~2 s hot by definition - report it, never calibrate against it.",
    ]


SECTORS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
# The correction OPEN-ITEMS 25 asks for would be applied to the near-term forecast, so
# the profile is measured there: a diurnal term fitted across every lead would be smeared
# by the leads whose own error already dwarfs it.
BIAS_PROFILE_MAX_LEAD_H = 24.0


def _sector(deg: float) -> str:
    return SECTORS[int((deg % 360.0 + 22.5) // 45.0) % 8]


def station_bias_profile(
    rows: list[dict],
    obs: list[BuoyObs],
    *,
    lon: float,
    tol_min: int = 30,
    max_lead_h: float = BIAS_PROFILE_MAX_LEAD_H,
) -> dict[str, dict[str, VarScore]]:
    """Wind-speed bias broken out by solar hour and by observed wind sector.

    The pooled lead card answers "is the model biased on average" and at these stations
    the answer is no. That average can still hide a sea breeze: a model that under-calls
    every afternoon and over-calls every night scores zero bias over the day. This groups
    the SAME pairs the lead card scores - identical tolerance, identical nearest-obs
    match, identical collapse of the several archived runs covering one valid hour - by
    hour and by sector instead of by lead, so a structured error has somewhere to show.

    Hour is SOLAR (lon/15 from UTC), not civil: a sea breeze tracks the sun, and civil
    time would smear stations that share a timezone across a 30-degree span of longitude.
    Sector is the OBSERVED direction, so a bias is attributed to the wind that actually
    blew, not to the one the model guessed.
    """
    tol = timedelta(minutes=tol_min)
    idx = {
        o_attr: _obs_index([o for o in obs if getattr(o, o_attr) is not None])
        for *_head, o_attr, _circ in STATION_VARIABLES
    }
    obs_times = [o.time for o in obs]
    window = (min(obs_times) - tol, max(obs_times) + tol) if obs_times else None
    offset = timedelta(hours=lon / 15.0)

    # group -> variable -> valid hour -> the runs covering it (collapsed exactly as the
    # lead card collapses them, so n counts compared hours and not archived runs)
    grouped: dict[str, dict[str, dict[str, list[tuple[float, float]]]]] = {}
    for row in rows:
        valid = datetime.fromisoformat(row["valid"])
        if window is None or not window[0] <= valid <= window[1]:
            continue
        lead_h = (valid - datetime.fromisoformat(row["run"])).total_seconds() / 3600.0
        if not 0.0 <= lead_h < max_lead_h:
            continue
        for key, _label, _unit, _m_attr, o_attr, _circ in STATION_VARIABLES:
            mv = row.get(key)
            if mv is None:
                continue
            o = _nearest_obs(valid, idx[o_attr], tol)
            if o is None:
                continue
            groups = [f"h{(valid + offset).hour:02d}"]
            if o.wdir_deg is not None and getattr(o, "wspd_ms", None):
                # a calm hour has no meaningful direction to attribute a bias to
                groups.append(_sector(o.wdir_deg))
            for g in groups:
                bucket = grouped.setdefault(g, {k: {} for k, *_ in STATION_VARIABLES})
                bucket[key].setdefault(row["valid"], []).append((mv, getattr(o, o_attr)))

    return {
        g: {
            key: _score_hours(key, lbl, unit, list(grouped[g][key].values()), circ)
            for key, lbl, unit, _m, _o, circ in STATION_VARIABLES
        }
        for g in grouped
    }


def merge_bias_profiles(
    profiles: list[dict[str, dict[str, VarScore]]],
) -> dict[str, dict[str, VarScore]]:
    """n-weighted pool of per-station profiles - the same weighting the fleet lead card uses."""
    out: dict[str, dict[str, VarScore]] = {}
    keys = [(k, lbl, unit, circ) for k, lbl, unit, _m, _o, circ in STATION_VARIABLES]
    groups = sorted({g for p in profiles for g in p})
    for g in groups:
        out[g] = {}
        for key, lbl, unit, _circ in keys:
            cells = [p[g][key] for p in profiles if g in p and p[g][key].n]
            n = sum(c.n for c in cells)
            if not n:
                out[g][key] = VarScore(key, lbl, unit, 0, 0.0, 0.0, 0.0, None)
                continue
            out[g][key] = VarScore(
                key,
                lbl,
                unit,
                n,
                sum(c.bias * c.n for c in cells) / n,
                sum(c.mae * c.n for c in cells) / n,
                math.sqrt(sum(c.rmse**2 * c.n for c in cells) / n),
                None,
            )
    return out


def render_bias_profile(profile: dict[str, dict[str, VarScore]], title: str) -> str:
    """Two tables - solar hour and observed sector - for the wind-speed bias only."""
    lines = [f"{title} - wind-speed bias by solar hour and by sector (lead < 24 h)"]
    hours = sorted(g for g in profile if g.startswith("h"))
    sectors = [s for s in SECTORS if s in profile]
    for label, groups in (("solar hour", hours), ("sector (observed)", sectors)):
        if not groups:
            continue
        lines.append(f"  {label:18s} {'n':>7} {'bias':>10} {'mae':>10}")
        for g in groups:
            c = profile[g][ws_key()]
            if not c.n:
                continue
            name = f"{g[1:]}:00" if g.startswith("h") else g
            lines.append(f"  {name:18s} {c.n:7d} {c.bias:+9.2f}m/s {c.mae:9.2f}m/s")
        cells = [profile[g][ws_key()] for g in groups if profile[g][ws_key()].n]
        if cells:
            lo = min(cells, key=lambda c: c.bias)
            hi = max(cells, key=lambda c: c.bias)
            lines.append(
                f"  {'spread':18s} {'':7} {hi.bias - lo.bias:9.2f}m/s "
                f"(most under-called to most over-called)"
            )
    return "\n".join(lines)


def ws_key() -> str:
    return STATION_VARIABLES[0][0]


def _station_pairs(
    rows: list[dict],
    obs: list[BuoyObs],
    *,
    lon: float,
    tol_min: int,
    max_lead_h: float,
) -> list[tuple[datetime, int, float, float]]:
    """(valid, solar hour, model ws, observed ws) for every compared hour.

    The pairing is the lead card's, unchanged - same tolerance, same nearest-obs match,
    same collapse of the several archived runs covering one valid hour - so a correction
    fitted here is fitted to the numbers the scorecard grades.
    """
    key = ws_key()
    o_attr = STATION_VARIABLES[0][4]
    tol = timedelta(minutes=tol_min)
    idx = _obs_index([o for o in obs if getattr(o, o_attr) is not None])
    obs_times = [o.time for o in obs]
    if not obs_times:
        return []
    window = (min(obs_times) - tol, max(obs_times) + tol)
    offset = timedelta(hours=lon / 15.0)
    grouped: dict[str, list[tuple[float, float]]] = {}
    for row in rows:
        valid = datetime.fromisoformat(row["valid"])
        if not window[0] <= valid <= window[1]:
            continue
        lead_h = (valid - datetime.fromisoformat(row["run"])).total_seconds() / 3600.0
        if not 0.0 <= lead_h < max_lead_h:
            continue
        mv = row.get(key)
        if mv is None:
            continue
        o = _nearest_obs(valid, idx, tol)
        if o is not None:
            grouped.setdefault(row["valid"], []).append((mv, getattr(o, o_attr)))
    out = []
    for valid_iso, hour_pairs in grouped.items():
        m, o = _collapse_hour(hour_pairs, False)
        valid = datetime.fromisoformat(valid_iso)
        out.append((valid, (valid + offset).hour, m, o))
    return sorted(out)


# The fit needs enough hours behind each of the 24 slots to mean anything; below this the
# slot keeps the pooled correction rather than a number drawn from a handful of hours.
MIN_HOURS_PER_SLOT = 40


def fit_diurnal_correction(
    pairs: list[tuple[datetime, int, float, float]],
    *,
    train_frac: float = 0.67,
) -> tuple[dict[int, float], dict[str, float]]:
    """Fit a per-solar-hour wind-speed correction on the earlier hours, score it on the later.

    Split is by TIME, not at random: a random split leaks, because the same weather system
    sits in both halves and a correction fitted to it would score well on itself. The
    earlier two thirds fit, the later third grades, and the numbers reported are the
    held-out ones - the only ones that say whether this helps a forecast it has not seen.
    """
    if not pairs:
        return {}, {}
    cut = pairs[int(len(pairs) * train_frac)][0]
    train = [p for p in pairs if p[0] < cut]
    test = [p for p in pairs if p[0] >= cut]
    if not train or not test:
        return {}, {}

    by_hour: dict[int, list[float]] = {}
    for _valid, hour, m, o in train:
        by_hour.setdefault(hour, []).append(m - o)
    all_diffs = [d for ds in by_hour.values() for d in ds]
    overall = sum(all_diffs) / len(all_diffs)
    table = {
        h: (sum(ds) / len(ds) if len(ds) >= MIN_HOURS_PER_SLOT else overall)
        for h, ds in by_hour.items()
    }

    def score(apply: bool) -> tuple[float, float]:
        diffs = [(m - table.get(hour, overall) if apply else m) - o for _v, hour, m, o in test]
        n = len(diffs)
        return sum(diffs) / n, sum(abs(d) for d in diffs) / n

    bias_before, mae_before = score(False)
    bias_after, mae_after = score(True)
    return table, {
        "n_train": float(len(train)),
        "n_test": float(len(test)),
        "bias_before": bias_before,
        "bias_after": bias_after,
        "mae_before": mae_before,
        "mae_after": mae_after,
    }


def render_diurnal_fit(table: dict[int, float], stats: dict[str, float], title: str) -> str:
    if not stats:
        return f"{title}: not enough paired hours to fit"
    d_mae = stats["mae_after"] - stats["mae_before"]
    lines = [
        f"{title} - diurnal wind correction, fitted on the earlier hours, scored on the later",
        f"  train {int(stats['n_train'])} h   test {int(stats['n_test'])} h",
        f"  bias  {stats['bias_before']:+.3f} -> {stats['bias_after']:+.3f} m/s",
        f"  mae   {stats['mae_before']:.3f} -> {stats['mae_after']:.3f} m/s "
        f"({d_mae:+.3f}, {100 * d_mae / stats['mae_before']:+.1f}%)",
        "  correction subtracted from the model, by solar hour:",
    ]
    for h in sorted(table):
        lines.append(f"    {h:02d}:00  {table[h]:+.2f} m/s")
    return "\n".join(lines)


def render_lead_scorecard(
    buoy: Buoy | Station, by_lead: dict[str, dict[str, VarScore]], *, kind: str = "buoy"
) -> str:
    """One row per lead x variable, **bias first**.

    Bias is the calibratable quantity - it is what an input-side de-bias would correct, and
    what tells a hot model from a cold one. An rmse-only card hid a +2.8 s period bias for
    six days (CALIBRATION.md 2026-07-29); rmse alone cannot show sign."""
    lines = [
        f"lead-time skill vs {kind} {buoy.id} - {buoy.name}",
        f"  {'lead':<6}{'var':<18}{'n':>6}  {'bias':>8}  {'mae':>8}  {'rmse':>8}",
    ]
    for lead_label, scores in by_lead.items():
        # Iterate the card that was handed in, not the module-level VARIABLES. The caller may
        # have built it from ENERGY_PERIOD_/GFSWAVE_/ECMWF_VARIABLES (cli.py:476-493); that
        # works today only because all four tuples happen to share the same three keys, an
        # invariant nothing enforces. A source that adds a fourth variable would silently
        # print three rows and drop it. `label`/`unit` already come off the VarScore.
        if not any(s.n for s in scores.values()):
            lines.append(f"  {lead_label:<6}(no matured forecasts yet)")
            continue
        for s in scores.values():
            if not s.n:
                continue
            lines.append(
                f"  {lead_label:<6}{s.label:<18}{s.n:>6}  {s.bias:>+7.2f}{s.unit}  "
                f"{s.mae:>7.2f}{s.unit}  {s.rmse:>7.2f}{s.unit}"
            )
    lines.extend(_apd_footnote(*by_lead.values()))
    return "\n".join(lines)


def render_pooled_lead(cards: list[dict[str, dict[str, VarScore]]], title: str) -> str:
    """One fleet card from many per-station lead cards - each (lead, variable) cell is the
    n-weighted merge (merge_var_scores). Sign survives the merge, so a fleet-wide hot or
    cold model reads straight off the bias column."""
    lines = [
        title,
        f"  {'lead':<6}{'var':<18}{'n':>6}  {'bias':>8}  {'mae':>8}  {'rmse':>8}",
    ]
    if not cards:
        lines.append("  (nothing scored)")
        return "\n".join(lines)
    for lead_label in cards[0]:
        keys = list(cards[0][lead_label])
        merged = [
            merge_var_scores([c[lead_label][k] for c in cards if lead_label in c]) for k in keys
        ]
        rows = [m for m in merged if m is not None and m.n]
        if not rows:
            lines.append(f"  {lead_label:<6}(no matured forecasts yet)")
            continue
        for s in rows:
            lines.append(
                f"  {lead_label:<6}{s.label:<18}{s.n:>6}  {s.bias:>+7.2f}{s.unit}  "
                f"{s.mae:>7.2f}{s.unit}  {s.rmse:>7.2f}{s.unit}"
            )
    # Same tail as the two per-buoy renderers: an APD-paired period row never reaches a
    # fleet card without its warning. (Today the only pooled card is wind, so this is a
    # no-op - it is here for the first pooled buoy card.)
    lines.extend(_apd_footnote(*(c[lead] for c in cards for lead in c)))
    return "\n".join(lines)


def render_scorecard(buoy: Buoy, dist_km: float | None, scores: dict[str, VarScore]) -> str:
    where = f"{buoy.id} - {buoy.name}"
    if dist_km is not None:
        where += f"  ({dist_km:.0f} km from spot)"
    lines = [
        f"model skill vs buoy {where}",
        f"  {'var':<18}{'n':>4}  {'bias':>8}  {'mae':>8}  {'rmse':>8}  {'SI':>6}",
    ]
    # As in render_lead_scorecard: render what the card holds, not what VARIABLES lists -
    # and, also as there, skip rows with no samples. The nowcast path never joins wind
    # onto the model (that is the archive's join), so its ws/wdir rows are n=0 forever,
    # and a permanent "+0.00" row is exactly the reads-like-a-measurement problem that
    # keeps wind off the ECMWF tuple (see _WIND_VARIABLES). The all-zero card keeps its
    # explicit no-overlap note below.
    for s in scores.values():
        if not s.n:
            continue
        si = f"{s.scatter_index:.2f}" if s.scatter_index is not None else "  -"
        unit = s.unit
        lines.append(
            f"  {s.label:<18}{s.n:>4}  {s.bias:>+7.2f}{unit}  {s.mae:>7.2f}{unit}  "
            f"{s.rmse:>7.2f}{unit}  {si:>6}"
        )
    if all(s.n == 0 for s in scores.values()):
        lines.append("  (no overlapping model/obs hours - buoy may be met-only or offline)")
    lines.extend(_apd_footnote(scores))
    return "\n".join(lines)
