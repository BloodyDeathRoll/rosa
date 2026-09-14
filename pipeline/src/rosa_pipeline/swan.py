"""SWAN run inputs for a Stage-4 region (docs/rosa-stage4-plan.md 4.2).

What SWAN needs at the edge of a regional grid is a 2-D wave spectrum per boundary node
per step, and a wind field over the grid. Neither is downloadable: no free product carries
gridded 2-D spectra (docs/rosa-stage3-plan.md §2), so the boundary is REBUILT from the
partitions GFS-Wave does publish at every 0.25 deg node - wind sea + three swells, each
(Hs, mean period, direction) - and the wind comes from the GFS 0.25 deg atmos grid
(`gfsatmos`, plan C3b). Both are the feeds the cycle already pulls; this module adds one
grib-filter request per (box x step) on each, nothing per spot.

Per partition the spectrum is a JONSWAP shape in frequency and a cos^m shape in direction:

* The peak frequency is the one whose JONSWAP has the partition's MEAN period (``Tm01``).
  GFS-Wave's partition periods are means (``blend._PARTITION_TP_KEYS`` explains why the
  transform cannot invent a peak period from them); a JONSWAP of a given mean period has
  a definite peak, so nothing is invented here - the synthesized partition's own Tm01 is
  the number GFS gave.
* The directional spread is the same class table `spectral.parametric_spread_deg` ships in
  the payload (wind sea 35 deg; swell 25 / 20 / 24 deg by period), turned into the cos^m
  power SWAN uses through sigma^2 = 2 / (m + 1).

Partitions add in energy. The result is what SWAN's own boundary reader consumes: a
"SWAN 1" spectral file (variance density in m2/Hz/deg on an absolute-frequency,
nautical-direction grid), one location per boundary node, plus the BOUNDSPEC SEGMENT lines
that place those locations along each open side. Stationary runs get one file per step
with no TIME block (SWAN refuses a TIME header in stationary mode).

The wind file is SWAN's READINP WIND layout: the u block then the v block, IDLA=3 (first
record = southern row), on the GFS 0.25 deg nodes covering the grid; SWAN interpolates.

Nothing here runs SWAN. `rosa-pipeline swan` writes a run directory; the runtime spike
(plan 4.3) executes it on rosa-arm and the nearshore source (plan 4.4) reads the tables.
"""

from __future__ import annotations

import math
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from .gfswave import Box
from .spectral import (
    SPREAD_LONG_SWELL_DEG,
    SPREAD_MID_SWELL_DEG,
    SPREAD_SHORT_SWELL_DEG,
    SPREAD_WINDSEA_DEG,
)

# Spectral grid for the boundary files. 0.035 Hz = 28.6 s reaches the longest Pacific
# groundswell; 0.5 Hz = 2 s is where wind sea stops mattering to a breaker. Logarithmic in
# frequency (SWAN's CGRID CIRCLE convention), 10 deg direction bins.
FREQ_LO_HZ = 0.035
FREQ_HI_HZ = 0.5
NFREQ = 32
NDIR = 36
JONSWAP_GAMMA = 3.3
# Nodes over land carry no partition; a partition under this height is noise in the grib.
MIN_PARTITION_HS_M = 0.05
GFS_GRID_DEG = 0.25
# SWAN's spectral-file exception value (its own writer's default).
EXCEPTION_VALUE = -99.0

_GFS_SINGLE = ("swh", "perpw", "dirpw", "shww", "mpww", "wvdir")
_GFS_TRIPLE = ("shts", "mpts", "swdir")


# --- spectral shapes ----------------------------------------------------------------------


def frequency_grid(lo: float = FREQ_LO_HZ, hi: float = FREQ_HI_HZ, n: int = NFREQ) -> np.ndarray:
    return np.exp(np.linspace(math.log(lo), math.log(hi), n))


def direction_grid(n: int = NDIR) -> np.ndarray:
    """Nautical bin centres, degrees, starting at 0 (from north)."""
    return np.arange(n) * (360.0 / n)


