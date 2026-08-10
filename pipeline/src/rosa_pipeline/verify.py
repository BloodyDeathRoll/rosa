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

# the APD-paired period label; the renderers footnote it so a reader can never mistake
# this row for a calibratable bias (see module docstring)
APD_FALLBACK_LABEL = "Mean per. vs APD"

# variable key -> (label, unit, model attr, obs attr, circular?)
# FALLBACK pairing: period vs the buoy's APD (Tm02). Definitionally ~2 s hot against
# Open-Meteo's Tm-1,0 - used only where no spectrum is published. Prefer the tuple below.
VARIABLES = (
    ("hs", "Sig. wave height", "m", "hs", "hs_m", False),
    ("tp", APD_FALLBACK_LABEL, "s", "tp", "apd_s", False),
    ("dir", "Wave direction", "°", "dir", "mwd_deg", True),
)

# PREFERRED pairing for Open-Meteo: like-for-like against the measured energy period.
# Needs obs enriched by with_energy_period().
ENERGY_PERIOD_VARIABLES = (
    ("hs", "Sig. wave height", "m", "hs", "hs_m", False),
    ("tp", "Energy period", "s", "tp", "tm_m10_s", False),
    ("dir", "Wave direction", "°", "dir", "mwd_deg", True),
)

# GFS-Wave archive rows carry a PEAK period (perpw), so tp pairs with the buoy's DPD
# (dominant period), not APD - pairing mean-vs-dominant would fabricate a bias (Stage 3a).
GFSWAVE_VARIABLES = (
    ("hs", "Sig. wave height", "m", "hs", "hs_m", False),
    ("tp", "Peak period", "s", "tp", "dpd_s", False),
    ("dir", "Wave direction", "°", "dir", "mwd_deg", True),
)

# ECMWF archive rows store pp1d - also a peak period, same DPD pairing (Stage 3b).
ECMWF_VARIABLES = GFSWAVE_VARIABLES


@dataclass(frozen=True, slots=True)
class WavePoint:
    time: datetime  # tz-aware UTC
    hs: float | None
    tp: float | None
    dir: float | None


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
    true mean across runs. Direction averages as a vector, not arithmetically."""
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
    confidence_meta: a fleet-wide ceiling measured at one buoy must say so."""
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
    return {
        "generated": generated,
        "variable": key,
        "buoys": len(per_buoy),
        "buoy_ids": sorted(buoy_ids or []),
        "buckets": buckets,
    }


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
    # (2026-08-07 Dream review). Collapse to one averaged comparison per distinct
    # valid hour per bucket: every run still contributes signal, but n counts
    # what a reader assumes it counts - independent compared hours.
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
    pairs: dict[str, dict[str, list[tuple[float, float]]]] = {
        label: {
            key: [_collapse_hour(hour_pairs, circ) for hour_pairs in grouped[label][key].values()]
            for key, _lbl, _unit, _m, _o, circ in variables
        }
        for label, _lo, _hi in buckets
    }
    return {
        label: {
            key: _score_var(key, lbl, unit, pairs[label][key], circ)
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


def render_lead_scorecard(buoy: Buoy, by_lead: dict[str, dict[str, VarScore]]) -> str:
    """One row per lead x variable, **bias first**.

    Bias is the calibratable quantity - it is what an input-side de-bias would correct, and
    what tells a hot model from a cold one. An rmse-only card hid a +2.8 s period bias for
    six days (CALIBRATION.md 2026-07-29); rmse alone cannot show sign."""
    lines = [
        f"lead-time skill vs buoy {buoy.id} - {buoy.name}",
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


def render_scorecard(buoy: Buoy, dist_km: float | None, scores: dict[str, VarScore]) -> str:
    where = f"{buoy.id} - {buoy.name}"
    if dist_km is not None:
        where += f"  ({dist_km:.0f} km from spot)"
    lines = [
        f"model skill vs buoy {where}",
        f"  {'var':<18}{'n':>4}  {'bias':>8}  {'mae':>8}  {'rmse':>8}  {'SI':>6}",
    ]
    # As in render_lead_scorecard: render what the card holds, not what VARIABLES lists.
    for s in scores.values():
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
