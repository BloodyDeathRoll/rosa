"""Same-input A/B of the GRIB wave samplers: which grid node does each spot read?

Node choice depends on the model's land mask and the sampler's metric, not on the
weather, so one global significant-height field per model is enough to see every spot
that would change node under a candidate sampler - and by how much the sampled height
moves on that field. The GRIB path costs no Open-Meteo quota (~1 MB per model).

    fetch  <grids>                      download one global swh field per model (f000)
    sample <grids> <out.json> [--no-aim] run the SHIPPED samplers over every spot's
                                        offshore point; --no-aim drops Spot.shore_normal
    diff   <base.json> <cand.json>      footprint: rescued / lost / moved, with spot ids

An A/B is `sample` on the base commit (a `git worktree` with PYTHONPATH pointing at it)
and on the candidate, then `diff`. CALIBRATION.md 2026-09-11 is the first use.
"""

from __future__ import annotations

import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

SPOTS_DIR = Path("data/spots")


def _key(p: tuple[float, float]) -> str:
    return f"{p[0]:.4f},{p[1]:.4f}"


def fetch(grids: Path) -> None:
    import httpx

    from rosa_pipeline import ecmwf, gfswave

    grids.mkdir(parents=True, exist_ok=True)
    cyc = gfswave.pick_cycle(datetime.now(UTC))
    d = quote(f"/gfs.{cyc:%Y%m%d}/{cyc:%H}/wave/gridded", safe="")
    f = f"gfswave.t{cyc:%H}z.global.{gfswave.RESOLUTION}.f000.grib2"
    url = (
        f"{gfswave.FILTER_URL}?dir={d}&file={f}&var_HTSGW=on&subregion="
        "&toplat=90&leftlon=0&rightlon=360&bottomlat=-90"
    )
    g = httpx.get(url, timeout=120).content
    assert gfswave._is_grib(g), "NOMADS answered with an error page"
    (grids / "gfs_swh_f000.grib2").write_bytes(g)
    ec = ecmwf.pick_cycle(datetime.now(UTC))
    ix = httpx.get(ecmwf.index_url(ec, 0), timeout=60, follow_redirects=True).text
    ((off, ln),) = ecmwf.parse_index(ix, ("swh",))
    e = httpx.get(
        ecmwf.data_url(ec, 0),
        headers={"Range": f"bytes={off}-{off + ln - 1}"},
        timeout=120,
        follow_redirects=True,
    ).content
    assert e[:4] == b"GRIB"
    (grids / "ecmwf_swh_f000.grib2").write_bytes(e)
    (grids / "cycles.txt").write_text(
        f"gfswave {cyc.isoformat()}\necmwf {ec.isoformat()}\n"
    )
    print(
        f"gfswave {cyc:%Y-%m-%d %Hz} {len(g) // 1024} KB | ecmwf {ec:%Y-%m-%d %Hz} {len(e) // 1024} KB"
    )


def sample(grids: Path, out: Path, aim: bool) -> None:
    from rosa_pipeline import blend, ecmwf, gfswave, spots
    from rosa_pipeline.geo import Seaward

    all_spots = spots.load_spots(SPOTS_DIR)
    groups: dict[tuple[float, float], list] = {}
    for s in all_spots.values():
        groups.setdefault(s.offshore_point, []).append(s)
    pts = list(groups)
    aims = (
        {p: Seaward(g[0].lat, g[0].lon, g[0].shore_normal) for p, g in groups.items()}
        if aim
        else None
    )
    valid = datetime.now(UTC)
    gfs = (grids / "gfs_swh_f000.grib2").read_bytes()
    ec = (grids / "ecmwf_swh_f000.grib2").read_bytes()
    kw = {"aims": aims} if aims is not None else {}
    g = gfswave.parse_grib_points(gfs, pts, valid, **kw)
    b = blend.parse_gfs_full(gfs, pts, valid, **kw)
    e = ecmwf.parse_grib_points(ec, pts, valid, params=("swh",), **kw)
    res = {
        _key(p): {
            "gfs": None if wp is None else wp.hs,
            "blend": None if gs is None else gs.fields.get("swh"),
            "ecmwf": None if ss is None else ss.swh,
        }
        for p, wp, gs, ss in zip(pts, g, b, e, strict=True)
    }
    out.write_text(json.dumps(res))
    print(
        f"{len(all_spots)} spots, {len(pts)} points, aim={'on' if aim else 'off'} -> {out}"
    )


def diff(base: Path, cand: Path) -> None:
    from rosa_pipeline import spots

    old = json.loads(base.read_text())
    new = json.loads(cand.read_text())
    by_pt: dict[str, list] = {}
    for s in spots.load_spots(SPOTS_DIR).values():
        by_pt.setdefault(_key(s.offshore_point), []).append(s)

    def ids(k: str) -> str:
        return ",".join(f"{s.id}({s.lat:.1f})" for s in by_pt.get(k, []))

    def n_spots(keys) -> int:
        return sum(len(by_pt.get(k, [])) for k in keys)

    for arm in ("gfs", "blend", "ecmwf"):
        rescued, lost, moved, same = [], [], [], 0
        for k in old:
            a, b = old[k][arm], new.get(k, {}).get(arm)
            if a is None and b is None:
                same += 1
            elif a is None:
                rescued.append((k, b))
            elif b is None:
                lost.append((k, a))
            elif abs(a - b) > 1e-9:
                moved.append((k, a, b))
            else:
                same += 1
        none_old = sum(1 for k in old if old[k][arm] is None)
        none_new = sum(1 for k in new if new[k][arm] is None)
        print(
            f"\n== {arm}: points {len(old)} | refused before {none_old} after {none_new}"
        )
        print(
            f"   unchanged {same} | rescued {len(rescued)} | lost {len(lost)} | moved {len(moved)}"
            f" (spots: {n_spots(k for k, *_ in rescued)} / {n_spots(k for k, *_ in lost)}"
            f" / {n_spots(k for k, *_ in moved)})"
        )
        if moved:
            d = [b - a for _, a, b in moved]
            ad = sorted(abs(x) for x in d)
            print(
                f"   swh delta m: median {statistics.median(d):+.3f} | |d| median"
                f" {statistics.median(ad):.3f} p90 {ad[int(0.9 * (len(ad) - 1))]:.3f}"
                f" max {ad[-1]:.3f} | >0.10 m: {sum(1 for x in ad if x > 0.10)}"
                f" | >0.25 m: {sum(1 for x in ad if x > 0.25)}"
            )
            for k, a, b in sorted(moved, key=lambda t: -abs(t[2] - t[1]))[:10]:
                print(f"     {ids(k)}: {a:.2f} -> {b:.2f}")
        for k, b in rescued[:10]:
            print(f"   rescued {ids(k)} -> {b:.2f}")
        for k, a in lost[:10]:
            print(f"   LOST {ids(k)} was {a:.2f}")


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "fetch":
        fetch(Path(argv[1]))
    elif len(argv) >= 3 and argv[0] == "sample":
        sample(Path(argv[1]), Path(argv[2]), aim="--no-aim" not in argv[3:])
    elif len(argv) == 3 and argv[0] == "diff":
        diff(Path(argv[1]), Path(argv[2]))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