def spread_deg(kind: str, period_s: float) -> float:
    """The payload's modeled spread class (spectral.parametric_spread_deg), by kind/period."""
    if kind == "wind":
        return SPREAD_WINDSEA_DEG
    if period_s < 10.0:
        return SPREAD_SHORT_SWELL_DEG
    if period_s < 14.0:
        return SPREAD_MID_SWELL_DEG
    return SPREAD_LONG_SWELL_DEG


def spread_power(sigma_deg: float) -> float:
    """cos^m power for a one-sided directional spread sigma: sigma^2 = 2 / (m + 1)."""
    s = math.radians(sigma_deg)
    return max(1.0, 2.0 / (s * s) - 1.0)


def jonswap(freqs: np.ndarray, hs: float, tp: float, gamma: float = JONSWAP_GAMMA) -> np.ndarray:
    """JONSWAP variance density S(f) in m2/Hz, scaled so that its zeroth moment on THIS
    grid is Hs^2/16 (the shape is normalized numerically, not by the alpha formula, so the
    discrete integral returns the height that went in)."""
    fp = 1.0 / tp
    sigma = np.where(freqs <= fp, 0.07, 0.09)
    r = np.exp(-((freqs - fp) ** 2) / (2.0 * sigma**2 * fp**2))
    shape = freqs**-5 * np.exp(-1.25 * (fp / freqs) ** 4) * gamma**r
    m0 = np.trapezoid(shape, freqs)
    if m0 <= 0:
        return np.zeros_like(freqs)
    return shape * (hs * hs / 16.0) / m0


def _tm01(freqs: np.ndarray, s: np.ndarray) -> float:
    m0 = np.trapezoid(s, freqs)
    m1 = np.trapezoid(s * freqs, freqs)
    return m0 / m1 if m1 > 0 else 0.0


_TP_OVER_TM01: dict[tuple[float, ...], float] = {}


def peak_period_for_mean(tm01: float, freqs: np.ndarray, gamma: float = JONSWAP_GAMMA) -> float:
    """The Tp whose JONSWAP (on this grid) has mean period Tm01. The ratio is a property
    of the shape, measured once per grid at a mid-band period and applied as a constant -
    it drifts by a few percent where the grid truncates a very long or very short shape,
    which is the honest price of a fixed frequency window."""
    key = (float(freqs[0]), float(freqs[-1]), len(freqs), gamma)
    ratio = _TP_OVER_TM01.get(key)
    if ratio is None:
        probe_tp = 10.0
        ratio = probe_tp / _tm01(freqs, jonswap(freqs, 1.0, probe_tp, gamma))
        _TP_OVER_TM01[key] = ratio
    return tm01 * ratio


def cos_power_spread(dirs: np.ndarray, mean_dir: float, power: float) -> np.ndarray:
    """D(theta) = A cos^m(theta - theta0) over +-90 deg, normalized to unit integral over
    the direction grid in DEGREES (so S(f) x D(theta) is m2/Hz/deg)."""
    rel = np.deg2rad(((dirs - mean_dir + 180.0) % 360.0) - 180.0)
    d = np.clip(np.cos(rel), 0.0, None) ** power  # zero beyond +-90 deg
    total = d.sum() * (360.0 / len(dirs))
    return d / total if total > 0 else d


@dataclass(frozen=True, slots=True)
class Partition:
    kind: str  # "wind" | "swell"
    hs: float
    tm01: float  # GFS-Wave publishes MEAN partition periods
    direction: float  # nautical, degrees FROM


def synth_spectrum(
    partitions: Iterable[Partition], freqs: np.ndarray, dirs: np.ndarray
) -> np.ndarray:
    """Variance density E(f, theta) in m2/Hz/deg, partitions added in energy."""
    e = np.zeros((len(freqs), len(dirs)))
    for p in partitions:
        if p.hs < MIN_PARTITION_HS_M or p.tm01 <= 0:
            continue
        tp = peak_period_for_mean(p.tm01, freqs)
        s = jonswap(freqs, p.hs, tp)
        d = cos_power_spread(dirs, p.direction, spread_power(spread_deg(p.kind, p.tm01)))
        e += np.outer(s, d)
    return e


def significant_height(e: np.ndarray, freqs: np.ndarray, dirs: np.ndarray) -> float:
    m0 = np.trapezoid(e.sum(axis=1) * (360.0 / len(dirs)), freqs)
    return 4.0 * math.sqrt(max(m0, 0.0))


