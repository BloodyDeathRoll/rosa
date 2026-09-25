#!/usr/bin/env bash
# Dev server on a free port per workspace (from 5173 up), pid recorded for teardown.
set -euo pipefail
cd "${SUPERSET_WORKSPACE_PATH:-$PWD}"
port=5173
while (echo >"/dev/tcp/127.0.0.1/$port") 2>/dev/null; do port=$((port + 1)); done
echo "dev server: http://localhost:$port"
cd web && exec npm run dev -- --port "$port" --strictPort
