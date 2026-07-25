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
        return cls(
            spot=row["spot"],
            at=datetime.fromisoformat(row["at"]),
            verdict=row["verdict"],
            predicted=row.get("predicted", {}),
            observed=row.get("observed", {}),
            source=row.get("source", "cli"),
        )


def predicted_from_payload(payload: dict, at: datetime) -> dict:
    """Snapshot what Rosa showed for a spot at time ``at`` - the hour entry nearest ``at``,
    falling back to ``current``. This is what the human's eyes are being compared against."""
    best: dict | None = None
    best_gap = float("inf")
    for h in payload.get("hours", []):
        try:
            t = datetime.fromisoformat(h["t"])
        except (ValueError, KeyError):
            continue
        gap = abs((t - at).total_seconds())
        if gap < best_gap:
            best, best_gap = h, gap
    src = best if best is not None else payload.get("current", {})
    return {
        "rating": src.get("rating"),
        "bucket": src.get("bucket"),
        "h": src.get("h"),
        "phrase": src.get("phrase"),
    }


def bucket_delta(predicted_bucket: str | None, observed_bucket: str | None) -> int | None:
    """Signed bucket error: + = Rosa called it BIGGER than observed (running hot)."""
    if predicted_bucket not in BUCKET_ORDER or observed_bucket not in BUCKET_ORDER:
        return None
    return BUCKET_ORDER.index(predicted_bucket) - BUCKET_ORDER.index(observed_bucket)


def _mid(h: object) -> float | None:
    if isinstance(h, (list, tuple)) and len(h) == 2:
        return (float(h[0]) + float(h[1])) / 2
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
        m - float(r.observed["h_mid"])
        for r in records
        if r.observed.get("h_mid") is not None and (m := _mid(r.predicted.get("h"))) is not None
    ]
    return {
        "n": n,
        "agreement": (ups / n) if n else None,
        "n_bucketed": len(deltas),
        "bucket_bias": (sum(deltas) / len(deltas)) if deltas else None,
        "n_height": len(h_errs),
        "height_bias_m": (sum(h_errs) / len(h_errs)) if h_errs else None,
    }


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
        obs = " ".join(
            s for s in [o.get("bucket"), o.get("phrase"), o.get("note")] if s
        ) or "-"
        icon = "👍" if r.verdict == "up" else "👎"
        d, t = r.at.date().isoformat(), r.at.strftime("%H:%M")
        out.append(f"| {d} | {t} | {r.spot} | {pred} | {obs} | - | {icon} feedback |")
    return "\n".join(out)
