"""Stage 3b acceptance harness - NDBC measured spectra: parsing, moments, derived
measures, the spread/consistency validation report, and the CLI wiring.

The fixtures are REAL realtime2 captures (buoy 51201 Waimea, 2026-07-23, first 6 hourly
rows of .data_spec and .swr1) - parsing and the report run fully offline against them."""

from __future__ import annotations

import math
import shutil
from datetime import UTC, datetime
from pathlib import Path

from rosa_pipeline.buoys import Buoy
from rosa_pipeline.spectra import (
    SpectrumObs,
    build_report,
    mean_direction,
    measure,
    moment,
    parse_spectra,
    render_report,
    spearman,
)

FIXTURES = Path(__file__).parent / "fixtures" / "spectra"
DATA_SPEC = (FIXTURES / "51201.data_spec").read_text(encoding="utf-8")
SWR1 = (FIXTURES / "51201.swr1").read_text(encoding="utf-8")

T0 = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)


# --- parsing (real capture) ---


def test_parse_spectra_joins_energy_and_r1() -> None:
    specs = parse_spectra(DATA_SPEC, SWR1, "51201")
    assert len(specs) == 6
    assert specs[0].time < specs[-1].time  # oldest-first
    newest = specs[-1]
    assert newest.time == T0
    assert list(newest.freqs) == sorted(newest.freqs)
    assert newest.sep_freq is None  # 9.999 = not computed
    # r1 aligned to the energy frequencies; peak-region r1 at Waimea is high (organized)
    assert len(newest.r1) == len(newest.freqs)
    peak_i = max(range(len(newest.energy)), key=lambda i: newest.energy[i])
    assert newest.r1[peak_i] is not None and 0.8 < newest.r1[peak_i] <= 1.0


def test_parse_spectra_without_swr1_leaves_r1_none() -> None:
    specs = parse_spectra(DATA_SPEC, "", "51201")
    assert all(r is None for r in specs[-1].r1)


# --- moments and measures (synthetic, exact) ---


def _synthetic(energies: dict[float, float], sep: float | None = None) -> SpectrumObs:
    freqs = tuple(sorted(energies))
    return SpectrumObs(
        station="x",
        time=T0,
        freqs=freqs,
        energy=tuple(energies[f] for f in freqs),
        r1=tuple(None for _ in freqs),
        sep_freq=sep,
    )


def test_moment_trapezoid() -> None:
    # constant E=2 over 0.1..0.3: m0 = 2*0.2 = 0.4
    spec = _synthetic({0.1: 2.0, 0.2: 2.0, 0.3: 2.0})
    assert abs(moment(spec.freqs, spec.energy, 0) - 0.4) < 1e-12


def test_measure_narrow_beats_broad_on_qp_and_consistency() -> None:
    # same m0, concentrated at 0.07 Hz (14 s groundswell) vs spread flat
    narrow = _synthetic({0.05: 0.0, 0.065: 2.0, 0.07: 30.0, 0.075: 2.0, 0.09: 0.0, 0.3: 0.0})
    broad = _synthetic({0.05: 1.5, 0.1: 1.5, 0.15: 1.5, 0.2: 1.5, 0.25: 1.5, 0.3: 1.5})
    mn, mb = measure(narrow), measure(broad)
    assert mn is not None and mb is not None
    assert mn.qp > mb.qp
    assert mn.consistency > mb.consistency
    assert abs(mn.tp_s - 1 / 0.07) < 1e-9


def test_measure_rejects_flat_sea() -> None:
    # Hs ~ 4*sqrt(m0) below the floor → unusable for validation
    assert measure(_synthetic({0.1: 0.001, 0.2: 0.001, 0.3: 0.001})) is None


def test_measure_sigma_from_r1() -> None:
    spec = _synthetic({0.06: 1.0, 0.07: 10.0, 0.08: 1.0})
    spec = SpectrumObs(
        station="x",
        time=T0,
        freqs=spec.freqs,
        energy=spec.energy,
        r1=(None, 0.94, None),
        sep_freq=None,
    )
    m = measure(spec)
    assert m is not None and m.sigma_peak_deg is not None
    assert abs(m.sigma_peak_deg - math.degrees(math.sqrt(2 * 0.06))) < 1e-9  # ~19.8 deg


def test_measure_windsea_classification() -> None:
    # with a separation frequency: peak above it = windsea
    windsea = _synthetic({0.15: 1.0, 0.2: 10.0, 0.25: 1.0}, sep=0.1)
    swell = _synthetic({0.05: 1.0, 0.07: 10.0, 0.09: 1.0}, sep=0.1)
    assert measure(windsea).windsea is True
    assert measure(swell).windsea is False
    # without one: the short-Tp heuristic (5 s peak = windsea, 14 s = swell)
    assert measure(_synthetic({0.15: 1.0, 0.2: 10.0, 0.25: 1.0})).windsea is True
    assert measure(_synthetic({0.05: 1.0, 0.07: 10.0, 0.09: 1.0})).windsea is False


# --- spearman ---


def test_spearman_monotonic_and_reversed() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert spearman([1, 2], [2, 1]) is None  # below n=3
    r = spearman([1.0, 1.0, 2.0, 3.0], [5.0, 6.0, 7.0, 8.0])  # ties get average ranks
    assert r is not None and 0.9 < r <= 1.0


# --- report on the real capture ---


