"""Self-imposed daily budget for the Open-Meteo marine host.

Open-Meteo's free tier caps calls per MINUTE, per HOUR and per DAY, per IP. The minute cap
has been handled since 2026-08-02 inside ``fetch.py`` (``MARINE_BATCH_SIZE`` plus a pause
past each minute boundary). The DAY cap had nothing in front of it, and on 2026-08-15 that
cost a cycle: an ad-hoc ``run --all`` on top of the cron's four fleet runs exhausted the
daily quota, ``run --all`` raised a 429 mid-fleet, ``publish.sh`` died at step 2 and the
admin alert fired. The quota resets at 00:00Z, so the next scheduled cycle recovered on its
own - which is exactly why this is worth guarding rather than escalating: the cost of the
failure was a stale forecast and a false alarm, and both were avoidable.

The arithmetic that matters, from ``fetch.py``'s own derivation: an OM-arm marine batch
costs about ``MARINE_UNITS_PER_POINT`` weighted units per point (17 vars x 3 models -> 5.1,
scaled by 17/14 days -> 6.2, plus the ensemble's 1.5). At 265 spots that was ~2,040 units
a fleet run, four cron runs ~8,150 of a 10,000/day allowance - the fleet at the edge of
the daily cap by itself, open item 14's ceiling. **Since 2026-08-26 the default arm is the
blend** (docs/rosa-fetch-plane-plan.md D3): waves come from global GFS-Wave + ECMWF files
downloaded once per cycle, and the only marine-host traffic left is the 2-variable
SST/tide-fallback leg at ``MARINE_LIGHT_UNITS_PER_POINT`` - ~320 units a fleet run, ~1,280
a day. Spot count no longer sets the ceiling. The guard stays for the ``--wave-source om``
fallback arm and for the archive/verify steps that share the host: a fifth OM-arm fleet
run of any kind will still be refused. Refused, not throttled: there is no useful way to
wait out a daily quota inside a cycle, and a skipped refresh (the previous payloads keep
serving, ~6 h old at worst) is a far better outcome than a failed cycle.

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
# the minute-bucket batch size is cut from. Was 8.8 until 2026-08-16, when three total-sea
# fields nothing reads came out of MARINE_HOURLY (20 vars -> 17): a 12.5% cut of the marine
# host's per-point cost, and the cheapest headroom available against this cap.
MARINE_UNITS_PER_POINT = 7.69

# Self-imposed daily ceiling for FLEET RUNS, not a measured vendor limit, and deliberately
# below Open-Meteo's published 10,000 calls/day. At 265 spots the cron's four cycles cost
# 4 x 2,038 = 8,152 units by themselves (9,328 before the 2026-08-16 variable trim), so this
# budget's whole job is to refuse the FIFTH run, not to ration the first four.
#
# The buoy archive (~130 units/cycle, ~530/day) is deliberately NOT counted here and is not
# reserved for. That is a choice about WHICH step absorbs an overrun: `run --all` is the
# essential one - it is the published forecast - while `archive` has been alert-and-continue
# since 2026-08-15 (OPEN-ITEMS 9). If the real allowance ever bites, it should bite the step
# that fails softly, not the one every user reads.
#
# This guard never bought room for more spots; it only stopped one avoidable failure mode.
# Under the OM arm four cycles plus the archive sat at ~87% of the vendor allowance at 265
# spots (99% before the trim). Under the blend arm (the default since 2026-08-26) the same
# four cycles are ~1,280 units, so the budget is no longer near the fleet: it is the ceiling
# on OM-arm fallback runs and ad-hoc A/Bs. The number is left where it was on purpose - it
# still fits exactly four OM-arm fleet runs, so a region-wide fallback to OM keeps working.
# Override with ROSA_OM_DAILY_BUDGET when the fleet, the schedule or the allowance changes.
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


# The blend arm's transitional marine-light leg (blend.MARINE_LIGHT_FIELDS: SST + tide)
# bills the SAME marine host. Open-Meteo floors every location at weight 1
# (max(1, vars/10) per fetch.py's derivation), so 2 vars is 1.0/point - not the ~0.2 a
# bare vars/10 reads - scaled by 17/14 days -> 1.21. Small beside the om arm's 7.69,
# but a live blend fleet run is an ad-hoc run on top of the cron's four, which is
# exactly the 2026-08-15 scenario this ledger exists to refuse.
MARINE_LIGHT_UNITS_PER_POINT = 1.21


def marine_light_units(points: int) -> float:
    """Weighted units one blend-arm fetch of `points` costs on the marine host."""
    return round(points * MARINE_LIGHT_UNITS_PER_POINT, 1)


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
