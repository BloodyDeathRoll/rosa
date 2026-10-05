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

# The evidence legs: the coastal-station wind archive + scorecard and the SWAN pilot.
# They RECORD, they never publish - so since 2026-09-17 they run AFTER the public deploy
# (together they held the forecast back ~2 h of a ~4.5 h cycle: ~70 min of paced NOMADS
# wind requests and ~50 min of SWAN, measured 2026-09-16 20:20Z). Their archives cannot
# be back-filled, so the EXIT trap below fires them on EVERY way out - a cycle that dies
# at `run --all` or at the Vercel upload (2026-09-07: two days of "api-upload-free")
# still records. Once per cycle; every command is non-fatal.
EVIDENCE_DONE=0
run_evidence() {
  [ "$EVIDENCE_DONE" -eq 1 ] && return 0
  EVIDENCE_DONE=1
  cd "$HOME/rosa" || return 0
  # 4c) the coastal-station wind archive (the published model's wind at every station in
  #     data/stations; the raw GFS atmos GRIB candidate, plan C3b, rode here 2026-09-12 to
  #     2026-09-26 and was dropped when its A/B lost). Split off step 1 on 2026-09-17 - see
  #     there. Evidence only and guarded inside the command; never fatal.
  uv run --project pipeline rosa-pipeline archive --stations only \
    || echo "warn: station wind archive failed"

  # 4d) coastal wind truth: the model's 10 m wind (archived at every station in
  #     data/stations by step 4c) vs the airports' METARs and IMS's beach stations, by
  #     lead. Scores the published model (GFS since 2026-08-30); `--wind-model icon`
  #     scores the archived A/B member. Evidence only - nothing reads it yet
  #     (OPEN-ITEMS 25); ~90 small
  #     aviationweather.gov requests, a few minutes, after the deploy and non-fatal
  #     for the same reason as 4b. IMS stations need IMS_API_TOKEN in ~/rosa/.env.
  uv run --project pipeline rosa-pipeline verify --stations --archive \
    || echo "warn: station wind measurement failed"

  # 4e) Stage-4 pilot (docs/rosa-stage4-plan.md): for every region with committed SWAN
  #     grids, rebuild the boundary from this cycle's GFS-Wave partitions, run the SWAN
  #     chain (outer + nests, ~56 min for days 0-7 on this box, 2026-10-05) and append
  #     SWAN's sea at the registered buoys to the archive as the `swan` member. RECORDING
  #     ONLY: `run --all` above still publishes the march. The 4.5 A/B on the .swan rows
  #     is what earns `--nearshore swan` a place in that command. Non-fatal and silent
  #     on failure (a pilot is never worth a forecast cycle); run.log in the run dir has
  #     every SWAN run's timing. The 80 min `timeout` is the slot guard: a cycle takes
  #     ~3.3 h of its 6 h (2026-10-05), and an overrun makes the lock skip the next cycle -
  #     a pilot must never cost a public refresh. It was 50 min until 2026-10-06; the chain
  #     grew to ~56 min and the guard killed every run from 2026-09-27 on. LAST since 2026-09-17 (it ran before
  #     `run --all` until then and delayed the public forecast ~50 min a cycle); it
  #     fetches its own GFS-Wave box, so nothing upstream depends on its position.
  cd "$HOME/rosa"
  for REGION in socal; do
    if [ -f "data/swan/$REGION/outer/meta.json" ] && [ -x "$HOME/bin/swan-omp.exe" ]; then
      ( uv run --project pipeline rosa-pipeline swan --region "$REGION" --steps 0-168 --nests --chain \
          && timeout 4800 bash "data/swan/$REGION/run/run.sh" \
          && uv run --project pipeline rosa-pipeline swan-archive --run "data/swan/$REGION/run" ) \
        || echo "warn: swan $REGION failed - cycle continues on the march"
    fi
  done
}
trap 'trap - ERR; set +e; run_evidence >> "$LOG" 2>&1' EXIT