def test_build_and_render_report() -> None:
    specs = parse_spectra(DATA_SPEC, SWR1, "51201")
    report = build_report(specs)
    assert report.n_hours == 6
    # 6 hours of the same Hawaiian summer sea - every class present has sane stats
    assert report.spread, "r1 present in fixture → spread stats expected"
    for s in report.spread:
        assert s.n > 0
        assert 0.0 < s.measured_mean_deg < 90.0
        assert s.mae_deg >= abs(s.bias_deg) - 1e-9
    buoy = Buoy(id="51201", name="Waimea Bay - Oahu, HI", lat=21.67, lon=-158.12, source="ndbc")
    text = render_report(buoy, report)
    assert "measured spectra vs Stage-3b assumptions" in text
    assert "directional spread" in text


# --- CLI wiring ---

BUOYS_YAML = """\
buoys:
  - id: "51201"
    name: "Waimea Bay - Oahu, HI"
    lat: 21.67
    lon: -158.12
    source: ndbc
"""


def test_cli_verify_spectra_offline(tmp_path, capsys) -> None:
    from rosa_pipeline.cli import main

    buoys_dir = tmp_path / "buoys"
    buoys_dir.mkdir()
    (buoys_dir / "test.yaml").write_text(BUOYS_YAML, encoding="utf-8")
    obs_dir = tmp_path / "obs"
    obs_dir.mkdir()
    shutil.copy(FIXTURES / "51201.data_spec", obs_dir / "51201.data_spec")
    shutil.copy(FIXTURES / "51201.swr1", obs_dir / "51201.swr1")

    rc = main(
        [
            "verify",
            "--buoy",
            "51201",
            "--spectra",
            "--buoys-dir",
            str(buoys_dir),
            "--obs-fixtures",
            str(obs_dir),
            "--isramar-dir",
            str(tmp_path / "no-isramar"),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "measured spectra vs Stage-3b assumptions - buoy 51201" in out
    assert "usable spectra: 6 hrs" in out


# --- measured MEAN wave direction from alpha1 + r1 (2026-10-08, OPEN-ITEMS 37b) ---
# Real capture: buoy 46042 Monterey, 2026-10-08 10:50-11:50Z, first 3 rows of .data_spec,
# .swr1 and .swdir. NDBC's own WVHT for those rows is 1.7 m and MWD (the PEAK) 258-270 deg.


def _spec46042() -> list[SpectrumObs]:
    def read(ext: str) -> str:
        return (FIXTURES / f"46042.{ext}").read_text(encoding="utf-8")

    return parse_spectra(read("data_spec"), read("swr1"), "46042", read("swdir"))


def _flat(alpha: list[float | None], r1: list[float | None], energy: list[float]) -> SpectrumObs:
    freqs = tuple(0.05 + 0.01 * i for i in range(len(energy)))
    return SpectrumObs(
        station="x",
        time=T0,
        freqs=freqs,
        energy=tuple(energy),
        r1=tuple(r1),
        sep_freq=None,
        alpha1=tuple(alpha),
    )


def test_parse_spectra_reads_alpha1_and_drops_ndbc_999() -> None:
    specs = _spec46042()
    assert len(specs) == 3
    newest = specs[-1]
    assert len(newest.alpha1) == len(newest.freqs)
    # the four lowest bins are 999.0 in the file (no energy there) - missing, not 999 deg
    assert newest.alpha1[:4] == (None, None, None, None)
    assert newest.alpha1[4] == 208.0


def test_real_spectrum_mean_direction_sits_between_swell_peak_and_wind_sea() -> None:
    """A bimodal sea: an 11 s swell from ~265 (NDBC's MWD, the peak) and a NW wind sea
    at the higher frequencies. The energy-weighted mean lands between them, ~296 deg -
    the peak-vs-mean offset 37(b) exists to stop scoring as a model bias."""
    ms = [measure(s) for s in _spec46042()]
    assert all(m is not None for m in ms)
    assert [round(m.hs_m, 1) for m in ms] == [1.7, 1.7, 1.6]  # = NDBC's WVHT
    assert [round(m.mean_dir_deg) for m in ms] == [297, 296, 297]


def test_mean_direction_of_a_one_direction_sea_is_that_direction() -> None:
    s = _flat([270.0] * 5, [0.8] * 5, [1.0, 2.0, 3.0, 2.0, 1.0])
    assert abs(mean_direction(s) - 270.0) < 1e-9


def test_mean_direction_wraps_through_north() -> None:
    s = _flat([350.0, 350.0, 10.0, 10.0], [0.9] * 4, [1.0, 1.0, 1.0, 1.0])
    d = mean_direction(s)
    assert min(d, 360.0 - d) < 1e-6  # 0, not 180


def test_mean_direction_weights_by_r1_not_energy_alone() -> None:
    """Equal energy from 270 (r1 0.9, a clean swell) and 180 (r1 0.1, spread wind sea).
    The first-moment mean leans hard to 270; an E-weighted circular mean of alpha1 would
    say 225 - the form mean_direction deliberately is not."""
    s = _flat([270.0, 270.0, 180.0, 180.0], [0.9, 0.9, 0.1, 0.1], [1.0, 1.0, 1.0, 1.0])
    assert 255.0 < mean_direction(s) < 265.0


def test_mean_direction_refuses_a_row_missing_its_energetic_bins() -> None:
    s = _flat([270.0, None, None, 270.0], [0.8] * 4, [0.1, 5.0, 5.0, 0.1])
    assert mean_direction(s) is None


def test_mean_direction_none_without_a_swdir_file() -> None:
    spec = parse_spectra(DATA_SPEC, SWR1, "51201")[-1]
    assert spec.alpha1 == ()
    m = measure(spec)
    assert m is not None and m.mean_dir_deg is None
