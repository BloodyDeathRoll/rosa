#!/usr/bin/env bash
# One-time bootstrap on a fresh Oracle Always Free VM (Ubuntu ARM/Ampere).
# Prereq: the repo is already cloned to ~/rosa (see README.md §2 for private-repo access).
# Installs uv + deps and enables the 4x/day systemd --user timer. Re-runnable.
set -euo pipefail

REPO="${ROSA_REPO:-$HOME/rosa}"

echo "==> system packages"
sudo apt-get update -y
sudo apt-get install -y git curl

echo "==> uv (manages its own Python 3.11+, no system Python needed)"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

if [ ! -d "$REPO/.git" ]; then
  echo "!! repo not found at $REPO — clone it first (README.md §2), e.g.:"
  echo "     git clone git@github.com:BloodyDeathRoll/rosa.git \"$REPO\""
  exit 1
fi
cd "$REPO"
git pull --ff-only origin main || true
uv sync --project pipeline

echo "==> Node.js + Vercel CLI (publishes forecasts to the data CDN)"
if ! command -v vercel >/dev/null 2>&1; then
  sudo apt-get install -y nodejs npm
  sudo npm i -g vercel
fi

echo "==> installing systemd --user timer"
mkdir -p "$HOME/.config/systemd/user"
cp deploy/oracle/rosa-cycle.service deploy/oracle/rosa-cycle.timer "$HOME/.config/systemd/user/"
# let the timer fire without an active login session (survives logout/reboot)
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now rosa-cycle.timer

echo
echo "==> done. upcoming runs:"
systemctl --user list-timers rosa-cycle.timer --no-pager || true
echo
echo "to publish forecasts to the data CDN, create ~/.config/rosa/env with:"
echo "  VERCEL_TOKEN=...   VERCEL_ORG_ID=...   VERCEL_PROJECT_ID=<rosa-data project id>"
echo "(until it exists the cycle still archives + runs, just skips publishing)"
echo
echo "force one cycle now:  systemctl --user start rosa-cycle.service"
echo "watch it:             journalctl --user -u rosa-cycle -f"
