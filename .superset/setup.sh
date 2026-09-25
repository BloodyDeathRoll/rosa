#!/usr/bin/env bash
# New-workspace setup: copy untracked local files from the main checkout, install deps.
set -euo pipefail
ROOT="${SUPERSET_ROOT_PATH:?SUPERSET_ROOT_PATH not set}"
WS="${SUPERSET_WORKSPACE_PATH:-$PWD}"
cd "$WS"

# Gitignored env/secrets + local Claude settings (skip any the main checkout lacks).
for f in .env.local web/.env.local web/.env.development deploy/push-api/.env.local .claude/settings.local.json; do
  if [ -f "$ROOT/$f" ] && [ ! -e "$f" ]; then
    mkdir -p "$(dirname "$f")"; cp "$ROOT/$f" "$f"; echo "copied $f"
  fi
done

# Last published forecast (~50 MB) so `npm run dev` has spot data to serve.
if [ -d "$ROOT/data/out" ] && [ ! -e data/out ]; then
  mkdir -p data; cp -r "$ROOT/data/out" data/out; echo "copied data/out"
fi

(cd web && npm ci --no-audit --no-fund)
(cd pipeline && uv sync)
