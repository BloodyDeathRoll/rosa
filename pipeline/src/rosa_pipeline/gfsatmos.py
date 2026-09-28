"""The GFS 0.25 deg ATMOSPHERIC grib-filter URL - what the SWAN wind field is fetched with.

This module was the plan C3b A/B member (2026-09-12 to 2026-09-26): a paced NOMADS fetcher
that archived the raw GFS 10 m wind at every registered wind station each cycle under the
``.gfs_grib`` key, beside Open-Meteo's ``gfs_seamless``. That A/B lost to Open-Meteo at the
stations (docs/CALIBRATION.md 2026-09-26) and the member was dropped from the archive step,
so the fetcher, its pacer and its GRIB parser went with it on 2026-09-28 - nothing called
them. ``verify --stations --wind-model gfs_grib`` still scores the rows already archived;
it reads ``<station>.gfs_grib.jsonl`` and never imports this module.

What stays is the request shape, live-verified 2026-09-12: ``filter_gfs_0p25_1hr.pl``,
``pgrb2.0p25`` files, UGRD/VGRD at 10 m above ground, subregion by box (a 4x3 deg box is
~1.3 KB a step; f000-f120 hourly then 3-hourly to f384). ``run swan`` (cli._cmd_swan) fetches
one of these per step for the region box and hands the bytes to ``swan.parse_wind_grid``.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from .gfswave import Box

FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25_1hr.pl"


def filter_url(cycle: datetime, step: int, box: Box) -> str:
    d = quote(f"/gfs.{cycle:%Y%m%d}/{cycle:%H}/atmos", safe="")
    f = f"gfs.t{cycle:%H}z.pgrb2.0p25.f{step:03d}"
    return (
        f"{FILTER_URL}?dir={d}&file={f}&var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on"
        f"&subregion=&toplat={box.top:g}&leftlon={box.left:g}"
        f"&rightlon={box.right:g}&bottomlat={box.bottom:g}"
    )
