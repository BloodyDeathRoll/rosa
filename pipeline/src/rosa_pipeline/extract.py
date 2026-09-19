"""Turn raw API responses into typed hourly records at the offshore point."""

from __future__ import annotations

from bisect import bisect_left
from datetime import UTC, datetime, timedelta

from .confidence import agreement_from_members, member_directions_at, member_heights_at
from .fetch import TP_MODEL, TP_SUFFIX, RawForecast
from .models import HourForecast, SpectralSea, SwellPartition

# a 3-hourly published hour joins the nearest 6-hourly ECMWF step within this - the
# spectral-shape quantities it feeds vary over hours, not minutes
SPECTRAL_JOIN_TOL_H = 3.0

_SWELL_PREFIXES: tuple[tuple[str, str], ...] = (
    ("swell_wave", "swell"),
    ("secondary_swell_wave", "swell"),
    ("tertiary_swell_wave", "swell"),
    ("wind_wave", "wind"),
)


def _merge_models(hourly: dict) -> tuple[dict, list[bool]]:
    """Collapse a multi-model marine response (fields suffixed `_marine_best_match`,
    `_ncep_gfswave016`, `_gwam`) into a single unsuffixed series, per hour: use best_match
    where it has data (days 0-9), else GFS-Wave (days 10-16). Anchored on wave_height so every
    field in an hour comes from one model. A single-model / fixture response passes through
    unchanged.

    ONE field family is exempt from the single-model rule: `*_peak_period` falls through to
    `fetch.TP_MODEL` (gwam) where the primary chain published none, which outside Europe is
    always - see the TP_MODEL note in fetch.py for why that join is safe and why gwam is
    never a horizon fallback for anything else (it stops at ~7.3 days, short of best_match).

    Returns (merged, from_tail) where from_tail[i] says the hour came from the GFS-Wave
    tail rather than best_match. The merge has always KNOWN this per hour and threw it
    away; publish turns it into one `tail_from` stamp. That is the only model label that
    would be true - a single constant name was wrong on ~40% of rows (2026-08-14).
    """
    if "wave_height" in hourly:  # single model (or fixture) - nothing to merge
        return hourly, [False] * len(hourly.get("time", []))
    suffixes = {k[len("wave_height_") :] for k in hourly if k.startswith("wave_height_")}
    if not suffixes:
        return hourly, [False] * len(hourly.get("time", []))
    bm = next((s for s in suffixes if "best_match" in s), None)
    tp = next((s for s in suffixes if s == TP_MODEL), None)
    # sorted() so the tail model is deterministic once there are three suffixes in play
    gf = next((s for s in sorted(suffixes) if "best_match" not in s and s != tp), None)
    anchor = hourly.get(f"wave_height_{bm}") if bm else None

    known = [s for s in (bm, gf, tp) if s]
    bases: set[str] = set()
    for k in hourly:
        if k == "time":
            continue
        for s in known:
            if k.endswith(f"_{s}"):
                bases.add(k[: -(len(s) + 1)])
                break

    merged: dict = {"time": hourly["time"]}
    n = len(hourly["time"])
    # anchored on wave_height, exactly like the per-field choice below, so the flag
    # describes the whole hour and not whichever field happened to be iterated last
    from_tail = [
        not (anchor is not None and i < len(anchor) and anchor[i] is not None) for i in range(n)
    ]
    for base in sorted(bases):
        bm_arr = hourly.get(f"{base}_{bm}") if bm else None
        gf_arr = hourly.get(f"{base}_{gf}") if gf else None
        tp_arr = hourly.get(f"{base}_{tp}") if tp and base.endswith(TP_SUFFIX) else None
        out: list = []
        for i in range(n):
            use_bm = anchor is not None and i < len(anchor) and anchor[i] is not None
            src = bm_arr if use_bm else gf_arr
            v = src[i] if src is not None and i < len(src) else None
            if v is None and tp_arr is not None and i < len(tp_arr):
                v = tp_arr[i]  # peak period only - never Hs / direction / mean period
            out.append(v)
        merged[base] = out
    return merged, from_tail


def _partition(hourly: dict, prefix: str, kind: str, i: int) -> SwellPartition | None:
    height = hourly[f"{prefix}_height"][i]
    direction = hourly[f"{prefix}_direction"][i]
    period = hourly[f"{prefix}_period"][i]
    if height is None or direction is None or period is None or height <= 0:
        return None
    # peak period is only published for the total/primary-swell/wind-wave (not sec/tert),
    # and absent from pre-Stage-1 fixtures - .get keeps those partitions valid with None
    peak_arr = hourly.get(f"{prefix}_peak_period")
    peak = peak_arr[i] if peak_arr is not None and i < len(peak_arr) else None
    # Tp < Tm is spectrally impossible for the partition it claims to describe, and it
    # happens: the Tp join is cross-model (GWAM's one swell + one wind sea onto GFS-Wave's
    # partitions), so GWAM's "wind sea" can be a different sea than the partition it lands
    # on (measured 2026-08-27: Tp 2.2 s stamped on a 1.31 m / 7.8 s poleg sea, crushing
    # rideability and swinging the published day 3x while Surfline's stayed flat - 35/74
    # poleg partitions). A mismatched peak is no peak: fall back to the mean.
    if peak is not None and peak < period:
        peak = None
    return SwellPartition(
        height_m=height,
        period_s=period,
        direction_deg=direction,
        kind=kind,  # type: ignore[arg-type]
        peak_period_s=peak,
    )


