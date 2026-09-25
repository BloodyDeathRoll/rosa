#!/usr/bin/env bash
# Stop the dev server run.sh started (the only long-lived process setup/run create).
WS="${SUPERSET_WORKSPACE_PATH:-$PWD}"
pkill -TERM -f "$WS/web/node_modules/.bin/vite" 2>/dev/null || true
exit 0
