#!/usr/bin/env bash
# One Rosa cycle on the Oracle VM, fired by cron 4x/day (see README).
# archive (buoy lead-time truth - the calibration clock) + run --all + publish
# data/out to the rosa-data Vercel project as a prebuilt static site with
# permissive CORS on /data/*.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

# Secrets: VERCEL_TOKEN lives in ~/rosa/.env (chmod 600), never in the repo.
if [ -f "$HOME/rosa/.env" ]; then set -a; . "$HOME/rosa/.env"; set +a; fi
: "${VERCEL_TOKEN:?VERCEL_TOKEN not set (put it in ~/rosa/.env)}"

LOG="$HOME/rosa/publish.log"
STAGE="$HOME/rosa-data"   # dir basename becomes the Vercel project name

# Ops alerting: a failed essential step pushes to the admin devices
# (~/rosa-push/admin-subs.json snapshot) and pings the healthcheck's /fail URL;
# a clean cycle pings the healthcheck. Both are best-effort - alerting must
# never break the cycle - and HEALTHCHECK_URL is optional (set in ~/rosa/.env).
on_fail() {
  local step="$1"
  echo "!!! $(date -u +%FT%TZ) FAILED at: $step"
  uv run --project "$HOME/rosa/pipeline" rosa-pipeline alert \
    --message "Cycle FAILED at: $step ($(date -u +%H:%MZ)). Stale data keeps serving until the next good run." \
    || echo "warn: failure alert push failed too"
  [ -n "${HEALTHCHECK_URL:-}" ] && curl -fsS -m 10 --retry 3 -o /dev/null \
    --data-raw "$step" "$HEALTHCHECK_URL/fail" || true
}
trap 'on_fail "${BASH_COMMAND} (line $LINENO)"' ERR

{
  echo "=== $(date -u +%FT%TZ) run start ==="
  cd "$HOME/rosa"

  # stay current with main (code pushes reach the box on the next cycle);
  # data/ and .env are gitignored, so a pull never touches archive/forecasts
  git pull --ff-only origin main || echo "warn: git pull skipped - running local code"
  uv sync --project pipeline --quiet

  # 1) ESSENTIAL - append the model's forecast at every registered buoy
  #    (lead-time archive on this disk; the clock that can't be back-filled)
  uv run --project pipeline rosa-pipeline archive

  # 2) refresh the per-spot forecasts
  uv run --project pipeline rosa-pipeline run --all

  # 2b) SwellMap basin frames (animated wave fields, ~5 min). Non-fatal: on a
  #     NOMADS outage the previous cycle's frames keep serving.
  uv run --project pipeline rosa-pipeline swellmap || echo "warn: swellmap failed"

  # 3) publish: Vercel Build Output API v3 payload, served at /data/*
  rm -rf "$STAGE/.vercel/output"
  mkdir -p "$STAGE/.vercel/output/static/data"
  cp -r data/out/. "$STAGE/.vercel/output/static/data/"
  cat > "$STAGE/.vercel/output/config.json" <<'JSON'
{"version":3,"routes":[{"src":"/data/(.*)","headers":{"access-control-allow-origin":"*","cache-control":"public, max-age=300, s-maxage=300"},"continue":true}]}
JSON

  cd "$STAGE"
  vercel deploy --prebuilt --prod --yes --token="$VERCEL_TOKEN"

  # 4) swell-alert pushes (grouped: one swell = one notification). Only runs
  #    when the push secrets are present in ~/rosa/.env; never fails the cycle.
  if [ -n "${PUSH_SUBS_URL:-}" ]; then
    cd "$HOME/rosa"
    uv run --project pipeline rosa-pipeline notify || echo "warn: notify failed"
  fi

  # 5) dead-man ping: "a cycle completed" - its absence is the alarm
  if [ -n "${HEALTHCHECK_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 -o /dev/null "$HEALTHCHECK_URL" \
      || echo "warn: healthcheck ping failed"
  fi
  echo "=== $(date -u +%FT%TZ) done ==="
} >> "$LOG" 2>&1