def _nearest_spectral(
    t: datetime, spectral: list[SpectralSea], times: list[datetime]
) -> SpectralSea | None:
    """Nearest ECMWF step within SPECTRAL_JOIN_TOL_H (``times`` = sorted spectral times)."""
    if not spectral:
        return None
    i = bisect_left(times, t)
    best: SpectralSea | None = None
    best_gap = timedelta(hours=SPECTRAL_JOIN_TOL_H)
    for j in (i - 1, i):
        if 0 <= j < len(spectral):
            gap = abs(spectral[j].time - t)
            if gap <= best_gap:
                best, best_gap = spectral[j], gap
    return best


def _member_at(
    t: datetime, sp: SpectralSea | None, spectral: list[SpectralSea], times: list[datetime]
) -> tuple[float | None, float | None]:
    """The ECMWF member's (swh, mwd) AT hour ``t``, for the agreement pool only.

    ``sp`` is the nearest-step join, right for what it was written for - spectral SHAPE,
    which varies over hours. Hs while a swell arrives does not: every other member in the
    pool is already at the hour (OM serves hourly, the blend arm's GFS total is
    ``_interp_hourly``'s), so pairing them with a step up to 3 h away scored a time offset
    as model disagreement - two identical forecasts ramping 0.25 m/h read 0.67 "medium".
    Linear between the two steps that bracket ``t`` (bearing circular) when both carry a
    height and sit within twice the join tolerance - the same fill the other members get;
    anywhere else (series edge, a purged step) the nearest step stands in, as before.
    ``sp`` None = no member at this hour, unchanged."""
    if sp is None or sp.swh is None or sp.time == t:
        return (sp.swh, sp.mwd) if sp is not None else (None, None)
    i = bisect_left(times, t)
    if not 0 < i < len(spectral):
        return sp.swh, sp.mwd
    a, b = spectral[i - 1], spectral[i]
    span_h = (b.time - a.time).total_seconds() / 3600.0
    if a.swh is None or b.swh is None or not 0.0 < span_h <= 2 * SPECTRAL_JOIN_TOL_H:
        return sp.swh, sp.mwd
    w = (t - a.time).total_seconds() / 3600.0 / span_h
    mwd = sp.mwd
    if a.mwd is not None and b.mwd is not None:
        mwd = (a.mwd + (((b.mwd - a.mwd + 180.0) % 360.0) - 180.0) * w) % 360.0
    return round(a.swh + (b.swh - a.swh) * w, 3), mwd


