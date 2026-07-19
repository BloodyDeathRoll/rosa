#!/usr/bin/env bash
# Render satellite crosshair screenshots for every spot in a YAML file.
#   ./run-local.sh ../../data/spots/israel.yaml /tmp/spot-shots [zoom]
# Starts a static server + headless Chrome, extracts spots, shoots, tears down.
# Zero model quota — pure network + rendering. Look at the PNGs (or feed them to
# a vision model) to spot pins that land in open water / inland / off the break.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
YAML="${1:?usage: run-local.sh <spots.yaml> <out-dir> [zoom]}"
OUT="${2:?usage: run-local.sh <spots.yaml> <out-dir> [zoom]}"
ZOOM="${3:-16}"
HTTP_PORT="${SPOT_HTTP_PORT:-4174}"
CDP_PORT="${SPOT_CDP_PORT:-9222}"
CHROME="$(command -v google-chrome || command -v chromium || command -v chromium-browser)"

mkdir -p "$OUT"
python3 "$HERE/spots_to_json.py" "$YAML" --out "$OUT/spots.json"

# static server for satverify.html
( cd "$HERE" && python3 -m http.server "$HTTP_PORT" >/dev/null 2>&1 ) &
HTTP_PID=$!
# headless chrome with a CDP endpoint
"$CHROME" --headless=new --enable-unsafe-swiftshader \
  --remote-debugging-port="$CDP_PORT" \
  --user-data-dir="$(mktemp -d)" >/dev/null 2>&1 &
CHROME_PID=$!
cleanup() { kill "$HTTP_PID" "$CHROME_PID" 2>/dev/null || true; }
trap cleanup EXIT

timeout 25 bash -c "until curl -sf http://127.0.0.1:$CDP_PORT/json/version >/dev/null; do sleep 1; done"
SPOT_HTTP_PORT="$HTTP_PORT" SPOT_CDP_PORT="$CDP_PORT" node "$HERE/shoot.mjs" "$OUT/spots.json" "$OUT" "$ZOOM"
echo "shots in $OUT"
