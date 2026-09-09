# coastal wind bias

Behind `docs/CALIBRATION.md` 2026-09-09 (OPEN-ITEMS 25). Fits the three corrections that
item names and scores each on held-out hours:

```
rosa-pipeline verify --stations --archive --bias-profile      # the measurement + pooled fit
uv run --project pipeline python tools/wind-bias/fit_variants.py   # all three candidates
```

Both need the station archive (`data/verify/stations/`, VM-local and gitignored - rsync it
from rosa-arm first) and reach METAR live for the observations.

The answer as of 2026-09-09 is that none of them ships: the diurnal term is real but buys
0.5%, and the per-station constant buys 12% by fitting each airfield's shelter, which is the
wrong thing to carry to a beach. Read the CALIBRATION entry before re-running.