# --- GFS-Wave grid -> boundary nodes -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WaveGrid:
    """One GFS-Wave step over a box: node axes (lat ascending, lon in -180..180 ascending)
    and per-field 2-D arrays (NaN over land). Triple fields are keyed swell1_h etc."""

    lats: np.ndarray
    lons: np.ndarray
    fields: dict[str, np.ndarray]


def parse_gfs_grid(grib_bytes: bytes) -> WaveGrid:
    """Every wave field of one grib-filter subset as full arrays (not point samples)."""
    import pygrib

    fields: dict[str, np.ndarray] = {}
    counts: dict[str, int] = {}
    lats = lons = None
    with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
        tf.write(grib_bytes)
        tf.flush()
        grbs = pygrib.open(tf.name)
        for m in grbs:
            sn = m.shortName
            if sn in _GFS_SINGLE:
                key = sn
                if key in fields:
                    continue
            elif sn in _GFS_TRIPLE:
                idx = counts.get(sn, 0) + 1
                counts[sn] = idx
                if idx > 3:
                    continue
                key = {"shts": "swell{}_h", "mpts": "swell{}_p", "swdir": "swell{}_d"}[sn].format(
                    idx
                )
            else:
                continue
            vals = np.ma.filled(np.ma.asarray(m.values, dtype=float), np.nan)
            if lats is None:
                glats, glons = m.latlons()
                # snap the grib's float noise (30.000001) back onto the 0.25 deg lattice
                lats = np.round(np.asarray(glats[:, 0], dtype=float), 4)
                lons = np.round(((np.asarray(glons[0, :], dtype=float) + 180.0) % 360.0) - 180.0, 4)
            fields[key] = vals
        grbs.close()
    if lats is None or lons is None:
        raise ValueError("grib subset holds no wave field")
    # north->south is how NOMADS writes them; store ascending so rows follow SWAN's IDLA=3
    if lats[0] > lats[-1]:
        lats = lats[::-1]
        fields = {k: v[::-1, :] for k, v in fields.items()}
    order = np.argsort(lons)
    if not np.all(order == np.arange(len(lons))):
        lons = lons[order]
        fields = {k: v[:, order] for k, v in fields.items()}
    return WaveGrid(lats=lats, lons=lons, fields=fields)


def node_partitions(grid: WaveGrid, i: int, j: int) -> list[Partition]:
    f = grid.fields
    out: list[Partition] = []

    def val(key: str) -> float | None:
        a = f.get(key)
        if a is None:
            return None
        v = float(a[i, j])
        return None if math.isnan(v) else v

    h, p, d = val("shww"), val("mpww"), val("wvdir")
    if h is not None and p is not None and d is not None:
        out.append(Partition("wind", h, p, d))
    for k in (1, 2, 3):
        h, p, d = val(f"swell{k}_h"), val(f"swell{k}_p"), val(f"swell{k}_d")
        if h is not None and p is not None and d is not None:
            out.append(Partition("swell", h, p, d))
    return out


@dataclass(frozen=True, slots=True)
class BoundaryNode:
    side: str  # "W" | "S" | "N" | "E"
    lat: float
    lon: float
    along_deg: float  # distance along the side's segment from its start, in grid degrees
    i: int
    j: int


