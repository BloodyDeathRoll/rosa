"""rosa_pipeline.gfsatmos: the GFS 0.25 atmos grib-filter URL the SWAN wind field is
fetched with. The C3b station fetcher that once lived here was removed 2026-09-28 (its A/B
lost 2026-09-26); the captured gribs under fixtures/gfsatmos/ are test_swan.py's now."""

from __future__ import annotations

from datetime import UTC, datetime

from rosa_pipeline import gfsatmos
from rosa_pipeline.gfswave import Box

CYCLE = datetime(2026, 9, 12, 0, tzinfo=UTC)


def test_filter_url_names_the_atmos_dataset_and_only_the_10m_wind():
    url = gfsatmos.filter_url(CYCLE, 123, Box(bottom=30, top=34, left=33, right=36))
    assert url.startswith(gfsatmos.FILTER_URL)
    assert "gfs.20260912%2F00%2Fatmos" in url
    assert "file=gfs.t00z.pgrb2.0p25.f123" in url
    assert "var_UGRD=on&var_VGRD=on&lev_10_m_above_ground=on" in url
    assert "toplat=34&leftlon=33&rightlon=36&bottomlat=30" in url
