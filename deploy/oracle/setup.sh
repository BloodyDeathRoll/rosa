#!/usr/bin/env bash
# One-time bootstrap on the Oracle VM (Ubuntu). Prereq: repo cloned to ~/rosa
# (read-only deploy key, README §2). Installs uv + Node/Vercel and the 4x/day
# cron. Re-runnable.
set -euo pipefail

REPO="${ROSA_REPO:-$HOME/rosa}"

echo "==> system packages"
sudo apt-get update -y
sudo apt-get install -y git curl nodejs npm

echo "==> uv (manages its own Python 3.11+)"
command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "==> vercel CLI"
command -v vercel >/dev/null 2>&1 || sudo npm i -g vercel

cd "$REPO"
git pull --ff-only origin main || true
uv sync --project pipeline

echo "==> cron (4x/day, ~2h after each NOAA run publishes)"
( crontab -l 2>/dev/null | grep -v "rosa/deploy/oracle/publish.sh" ;
  echo "20 2,8,14,20 * * * $REPO/deploy/oracle/publish.sh" ) | crontab -

echo
echo "==> done. Secrets: put VERCEL_TOKEN=... in ~/rosa/.env (chmod 600)."
echo "force a cycle now:  ~/rosa/deploy/oracle/publish.sh ; tail -f ~/rosa/publish.log"
