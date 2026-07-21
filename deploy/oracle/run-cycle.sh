#!/usr/bin/env bash
# One Rosa forecast cycle, fired by the systemd timer 4x/day on the Oracle VM.
# Essential job: append the lead-time verification archive so Stage-0 skill (and the
# bias-correction it unblocks) can accumulate — the clock that can't be back-filled.
# Idempotent; logs to journald via stdout/stderr. data/ is gitignored so `git pull`
# never touches the archive or the published forecasts.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

REPO="${ROSA_REPO:-$HOME/rosa}"
cd "$REPO"

# stay current with main (auto-deploys code pushes on the next cycle)
git pull --ff-only origin main || echo "warn: git pull skipped — running local code"
uv sync --project pipeline --quiet

# 1) ESSENTIAL — append the model's forecast at every registered buoy (lead-time archive)
uv run --project pipeline rosa-pipeline archive

# 2) also refresh the published per-spot forecasts (cheap; ready for a future publish step)
uv run --project pipeline rosa-pipeline run --all

echo "rosa cycle done @ $(date -u +%FT%TZ)"
