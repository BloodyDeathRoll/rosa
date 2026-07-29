"""Measured-spectra validation harness (Stage 3b acceptance) - NDBC 1-D spectra + r1.

The spectral-lite proxies (``spectral.py``) are assumptions until measured against real
spectra. NDBC realtime2 publishes, per station, ~45 days of hourly:
  ``<id>.data_spec`` - spectral energy density E(f), m^2/Hz, plus the windsea/swell
      separation frequency (9.999 = not computed);
  ``<id>.swr1``      - r1, the first normalized directional Fourier coefficient (0-1),
      from which directional spread sigma = sqrt(2 * (1 - r1)).

Two validations, both runnable today from that history (`verify --spectra`):
- **Spread bound**: the parametric per-class spread vs measured sigma at the spectral
  peak, grouped by the class the peak maps to → bias/MAE per class = the published
  error bound for the "modeled" spread label.
- **Consistency correlation**: the proxy formula fed MEASURED periods (Tp, Tm-1,0, Tm02
  from spectral moments) vs an independent narrowness truth, Goda's peakedness
  Qp = (2/m0^2) * ∫ f E(f)^2 df - Spearman rank correlation. This validates the
  formula itself; whether ECMWF's *periods* are right at a buoy accumulates separately
  in the ``<buoy>.ecmwf`` archive (mwp/mp2 now stored per row).

NDBC data is public domain; sources mirror ``observe.py`` (live + capture / fixture).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from .buoys import Buoy
from .models import SwellPartition
from .observe import NDBC_REALTIME
from .spectral import consistency_from_periods, parametric_spread_deg

SEP_FREQ_MISSING = 9.0  # NDBC writes 9.999 when the separation frequency isn't computed
HS_FLOOR_M = 0.2  # spectra below this carry too little energy to validate against
# with no separation frequency, a peak this short is windsea, not swell (Med windsea
# runs 4-7 s, trade-wind seas ~7-8 s) - heuristic, stated in the report
WINDSEA_TP_MAX_S = 8.0


@dataclass(frozen=True, slots=True)
class SpectrumObs:
    station: str
    time: datetime  # tz-aware UTC
    freqs: tuple[float, ...]  # Hz, ascending
    energy: tuple[float, ...]  # m^2/Hz, aligned to freqs
    r1: tuple[float | None, ...]  # 0-1, aligned to freqs; None where unreported
    sep_freq: float | None  # windsea/swell separation frequency, Hz


def _parse_pairs(tokens: list[str]) -> list[tuple[float, float]]:
    """``val (freq)`` token pairs → [(freq, val)]; malformed pairs are skipped."""
    out: list[tuple[float, float]] = []
    for i in range(0, len(tokens) - 1, 2):
        try:
            val = float(tokens[i])
            freq = float(tokens[i + 1].strip("()"))
        except ValueError:
            continue
        out.append((freq, val))
    return out


def _parse_rows(text: str, skip: int) -> dict[datetime, list[tuple[float, float]]]:
    """Timestamp → (freq, value) pairs for an NDBC spectral file; ``skip`` = tokens
    between the 5 date fields and the first pair (1 for data_spec's Sep_Freq, 0 for swr1)."""
    rows: dict[datetime, list[tuple[float, float]]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if len(f) < 5 + skip + 2:
            continue
        try:
            t = datetime(*(int(f[i]) for i in range(5)), tzinfo=UTC)
        except ValueError:
            continue
        rows[t] = _parse_pairs(f[5 + skip :])
    return rows


def parse_spectra(data_spec: str, swr1: str, station: str) -> list[SpectrumObs]:
    """Join the energy and r1 files by timestamp, oldest-first. r1 is aligned to the
    energy frequencies (None where the swr1 row lacks that frequency or is absent)."""
    energy_rows = _parse_rows(data_spec, skip=1)
    r1_rows = _parse_rows(swr1, skip=0)

    sep_by_time: dict[datetime, float | None] = {}
    for line in data_spec.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        f = line.split()
        if len(f) < 6:
            continue
        try:
            t = datetime(*(int(f[i]) for i in range(5)), tzinfo=UTC)
            sep = float(f[5])
        except ValueError:
            continue
        sep_by_time[t] = None if sep >= SEP_FREQ_MISSING else sep

    out: list[SpectrumObs] = []
    for t, pairs in energy_rows.items():
        pairs = sorted(pairs)
        r1_map = dict(r1_rows.get(t, []))
        freqs = tuple(f for f, _ in pairs)
        out.append(
            SpectrumObs(
                station=station,
                time=t,
                freqs=freqs,
                energy=tuple(v for _, v in pairs),
                r1=tuple(r1_map.get(f) for f in freqs),
                sep_freq=sep_by_time.get(t),
            )
        )
    out.sort(key=lambda s: s.time)
    return out


# --- spectral moments and derived measures (pure) ---


def moment(freqs: tuple[float, ...], energy: tuple[float, ...], n: int) -> float:
    """m_n = ∫ f^n E(f) df, trapezoidal (NDBC bins have non-uniform bandwidth)."""
    m = 0.0
    for i in range(len(freqs) - 1):
        a = freqs[i] ** n * energy[i]
        b = freqs[i + 1] ** n * energy[i + 1]
        m += 0.5 * (a + b) * (freqs[i + 1] - freqs[i])
    return m


@dataclass(frozen=True, slots=True)
class SpectrumMeasures:
    time: datetime
    hs_m: float
    tp_s: float  # 1 / peak frequency
    tm_m10_s: float  # m-1/m0 - pairs with ECMWF mwp
    tm02_s: float  # sqrt(m0/m2) - pairs with ECMWF mp2
    qp: float  # Goda peakedness - independent narrowness truth
    consistency: int  # the proxy formula fed these measured periods
    sigma_peak_deg: float | None  # measured directional spread at the peak
    windsea: bool  # peak classified as windsea (sep_freq, else short-Tp heuristic)


def measure(spec: SpectrumObs) -> SpectrumMeasures | None:
    """Derived measures, or None when the spectrum is too weak/degenerate to use."""
    if len(spec.freqs) < 3:
        return None
    m0 = moment(spec.freqs, spec.energy, 0)
    m2 = moment(spec.freqs, spec.energy, 2)
    m_m1 = moment(spec.freqs, spec.energy, -1)
    hs = 4.0 * math.sqrt(m0) if m0 > 0 else 0.0
    if hs < HS_FLOOR_M or m2 <= 0:
        return None
    peak_i = max(range(len(spec.energy)), key=lambda i: spec.energy[i])
    f_peak = spec.freqs[peak_i]
    if f_peak <= 0:
        return None
    tp = 1.0 / f_peak
    tm_m10 = m_m1 / m0
    tm02 = math.sqrt(m0 / m2)
    # Qp = (2/m0^2) ∫ f E(f)^2 df
    qp = (2.0 / m0**2) * moment(spec.freqs, tuple(e * e for e in spec.energy), 1)
    r1 = spec.r1[peak_i]
    sigma = math.degrees(math.sqrt(2.0 * (1.0 - r1))) if r1 is not None and r1 <= 1.0 else None
    windsea = f_peak > spec.sep_freq if spec.sep_freq is not None else tp < WINDSEA_TP_MAX_S
    return SpectrumMeasures(
        time=spec.time,
        hs_m=hs,
        tp_s=tp,
        tm_m10_s=tm_m10,
        tm02_s=tm02,
        qp=qp,
        consistency=consistency_from_periods(tp, tm_m10, tm02),
        sigma_peak_deg=sigma,
        windsea=windsea,
    )


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation (ties get average ranks); None below n=3."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None

    def ranks(v: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


# --- the report ---


def _assumed_class(m: SpectrumMeasures) -> tuple[str, float]:
    """(class label, parametric spread) the pipeline would assume for this peak."""
    part = SwellPartition(
        height_m=m.hs_m,
        period_s=m.tp_s,
        direction_deg=0.0,
        kind="wind" if m.windsea else "swell",
    )
    if m.windsea:
        label = "windsea"
    elif m.tp_s < 10.0:
        label = "swell <10s"
    elif m.tp_s < 14.0:
        label = "swell 10-14s"
    else:
        label = "swell >=14s"
    return label, parametric_spread_deg(part)


@dataclass(frozen=True, slots=True)
class SpreadClassStats:
    label: str
    n: int
    assumed_deg: float
    measured_mean_deg: float
    bias_deg: float  # assumed - measured mean
    mae_deg: float


@dataclass(frozen=True, slots=True)
class SpectraReport:
    station: str
    n_hours: int  # usable spectra (past the energy floor)
    consistency_n: int
    consistency_spearman: float | None  # proxy vs Qp (negative would mean it's wrong)
    spread: tuple[SpreadClassStats, ...]


def build_report(specs: list[SpectrumObs]) -> SpectraReport:
    measures = [m for m in (measure(s) for s in specs) if m is not None]
    proxy = [float(m.consistency) for m in measures]
    qp = [m.qp for m in measures]

    by_class: dict[str, tuple[float, list[float]]] = {}
    for m in measures:
        if m.sigma_peak_deg is None:
            continue
        label, assumed = _assumed_class(m)
        by_class.setdefault(label, (assumed, []))[1].append(m.sigma_peak_deg)
    spread = tuple(
        SpreadClassStats(
            label=label,
            n=len(sigmas),
            assumed_deg=assumed,
            measured_mean_deg=sum(sigmas) / len(sigmas),
            bias_deg=assumed - sum(sigmas) / len(sigmas),
            mae_deg=sum(abs(assumed - s) for s in sigmas) / len(sigmas),
        )
        for label, (assumed, sigmas) in sorted(by_class.items())
    )
    return SpectraReport(
        station=specs[0].station if specs else "?",
        n_hours=len(measures),
        consistency_n=len(proxy),
        consistency_spearman=spearman(proxy, qp),
        spread=spread,
    )


def render_report(buoy: Buoy, report: SpectraReport) -> str:
    lines = [
        f"measured spectra vs Stage-3b assumptions - buoy {buoy.id} - {buoy.name}",
        f"  usable spectra: {report.n_hours} hrs (Hs >= {HS_FLOOR_M} m)",
    ]
    r = report.consistency_spearman
    if r is not None:
        lines.append(
            f"  consistency proxy vs Qp narrowness: spearman r={r:+.2f} (n={report.consistency_n})"
        )
    else:
        lines.append("  consistency proxy vs Qp narrowness: (not enough spectra)")
    if report.spread:
        lines.append("  directional spread - parametric assumption vs measured sigma@peak:")
        lines.append(
            f"    {'class':<14}{'n':>5}  {'assumed':>8}  {'measured':>9}  {'bias':>7}  {'mae':>6}"
        )
        for s in report.spread:
            lines.append(
                f"    {s.label:<14}{s.n:>5}  {s.assumed_deg:>7.0f}°  {s.measured_mean_deg:>8.1f}°"
                f"  {s.bias_deg:>+6.1f}°  {s.mae_deg:>5.1f}°"
            )
    else:
        lines.append("  directional spread: (no r1 data at this station)")
    return "\n".join(lines)


# --- sources (mirror observe.py) ---


class SpectraSource(Protocol):
    def fetch(self, buoy: Buoy) -> list[SpectrumObs]: ...


class NDBCSpectraSource:
    def __init__(self, capture_dir: Path | None = None, timeout_s: float = 30.0) -> None:
        self.capture_dir = capture_dir
        self.timeout_s = timeout_s

    def fetch(self, buoy: Buoy) -> list[SpectrumObs]:
        with httpx.Client(timeout=self.timeout_s) as client:
            data_spec = client.get(f"{NDBC_REALTIME}/{buoy.id}.data_spec")
            if data_spec.status_code == 404:
                return []  # met-only / non-spectral station - honest empty, not a crash
            data_spec.raise_for_status()
            # r1 is optional kit - a station without it still validates consistency
            swr1 = client.get(f"{NDBC_REALTIME}/{buoy.id}.swr1")
            swr1_text = swr1.text if swr1.status_code == 200 else ""
        if self.capture_dir is not None:
            self.capture_dir.mkdir(parents=True, exist_ok=True)
            (self.capture_dir / f"{buoy.id}.data_spec").write_text(data_spec.text, encoding="utf-8")
            (self.capture_dir / f"{buoy.id}.swr1").write_text(swr1_text, encoding="utf-8")
        return parse_spectra(data_spec.text, swr1_text, buoy.id)


class SpectraFixtureSource:
    def __init__(self, fixtures_dir: Path) -> None:
        self.fixtures_dir = fixtures_dir

    def fetch(self, buoy: Buoy) -> list[SpectrumObs]:
        data_spec = (self.fixtures_dir / f"{buoy.id}.data_spec").read_text(encoding="utf-8")
        swr1_path = self.fixtures_dir / f"{buoy.id}.swr1"
        swr1 = swr1_path.read_text(encoding="utf-8") if swr1_path.exists() else ""
        return parse_spectra(data_spec, swr1, buoy.id)
