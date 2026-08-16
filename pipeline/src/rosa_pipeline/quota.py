"""Self-imposed daily budget for the Open-Meteo marine host.

Open-Meteo's free tier caps calls per MINUTE, per HOUR and per DAY, per IP. The minute cap
has been handled since 2026-08-02 inside ``fetch.py`` (``MARINE_BATCH_SIZE`` plus a pause
past each minute boundary). The DAY cap had nothing in front of it, and on 2026-08-15 that
cost a cycle: an ad-hoc ``run --all`` on top of the cron's four fleet runs exhausted the
daily quota, ``run --all`` raised a 429 mid-fleet, ``publish.sh`` died at step 2 and the
admin alert fired. The quota resets at 00:00Z, so the next scheduled cycle recovered on its
own - which is exactly why this is worth guarding rather than escalating: the cost of the
failure was a stale forecast and a false alarm, and both were avoidable.

The arithmetic that matters, from ``fetch.py``'s own derivation: a marine batch costs about
``MARINE_UNITS_PER_POINT`` weighted units per point (20 vars x 3 models -> 6.0, scaled by
17/14 days -> 7.3, plus the ensemble's 1.5). At 265 spots a fleet run is ~2,300 units and
the cron runs four of them, so a normal day already spends ~9,300 of a 10,000/day allowance.
**The fleet is at the edge of the daily cap by itself** - that is open item 14's ceiling
arriving, not a bug in this module - so the budget below leaves only enough room for the
archive and verify steps that share the host, and a fifth fleet run of any kind will be
refused. Refused, not throttled: there is no useful way to wait out a daily quota inside a
cycle, and a skipped refresh (the previous payloads keep serving, ~6 h old at worst) is a
far better outcome than a failed cycle.

The ledger is VM-local state under ``data/verify/`` (gitignored, like the archive and
skill.json). A missing or corrupt file is treated as a fresh day: this guard must never be
the reason a cycle cannot run.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Weighted units per point for one marine + one ensemble request, per fetch.py's derivation.
# Re-derive it there whenever MARINE_MODELS or MARINE_HOURLY changes; this is the same number
# the minute-bucket batch size is cut from.
MARINE_UNITS_PER_POINT = 8.8

# Self-imposed daily ceiling for FLEET RUNS, not a measured vendor limit, and deliberately
# below Open-Meteo's published 10,000 calls/day. The margin is thinner than it looks: at 265
# spots the cron's four cycles cost 4 x 2,332 = 9,328 units by themselves, so this budget's
# whole job is to refuse the FIFTH run, not to ration the first four.
#
# The buoy archive (~130 units/cycle, ~530/day) is deliberately NOT counted here and is not
# reserved for. That is a choice about WHICH step absorbs an overrun: `run --all` is the
# essential one - it is the published forecast - while `archive` has been alert-and-continue
# since 2026-08-15 (OPEN-ITEMS 9). If the real allowance ever bites, it should bite the step
# that fails softly, not the one every user reads.
#
# It follows that this guard cannot buy room for more spots. It only stops one avoidable
# failure mode. Four cycles plus the archive already sit at ~99% of the vendor allowance at
# 265 spots, so the NEXT region is gated on the fetch-plane migration, not on this file
# (OPEN-ITEMS 14, docs/rosa-fetch-plane-plan.md). Override with ROSA_OM_DAILY_BUDGET when the
# fleet, the schedule or the allowance changes.
DEFAULT_DAILY_BUDGET = 9_400.0

DEFAULT_STATE = Path("data/verify/quota.json")

# `run` returns this when it refuses to fetch. publish.sh treats it as a skip, not a failure:
# distinct from 1 (a real error) and 2 (bad arguments) so the cron can tell them apart.
EXIT_QUOTA_EXHAUSTED = 3


def daily_budget() -> float:
    raw = os.environ.get("ROSA_OM_DAILY_BUDGET")
    if not raw:
        return DEFAULT_DAILY_BUDGET
    try:
        return max(0.0, float(raw))
    except ValueError:
        print(
            f"warn: ROSA_OM_DAILY_BUDGET={raw!r} is not a number - using the default",
            file=sys.stderr,
        )
        return DEFAULT_DAILY_BUDGET


def marine_units(points: int) -> float:
    """Weighted units one fleet fetch of `points` deep-water points costs."""
    return round(points * MARINE_UNITS_PER_POINT, 1)


@dataclass
class Ledger:
    """Spend against today's budget. `day` is a UTC date string; a new day resets `spent`."""

    path: Path
    day: str
    spent: float
    budget: float

    @classmethod
    def load(cls, path: Path | None = None, *, now: datetime | None = None) -> Ledger:
        path = path or DEFAULT_STATE
        today = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
        spent = 0.0
        try:
            raw = json.loads(path.read_text())
            # a stale day is not an error - it is yesterday, and yesterday's quota is gone
            if raw.get("day") == today:
                spent = float(raw.get("spent", 0.0))
        except FileNotFoundError:
            pass
        except Exception as exc:  # corrupt/unreadable: start the day fresh, never block a run
            print(
                f"warn: quota ledger unreadable ({exc}) - counting today from zero", file=sys.stderr
            )
        return cls(path=path, day=today, spent=spent, budget=daily_budget())

    @property
    def remaining(self) -> float:
        return max(0.0, self.budget - self.spent)

    def affords(self, units: float) -> bool:
        return self.spent + units <= self.budget

    def record(self, units: float) -> None:
        """Add spend and persist. Never raises: a ledger write must not fail a published run."""
        self.spent = round(self.spent + units, 1)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps({"day": self.day, "spent": self.spent}, indent=1))
            tmp.replace(self.path)
        except Exception as exc:
            print(f"warn: could not write the quota ledger ({exc})", file=sys.stderr)

    def refusal(self, units: float) -> str:
        """The message printed when a run is refused - it has to say what to do next."""
        return (
            f"quota: refusing to fetch {units:g} units - {self.spent:g} of "
            f"{self.budget:g} already spent today ({self.day} UTC, {self.remaining:g} left). "
            "The Open-Meteo daily cap is per-IP and resets at 00:00Z; the previous payloads "
            "keep serving until the next cycle. Override with --ignore-quota (an ad-hoc run "
            "on top of the cron's four is what exhausted the day on 2026-08-15), or raise "
            "ROSA_OM_DAILY_BUDGET if the vendor allowance actually changed."
        )
