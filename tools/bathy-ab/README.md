# bathy A/B

Scripts behind `docs/CALIBRATION.md` 2026-09-09 - the gebco2020-API vs local-GEBCO-2024
source swap (OPEN-ITEMS 17/23). Run from the repo root under the pipeline venv:

```
rosa-pipeline bathy --all --source local --out /tmp/bathy-local   # ~3 s, cuts nothing committed
uv run --project pipeline python tools/bathy-ab/compare_bathy.py /tmp/bathy-local  # geometry
uv run --project pipeline python tools/bathy-ab/ab_height.py     /tmp/bathy-local  # same-input heights
uv run --project pipeline python tools/bathy-ab/zeros.py         /tmp/bathy-local  # who goes flat
rosa-pipeline experiment --bathy-dir /tmp/bathy-local                              # the eye frames
```

`ab_height.py` holds weather fixed by construction - the same three synthetic seas down each
spot's own window centre through both cuts - so it is a same-input A/B over all 1408 spots
without a fetch. Re-run all four after any change to `BOTTOM_FRICTION_CB`: the grid and the
friction coefficient are coupled (see the CALIBRATION entry).
