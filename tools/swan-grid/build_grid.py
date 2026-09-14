"""Build the SWAN bathymetry grids for a Stage-4 region (docs/rosa-stage4-plan.md 4.1).

One region = one YAML in ``tools/swan-grid/regions/`` naming the seabed source, an outer
grid, its nests and the spots that get an output point. For each grid the tool writes:

    data/swan/<region>/<grid>/bot.grd     depths, metres positive-down, IDLA=3 (rows
                                          south->north, west->east); land negative,
                                          no data -999 - SWAN treats both as dry
    data/swan/<region>/<grid>/meta.json   bounds, resolution, provenance, wet count

and once per region:

    data/swan/<region>/points.loc         one output point per spot: the first cell at or
                                          past ``handoff_depth_m`` walking the spot's own
                                          ray (its committed profile's bearing) on the
                                          finest built grid - where SWAN hands off to the
                                          breaker march
    data/swan/<region>/points.json        the same points with spot id, bearing, distance,
                                          the grid that holds them and its depth there

Sources:
  crm          NCEI Coastal Relief Model via THREDDS NetCDF subset service (public domain).
               Native-resolution cuts are cached under data/swan/<region>/src/ (gitignored,
               tens of MB); re-run with --refetch to pull them again.
  gebco-local  the local GEBCO_2024.nc the pipeline's bathy profiles are cut from.

Every grid is a block AVERAGE of the source cells whose centres fall inside each target
cell - never a nearest-sample pick, which would let one cliff cell dry a 1 km sea cell or
one wet cell flood a headland.

Run from the repo root:

    uv run --project pipeline python tools/swan-grid/build_grid.py socal
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline" / "src"))

from rosa_pipeline.bathymetry import LocalGebcoSource, load_profile
from rosa_pipeline.spots import load_spots

REGIONS_DIR = Path(__file__).resolve().parent / "regions"
NODATA = -999.0
NCSS_TIMEOUT_S = 900.0


def load_region(name: str) -> dict:
    path = REGIONS_DIR / f"{name}.yaml"
    if not path.exists():
        raise SystemExit(f"no region config at {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- sources: (lat axis ascending, lon axis ascending, elevation m, NaN = no data) --------


def fetch_crm(
    ncss: str, dataset: str, box: dict, cache: Path, *, refetch: bool
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """One native-resolution cut of a CRM dataset, as netCDF-3 (scipy reads it, no
    netCDF4 stack - the same call as the pipeline's h5py-not-xarray rule)."""
    from scipy.io import netcdf_file

    if refetch or not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        params = {
            "var": "Band1",
            "north": box["north"],
            "south": box["south"],
            "west": box["west"],
            "east": box["east"],
            "horizStride": 1,
            "accept": "netcdf3",
        }
        print(
            f"  fetching {dataset} {box['south']}..{box['north']}N {box['west']}..{box['east']}E"
        )
        with (
            httpx.Client(timeout=NCSS_TIMEOUT_S) as client,
            client.stream("GET", f"{ncss}/{dataset}.nc", params=params) as resp,
        ):
            resp.raise_for_status()
            with cache.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
        print(f"  cached {cache} ({cache.stat().st_size / 1e6:.1f} MB)")
    f = netcdf_file(str(cache), "r", mmap=False)
    try:
        lat = np.array(f.variables["lat"][:], dtype=float)
        lon = np.array(f.variables["lon"][:], dtype=float)
        band = f.variables["Band1"]
        fill = getattr(band, "_FillValue", -9999)
        elev = np.array(band[:], dtype=float)
    finally:
        f.close()
    elev[elev == float(fill)] = np.nan
    if lat[0] > lat[-1]:
        lat, elev = lat[::-1], elev[::-1, :]
    if lon[0] > lon[-1]:
        lon, elev = lon[::-1], elev[:, ::-1]
    return lat, lon, elev


def read_gebco_local(box: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    src = LocalGebcoSource()
    i0, _ = src._index(box["south"], box["west"])
    i1, _ = src._index(box["north"], box["west"])
    j0 = round((box["west"] - src.lon0) / src.dlon)
    j1 = round((box["east"] - src.lon0) / src.dlon)
    elev = np.array(src._elev[i0 : i1 + 1, j0 : j1 + 1], dtype=float)
    lat = src.lat0 + np.arange(i0, i1 + 1) * src.dlat
    lon = src.lon0 + np.arange(j0, j1 + 1) * src.dlon
    return lat, lon, elev


# --- regrid -------------------------------------------------------------------------------


def target_axes(grid: dict) -> tuple[np.ndarray, np.ndarray]:
    """Grid POINTS (cell centres) at res_deg from the south-west corner, inclusive."""
    d = grid["res_deg"]
    nx = round((grid["east"] - grid["west"]) / d) + 1
    ny = round((grid["north"] - grid["south"]) / d) + 1
    return grid["south"] + np.arange(ny) * d, grid["west"] + np.arange(nx) * d


def block_average(
    src_lat: np.ndarray, src_lon: np.ndarray, elev: np.ndarray, grid: dict
) -> tuple[np.ndarray, np.ndarray]:
    """Mean source elevation per target cell (cell j spans +-res/2 around its centre), and
    the count of source cells that went in. Empty cells come back NaN."""
    tlat, tlon = target_axes(grid)
    d = grid["res_deg"]
    ii = np.floor((src_lat - grid["south"]) / d + 0.5).astype(int)
    jj = np.floor((src_lon - grid["west"]) / d + 0.5).astype(int)
    ok_i = (ii >= 0) & (ii < len(tlat))
    ok_j = (jj >= 0) & (jj < len(tlon))
    sums = np.zeros((len(tlat), len(tlon)))
    counts = np.zeros((len(tlat), len(tlon)), dtype=int)
    sub = elev[np.ix_(ok_i, ok_j)]
    valid = ~np.isnan(sub)
    flat_i = np.repeat(ii[ok_i], sub.shape[1])
    flat_j = np.tile(jj[ok_j], sub.shape[0])
    v = valid.ravel()
    np.add.at(sums, (flat_i[v], flat_j[v]), sub.ravel()[v])
    np.add.at(counts, (flat_i[v], flat_j[v]), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(counts > 0, sums / np.maximum(counts, 1), np.nan)
    return mean, counts


def write_grid(
    out_dir: Path,
    name: str,
    grid: dict,
    mean_elev: np.ndarray,
    counts: np.ndarray,
    provenance: dict,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    depth = np.where(np.isnan(mean_elev), NODATA, -mean_elev)
    tlat, tlon = target_axes(grid)
    with (out_dir / "bot.grd").open("w", encoding="utf-8") as f:
        for row in depth:  # IDLA=3: first record = southern row
            f.write(" ".join(f"{v:.1f}" for v in row) + "\n")
    wet = int((depth > 0).sum())
    empty = int((counts == 0).sum())
    meta = {
        "grid": name,
        **provenance,
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "lon0": grid["west"],
        "lat0": grid["south"],
        "nx": len(tlon),
        "ny": len(tlat),
        "dlon": grid["res_deg"],
        "dlat": grid["res_deg"],
        "idla": 3,
        "depth_convention": f"metres positive-down; land negative; no data {NODATA:g}",
        "aggregation": "block mean of source cell elevations inside each target cell",
        "source_cells_per_target_median": float(np.median(counts[counts > 0]))
        if wet
        else 0,
        "wet_cells": wet,
        "cells": int(depth.size),
        "empty_cells": empty,
    }
    (out_dir / "meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"  {name}: {len(tlon)}x{len(tlat)} @ {grid['res_deg']} deg, wet {wet}/{depth.size}, empty {empty}"
    )
    return {"name": name, "grid": grid, "depth": depth, "lat": tlat, "lon": tlon}


def depth_at(built: dict, lat: float, lon: float) -> float | None:
    g = built["grid"]
    if not (g["south"] <= lat <= g["north"] and g["west"] <= lon <= g["east"]):
        return None
    i = round((lat - g["south"]) / g["res_deg"])
    j = round((lon - g["west"]) / g["res_deg"])
    return float(built["depth"][i, j])


# --- output points -----------------------------------------------------------------------


def output_points(cfg: dict, grids: list[dict]) -> list[dict]:
    sel = cfg["spots"]
    spots = [
        s
        for s in load_spots(ROOT / "data" / "spots").values()
        if s.region == sel["region"]
        and sel.get("south", -90) <= s.lat <= sel.get("north", 90)
        and sel.get("west", -180) <= s.lon <= sel.get("east", 180)
    ]
    spots.sort(key=lambda s: (-s.lat, s.lon))
    handoff = float(cfg["handoff_depth_m"])
    rows = []
    for s in spots:
        prof = load_profile(s.id, ROOT / "data" / "spots" / "derived" / "bathy")
        if prof is None:
            print(f"  WARN {s.id}: no committed bathy profile - no output point")
            continue
        # Walk the spot's own ray on the FINEST built grid, not on the GEBCO profile: the
        # profile's 450 m cells put lunada-bay in 90 m of water at 0.25 km where the 1as
        # nest reads 5 m. The grid SWAN runs on is the one that says where 15 m is.
        pick = None
        for dist_km in np.arange(RAY_STEP_KM, RAY_MAX_KM + 1e-9, RAY_STEP_KM):
            lat, lon = destination(s.lat, s.lon, prof.bearing_seaward_deg, dist_km)
            holder, gdepth = finest_depth(grids, lat, lon)
            if gdepth is not None and gdepth >= handoff:
                pick = (lat, lon, float(dist_km), holder, gdepth)
                break
        if pick is None:
            print(
                f"  WARN {s.id}: no cell >= {handoff:g} m within {RAY_MAX_KM} km on the ray"
            )
            continue
        lat, lon, dist_km, holder, gdepth = pick
        prof_depth = next(
            (p.depth_m for p in prof.samples if p.dist_km >= dist_km), None
        )
        rows.append(
            {
                "spot": s.id,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "bearing_deg": prof.bearing_seaward_deg,
                "handoff_km": round(dist_km, 2),
                "grid": holder,
                "grid_depth_m": round(gdepth, 1),
                "profile_depth_m": prof_depth,
            }
        )
    return rows


RAY_STEP_KM = 0.1
RAY_MAX_KM = 18.0  # the committed profiles' reach
EARTH_R_KM = 6371.0088


def destination(
    lat: float, lon: float, bearing_deg: float, dist_km: float
) -> tuple[float, float]:
    la, lo, b = math.radians(lat), math.radians(lon), math.radians(bearing_deg)
    ad = dist_km / EARTH_R_KM
    la2 = math.asin(
        math.sin(la) * math.cos(ad) + math.cos(la) * math.sin(ad) * math.cos(b)
    )
    lo2 = lo + math.atan2(
        math.sin(b) * math.sin(ad) * math.cos(la),
        math.cos(ad) - math.sin(la) * math.sin(la2),
    )
    return math.degrees(la2), (math.degrees(lo2) + 540) % 360 - 180


def finest_depth(
    grids: list[dict], lat: float, lon: float
) -> tuple[str | None, float | None]:
    """Depth on the finest grid holding the point (nests first - the list is outer, then
    nests). None when no grid holds it."""
    for built in reversed(grids):
        gd = depth_at(built, lat, lon)
        if gd is not None:
            return built["name"], gd
    return None, None


# --- main ---------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("region", help="name of a YAML in tools/swan-grid/regions/")
    ap.add_argument("--refetch", action="store_true", help="ignore cached source cuts")
    args = ap.parse_args()

    cfg = load_region(args.region)
    out_root = ROOT / "data" / "swan" / cfg["region"]
    src_dir = out_root / "src"
    source = cfg["source"]
    print(f"{cfg['region']}: source {source['kind']}")

    grids: list[dict] = []
    for name, grid in [
        ("outer", cfg["outer"]),
        *((n["name"], n) for n in cfg.get("nests", [])),
    ]:
        if source["kind"] == "crm":
            dataset = grid["dataset"]
            # the box is in the name: a widened nest must not read the old cut
            box_tag = (
                f"{grid['south']:g}_{grid['north']:g}_{grid['west']:g}_{grid['east']:g}"
            )
            cache = src_dir / f"{name}_{dataset}_{box_tag}.nc"
            lat, lon, elev = fetch_crm(
                source["ncss"], dataset, grid, cache, refetch=args.refetch
            )
            prov = {
                "source": f"NCEI CRM {dataset} via THREDDS NCSS ({source['ncss']})",
                "source_cut": cache.name,
            }
        elif source["kind"] == "gebco-local":
            lat, lon, elev = read_gebco_local(grid)
            prov = {"source": "GEBCO 2024 via local grid (data/bathy/GEBCO_2024.nc)"}
        else:
            raise SystemExit(f"unknown source kind {source['kind']!r}")
        mean, counts = block_average(lat, lon, elev, grid)
        grids.append(write_grid(out_root / name, name, grid, mean, counts, prov))

    rows = output_points(cfg, grids)
    with (out_root / "points.loc").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{r['lon']:.5f} {r['lat']:.5f}\n")
    (out_root / "points.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    km = sorted(r["handoff_km"] for r in rows)
    in_nest = sum(1 for r in rows if r["grid"] != "outer")
    print(
        f"  output points: {len(rows)} spots ({in_nest} inside a nest), handoff at "
        f"{cfg['handoff_depth_m']:g} m reached {km[0]:g}-{km[-1]:g} km out (median {km[len(km) // 2]:g})"
        if rows
        else "  output points: none"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
