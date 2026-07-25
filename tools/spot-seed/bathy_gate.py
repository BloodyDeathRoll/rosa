#!/usr/bin/env python3
"""Bathymetry gate - prunes generated coastline candidates using seabed depth.

Coastline generation (coast_generate.py) over-produces: harbor walls, river
mouths, enclosed lagoons, and normals that point inland all survive the pure
geometric pass. This gate samples a seaward depth transect (GEBCO 2020 via
OpenTopoData) at each candidate and drops the ones the seabed says can't hold a
rideable break:

  - land on the seaward ray within 3 km  -> enclosed bay / harbor / wrong-facing
  - no water depth at all (all land)      -> normal points inland
  - stays < 2 m out to 3 km               -> mudflat / lagoon

CAVEAT: GEBCO 2020 is ~450 m resolution and unreliable in the first ~500 m, so
this gate uses the 1-3 km SHELF band + land detection, not fine near-shore slope.
A higher-res source (EMODnet in EU, national LIDAR) would sharpen it - that's the
production upgrade. The gate is deliberately conservative: it must not drop real
spots (validated against the 40 hand-verified Israel spots below).

Usage: python tools/spot-seed/bathy_gate.py
"""
from __future__ import annotations
import json, math, sys, time, urllib.request, urllib.parse
from pathlib import Path

GEBCO_URL = "https://api.opentopodata.org/v1/gebco2020"
ROOT = Path(__file__).resolve().parents[2]
CAND = Path(__file__).resolve().parent / "candidates" / "israel-generated.json"
BATHY_DIR = ROOT / "data" / "spots" / "derived" / "bathy"
YAML = ROOT / "data" / "spots" / "israel.yaml"
XSECT_KM = [0.25, 0.5, 1.0, 2.0, 3.0]
SHELF_MIN_KM = 1.0            # trust depths only from here out (GEBCO near-shore noise)


def destination(lat, lon, bearing_deg, dist_km):
    R = 6371.0
    d = dist_km / R
    br = math.radians(bearing_deg)
    la1, lo1 = math.radians(lat), math.radians(lon)
    la2 = math.asin(math.sin(la1)*math.cos(d) + math.cos(la1)*math.sin(d)*math.cos(br))
    lo2 = lo1 + math.atan2(math.sin(br)*math.sin(d)*math.cos(la1),
                           math.cos(d) - math.sin(la1)*math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def gebco_elevations(points):
    """Batched GEBCO elevation (m, negative = underwater). 100/req, 1 req/s, backoff."""
    out = []
    for i in range(0, len(points), 100):
        batch = points[i:i+100]
        locs = "|".join(f"{la:.5f},{lo:.5f}" for la, lo in batch)
        for attempt in range(4):
            try:
                url = GEBCO_URL + "?" + urllib.parse.urlencode({"locations": locs})
                req = urllib.request.Request(url, headers={"User-Agent": "rosa-bathy-gate/0.1"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    res = json.load(r)["results"]
                out.extend(x["elevation"] for x in res)
                break
            except Exception as ex:
                if attempt == 3:
                    print(f"  gebco batch failed: {ex}", file=sys.stderr)
                    out.extend([None]*len(batch))
                else:
                    time.sleep(2*(attempt+1))
        time.sleep(1.1)  # respect 1 req/s public limit
        print(f"  ...bathy {min(i+100, len(points))}/{len(points)}", file=sys.stderr)
    return out


def classify(shelf_elevs):
    """shelf_elevs: elevations (m, neg=water) at >=1 km. Returns (keep, reason)."""
    vals = [e for e in shelf_elevs if e is not None]
    if not vals:
        return False, "no-data"
    if any(e > 0 for e in vals):
        return False, "land on seaward ray (enclosed / backing / inland)"
    depths = [-e for e in vals]
    if max(depths) < 2.0:
        return False, "too shallow to 3 km (mudflat / lagoon)"
    return True, "open shelf"


def gate_candidates(cands):
    # build all transect points, fetch once
    pts, spans = [], []
    for c in cands:
        ray = [destination(c["lat"], c["lon"], c["seaward"], d) for d in XSECT_KM]
        spans.append((len(pts), len(pts)+len(ray)))
        pts.extend(ray)
    print(f"fetching GEBCO for {len(pts)} transect points "
          f"({len(cands)} candidates x {len(XSECT_KM)}) ...", file=sys.stderr)
    elev = gebco_elevations(pts)
    kept, reasons = [], {}
    for c, (a, b) in zip(cands, spans):
        ev = elev[a:b]
        shelf = [ev[i] for i, d in enumerate(XSECT_KM) if d >= SHELF_MIN_KM]
        ok, why = classify(shelf)
        reasons[why] = reasons.get(why, 0) + 1
        if ok:
            c["depth_shelf_m"] = [round(-e) if e is not None else None for e in shelf]
            kept.append(c)
    return kept, reasons


def recall_on_known():
    """Run the SAME classifier on the 40 hand-verified Israel spots' committed
    GEBCO profiles. The gate is only safe if it keeps (nearly) all of them."""
    ids = []
    text = YAML.read_text(encoding="utf-8")
    import re
    for m in re.finditer(r"\bid:\s*([a-z0-9-]+)", text):
        ids.append(m.group(1))
    passed, failed, missing = 0, [], 0
    for sid in ids:
        p = BATHY_DIR / f"{sid}.json"
        if not p.exists():
            missing += 1
            continue
        prof = json.loads(p.read_text())
        # committed samples store positive depth_m; convert to elevation for the classifier
        shelf = [-s["depth_m"] for s in prof["samples"]
                 if s["dist_km"] >= SHELF_MIN_KM and s.get("depth_m") is not None]
        ok, why = classify(shelf)
        if ok:
            passed += 1
        else:
            failed.append((sid, why))
    return len(ids), passed, failed, missing


def main():
    cands = json.load(open(CAND))["candidates"]
    print(f"loaded {len(cands)} geometric candidates from {CAND.name}\n", file=sys.stderr)

    total, passed, failed, missing = recall_on_known()
    print("=== recall check: gate vs the 40 hand-verified Israel spots ===")
    print(f"  spots with committed profile : {total-missing}/{total}")
    print(f"  KEPT by the bathy gate       : {passed}/{total-missing}"
          f"  ({100*passed//max(total-missing,1)}%)")
    if failed:
        print(f"  wrongly dropped              : {[f[0] for f in failed]}")

    kept, reasons = gate_candidates(cands)
    print("\n=== bathy gate on generated candidates ===")
    for why, n in sorted(reasons.items(), key=lambda x: -x[1]):
        mark = "KEEP" if why == "open shelf" else "drop"
        print(f"  [{mark}] {why:48} {n}")
    print(f"\n  {len(cands)} candidates -> {len(kept)} pass the bathy gate")

    outp = Path(__file__).resolve().parent / "candidates" / "israel-bathy-passed.json"
    json.dump({"kept": kept, "reasons": reasons}, open(outp, "w"), indent=1)
    print(f"  survivors -> {outp}")


if __name__ == "__main__":
    main()
