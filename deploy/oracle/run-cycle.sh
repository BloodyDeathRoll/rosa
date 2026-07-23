#!/usr/bin/env bash
# One Rosa forecast cycle, fired by the systemd timer 4x/day on the Oracle VM — the single
# scheduling home: archive + run --all + publish. The archive appends the lead-time
# verification truth so Stage-0 skill (and the bias-correction it unblocks) accumulates on
# the VM's persistent disk — the clock that can't be back-filled.
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

# 2) refresh the per-spot forecasts
uv run --project pipeline rosa-pipeline run --all

# 3) publish the fresh forecasts to the data CDN (Vercel). Configure the box with
#    VERCEL_TOKEN / VERCEL_ORG_ID / VERCEL_PROJECT_ID (the rosa-data project) in
#    ~/.config/rosa/env (loaded by rosa-cycle.service). Until then this is skipped with a
#    note, so a fresh box still archives + runs. Mirrors web/'s prebuilt deploy: data/out/*
#    is served at /data/** — exactly what the app fetches via VITE_DATA_BASE.
if [ -n "${VERCEL_TOKEN:-}" ] && [ -n "${VERCEL_ORG_ID:-}" ] && [ -n "${VERCEL_PROJECT_ID:-}" ]; then
  if command -v vercel >/dev/null 2>&1; then
    stage="$REPO/.data-publish"
    rm -rf "$stage"
    mkdir -p "$stage/.vercel/output/static/data"
    printf '{"version":3}\n' > "$stage/.vercel/output/static/config.json"
    cp -r "$REPO/data/out/." "$stage/.vercel/output/static/data/"
    ( cd "$stage" && vercel deploy --prebuilt --prod --yes --token "$VERCEL_TOKEN" )
    echo "published forecasts to the data CDN"
  else
    echo "warn: vercel CLI missing — skipping publish (re-run setup.sh)"
  fi
else
  echo "note: VERCEL_* not set — skipping publish (archive + run still done)"
fi

echo "rosa cycle done @ $(date -u +%FT%TZ)"