{
  echo "=== $(date -u +%FT%TZ) run start ==="
  cd "$HOME/rosa"

  # stay current with main (code pushes reach the box on the next cycle);
  # data/ and .env are gitignored, so a pull never touches archive/forecasts.
  # data/spots IS tracked, and step 1b rewrites cam ids in it every cycle - drop
  # those local edits first so the pull stays a clean fast-forward. Nothing else on
  # this box is allowed to hand-edit a spot YAML; a real cam fix is committed to main.
  git checkout -- data/spots || true
  git pull --ff-only origin main || echo "warn: git pull skipped - running local code"
  uv sync --project pipeline --quiet

  # 1b) refresh dead cam ids. YouTube rotates the video id whenever a 24/7 stream
  #     restarts, so a pinned id in data/spots rots on its own - the daylight-only cams
  #     die every night (santa-teresa died twice in two days, OPEN-ITEMS 8). Until now
  #     repair was a weekly human action behind cam-watch.sh's alert, so a spot could sit
  #     dark for a week. --resolve --apply swaps in a replacement ONLY when the new
  #     stream's title still matches the dead one; everything else it prints as
  #     "NEEDS A HUMAN" and leaves alone (a channel's OTHER live stream is a different
  #     beach - it once proposed Miura's cam, 30 km away, for chigasaki, 2026-07-29).
  #
  #     cam-watch.sh would not --apply because this box holds a READ-ONLY deploy key:
  #     a dirty data/spots breaks the next `git pull --ff-only` and silently freezes the
  #     VM on local code. The `git checkout -- data/spots` above is what makes it safe -
  #     the patch lives for exactly one cycle and the pull is always clean. So this is a
  #     stopgap that keeps a cam live, NOT the durable fix: committing the new id to main
  #     from a clone that can push is still the repair. cam-watch.sh keeps its weekly
  #     admin push, which is where the NEEDS-A-HUMAN cases surface.
  #
  #     Cost: ~1 unit for a clean cycle, +100 per dead cam, against 10,000/day.
  #     Non-fatal: a cam is never worth a forecast cycle.
  KEY="${YOUTUBE_API_KEY:-${GOOGLE_MAPS_API_KEY:-}}"
  if [ -n "$KEY" ]; then
    YOUTUBE_API_KEY="$KEY" uv run --project pipeline python tools/cam-scan/scan.py \
      verify --resolve --apply \
      || echo "warn: cam refresh failed - cams keep their current ids"
  else
    echo "warn: no YOUTUBE_API_KEY/GOOGLE_MAPS_API_KEY in ~/rosa/.env - cam refresh skipped"
  fi

  # 1) append the model's forecast at every registered buoy (lead-time archive on
  #    this disk; the clock that can't be back-filled). ALERT-AND-CONTINUE, not
  #    fatal (2026-08-15, closes OPEN-ITEMS item 9): the archive hour is lost
  #    either way when this fails, so aborting the cycle turned one unrecoverable
  #    loss into two - a daily-quota 429 here once kept cam fixes undeployed and
  #    the public forecast stale for 12 h. The admin alert still fires so a
  #    silent archive rot cannot creep in.
  #    `--stations skip` since 2026-09-17: the coastal-station wind arm (its paced NOMADS
  #    leg was ~70 min until it was dropped 2026-09-26) is evidence only and now runs as step 4c, AFTER the deploy - it
  #    and the SWAN pilot used to hold the public forecast back ~2 h every cycle.
  uv run --project pipeline rosa-pipeline archive --stations skip \
    || on_fail "archive (non-fatal - cycle continues)"

  # 2) refresh the per-spot forecasts.
  #    Exit 3 is the daily-quota guard refusing to fetch (rosa_pipeline.quota), NOT a
  #    failure. Only the `--wave-source om` fallback arm can raise it since 2026-09-12:
  #    the default blend arm makes no marine-host request (its SST/tide fallback leg,
  #    1.21 units/spot, crossed the budget at 1947 spots and refused the 20:20Z cycle
  #    daily - so it was removed, not gated). On the om arm one 1947-spot run is 14,972
  #    units, so a second one the same day would 429 mid-fleet and kill the cycle, which
  #    is what happened on 2026-08-15 at 265 spots.
  #    Refusing costs one stale refresh; the previous payloads keep serving and the
  #    freshness watchdog still covers real rot. Alert so it stays visible, then skip
  #    straight past the deploy - re-publishing an unchanged tree buys nothing.
  #    `|| RUN_RC=$?`, not `set +e` (2026-09-17): bash fires the ERR trap on a non-zero
  #    command even with errexit off, so the old `set +e ... set -e` form pushed a false
  #    "Cycle FAILED" alert beside the quota-skip (3) and partial-run (4) alerts. A
  #    command on the left of `||` never fires the trap.
  RUN_RC=0
  uv run --project pipeline rosa-pipeline run --all || RUN_RC=$?
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
  elif [ "$RUN_RC" -eq 4 ]; then
    # Exit 4 is a PARTIAL run: a small share of the fleet failed and the rest published.
    # Deploy it. Withholding the whole forecast over a handful of spots is what kept 621
    # healthy spots and six freshly seeded regions off the CDN for a day on 2026-08-28
    # (3 spots raising the same ValueError). The failed spots keep serving their previous
    # payload, so the cost of deploying is that those few go stale - much cheaper than
    # every spot going stale. Alert so the failures cannot rot unnoticed, then fall
    # through to the deploy. rosa-pipeline draws the line, not this script: above its
    # share threshold it still returns 1 and the branch below kills the cycle.
    uv run --project pipeline rosa-pipeline alert \
      --message "Cycle PARTIAL: some spots failed and kept their previous payload ($(date -u +%H:%MZ)). The rest published. See publish.log for the ids." \
      || echo "warn: partial-run alert push failed"
  elif [ "$RUN_RC" -ne 0 ]; then
    # the `||` above keeps the ERR trap quiet for this command, so raise the alert by hand
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
  # --archive=tgz uploads ONE tarball instead of one request per file. The fleet
  # publishes ~1500 files a cycle (1408 spots + index + swellmap frames), and at
  # 4 cycles a day that is ~6000 uploads against Vercel's free ceiling of 5000
  # per 24 h - every cycle from 2026-09-07 16:33Z on died with
  # "api-upload-free", leaving two-day-old forecasts on the CDN.
  # No --token: the CLI reads VERCEL_TOKEN (exported by the .env load above) itself,
  # and an argv token shows in `ps` for the whole deploy (Dream review 2026-09-25).
  vercel deploy --prebuilt --prod --yes --archive=tgz

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

  # 4c-4e) the evidence legs (station wind archive + its scorecard, SWAN pilot) - see
  #     run_evidence above. Also fired from the EXIT trap, so a cycle that dies at
  #     `run --all` or the deploy still records them.
  run_evidence

  # 5) dead-man ping: "a cycle completed" - its absence is the alarm
  if [ -n "${HEALTHCHECK_URL:-}" ]; then
    curl -fsS -m 10 --retry 3 -o /dev/null "$HEALTHCHECK_URL" \
      || echo "warn: healthcheck ping failed"
  fi
  echo "=== $(date -u +%FT%TZ) done ==="
} >> "$LOG" 2>&1
