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

# Single-instance guard. Every cycle shares one checkout (~/rosa: same git pull,
# uv sync, data/out) and one stage dir, so an overrun - a slow `run --all` still
# going when the next cron fires - can deploy a half-written tree. Non-blocking
# on purpose: the loser exits 0 immediately rather than queueing, because a
# queued cycle would fetch stale-by-an-hour data and then race the next one too.
# Skips are a normal outcome, not a failure: this sits ABOVE the ERR trap so it
# never pushes an ops alert. The lock lives outside the repo so it can't dirty
# `git pull --ff-only`. Held for the whole cycle; released when the fd closes.
LOCK="$HOME/.rosa-publish.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "=== $(date -u +%FT%TZ) skipped - a cycle already holds $LOCK ===" >> "$LOG"
  exit 0
fi

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

  # 1) append the model's forecast at every registered buoy (lead-time archive on
  #    this disk; the clock that can't be back-filled). ALERT-AND-CONTINUE, not
  #    fatal (2026-08-15, closes OPEN-ITEMS item 9): the archive hour is lost
  #    either way when this fails, so aborting the cycle turned one unrecoverable
  #    loss into two - a daily-quota 429 here once kept cam fixes undeployed and
  #    the public forecast stale for 12 h. The admin alert still fires so a
  #    silent archive rot cannot creep in.
  uv run --project pipeline rosa-pipeline archive || on_fail "archive (non-fatal - cycle continues)"

  # 2) refresh the per-spot forecasts.
  #    Exit 3 is the daily-quota guard refusing to fetch (rosa_pipeline.quota), NOT a
  #    failure: at 265 spots four cycles already spend ~9,300 of Open-Meteo's 10,000/day,
  #    so a fifth fleet run of any kind - an ad-hoc one, or a cycle after someone else's -
  #    would 429 mid-fleet and kill the cycle, which is what happened on 2026-08-15.
  #    Refusing costs one stale refresh; the previous payloads keep serving and the
  #    freshness watchdog still covers real rot. Alert so it stays visible, then skip
  #    straight past the deploy - re-publishing an unchanged tree buys nothing.
  set +e
  uv run --project pipeline rosa-pipeline run --all
  RUN_RC=$?
  set -e
  if [ "$RUN_RC" -eq 3 ]; then
    uv run --project pipeline rosa-pipeline alert \
      --message "Cycle SKIPPED: Open-Meteo daily quota spent ($(date -u +%H:%MZ)). Existing forecasts keep serving; the quota resets 00:00Z." \
      || echo "warn: quota alert push failed"
    # still ping the dead-man: the cycle ran and decided not to fetch, which is not the
    # silence the healthcheck exists to catch. Skipping it would raise a SECOND alarm for
    # one deliberate skip.
    if [ -n "${HEALTHCHECK_URL:-}" ]; then
      curl -fsS -m 10 --retry 3 -o /dev/null "$HEALTHCHECK_URL" || echo "warn: healthcheck ping failed"
    fi
    echo "=== $(date -u +%FT%TZ) skipped - daily quota spent ==="
    exit 0
  elif [ "$RUN_RC" -ne 0 ]; then
    # set +e disarmed the ERR trap for this command, so raise the alert by hand
    on_fail "rosa-pipeline run --all (exit $RUN_RC)"
    exit "$RUN_RC"
  fi

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

  # 4b) measure forecast skill vs buoy truth: lead-bucket scorecards -> skill.json,
  #     the measured confidence ceilings the NEXT cycle's run --all publishes
  #     (this cycle already read the previous one). After the deploy on purpose -
  #     a buoy-obs outage must neither delay nor break publishing - and non-fatal
  #     for the same reason. ISRAMAR buoys are skipped inside the command (legal
  #     red line: manual calibration use only).
  cd "$HOME/rosa"
  uv run --project pipeline rosa-pipeline verify --all-buoys --archive --write-skill \
    || echo "warn: skill measurement failed - published ceilings stay as-is"

  # 5) dead-man ping: "a cycle completed" - its absence is the alarm
  if [ -n "${HEALTHCHECK_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 -o /dev/null "$HEALTHCHECK_URL" \
      || echo "warn: healthcheck ping failed"
  fi
  echo "=== $(date -u +%FT%TZ) done ==="
} >> "$LOG" 2>&1
