"""Surfer 👍👎 feedback - the truth no buoy can give (roadmap Stage 0, link 4-5).

Buoys score the offshore model; only a human on the beach can score the *rating* and
*breaker height* - "you said GOOD waist-high, it was shin-high POOR". This captures that
as structured rows so calibration runs on evidence, not one-off memory, and it surfaces the
one number that drives tuning: **bucket bias** (are we systematically hot or cold?).

Storage reuses the append-only JSONL store (FileArchiveStore); rows live under the gitignored
verify tree. `feedback --report --markdown` emits rows to paste into docs/CALIBRATION.md.

DATA CONTRACT (also the shape the web 👍👎 button will POST, and the eventual Supabase row):
    {
      "spot": "beit-yanai",
      "at": "2026-07-21T09:00+03:00",      # when observed (tz-aware)
      "verdict": "down",                    # "up" | "down"
      "predicted": {"rating": 55, "bucket": "GOOD", "h": [0.5, 0.8], "phrase": "waist-high"},
      "observed":  {"bucket": "POOR", "h_mid": 0.15, "phrase": "shin-high", "note": "..."},
      "source": "cli"                       # "cli" | "web"
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# rating buckets low→high; index gives the signed bucket error
BUCKET_ORDER = ("FLAT", "POOR", "FAIR", "GOOD", "FIRING")


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    spot: str
    at: datetime  # tz-aware
    verdict: str  # "up" | "down"
    predicted: dict = field(default_factory=dict)
    observed: dict = field(default_factory=dict)
    source: str = "cli"

    def to_row(self) -> dict:
        return {
            "spot": self.spot,
            "at": self.at.isoformat(timespec="minutes"),
            "verdict": self.verdict,
            "predicted": self.predicted,
            "observed": self.observed,
            "source": self.source,
        }

    @classmethod
    def from_row(cls, row: dict) -> FeedbackRecord:
        # a JSONL line parses as ANY JSON value, and the store hands every parsed line
        # over as a row: a bare string/number/array must fail THIS row's parse with the
        # TypeError records_from_rows catches, not the AttributeError `.get` raises
        if not isinstance(row, dict):
            raise TypeError(f"row must be an object, got {type(row).__name__}")
        predicted = row.get("predicted", {})
        observed = row.get("observed", {})
        # the drop-box API admits any JS "object" here - including arrays - so a
        # non-dict must fail THIS row's parse (records_from_rows skips it loudly)
        # rather than surface later as an AttributeError that sinks the report
        if not isinstance(predicted, dict) or not isinstance(observed, dict):
            raise TypeError("predicted/observed must be objects")
        return cls(
            spot=row["spot"],
            at=datetime.fromisoformat(row["at"]),
            verdict=row["verdict"],
            predicted=predicted,
            observed=observed,
            source=row.get("source", "cli"),
        )


def records_from_rows(rows: list[dict]) -> list[FeedbackRecord]:
    """Stored rows → records, skipping any row that can't be read.

    The store is append-only and fed from the public drop-box (notify.pull_feedback), whose
    API validates ``at`` only as "a string" - it never parses it. One row with an
    unparseable timestamp therefore lands in feedback.jsonl permanently and made
    ``feedback --report`` raise for the WHOLE store: the calibration surface goes dark until
    a human hand-edits a gitignored JSONL. Same heal-on-read contract every other reader in
    this pipeline already keeps (publish._read_index rebuilds, notify._iter_payloads skips,
    FileArchiveStore.read drops a torn line) - a bad row costs itself, never the report.
    Loud, not silent: a row that is being dropped from calibration has to say so."""
    out: list[FeedbackRecord] = []
    for row in rows:
        try:
            out.append(FeedbackRecord.from_row(row))
        except (KeyError, TypeError, ValueError) as exc:
            ident = row.get("id") or row.get("spot") if isinstance(row, dict) else row
            print(f"warn: unreadable feedback row skipped ({exc}) - {ident!r}")
    return out


# The published `hours` table is TABLE_STEP_H-spaced (3 h), so the worst honest gap
# between a graded moment and the row that forecast it is half a step. Anything past a
# whole step means the payload has no forecast for that hour at all - it was never
# published, or it has already rolled off the front of the table.
PREDICTED_MATCH_TOL_H = 3.0


def _gap_s(entry: object, at: datetime) -> float:
    """Seconds between a payload hour entry and ``at``; inf when that cannot be decided."""
    if not isinstance(entry, dict):
        return float("inf")
    try:
        return abs((datetime.fromisoformat(entry["t"]) - at).total_seconds())
    except (ValueError, KeyError, TypeError):
        # TypeError also covers a naive/aware mismatch - unprovable is not "close enough"
        return float("inf")


def predicted_from_payload(
    payload: dict, at: datetime, *, tol_h: float = PREDICTED_MATCH_TOL_H
) -> dict:
    """Snapshot what Rosa showed for a spot at time ``at`` - the hour entry nearest ``at``,
    falling back to ``current``. This is what the human's eyes are being compared against.

    The match is BOUNDED (``tol_h``). The nearest published hour is not automatically the
    hour that was graded: publish.build_payload emits from the spot's local today forward,
    so a session graded even one morning late has no row behind it, and the old unbounded
    nearest-search handed back a forecast up to 16 days away as though it were the one the
    surfer was looking at. Those rows are not harmless - they carry into
    ``summarize``'s bucket_bias / height_bias with full weight, which is what
    docs/CALIBRATION.md tunes the rating from, and a single such row moves the bucket bias
    by up to the width of the whole scale.

    Beyond the tolerance the answer is an EMPTY dict, not a nearby guess: the same
    "an absent key is honest, a fabricated one isn't" rule publish._spectral_entry keeps.
    The row is still stored - a 👍👎 with no prediction behind it is a real observation -
    it simply contributes nothing to a bias it cannot inform. Callers that want to refuse
    the grading outright should test for the empty dict (cli._cmd_feedback).

    The tolerance bounds the HOURS TABLE only. A payload carrying no ``hours`` at all
    keeps the documented fall back to ``current``, unbounded - that shape has no table to
    miss, and test_feedback.py::test_predicted_falls_back_to_current_when_no_hours pins
    the behaviour. Where a table exists it is the authority for what was shown at a given
    hour, and a miss against it means there is no forecast for that hour to report."""
    best: dict | None = None
    best_gap = float("inf")
    hours = payload.get("hours") or []
    for h in hours:
        gap = _gap_s(h, at)
        if gap < best_gap:
            best, best_gap = h, gap
    if not hours:
        return _predicted_fields(payload.get("current", {}))
    if best is None or best_gap > tol_h * 3600.0:
        return {}
    return _predicted_fields(best)


def _predicted_fields(src: dict) -> dict:
    return {
        "rating": src.get("rating"),
        "bucket": src.get("bucket"),
        "h": src.get("h"),
        "phrase": src.get("phrase"),
        # the hour's wind rides along so the wind-coefficient fit (below) can pair the
        # surfer's observed height with the wind Rosa predicted for that hour - the
        # automated route to WIND_BREAKER_COEFF, no one tasked with watching waves
        "wind": src.get("wind"),
    }


def bucket_delta(predicted_bucket: str | None, observed_bucket: str | None) -> int | None:
    """Signed bucket error: + = Rosa called it BIGGER than observed (running hot)."""
    if predicted_bucket not in BUCKET_ORDER or observed_bucket not in BUCKET_ORDER:
        return None
    return BUCKET_ORDER.index(predicted_bucket) - BUCKET_ORDER.index(observed_bucket)


def _as_float(x: object) -> float | None:
    """A number, or None - drop-box values are validated for JSON shape only, never type."""
    if isinstance(x, bool):
        return None
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _mid(h: object) -> float | None:
    if isinstance(h, (list, tuple)) and len(h) == 2:
        lo, hi = _as_float(h[0]), _as_float(h[1])
        if lo is not None and hi is not None:
            return (lo + hi) / 2
    return None


def summarize(records: list[FeedbackRecord]) -> dict:
    n = len(records)
    ups = sum(1 for r in records if r.verdict == "up")
    deltas = [
        d
        for r in records
        if (d := bucket_delta(r.predicted.get("bucket"), r.observed.get("bucket"))) is not None
    ]
    h_errs = [
        m - o
        for r in records
        if (o := _as_float(r.observed.get("h_mid"))) is not None
        and (m := _mid(r.predicted.get("h"))) is not None
    ]
    return {
        "n": n,
        "agreement": (ups / n) if n else None,
        "n_bucketed": len(deltas),
        "bucket_bias": (sum(deltas) / len(deltas)) if deltas else None,
        "n_height": len(h_errs),
        "height_bias_m": (sum(h_errs) / len(h_errs)) if h_errs else None,
    }


# the fit needs real wind and a real height on both sides; cross-shore rows carry no
# usable normal component and calm rows carry no signal
WIND_FIT_MIN_KPH = 20.0
WIND_FIT_MIN_N = 12
_GRAVITY = 9.81
_GAMMA = 0.78  # breaker index - h_b/gamma approximates the breaking depth


def wind_fit(records: list[FeedbackRecord]) -> dict:
    """Estimate WIND_BREAKER_COEFF from the surfer 👍👎 stream - the automated path
    to the wind knob (OPEN-ITEMS item 4), replacing the graded-frames requirement.

    Model: observed_h = predicted_h x (1 + c*w), w = U_n/sqrt(g*h_b) with U_n signed
    positive-offshore (physics.wind_breaker_factor's parameter). Each windy feedback
    row (>= WIND_FIT_MIN_KPH, class onshore/offshore) yields one (ratio-1, w) pair;
    least squares through the origin gives c and its standard error. The wind class
    gates the sign, the full speed stands in for the normal component, and the
    breaking depth is approximated as predicted h / gamma - crude, but every
    approximation is the SAME crudeness the scorer would apply, so the fitted c is
    calibrated for the formula that will consume it. Recording only: switching the
    coefficient on stays a pb_0049 change (same-input A/B + CALIBRATION.md entry)."""
    import math

    pairs: list[tuple[float, float]] = []
    for r in records:
        obs = _as_float(r.observed.get("h_mid"))
        pred = _mid(r.predicted.get("h"))
        # `predicted` nests drop-box values - wind can be any JSON shape, kph any type
        wind = r.predicted.get("wind")
        if not isinstance(wind, dict):
            wind = {}
        kph, cls = _as_float(wind.get("kph")), wind.get("class")
        if obs is None or pred is None or pred <= 0 or kph is None:
            continue
        if cls not in ("onshore", "offshore") or kph < WIND_FIT_MIN_KPH:
            continue
        sign = 1.0 if cls == "offshore" else -1.0
        u_n = sign * kph / 3.6
        depth = pred / _GAMMA
        w = u_n / math.sqrt(_GRAVITY * depth)
        pairs.append((obs / pred - 1.0, w))
    n = len(pairs)
    if n == 0:
        return {"n_windy": 0, "coeff": None, "stderr": None, "usable": False}
    sw2 = sum(w * w for _, w in pairs)
    c = sum(r * w for r, w in pairs) / sw2 if sw2 else 0.0
    resid = [r - c * w for r, w in pairs]
    stderr = math.sqrt(sum(e * e for e in resid) / (n - 1) / sw2) if n > 1 and sw2 else None
    usable = n >= WIND_FIT_MIN_N and stderr is not None and abs(c) > 2 * stderr
    return {
        "n_windy": n,
        "coeff": round(c, 4),
        "stderr": round(stderr, 4) if stderr else None,
        "usable": usable,
    }


def render_wind_fit(fit: dict) -> str:
    n = fit["n_windy"]
    if n == 0:
        return (
            "wind fit: no windy-hour rows yet (needs feedback on >=20 kph on/offshore "
            "hours; accumulates on its own)"
        )
    line = f"wind fit: c = {fit['coeff']}"
    if fit["stderr"] is not None:
        line += f" +- {fit['stderr']}"
    line += f" over {n} windy row(s)"
    if fit["usable"]:
        line += "  -> FITTABLE: run the pb_0049 A/B to switch WIND_BREAKER_COEFF on"
    else:
        line += f"  (needs n>={WIND_FIT_MIN_N} and |c| > 2*stderr before it means anything)"
    return line


def render_report(summary: dict) -> str:
    n = summary["n"]
    if n == 0:
        return "feedback: no records yet - add one with `feedback --spot <id> --verdict up|down`"
    lines = [f"surfer feedback ({n} record{'s' if n != 1 else ''})"]
    if summary["agreement"] is not None:
        lines.append(f"  agreement 👍: {summary['agreement'] * 100:.0f}%")
    bb = summary["bucket_bias"]
    if bb is not None:
        tag = "running HOT" if bb > 0.15 else "running COLD" if bb < -0.15 else "well-centred"
        lines.append(
            f"  bucket bias (pred - observed): {bb:+.2f} over {summary['n_bucketed']}  -> {tag}"
        )
    hb = summary["height_bias_m"]
    if hb is not None:
        lines.append(f"  height bias: {hb:+.2f} m over {summary['n_height']}")
    return "\n".join(lines)


def markdown_rows(records: list[FeedbackRecord]) -> str:
    """CALIBRATION.md-ready rows (Date | Time | Spot | Rosa pred | Observed | Buoy | Notes)."""
    out = []
    for r in records:
        p, o = r.predicted, r.observed
        phrase = p.get("phrase") or ""
        pred = f"{p.get('bucket')} {p.get('rating')}, {p.get('h')} m {phrase}".strip()
        obs = " ".join(s for s in [o.get("bucket"), o.get("phrase"), o.get("note")] if s) or "-"
        icon = "👍" if r.verdict == "up" else "👎"
        d, t = r.at.date().isoformat(), r.at.strftime("%H:%M")
        out.append(f"| {d} | {t} | {r.spot} | {pred} | {obs} | - | {icon} feedback |")
    return "\n".join(out)
