# ab-nodes - same-input A/B of the GRIB wave samplers

Which 0.25 deg grid node does each spot read from GFS-Wave and ECMWF, and does a
candidate sampler change it? Node choice depends on the land mask and the metric, not
the weather, so one global significant-height field per model settles it for all 1947
spots. No Open-Meteo quota is spent (the GRIB path, ~1 MB per model).

```sh
P=pipeline/.venv/bin/python
PYTHONPATH=pipeline/src $P tools/ab-nodes/ab_nodes.py fetch /tmp/grids
# base: the shipped samplers at some commit, in a worktree
git worktree add /tmp/base <commit>
PYTHONPATH=/tmp/base/pipeline/src $P tools/ab-nodes/ab_nodes.py sample /tmp/grids /tmp/base.json
# candidate: the working tree (add --no-aim to isolate the seaward rule)
PYTHONPATH=pipeline/src $P tools/ab-nodes/ab_nodes.py sample /tmp/grids /tmp/cand.json
PYTHONPATH=pipeline/src $P tools/ab-nodes/ab_nodes.py diff /tmp/base.json /tmp/cand.json
```

`diff` prints, per sampler: points refused before/after, rescued / lost / moved, the
sampled-height delta distribution over the moved spots, and the biggest movers by id.
To A/B the shoreline rule itself, edit `geo.SEAWARD_TOL_DEG` in the working tree (0 =
strict half-plane) and `sample` again.
First used for `docs/CALIBRATION.md` 2026-09-11 (ground-distance metric + seaward
preference, closing OPEN-ITEMS 27). The base commit of that A/B is `df1d72e`.
