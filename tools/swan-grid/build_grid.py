"""Build a regional SWAN bathymetry grid from GEBCO (Stage 4 scaffolding).

Samples a regular lon-lat box via the pipeline's OpenTopoData GEBCO source (same
batching + backoff as `bathy`) and writes the three files a SWAN run needs:

    data/swan/<region>/bot.grd        bottom depths, metres positive-down, IDLA=3
                                      (rows south->north, west->east within a row;
                                      land cells are negative -> SWAN treats as dry)
    data/swan/<region>/meta.json      bounds/resolution/provenance
    data/swan/<region>/points.loc     nearshore output points for the spot set

Run from the repo root (network - ~207 OpenTopoData calls for Israel, ~4 min,
well inside their 1000/day budget; the API is rate-limited to 1 req/s):

    uv run --project pipeline python tools/swan-grid/build_grid.py

The grid is Stage-4 *scaffolding*: coarse (~1 km; GEBCO itself is ~450 m), enough
to prove the SWAN pipeline shape with synthetic boundaries. Real Stage-4 regions
get finer nested grids forced by Stage-3 spectra (docs/rosa-accuracy-roadmap.md).
"""

from __future__ import annotations

import json
import time
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from rosa_pipeline.bathymetry import OpenTopoDataSource  # noqa: E402
from rosa_pipeline.spots import load_spots  # noqa: E402

# Israel box: Ashkelon (31.55) to Rosh Hanikra (33.15), open Med to 34.0E.
REGION = "israel"
LON0, LAT0 = 34.0, 31.5
NX, NY = 121, 171  # grid POINTS (cells = N-1)
DLON = DLAT = 0.01  # ~1 km

# Nearshore output points: each Israeli spot nudged ~1.1 km seaward so it lands in
# a wet cell of this coarse grid (the beach cell itself straddles the waterline).
POINT_OFFSHORE_LON = 0.012


def main() -> int:
    out_dir = ROOT / "data" / "swan" / REGION
    out_dir.mkdir(parents=True, exist_ok=True)

    pts = [
        (LAT0 + j * DLAT, LON0 + i * DLON)  # j (south->north) outer, i (west->east) inner
        for j in range(NY)
        for i in range(NX)
    ]
    print(f"{REGION}: sampling {len(pts)} GEBCO points ({NX}x{NY} @ {DLON} deg)...")
    src = OpenTopoDataSource()
    # elevations() enforces the API's 100-locations/request cap; batch here and hold
    # the public API's 1 req/s line ourselves (backoff inside handles any 429s).
    elevations: list[float | None] = []
    for start in range(0, len(pts), 100):
        elevations.extend(src.elevations(pts[start : start + 100]))
        done = start + 100
        if done % 2000 < 100:
            print(f"  ... {min(done, len(pts))}/{len(pts)}")
        time.sleep(1.0)
    depths = [(-e if e is not None else -999.0) for e in elevations]  # positive-down

    wet = sum(1 for d in depths if d > 0)
    print(f"  wet cells: {wet}/{len(depths)} ({100 * wet // len(depths)}%)")

    bot = out_dir / "bot.grd"
    with bot.open("w", encoding="utf-8") as f:
        for j in range(NY):  # IDLA=3: first record = southern row
            row = depths[j * NX : (j + 1) * NX]
            f.write(" ".join(f"{d:.1f}" for d in row) + "\n")

    spots = load_spots(ROOT / "data" / "spots")
    il = sorted((s for s in spots.values() if s.region == "Israel"), key=lambda s: -s.lat)
    with (out_dir / "points.loc").open("w", encoding="utf-8") as f:
        for s in il:
            f.write(f"{s.lon - POINT_OFFSHORE_LON:.5f} {s.lat:.5f}\n")
    print(f"  output points: {len(il)} Israeli spots, nudged {POINT_OFFSHORE_LON} deg seaward")

    meta = {
        "region": REGION,
        "source": "gebco2020 via opentopodata",
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "lon0": LON0,
        "lat0": LAT0,
        "nx": NX,
        "ny": NY,
        "dlon": DLON,
        "dlat": DLAT,
        "idla": 3,
        "depth_convention": "metres positive-down; land negative; missing -999",
        "wet_cells": wet,
        "points": [s.id for s in il],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"  wrote {bot}, meta.json, points.loc")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
