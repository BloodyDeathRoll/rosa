"""OPEN-ITEMS 25 step 3: which coastal-wind correction actually pays, out of sample.

Three candidates the item names, each fitted on the earlier two thirds of each station's
paired hours and scored on the later third. Pairing is the shipped harness's
(`verify._station_pairs`), so these are the same compared hours the scorecard grades.
"""
import statistics as st
from pathlib import Path

from rosa_pipeline.observe import MetarSource
from rosa_pipeline.stations import load_stations
from rosa_pipeline.archive import FileArchiveStore
from rosa_pipeline.verify import BIAS_PROFILE_MAX_LEAD_H, _station_pairs

MIN_SLOT = 40
store = FileArchiveStore(Path("data/verify/stations"))
stations = load_stations(Path("data/stations"))
src = MetarSource()

per_station = {}
for sid, stn in sorted(stations.items()):
    rows = store.read(sid)
    if not rows:
        continue
    try:
        obs = src.fetch(stn)
    except Exception:
        continue
    pairs = _station_pairs(rows, obs, lon=stn.lon, tol_min=30,
                           max_lead_h=BIAS_PROFILE_MAX_LEAD_H)
    if len(pairs) >= 120:
        per_station[sid] = pairs
print(f"{len(per_station)} stations, {sum(len(p) for p in per_station.values())} paired hours")

def split(pairs):
    cut = pairs[int(len(pairs) * 0.67)][0]
    return [p for p in pairs if p[0] < cut], [p for p in pairs if p[0] >= cut]

train_all, test_all = [], []
splits = {}
for sid, pairs in per_station.items():
    tr, te = split(sorted(pairs))
    if not tr or not te:
        continue
    splits[sid] = (tr, te)
    train_all += tr
    test_all += te

def mae(diffs):
    return sum(abs(d) for d in diffs) / len(diffs)

def bias(diffs):
    return sum(diffs) / len(diffs)

base = [m - o for _v, _h, m, o in test_all]
print(f"\nuncorrected            mae {mae(base):.4f}  bias {bias(base):+.4f}  n {len(base)}")

# (a) pooled diurnal - one 24-slot table for the whole fleet
by_hour = {}
for _v, h, m, o in train_all:
    by_hour.setdefault(h, []).append(m - o)
overall = st.fmean([d for ds in by_hour.values() for d in ds])
pooled = {h: (st.fmean(ds) if len(ds) >= MIN_SLOT else overall) for h, ds in by_hour.items()}
a = [(m - pooled.get(h, overall)) - o for _v, h, m, o in test_all]
print(f"pooled diurnal         mae {mae(a):.4f}  bias {bias(a):+.4f}"
      f"   {100*(mae(a)-mae(base))/mae(base):+.2f}%")

# (b) per-station constant
b = []
for sid, (tr, te) in splits.items():
    c = st.fmean([m - o for _v, _h, m, o in tr])
    b += [(m - c) - o for _v, _h, m, o in te]
print(f"per-station constant   mae {mae(b):.4f}  bias {bias(b):+.4f}"
      f"   {100*(mae(b)-mae(base))/mae(base):+.2f}%")

# (c) per-station diurnal, falling back to that station's constant in thin slots
c_all = []
for sid, (tr, te) in splits.items():
    const = st.fmean([m - o for _v, _h, m, o in tr])
    hrs = {}
    for _v, h, m, o in tr:
        hrs.setdefault(h, []).append(m - o)
    tbl = {h: (st.fmean(ds) if len(ds) >= MIN_SLOT else const) for h, ds in hrs.items()}
    c_all += [(m - tbl.get(h, const)) - o for _v, h, m, o in te]
print(f"per-station diurnal    mae {mae(c_all):.4f}  bias {bias(c_all):+.4f}"
      f"   {100*(mae(c_all)-mae(base))/mae(base):+.2f}%")

# Which way would the per-station correction push the published wind? A sheltered
# inland airfield reads light, so its fitted bias is positive and the correction
# SUBTRACTS wind - at a beach that is the wrong direction, and it is the same
# direction as the lightness OPEN-ITEMS 25 exists to explain.
consts = {sid: st.fmean([m - o for _v, _h, m, o in tr]) for sid, (tr, _te) in splits.items()}
vals = sorted(consts.values())
pos = [v for v in vals if v > 0]
print(f"\nper-station constants: n {len(vals)}  median {st.median(vals):+.2f} m/s"
      f"  p10 {vals[len(vals)//10]:+.2f}  p90 {vals[9*len(vals)//10]:+.2f}")
print(f"  stations where the model reads HOT (correction removes wind): {len(pos)} of {len(vals)}"
      f"  ({100*len(pos)/len(vals):.0f}%)")
print(f"  mean magnitude {st.fmean(abs(v) for v in vals):.2f} m/s")