def extract_hours(
    raw: RawForecast,
    spectral: list[SpectralSea] | None = None,
    tide_constants=None,
) -> list[HourForecast]:
    """``tide_constants`` (tide.TideConstants, plan C1-switch): when given, tide_m is
    synthesised locally from the committed EOT20 harmonics for EVERY hour - including
    the day-10-16 tail, where the OM field is null - and the OM sea-level column is
    ignored. Semantics shift with the source: EOT20 is the astronomical tide alone,
    OM's field includes non-tidal sea level (steric/surge; offsets -0.81..+0.41 m
    measured fleet-wide, CALIBRATION.md 2026-08-14). Default None = the OM field,
    unchanged - the pb_0049 A/B decides the flip, not this parameter."""
    marine, from_tail = _merge_models(raw.marine["hourly"])
    weather = raw.weather["hourly"]
    weather_index = {t: i for i, t in enumerate(weather["time"])}
    eot20_tide: list[float] | None = None
    if tide_constants is not None:
        from . import tide as tide_mod  # lazy: pulls numpy/pyTMD only when switched on

        times = [
            datetime.fromisoformat(t).replace(tzinfo=UTC) for t in raw.marine["hourly"]["time"]
        ]
        eot20_tide = tide_mod.predict(tide_constants, times)
    # ensemble (independent members) drives per-hour confidence; aligned by timestamp so a
    # different horizon/ordering can't misalign it. Absent in pre-Stage-1 fixtures → None.
    ens = raw.ensemble["hourly"] if raw.ensemble else None
    ens_index = {t: i for i, t in enumerate(ens["time"])} if ens else {}
    # ECMWF spectral-lite member (Stage 3b), joined per hour by nearest step
    sp_series = sorted(spectral or [], key=lambda s: s.time)
    sp_times = [s.time for s in sp_series]
    # SST comes only from best_match (~9 days); carry the last real reading into the
    # GFS-Wave tail so extended days still show a water temp (it drifts ~1 C/week).
    last_sst: float | None = None

    hours: list[HourForecast] = []
    for i, t in enumerate(marine["time"]):
        if marine["wave_height"][i] is None:
            # Beyond the marine model's horizon (~day 10 the API pads with nulls to
            # forecast_days). Publishing these as flat would fabricate a forecast.
            continue
        j = weather_index.get(t)
        if j is None:
            continue
        wind_speed = weather["wind_speed_10m"][j]
        wind_dir = weather["wind_direction_10m"][j]
        if wind_speed is None or wind_dir is None:
            # the weather API can pad nulls (seen on past_days hours at some points);
            # skipping is honest - a fabricated calm would score as fake offshore
            continue
        partitions = tuple(
            p
            for prefix, kind in _SWELL_PREFIXES
            if (p := _partition(marine, prefix, kind, i)) is not None
        )
        sst = marine["sea_surface_temperature"][i]
        if sst is not None:
            last_sst = sst
        # the source's own combined Hs. Until 2026-07-30 this was read only as the horizon
        # null-sentinel above and discarded; keeping it lets publish report how much of the
        # sea the four partition fields actually account for (transform.partition_closure).
        total_hs = marine["wave_height"][i]
        time = datetime.fromisoformat(t).replace(tzinfo=UTC)
        sp = _nearest_spectral(time, sp_series, sp_times)
        # the ECMWF member joins the OM ensemble as one more independent voice in the
        # per-hour agreement (Stage 1 confidence axis - the plan's "two birds")
        member_hs = (
            member_heights_at(ens, ens_index[t]) if ens is not None and t in ens_index else []
        )
        # member bearings feed Agreement.dir_span_deg, a recorded DIAGNOSTIC only
        # (2026-08-07) - direction does not score until a calibration entry says
        # how (see confidence.py). A member that is SILENT must never widen the fan,
        # so each bearing is appended only when it actually arrived: the published
        # dir_n says how many did (2026-08-11 - the span is a max over pairs, so it
        # is only poolable within a fixed member count).
        member_dirs = (
            member_directions_at(ens, ens_index[t]) if ens is not None and t in ens_index else []
        )
        # ...compared AT this hour, not at the nearest 6-hourly step (see _member_at)
        sp_hs, sp_dir = _member_at(time, sp, sp_series, sp_times)
        if sp_hs is not None:
            member_hs = [*member_hs, sp_hs]
        # the ECMWF member's own total-sea mean direction (SpectralSea.mwd, fetched
        # since Stage 3b) joins the fan. On the OM arm that is like-for-like with OM's
        # wave_direction_<member> - all means, same convention (measured 2026-08-11
        # against the archived OM bearings at four buoys: mean offset -2.6 deg .. +5.1
        # deg, MAE 4-7 deg, so no flip). On the BLEND arm the other member is GFS's
        # dirpw, a PEAK direction, so a blend-era span (dir_n = 2) is peak-vs-mean:
        # never pool it with OM-era spans or fit a direction tolerance to it
        # (CALIBRATION.md 2026-09-13). Both arms carry pb_0048's bimodal-sea caveat.
        # Gated on swh like member_directions_at is on its heights: a member the
        # agreement did not count adds no bearing (2026-09-13).
        if sp_hs is not None and sp_dir is not None:
            member_dirs = [*member_dirs, float(sp_dir) % 360.0]
        agreement = agreement_from_members(member_hs, member_dirs)
        hours.append(
            HourForecast(
                time=time,
                partitions=partitions,
                sst_c=sst if sst is not None else last_sst,
                wind_speed_kph=wind_speed,
                wind_dir_deg=wind_dir,
                wind_gusts_kph=weather["wind_gusts_10m"][j],
                # .get: absent in captures made before these were added to the fetch
                pressure_msl=(pm[j] if (pm := weather.get("pressure_msl")) else None),
                air_c=(ta[j] if (ta := weather.get("temperature_2m")) else None),
                # tide/water level (Stage 2D); .get tolerates fixtures captured before it
                # existed. EOT20 (plan C1-switch) takes over the whole column when on.
                tide_m=(
                    round(eot20_tide[i], 3)
                    if eot20_tide is not None
                    else (sl[i] if (sl := marine.get("sea_level_height_msl")) is not None else None)
                ),
                agreement_score=agreement.score if agreement else None,
                n_models=agreement.n_models if agreement else 0,
                # measured every run but previously dropped here - the payload is the
                # only artifact a run leaves, so an unpersisted diagnostic can never
                # accumulate into the distribution its calibration entry needs
                dir_span_deg=agreement.dir_span_deg if agreement else None,
                # the span's own sample size: without it the recorded distribution
                # mixes 2-member and 4-member fans, and the maximum of k(k-1)/2 pairs
                # grows with k on its own (see confidence.Agreement.n_dirs)
                n_dir_members=agreement.n_dirs if agreement else 0,
                spectral=sp,
                total_hs_m=total_hs,
                from_tail=from_tail[i] if i < len(from_tail) else False,
            )
        )
    return hours