def boundary_nodes(
    grid: WaveGrid, outer: dict, sides: Sequence[str] = ("W", "S", "N")
) -> list[BoundaryNode]:
    """GFS nodes lying on the requested sides of the outer grid box (its edges must sit on
    the 0.25 deg lattice), wet ones only, ordered along each side. Sides run W: south to
    north, S and N: west to east, E: south to north - the SEGMENT XY order written later."""
    wet = ~np.isnan(grid.fields["swh"])
    tol = 1e-3  # grib lattices carry float noise (30.000001)

    def on(axis: np.ndarray, value: float) -> np.ndarray:
        return np.nonzero(np.abs(axis - value) < tol)[0]

    nodes: list[BoundaryNode] = []
    for side in sides:
        if side in ("W", "E"):
            lon = outer["west"] if side == "W" else outer["east"]
            js = on(grid.lons, lon)
            if len(js) == 0:
                raise ValueError(f"outer {side} edge {lon} is not on the GFS lattice in this box")
            j = int(js[0])
            for i in np.nonzero(
                (grid.lats >= outer["south"] - tol) & (grid.lats <= outer["north"] + tol)
            )[0]:
                if wet[i, j]:
                    nodes.append(
                        BoundaryNode(
                            side,
                            float(grid.lats[i]),
                            lon,
                            float(grid.lats[i] - outer["south"]),
                            int(i),
                            j,
                        )
                    )
        else:
            lat = outer["south"] if side == "S" else outer["north"]
            is_ = on(grid.lats, lat)
            if len(is_) == 0:
                raise ValueError(f"outer {side} edge {lat} is not on the GFS lattice in this box")
            i = int(is_[0])
            for j in np.nonzero(
                (grid.lons >= outer["west"] - tol) & (grid.lons <= outer["east"] + tol)
            )[0]:
                if wet[i, j]:
                    nodes.append(
                        BoundaryNode(
                            side,
                            lat,
                            float(grid.lons[j]),
                            float(grid.lons[j] - outer["west"]),
                            i,
                            int(j),
                        )
                    )
    return nodes


# --- SWAN files ---------------------------------------------------------------------------


def write_sp2(
    path: Path,
    locations: Sequence[tuple[float, float]],
    freqs: np.ndarray,
    dirs: np.ndarray,
    spectra: Sequence[np.ndarray | None],
    *,
    time: datetime | None = None,
    project: str = "rosa",
) -> None:
    """SWAN 'SWAN 1' 2-D spectral file: LONLAT locations, AFREQ, NDIR (nautical), VaDens in
    m2/Hz/deg. ``spectra[k]`` is E(f, theta) for location k, or None -> NODATA. With
    ``time`` a TIME block and one dated record are written (non-stationary runs only)."""
    lines = [
        "SWAN   1                                Swan standard spectral file, version",
        f"$   Data produced by rosa-pipeline swan ({project})",
    ]
    if time is not None:
        lines += [
            "TIME                                    time-dependent data",
            "     1                                  time coding option",
        ]
    lines += [
        "LONLAT                                  locations in spherical coordinates",
        f"{len(locations):6d}                                  number of locations",
    ]
    lines += [f"{lon:12.6f} {lat:12.6f}" for lat, lon in locations]
    lines += [
        "AFREQ                                   absolute frequencies in Hz",
        f"{len(freqs):6d}                                  number of frequencies",
    ]
    lines += [f"{f:12.6f}" for f in freqs]
    lines += [
        "NDIR                                    spectral nautical directions in degr",
        f"{len(dirs):6d}                                  number of directions",
    ]
    lines += [f"{d:12.4f}" for d in dirs]
    lines += [
        "QUANT",
        "     1                                  number of quantities in table",
        "VaDens                                  variance densities in m2/Hz/degr",
        "m2/Hz/degr                              unit",
        f"{EXCEPTION_VALUE:15.4E}                        exception value",
    ]
    if time is not None:
        lines.append(f"{time:%Y%m%d.%H%M%S}                         date and time")
    for e in spectra:
        if e is None or not np.any(e > 0):
            lines.append("NODATA" if e is None else "ZERO")
            continue
        peak = float(e.max())
        factor = peak / 1.0e6  # ints up to 1e6 keep six figures of the peak
        lines.append("FACTOR")
        lines.append(f"{factor:15.8E}")
        ints = np.rint(e / factor).astype(int)
        lines += [" ".join(f"{v:7d}" for v in row) for row in ints]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sp2_name(tag: str, node: BoundaryNode) -> str:
    return f"bnd_{tag}_{node.side}{node.along_deg * 100:04.0f}.sp2"


