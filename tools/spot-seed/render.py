#!/usr/bin/env python3
"""Render satellite crosshair tiles for spot-seed candidates - the visual leg of
validation. For each candidate it shoots an ESRI World Imagery tile with a crosshair
at the coordinate (via tools/spot-verify), so a vision pass can judge real break vs.
open water / inland / harbor. Rendering is deterministic + network-only; the JUDGE
step is the vision model reading the PNGs (ESRI is build-time verification only,
never redistributed - see docs/spot-mapping-approach.md).

Usage:
  python tools/spot-seed/render.py <region> [--tier new|corrections] [--zoom 16]
  python tools/spot-seed/render.py --file path/to/spots.json --out DIR
"""

from __future__ import annotations
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERIFY = HERE.parent / "spot-verify"
WORK = HERE / "work"


def _chrome():
    for c in ("google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(c)
        if p:
            return p
    raise RuntimeError("no chrome/chromium found")


def _node():
    p = shutil.which("node")
    if p:
        return p
    for g in Path.home().glob(".nvm/versions/node/*/bin/node"):
        return str(g)
    raise RuntimeError("node not found")


def _wait_cdp(port, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=2).read()
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("Chrome CDP endpoint did not come up")


def render_tiles(spots, out_dir, zoom=16, http_port=4180, cdp_port=9230):
    """spots: list[{id,name,lat,lon}] -> writes <out_dir>/<id>.png per spot."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sj = out_dir / "spots.json"
    sj.write_text(json.dumps(spots))
    srv = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(http_port)],
        cwd=str(VERIFY),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    udd = tempfile.mkdtemp()
    chrome = subprocess.Popen(
        [
            _chrome(),
            "--headless=new",
            "--enable-unsafe-swiftshader",
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={udd}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_cdp(cdp_port)
        env = {**os.environ, "SPOT_HTTP_PORT": str(http_port), "SPOT_CDP_PORT": str(cdp_port)}
        subprocess.run(
            [_node(), str(VERIFY / "shoot.mjs"), str(sj), str(out_dir), str(zoom)],
            env=env,
            check=True,
        )
    finally:
        srv.terminate()
        chrome.terminate()
    pngs = sorted(out_dir.glob("*.png"))
    return out_dir, pngs


def _spots_from_region(region, tier):
    res = json.loads((WORK / region / "result.json").read_text())
    rows = res.get(tier, [])
    out = []
    for r in rows:
        if tier == "corrections":  # {id, m, osm} - render at OUR pin? no coords; skip
            continue
        out.append(
            {"id": r["id"], "name": r.get("name", r["id"]), "lat": r["lat"], "lon": r["lon"]}
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("region", nargs="?")
    ap.add_argument("--tier", default="new", choices=["new"])
    ap.add_argument("--file", help="explicit spots.json [{id,name,lat,lon}]")
    ap.add_argument("--out")
    ap.add_argument("--zoom", type=int, default=16)
    a = ap.parse_args()
    if a.file:
        spots = json.loads(Path(a.file).read_text())
        out = a.out or (Path(a.file).parent / "tiles")
    else:
        if not a.region:
            ap.error("region or --file required")
        spots = _spots_from_region(a.region, a.tier)
        out = a.out or (WORK / a.region / "tiles")
    if not spots:
        print("no candidates to render", file=sys.stderr)
        return
    print(f"rendering {len(spots)} tiles → {out}", file=sys.stderr)
    out_dir, pngs = render_tiles(spots, out, zoom=a.zoom)
    for p in pngs:
        print(p)


if __name__ == "__main__":
    main()
