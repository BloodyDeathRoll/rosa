"""EOT20 tide constants: extraction geometry, synthesis, and DB integrity (plan C1).

Synthesis tests run from the COMMITTED per-spot constants - no grids, no network.
Extraction tests build a tiny synthetic EOT20-shaped grid in tmp_path with h5py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rosa_pipeline import tide
from rosa_pipeline.spots import load_spots

TIDE_DIR = Path(__file__).resolve().parents[2] / "data" / "spots" / "derived" / "tide"
SPOTS_DIR = Path(__file__).resolve().parents[2] / "data" / "spots"


def test_committed_constants_match_the_spot_db() -> None:
    # the bathy-profile rule: one constants file per spot, no gaps and no orphans
    spots = set(load_spots(SPOTS_DIR))
    files = {p.stem for p in TIDE_DIR.glob("*.json")}
    assert files == spots, (
        f"missing: {sorted(spots - files)[:5]} orphans: {sorted(files - spots)[:5]}"
    )


def test_committed_constants_are_sane() -> None:
    for path in TIDE_DIR.glob("*.json"):
        c = tide.load_constants(TIDE_DIR, path.stem)
        assert c is not None
        assert set(c.coeffs) == set(tide.CONSTITUENTS)
        amp = tide.amplitude_m(c)
        # sum of constituent amplitudes: Med microtidal ~0.3, macro coasts ~3;
        # 0 means a land cell slipped through, >6 m is nowhere we surf
        assert 0.05 < amp < 6.0, f"{path.stem}: sum-amp {amp:.2f} m out of range"


def test_predict_is_periodic_and_bounded() -> None:
    c = tide.load_constants(TIDE_DIR, "beit-yanai")
    assert c is not None
    t0 = datetime(2026, 8, 14, tzinfo=UTC)
    times = [t0 + timedelta(hours=h / 4) for h in range(4 * 24 * 30)]  # 30 days, 15-min
    heights = tide.predict(c, times)
    bound = tide.amplitude_m(c)
    assert all(abs(h) <= bound + 1e-6 for h in heights)
    # a month of Med tide must actually oscillate, roughly the OM-observed range
    assert 0.2 < max(heights) - min(heights) < 2 * bound


def test_predict_matches_the_m2_clock() -> None:
    # the dominant Med constituent is M2 (12.42 h): the autocorrelation of a
    # multi-day series at one M2 period must be strongly positive - a wrong
    # astronomical argument or nodal convention destroys this immediately
    import statistics

    c = tide.load_constants(TIDE_DIR, "beit-yanai")
    t0 = datetime(2026, 8, 1, tzinfo=UTC)
    step_s = 745.2  # 1/60th of an M2 period
    times = [t0 + timedelta(seconds=step_s * i) for i in range(60 * 8)]  # 8 M2 cycles
    h = tide.predict(c, times)
    lag = 60  # one full M2 period
    corr = statistics.correlation(h[:-lag], h[lag:])
    assert corr > 0.85, f"series does not repeat at the M2 period (corr {corr:.2f})"


def test_save_load_round_trip(tmp_path: Path) -> None:
    c = tide.TideConstants(
        spot_id="x",
        origin=(32.0, 34.5),
        sample=(32.0, 34.5),
        method="bilinear",
        coeffs={k: (0.01, -0.02) for k in tide.CONSTITUENTS},
    )
    tide.save_constants(c, tmp_path)
    back = tide.load_constants(tmp_path, "x")
    assert back == c
    assert tide.load_constants(tmp_path, "missing") is None


def _write_grid(path: Path, lats, lons, amp, phase) -> None:
    import h5py
    import numpy as np

    amp = np.asarray(amp, dtype=float)
    phase = np.asarray(phase, dtype=float)
    with h5py.File(path, "w") as f:
        f["lat"], f["lon"] = np.asarray(lats, float), np.asarray(lons, float)
        f["amplitude"], f["phase"] = amp, phase
        f["real"] = amp * np.cos(np.radians(phase))
        f["imag"] = amp * np.sin(np.radians(phase))


@pytest.fixture()
def fake_grids(tmp_path: Path) -> Path:
    # 4x4 cells at 0.125 deg: west column dry (amp 0 = the EOT20 land fill), rest wet
    lats = [32.000, 32.125, 32.250, 32.375]
    lons = [34.500, 34.625, 34.750, 34.875]
    amp = [[0.0, 20.0, 20.0, 20.0]] * 4
    phase = [[0.0, 45.0, 45.0, 45.0]] * 4
    for name in tide.CONSTITUENTS:
        _write_grid(tmp_path / f"{name.upper()}_ocean_eot20.nc", lats, lons, amp, phase)
    return tmp_path


def test_extraction_bilinear_in_open_water(fake_grids: Path) -> None:
    c = tide.extract_constants("s", (32.19, 34.81), fake_grids)
    assert c.method == "bilinear"
    assert c.sample == (32.19, 34.81)
    re, im = c.coeffs["m2"]
    assert re == pytest.approx(0.20 * 0.7071, rel=1e-3)  # 20 cm at 45 deg -> m
    assert im == pytest.approx(0.20 * 0.7071, rel=1e-3)


def test_extraction_falls_back_to_nearest_wet(fake_grids: Path) -> None:
    # aim between the dry west column and the wet second column
    c = tide.extract_constants("s", (32.19, 34.51), fake_grids)
    assert c.method == "nearest"
    assert c.sample[1] == pytest.approx(34.625)  # snapped east to the wet column
    assert c.coeffs["m2"][0] == pytest.approx(0.20 * 0.7071, rel=1e-3)


def test_extraction_refuses_dry_land(tmp_path: Path) -> None:
    lats = [32.000, 32.125]
    lons = [34.500, 34.625]
    for name in tide.CONSTITUENTS:
        _write_grid(
            tmp_path / f"{name.upper()}_ocean_eot20.nc",
            lats,
            lons,
            [[0.0, 0.0]] * 2,
            [[0.0, 0.0]] * 2,
        )
    with pytest.raises(ValueError, match="dry land"):
        tide.extract_constants("s", (32.06, 34.56), tmp_path)
