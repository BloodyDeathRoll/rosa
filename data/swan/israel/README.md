# SWAN Israel grid (Stage-4 scaffolding)

Coarse regional bathymetry + a synthetic proof-run deck for SWAN 41.51 on `rosa-arm`.
Built 2026-07-26 while Stage 4 proper waits on Stage-3 boundary spectra
(docs/rosa-accuracy-roadmap.md - Stage 4 is forced at the boundary by Stage 3).

## Files
- `bot.grd` - GEBCO depths, 121x171 points @ 0.01 deg (~1 km), box 34.0-35.2E x
  31.5-33.2N. Metres positive-down, land negative, IDLA=3 (rows south to north).
  Rebuild: `uv run --project pipeline python tools/swan-grid/build_grid.py`
  (~207 OpenTopoData calls; GEBCO attribution as in pipeline/bathymetry.py).
- `points.loc` - one output point per Israeli spot, nudged 0.012 deg (~1.1 km)
  seaward so each lands in a wet cell of this coarse grid. Regenerated with the grid.
- `INPUT.synthetic` - stationary run, constant 1.5 m / 8 s / W JONSWAP west-boundary
  + 5 m/s W wind. A pipeline-shape proof, deliberately not a forecast.
- `meta.json` - bounds/resolution/provenance.

## Run (on rosa-arm)
```
scp bot.grd points.loc INPUT.synthetic ubuntu@<rosa-arm>:~/swan/israel/
ssh ubuntu@<rosa-arm> 'cd ~/swan/israel && cp INPUT.synthetic INPUT && OMP_NUM_THREADS=4 ~/bin/swan-omp.exe'
# results: spots.tab (XP YP DEP HSIGN TPS DIR per spot point); Errfile empty = clean
```

## Honest limits
- ~1 km cells cannot resolve the surf zone; this grid answers "does the regional
  propagation pipeline work", not "what breaks on the sandbar". Stage-4 accuracy
  comes from finer nests forced by real spectra, validated per region on Stage 0.
- The Kinneret / Dead Sea below-sea-level basins lie east of the grid edge (35.2E),
  so no inland cell reads as false sea. Verified at build time.