def boundspec_lines(nodes: Sequence[BoundaryNode], outer: dict, tag: str) -> list[str]:
    """One BOUNDSPEC SEGMENT XY ... VARIABLE FILE line per side, every [len] naming its
    own one-location file (``sp2_name``), seq 1.

    Measured on rosa-arm 2026-09-14 against SWAN 41.51's parser: a file name repeated
    within a run is refused ("File is already opened"), and a [len] with no name is
    refused too ("Wrong type of data for variable FNAME") - so a multi-location file
    cannot be addressed by seq along a segment. One small file per node is what the
    parser accepts."""
    corners = {
        "W": (outer["west"], outer["south"], outer["west"], outer["north"]),
        "S": (outer["west"], outer["south"], outer["east"], outer["south"]),
        "N": (outer["west"], outer["north"], outer["east"], outer["north"]),
        "E": (outer["east"], outer["south"], outer["east"], outer["north"]),
    }
    out: list[str] = []
    for side in ("W", "S", "N", "E"):
        picks = [n for n in nodes if n.side == side]
        if not picks:
            continue
        x1, y1, x2, y2 = corners[side]
        parts = " ".join(f"{n.along_deg:.4f} '{sp2_name(tag, n)}' 1" for n in picks)
        out.append(f"BOUNDSPEC SEGMENT XY {x1:g} {y1:g} {x2:g} {y2:g} VARIABLE FILE {parts}")
    return out


@dataclass(frozen=True, slots=True)
class WindGrid:
    lats: np.ndarray  # ascending
    lons: np.ndarray  # ascending, -180..180
    u: np.ndarray
    v: np.ndarray


def parse_wind_grid(grib_bytes: bytes) -> WindGrid:
    import pygrib

    got: dict[str, np.ndarray] = {}
    lats = lons = None
    with tempfile.NamedTemporaryFile(suffix=".grib2") as tf:
        tf.write(grib_bytes)
        tf.flush()
        grbs = pygrib.open(tf.name)
        for m in grbs:
            if m.shortName in ("10u", "10v") and m.shortName not in got:
                got[m.shortName] = np.asarray(m.values, dtype=float)
                if lats is None:
                    glats, glons = m.latlons()
                    lats = np.round(np.asarray(glats[:, 0], dtype=float), 4)
                    lons = np.round(
                        ((np.asarray(glons[0, :], dtype=float) + 180.0) % 360.0) - 180.0, 4
                    )
        grbs.close()
    if "10u" not in got or "10v" not in got or lats is None or lons is None:
        raise ValueError("grib subset holds no 10 m wind")
    u, v = got["10u"], got["10v"]
    if lats[0] > lats[-1]:
        lats, u, v = lats[::-1], u[::-1, :], v[::-1, :]
    order = np.argsort(lons)
    if not np.all(order == np.arange(len(lons))):
        lons, u, v = lons[order], u[:, order], v[:, order]
    return WindGrid(lats=lats, lons=lons, u=u, v=v)


def write_wind(path: Path, wind: WindGrid) -> None:
    """READINP WIND layout: u block then v block, IDLA=3 (first record = southern row)."""
    with path.open("w", encoding="utf-8") as f:
        for block in (wind.u, wind.v):
            for row in block:
                f.write(" ".join(f"{x:.2f}" for x in row) + "\n")


def inpgrid_wind_line(wind: WindGrid) -> str:
    d = GFS_GRID_DEG
    return (
        f"INPGRID WIND REGULAR {wind.lons[0]:g} {wind.lats[0]:g} 0. "
        f"{len(wind.lons) - 1} {len(wind.lats) - 1} {d:g} {d:g}"
    )


