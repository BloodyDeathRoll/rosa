#!/usr/bin/env bash
# Weekly cam rot check on the Oracle VM (see README §Ops alerting).
#
# A cam dies without anyone touching it: YouTube rotates the video id whenever a
# 24/7 stream restarts, so a spot's embed can go dark for months before a human
# notices. This checks every assigned cam once a week and pushes ONE admin alert
# when something is dead.
#
# It deliberately does NOT run `--apply` - publish.sh step 1b does, every cycle,
# and this stays the read-only reporter so the two never race over data/spots.
# Since 2026-08-28 a title-matched id is therefore repaired within ~6 h instead of
# a week. What this alert is FOR is the other half: the cams cam-scan refuses to
# touch (channel dark, no title match) and the ones repaired over and over, which
# means nobody has committed the new id. The VM's patch is local and thrown away
# each cycle - it holds a READ-ONLY deploy key - so the durable repair is still a
# human action from a clone that can push:
#     YOUTUBE_API_KEY=$GOOGLE_MAPS_API_KEY \
#       python tools/cam-scan/scan.py verify --resolve --apply
#
# Cost: a clean week is ~1 API unit (one batched videos.list for all cams).
# Each dead cam adds a 100-unit channel search, against a 10,000/day quota.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

if [ -f "$HOME/rosa/.env" ]; then set -a; . "$HOME/rosa/.env"; set +a; fi
KEY="${YOUTUBE_API_KEY:-${GOOGLE_MAPS_API_KEY:-}}"
: "${KEY:?no YOUTUBE_API_KEY / GOOGLE_MAPS_API_KEY in ~/rosa/.env}"

LOG="$HOME/rosa/cam-watch.log"
OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT

{
  echo "=== $(date -u +%FT%TZ) cam check ==="
  cd "$HOME/rosa"

  # Read-only check. Never --apply here (see header). A non-zero exit must not
  # kill the run before the alert goes out, so failure is captured, not trapped.
  if ! YOUTUBE_API_KEY="$KEY" uv run --project "$HOME/rosa/pipeline" \
        python tools/cam-scan/scan.py verify --resolve >"$OUT" 2>&1; then
    echo "cam-scan itself failed:"
    sed 's/^/  /' "$OUT"
    uv run --project "$HOME/rosa/pipeline" rosa-pipeline alert \
      --message "Cam check FAILED to run ($(date -u +%H:%MZ)). See cam-watch.log on rosa-instance." \
      || echo "warn: alert push failed too"
    exit 0   # a broken checker must not look like a clean week
  fi
  cat "$OUT"

  ok=$(grep -c '^  OK ' "$OUT" || true)
  dead=$(grep -c '^  DEAD ' "$OUT" || true)
  human=$(grep -c 'NEEDS A HUMAN' "$OUT" || true)
  fixable=$(grep -c 'same title - same camera' "$OUT" || true)

  if [ "$dead" -eq 0 ]; then
    echo "all $ok cam(s) live - no alert"
    exit 0
  fi

  spots=$(grep '^  DEAD ' "$OUT" | sed 's/^  DEAD \([^:]*\):.*/\1/' | paste -sd, - )
  msg="$dead cam(s) dead: ${spots}. $fixable auto-repairable (same title), $human need a human. Run: scan.py verify --resolve --apply"
  echo "alerting: $msg"
  uv run --project "$HOME/rosa/pipeline" rosa-pipeline alert --message "$msg" \
    || echo "warn: alert push failed"
} >>"$LOG" 2>&1
