# A4 gate

Scripts behind `docs/CALIBRATION.md` 2026-09-17 (the 8-week archive-maturity gate, plan A4 in
`docs/rosa-fetch-plane-plan.md`). The first two need the VM's buoy archive; run from the repo root.

```
for s in om gfswave ecmwf blend; do
  uv run --project pipeline rosa-pipeline verify --archive --all-buoys --source $s > ~/a4/$s.txt
done                                   # never --write-skill here
python3 tools/a4-gate/pool.py          # in the dir holding the four .txt: pooled + per-region cards
uv run --project pipeline python tools/a4-gate/fit_w.py    # blend weight grid, fit/holdout by run-day parity
uv run --project pipeline python tools/a4-gate/dref_ab.py  # OPEN-ITEMS 15, workstation, no fetch
```

`pool.py` pools the PRINTED cards (2-decimal MAE per buoy); `fit_w.py` calls the shipped
`verify.lead_time_scorecard` directly and only varies the weight handed to `blend._wavg/_circ`.
Both score the 15 buoys that carry a full 8 weeks - the 21 Bight buoys registered 2026-09-14 are
left out.
