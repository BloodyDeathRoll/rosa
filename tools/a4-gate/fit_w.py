"""A4 re-fit of blend.W_GFS per lead. Shipped lead_time_scorecard both halves; only the
weight varies. Fit on one half of the runs (by calendar-day parity), score on the other."""
import json
import sys
from datetime import datetime
from pathlib import Path
from rosa_pipeline import blend
from rosa_pipeline.archive import FileArchiveStore
from rosa_pipeline.buoys import load_all_buoys
from rosa_pipeline.verify import ECMWF_VARIABLES, LEAD_BUCKETS, lead_time_scorecard
from rosa_pipeline.cli import ARCHIVE_DIR, CMEMSSource, NDBCSource

FLEET = "46042 46026 46022 46059 46218 46225 41008 41013 44013 51201 51202 51205 Faro-coast-buoy Leixoes-coast-buoy Sines-coast-buoy".split()
WS = [round(0.05 * i, 2) for i in range(21)]
buoys = load_all_buoys(Path("data/buoys"))
store = FileArchiveStore(ARCHIVE_DIR)

def rows_at(g_rows, e_rows, w):
    ec = {(r["run"], r["valid"]): r for r in e_rows if isinstance(r, dict) and r.get("run") and r.get("valid")}
    out = []
    for g in g_rows:
        e = ec.get((g.get("run"), g.get("valid"))) if isinstance(g, dict) else None
        if e is None: continue
        out.append({"run": g["run"], "valid": g["valid"],
                    "hs": blend._wavg(g.get("hs"), e.get("hs"), w),
                    "tp": blend._wavg(g.get("tp"), e.get("tp"), w),
                    "dir": blend._circ(g.get("dir"), e.get("dir"), w)})
    return out

def half(rows, parity):
    return [r for r in rows if datetime.fromisoformat(r["run"]).timetuple().tm_yday % 2 == parity]

# acc[parity][w][lead][var] = [n, n*mae]
acc = {p: {w: {} for w in WS} for p in (0, 1)}
for bid in FLEET:
    b = buoys[bid]
    obs = (CMEMSSource(capture_dir=None) if b.source == "cmems" else NDBCSource(capture_dir=None)).fetch(b)
    g, e = store.read(bid + ".gfswave"), store.read(bid + ".ecmwf")
    for w in WS:
        rows = rows_at(g, e, w)
        for p in (0, 1):
            card = lead_time_scorecard(half(rows, p), obs, variables=ECMWF_VARIABLES)
            for lead, vs in card.items():
                for key, s in vs.items():
                    if s is None or not s.n: continue
                    a = acc[p][w].setdefault(lead, {}).setdefault(key, [0, 0.0])
                    a[0] += s.n; a[1] += s.n * s.mae
    print("done", bid, len(obs), file=sys.stderr)

def mae(p, w, lead, key):
    a = acc[p][w].get(lead, {}).get(key)
    return (a[1] / a[0], a[0]) if a else (None, 0)

keys = sorted({k for p in acc for w in WS for l in acc[p][w] for k in acc[p][w][l]})
print("keys", keys)
hs = [k for k in keys if "hs" in k.lower() or "height" in k.lower()][0]
for fit, test in ((0, 1), (1, 0)):
    print(f"\nfit on parity {fit}, holdout parity {test}  [{hs}]")
    print("lead   w*   fit@w*  fit@.5 | hold@w*  hold@.5  gain   n_hold")
    for lead, *_ in LEAD_BUCKETS:
        c = [(mae(fit, w, lead, hs)[0], w) for w in WS if mae(fit, w, lead, hs)[0] is not None]
        if not c: continue
        m, w = min(c)
        hw, n = mae(test, w, lead, hs); h5, _ = mae(test, 0.5, lead, hs)
        print(f"{lead:5} {w:4.2f}  {m:.4f}  {mae(fit,0.5,lead,hs)[0]:.4f} | {hw:.4f}   {h5:.4f}  {h5-hw:+.4f}  {n}")
print("\nfull-archive Hs MAE by w (both halves pooled)")
print("lead  " + " ".join(f"{w:5.2f}" for w in WS[::2]))
for lead, *_ in LEAD_BUCKETS:
    vals = []
    for w in WS[::2]:
        n = s = 0
        for p in (0, 1):
            a = acc[p][w].get(lead, {}).get(hs)
            if a: n += a[0]; s += a[1]
        vals.append(s / n if n else float("nan"))
    print(f"{lead:5} " + " ".join(f"{v:5.3f}" for v in vals))
json.dump({str(p): {str(w): acc[p][w] for w in WS} for p in acc}, open(Path.home() / "a4/fit_w.json", "w"))