def input_text(
    *,
    run_id: str,
    outer_meta: dict,
    bottom_path: str,
    wind: WindGrid | None,
    wind_path: str | None,
    boundspec: Sequence[str],
    points_path: str,
    table_path: str,
    stationary: bool = True,
) -> str:
    """A stationary SWAN INPUT for one step on the outer grid."""
    nx, ny, d = outer_meta["nx"], outer_meta["ny"], outer_meta["dlon"]
    lon0, lat0 = outer_meta["lon0"], outer_meta["lat0"]
    lines = [
        f"$ rosa Stage-4 run {run_id} - generated by rosa-pipeline swan, do not edit",
        "PROJ 'rosa' " + f"'{run_id[:4]}'",
        "SET NAUTICAL",
        "MODE STATIONARY TWODIMENSIONAL" if stationary else "MODE NONSTATIONARY TWODIMENSIONAL",
        "COORDINATES SPHERICAL",
        f"CGRID REGULAR {lon0:g} {lat0:g} 0. {(nx - 1) * d:g} {(ny - 1) * d:g} {nx - 1} {ny - 1} "
        f"CIRCLE {NDIR} {FREQ_LO_HZ:g} {FREQ_HI_HZ:g} {NFREQ - 1}",
        f"INPGRID BOTTOM REGULAR {lon0:g} {lat0:g} 0. {nx - 1} {ny - 1} {d:g} {d:g}",
        f"READINP BOTTOM 1. '{bottom_path}' 3 0 FREE",
    ]
    if wind is not None and wind_path is not None:
        lines += [inpgrid_wind_line(wind), f"READINP WIND 1. '{wind_path}' 3 0 FREE"]
    lines += list(boundspec)
    lines += [
        "GEN3",
        "BREAKING",
        "FRICTION JONSWAP",
        "NUM ACCUR 0.02 0.02 0.02 98. STAT 50",
        f"POINTS 'SPOTS' FILE '{points_path}'",
        f"TABLE 'SPOTS' HEAD '{table_path}' XP YP DEP HSIGN TPS DIR DSPR",
        "COMPUTE",
        "STOP",
    ]
    return "\n".join(lines) + "\n"


# --- one step -> run files -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StepFiles:
    step: int
    valid: datetime
    input_path: Path
    nodes: int
    hs_boundary_max: float


def write_step(
    run_dir: Path,
    *,
    step: int,
    valid: datetime,
    outer_meta: dict,
    wave_grib: bytes,
    wind_grib: bytes | None,
    bottom_rel: str,
    points_rel: str,
) -> StepFiles:
    """Boundary sp2 + wind + INPUT for one forecast step, stationary."""
    run_dir.mkdir(parents=True, exist_ok=True)
    freqs, dirs = frequency_grid(), direction_grid()
    grid = parse_gfs_grid(wave_grib)
    outer = {
        "west": outer_meta["lon0"],
        "south": outer_meta["lat0"],
        "east": outer_meta["lon0"] + (outer_meta["nx"] - 1) * outer_meta["dlon"],
        "north": outer_meta["lat0"] + (outer_meta["ny"] - 1) * outer_meta["dlat"],
    }
    nodes = boundary_nodes(grid, outer)
    spectra = [synth_spectrum(node_partitions(grid, n.i, n.j), freqs, dirs) for n in nodes]
    tag = f"f{step:03d}"
    for n, e in zip(nodes, spectra, strict=True):
        write_sp2(run_dir / sp2_name(tag, n), [(n.lat, n.lon)], freqs, dirs, [e], project=tag)
    wind = wind_path = None
    if wind_grib is not None:
        wind = parse_wind_grid(wind_grib)
        wind_path = f"wind_{tag}.dat"
        write_wind(run_dir / wind_path, wind)
    text = input_text(
        run_id=tag,
        outer_meta=outer_meta,
        bottom_path=bottom_rel,
        wind=wind,
        wind_path=wind_path,
        boundspec=boundspec_lines(nodes, outer, tag),
        points_path=points_rel,
        table_path=f"spots_{tag}.tab",
    )
    inp = run_dir / f"INPUT_{tag}"
    inp.write_text(text, encoding="utf-8")
    hs_max = max((significant_height(e, freqs, dirs) for e in spectra), default=0.0)
    return StepFiles(
        step=step, valid=valid, input_path=inp, nodes=len(nodes), hs_boundary_max=hs_max
    )


def fetch_box(outer_meta: dict, pad_deg: float = 0.5) -> Box:
    """The grib-filter box covering the outer grid plus a margin, in the filter's 0-360
    longitude convention (gfswave.Box)."""
    west = outer_meta["lon0"] - pad_deg
    east = outer_meta["lon0"] + (outer_meta["nx"] - 1) * outer_meta["dlon"] + pad_deg
    south = outer_meta["lat0"] - pad_deg
    north = outer_meta["lat0"] + (outer_meta["ny"] - 1) * outer_meta["dlat"] + pad_deg
    return Box(bottom=south, top=north, left=west % 360.0, right=east % 360.0)


def valid_time(cycle: datetime, step: int) -> datetime:
    return cycle + timedelta(hours=step)
