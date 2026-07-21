#!/usr/bin/env bash
#
# beep-reminder.sh — audible nudge every N seconds to go refresh the Oracle
# console and re-click "Create" while hunting A1.Flex ARM capacity.
#
# Usage:
#   ./beep-reminder.sh            # beep every 120s
#   ./beep-reminder.sh 60         # beep every 60s
#   Ctrl-C to stop.
#
set -euo pipefail
INTERVAL="${1:-120}"

beep() {
  # Try real audio first, fall back to the terminal bell.
  if command -v paplay >/dev/null && [[ -f /usr/share/sounds/freedesktop/stereo/complete.oga ]]; then
    paplay /usr/share/sounds/freedesktop/stereo/complete.oga 2>/dev/null && return
  fi
  if command -v beep >/dev/null; then beep 2>/dev/null && return; fi
  # terminal bell (x3 so it's hard to miss)
  printf '\a'; sleep 0.3; printf '\a'; sleep 0.3; printf '\a'
}

echo "Beeping every ${INTERVAL}s — go refresh Oracle console & re-click Create. Ctrl-C to stop."
count=0
while :; do
  count=$((count + 1))
  printf '\r[%s]  reminder #%d — refresh & retry Create   ' "$(date +%H:%M:%S)" "$count"
  beep
  sleep "$INTERVAL"
done
