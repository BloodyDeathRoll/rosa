#!/usr/bin/env bash
# How many Rosa users. Reads the admin secret written at deploy time
# (~/rosa-push/user-api-admin-secret.txt) and prints the live counts.
#   users        everyone who ever signed in
#   new_7d/30d   signed up in the window
#   active_*     seen in the window (last_seen_at, touched at most once a day)
set -euo pipefail
SECRET_FILE="${ROSA_USER_API_SECRET_FILE:-$HOME/rosa-push/user-api-admin-secret.txt}"
URL="${ROSA_USER_API:-https://rosa-user-api.einhanamer.workers.dev}"
curl -sf -H "x-admin-secret: $(cat "$SECRET_FILE")" "$URL/admin/stats" | python3 -m json.tool
