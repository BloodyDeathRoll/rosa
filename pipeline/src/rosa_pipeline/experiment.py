"""Stage-2E experiment harness: grade candidate breaker transforms against the eye frames.

The pre-registered question (docs/CALIBRATION.md, 2026-07-25/26): ``period_rideability``
keys on the MEAN period, while the observed under-calls happened on days whose PEAK
period was 2-3 s longer - is that the mechanism, and does a peak- (or energy-) keyed
rideability fix the two Hilton under-calls WITHOUT re-inflating the 2026-07-19/24
small-windswell frames? This module runs exactly that experiment, offline, over the
machine-readable frames in ``data/calibration/frames.yaml``.

It changes no production behaviour: candidates are injected into
``breaker_height_from_profile`` via its ``rideability`` hook; the shipping default stays
``(Tm/10)^1.4``. The harness only *reports* - moving a knob still requires a
CALIBRATION.md entry (and, for the global constants, the buoy-archive half of 2E).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .bathymetry import load_profile
from .models import Spot, SwellPartition
from .transform import (
    RIDEABILITY_EXP,
    breaker_height_from_profile,
    breaker_range,
    energy_period,
)

RIDEABILITY_FLOOR = 0.3
RIDEABILITY_CAP = 1.0

PeriodKey = str  # "mean" | "peak" | "energy"


@dataclass(frozen=True, slots=True)
class Frame:
    """One graded observation: model-input sea state -> human-observed breaker height."""

    id: str
    spot_id: str
    observed_lo_m: float
    observed_hi_m: float
    slack_m: float
    tide_m: float
    partitions: tuple[SwellPartition, ...]
    calibration_row: str = ""


@dataclass(frozen=True, slots=True)
class Candidate:
    """A rideability variant: which period feeds the power law, and its exponent."""

    key: PeriodKey
    exp: float

    @property
    def label(self) -> str:
        return f"{self.key}^{self.exp:g}"

    def period_of(self, p: SwellPartition) -> float:
        if self.key == "mean":
            return p.period_s
        if self.key == "peak":
            return p.peak_period_s if p.peak_period_s is not None else p.period_s
        if self.key == "energy":
            return energy_period(p)  # Te = 0.9*Tp, mean-period fallback (transform.py)
        raise ValueError(f"unknown period key {self.key!r}")

    def rideability(self, p: SwellPartition) -> float:
        return min(RIDEABILITY_CAP, max(RIDEABILITY_FLOOR, (self.period_of(p) / 10.0) ** self.exp))


#: The shipping transform expressed as a candidate - the harness's regression anchor.
#: Peak-keyed since 2026-07-30 (Stage 2E resolved the pre-registered question in favour
#: of Tp); ``key="peak"`` mirrors ``transform.rideability_period`` exactly, Tp with a
#: mean-period fallback.
BASELINE = Candidate(key="peak", exp=RIDEABILITY_EXP)

#: Default grid: the three period keys the 2E question names, over a bracketing
#: exponent sweep. Kept small on purpose - this is a pre-registered experiment,
#: not a free parameter search.
#: Widened 2026-08-02 to bracket the refitted exponent - closing the depth march moved the
#: best-fitting exponent from 1.4 to 2.2, off the top of the old 1.0-1.6 grid.
EXPONENT_GRID: tuple[float, ...] = (1.0, 1.4, 1.8, 2.0, 2.2, 2.6)

DEFAULT_CANDIDATES: tuple[Candidate, ...] = tuple(
    Candidate(key=k, exp=e) for k in ("mean", "peak", "energy") for e in EXPONENT_GRID
)


@dataclass(frozen=True, slots=True)
class FrameResult:
    frame: Frame
    h_mid_m: float  # raw (pre-snap) mid, after height_coeff

    @property
    def passed(self) -> bool:
        lo = self.frame.observed_lo_m - self.frame.slack_m
        hi = self.frame.observed_hi_m + self.frame.slack_m
        return lo <= self.h_mid_m <= hi

    @property
    def error_m(self) -> float:
        """Signed distance to the observed band (0 inside it)."""
        if self.h_mid_m < self.frame.observed_lo_m:
            return self.h_mid_m - self.frame.observed_lo_m
        if self.h_mid_m > self.frame.observed_hi_m:
            return self.h_mid_m - self.frame.observed_hi_m
        return 0.0


@dataclass(frozen=True, slots=True)
class CandidateResult:
    candidate: Candidate
    frames: tuple[FrameResult, ...] = field(default_factory=tuple)

    @property
    def passes_all(self) -> bool:
        return all(f.passed for f in self.frames)

    @property
    def max_abs_error_m(self) -> float:
        return max((abs(f.error_m) for f in self.frames), default=0.0)


def load_frames(path: Path) -> list[Frame]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    frames: list[Frame] = []
    for raw in data["frames"]:
        parts = tuple(
            SwellPartition(
                height_m=float(p["hs"]),
                period_s=float(p["tm"]),
                direction_deg=float(p["dir"]),
                kind=p.get("kind", "swell"),
                peak_period_s=float(p["tp"]) if "tp" in p else None,
            )
            for p in raw["partitions"]
        )
        lo, hi = raw["observed_m"]
        frames.append(
            Frame(
                id=raw["id"],
                spot_id=raw["spot"],
                observed_lo_m=float(lo),
                observed_hi_m=float(hi),
                slack_m=float(raw.get("slack_m", 0.05)),
                tide_m=float(raw.get("tide_m", 0.0)),
                partitions=parts,
                calibration_row=raw.get("calibration_row", ""),
            )
        )
    return frames


def predict_frame(
    frame: Frame, spot: Spot, wet_samples: list[tuple[float, float]], candidate: Candidate
) -> float:
    """Raw h_mid for one frame under one candidate - the exact production path
    (tide-shifted depths -> physics march -> rideability -> height_coeff), minus
    only the display snapping, which would quantize grading."""
    samples = [(x, d + frame.tide_m) for x, d in wet_samples if d + frame.tide_m > 0]
    h = breaker_height_from_profile(
        frame.partitions,
        spot.swell_window,
        spot.shore_normal,
        samples,
        rideability=candidate.rideability,
    )
    return h * spot.height_coeff


def run_experiment(
    frames: list[Frame],
    spots: dict[str, Spot],
    bathy_dir: Path,
    candidates: tuple[Candidate, ...] = DEFAULT_CANDIDATES,
) -> list[CandidateResult]:
    # Resolve each frame's spot + profile ONCE, not once per candidate. The profile JSON is
    # read and parsed inside the inner loop otherwise, so a run re-reads the same files
    # len(candidates) times (18 by default) for no new information. Hoisting also moves the
    # two "bad frame file" errors to the top of the run, before any candidate is graded -
    # _cmd_experiment prints nothing before this call, so nothing depends on the old ordering.
    resolved: dict[str, tuple[Spot, list[float]]] = {}
    for fr in frames:
        if fr.spot_id in resolved:
            continue
        spot = spots.get(fr.spot_id)
        if spot is None:
            raise KeyError(f"frame {fr.id}: unknown spot {fr.spot_id!r}")
        profile = load_profile(fr.spot_id, bathy_dir)
        if profile is None:
            raise FileNotFoundError(f"frame {fr.id}: no bathy profile for {fr.spot_id}")
        resolved[fr.spot_id] = (spot, profile.wet_samples_deep_to_shallow())

    results: list[CandidateResult] = []
    for cand in candidates:
        frame_results = []
        for fr in frames:
            spot, wet_samples = resolved[fr.spot_id]
            mid = predict_frame(fr, spot, wet_samples, cand)
            frame_results.append(FrameResult(frame=fr, h_mid_m=mid))
        results.append(CandidateResult(candidate=cand, frames=tuple(frame_results)))
    return results


def render_report(results: list[CandidateResult]) -> str:
    """Plain-text grid: one row per candidate, one column per frame, display range
    included so a row can be read against what the app would have shown."""
    if not results:
        return "no candidates"
    frames = [fr.frame for fr in results[0].frames]
    short = [f.id.split("-", 3)[-1][:22] for f in frames]
    lines: list[str] = []
    head = f"{'candidate':<14}" + "".join(f"{s:>24}" for s in short) + f"{'verdict':>12}"
    lines.append(head)
    obs = f"{'observed':<14}" + "".join(
        f"{f'{f.observed_lo_m:.1f}-{f.observed_hi_m:.1f} m':>24}" for f in frames
    )
    lines.append(obs)
    lines.append("-" * len(head))
    for r in results:
        cells = []
        for fres in r.frames:
            lo, _, hi = breaker_range(fres.h_mid_m, 1.0)
            mark = "ok" if fres.passed else f"{fres.error_m:+.2f}"
            cells.append(f"{f'{fres.h_mid_m:.2f} ({lo:.1f}-{hi:.1f}) {mark}':>24}")
        verdict = "PASS ALL" if r.passes_all else ""
        tag = "  <- shipping" if r.candidate == BASELINE else ""
        lines.append(f"{r.candidate.label:<14}" + "".join(cells) + f"{verdict:>12}{tag}")
    passing = [r.candidate.label for r in results if r.passes_all]
    lines.append("")
    if passing:
        lines.append(f"candidates satisfying every frame: {', '.join(passing)}")
    else:
        best = min(results, key=lambda r: r.max_abs_error_m)
        most = max(results, key=lambda r: sum(1 for f in r.frames if f.passed))
        n_most = sum(1 for f in most.frames if f.passed)
        lines.append(
            "no candidate satisfies every frame; least-bad by max error: "
            f"{best.candidate.label} (max |err| {best.max_abs_error_m:.2f} m); "
            f"most frames passed: {most.candidate.label} ({n_most}/{len(most.frames)})"
        )
        lines.append(
            "the two rank differently - min-max-error favours a candidate that misses "
            "every frame slightly over one that fits most and misses one. 2026-07-30 chose "
            "frames-passed; see docs/CALIBRATION.md."
        )
    lines.append(
        "note: reporting only - knobs move via docs/CALIBRATION.md. 2E's buoy half is "
        "settled: no input de-bias is defensible (Hs bias flips sign by instrument class, "
        "period bias is +0.2 s after the SESSION-10 harness fix)."
    )
    return "\n".join(lines)


def _isclose(a: float, b: float, tol: float = 1e-9) -> bool:
    return math.isclose(a, b, abs_tol=tol)
