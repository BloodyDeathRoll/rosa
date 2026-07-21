"""Forecast-skill scoring against buoy truth (roadmap Stage 0).

Scores the OFFSHORE model field (link 1 of the forecast chain) — significant wave height,
period, and direction — sampled at a buoy against that buoy's observations. Pure functions
over paired series; the CLI wires live/fixture I/O around them.

Two comparison notes baked in:
- Open-Meteo ``wave_period`` is a MEAN period, so it pairs with the buoy's APD (average),
  not DPD (dominant/peak).
- Direction is circular — errors wrap at ±180°, and scatter-index is undefined for it.

The nowcast path (compare today's forecast hours to the buoy's recent obs) needs no stored
history and works immediately; the archive path (Stage 0 next increment) extends this to
lead-time skill by replaying forecasts stamped at successive run times.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .buoys import Buoy
from .observe import BuoyObs

# variable key -> (label, unit, model attr, obs attr, circular?)
VARIABLES = (
    ("hs", "Sig. wave height", "m", "hs", "hs_m", False),
    ("tp", "Mean period", "s", "tp", "apd_s", False),
    ("dir", "Wave direction", "°", "dir", "mwd_deg", True),
)


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


def _nearest_obs(t: datetime, obs: list[BuoyObs], tol: timedelta) -> BuoyObs | None:
    best: BuoyObs | None = None
    best_gap = tol
    for o in obs:
        gap = abs(o.time - t)
        if gap <= best_gap:
            best, best_gap = o, gap
    return best


def pair_series(
    model: list[WavePoint], obs: list[BuoyObs], *, tol_min: int = 30
) -> dict[str, list[tuple[float, float]]]:
    """(model, obs) value pairs per variable — each forecast hour matched to the nearest
    observation *that actually reports that variable* within ``tol_min``.

    Matching is per-variable, not per-row: many buoys log met every 10 min but waves only
    every ~30-60 min, so the time-nearest row is often wave-blank. Filtering to rows with
    the field present before the nearest-search is what keeps those hours scorable."""
    tol = timedelta(minutes=tol_min)
    pairs: dict[str, list[tuple[float, float]]] = {key: [] for key, *_ in VARIABLES}
    for key, _label, _unit, m_attr, o_attr, _circ in VARIABLES:
        valid = [o for o in obs if getattr(o, o_attr) is not None]
        for mp in model:
            mv = getattr(mp, m_attr)
            if mv is None:
                continue
            o = _nearest_obs(mp.time, valid, tol)
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
    model: list[WavePoint], obs: list[BuoyObs], *, tol_min: int = 30
) -> dict[str, VarScore]:
    pairs = pair_series(model, obs, tol_min=tol_min)
    return {
        key: _score_var(key, label, unit, pairs[key], circular)
        for key, label, unit, _m, _o, circular in VARIABLES
    }


def render_scorecard(
    buoy: Buoy, dist_km: float | None, scores: dict[str, VarScore]
) -> str:
    where = f"{buoy.id} — {buoy.name}"
    if dist_km is not None:
        where += f"  ({dist_km:.0f} km from spot)"
    lines = [
        f"model skill vs buoy {where}",
        f"  {'var':<18}{'n':>4}  {'bias':>8}  {'mae':>8}  {'rmse':>8}  {'SI':>6}",
    ]
    for key, *_ in VARIABLES:
        s = scores[key]
        si = f"{s.scatter_index:.2f}" if s.scatter_index is not None else "  -"
        unit = s.unit
        lines.append(
            f"  {s.label:<18}{s.n:>4}  {s.bias:>+7.2f}{unit}  {s.mae:>7.2f}{unit}  "
            f"{s.rmse:>7.2f}{unit}  {si:>6}"
        )
    if all(scores[k].n == 0 for k, *_ in VARIABLES):
        lines.append("  (no overlapping model/obs hours — buoy may be met-only or offline)")
    return "\n".join(lines)
