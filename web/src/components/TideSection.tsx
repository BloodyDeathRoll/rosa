import { dateOf } from "../format";
import type { HourEntry } from "../types";

/** Real tide curve for the selected day, from the pipeline's per-hour `tide`
    series (total water level vs MSL - Open-Meteo SMOC; null beyond ~day 9).
    Replaces the session-3 mock M2 sine. Samples are 3-hourly, so the curve is
    Catmull-Rom-smoothed and high/low times are parabolically refined between
    neighbours. Med spots are micro-tidal (~0.15 m) - the header says so bluntly;
    macro-tidal spots (Costa Rica ~1.8 m) get real High/Low readouts. */

const W = 326;
const H = 96;
const PAD = 8; // bottom padding inside the viewBox
const LABEL_H = 34; // top strip reserved for the high/low labels

interface Pt {
  min: number; // minutes since day start (can be <0 / >1440 for edge samples)
  v: number; // tide, m
}

interface Extreme {
  min: number;
  v: number;
  kind: "high" | "low";
}

const minOf = (t: string) => Number(t.slice(11, 13)) * 60 + Number(t.slice(14, 16));

const fmtMin = (m: number) => {
  const mm = ((Math.round(m) % 1440) + 1440) % 1440;
  return `${String(Math.floor(mm / 60)).padStart(2, "0")}:${String(mm % 60).padStart(2, "0")}`;
};

const fmtTide = (v: number, metric: boolean) =>
  metric ? `${v.toFixed(1)} m` : `${(v * 3.28084).toFixed(1)} ft`;

/** Local extrema of the sampled series, parabolically refined (3-hourly samples
    → vertex interpolation recovers times to ~minutes). Only extrema inside the
    day [0, 1440) are reported. */
function findExtremes(pts: Pt[]): Extreme[] {
  const out: Extreme[] = [];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i - 1]!.v;
    const b = pts[i]!.v;
    const c = pts[i + 1]!.v;
    const isMax = b >= a && b > c;
    const isMin = b <= a && b < c;
    if (!isMax && !isMin) continue;
    const denom = a - 2 * b + c;
    const off = denom !== 0 ? (0.5 * (a - c)) / denom : 0; // in sample steps
    const step = (pts[i + 1]!.min - pts[i - 1]!.min) / 2;
    const min = pts[i]!.min + off * step;
    const v = b - 0.25 * (a - c) * off;
    if (min < 0 || min >= 1440) continue;
    out.push({ min, v, kind: isMax ? "high" : "low" });
  }
  return out;
}

/** Catmull-Rom → cubic-bezier path through the points (smooth 3-hourly curve). */
function smoothPath(xs: number[], ys: number[]): string {
  if (xs.length < 2) return "";
  let d = `M${xs[0]!.toFixed(1)},${ys[0]!.toFixed(1)}`;
  for (let i = 0; i < xs.length - 1; i++) {
    const x0 = xs[i - 1] ?? xs[i]!;
    const y0 = ys[i - 1] ?? ys[i]!;
    const x1 = xs[i]!;
    const y1 = ys[i]!;
    const x2 = xs[i + 1]!;
    const y2 = ys[i + 1]!;
    const x3 = xs[i + 2] ?? x2;
    const y3 = ys[i + 2] ?? y2;
    const c1x = x1 + (x2 - x0) / 6;
    const c1y = y1 + (y2 - y0) / 6;
    const c2x = x2 - (x3 - x1) / 6;
    const c2y = y2 - (y3 - y1) / 6;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
  }
  return d;
}

export function TideSection({
  hours,
  date,
  nowT,
  metric,
  tideBest,
}: {
  /** the spot's full hourly series (neighbouring days pad the curve's edges) */
  hours: HourEntry[];
  /** the selected day (YYYY-MM-DD, spot-local) */
  date: string;
  /** spot-local "now" ISO - set only when the selected day is today */
  nowT?: string | null;
  metric: boolean;
  /** spot-DB local knowledge - "low" | "mid" | "high" when known */
  tideBest?: string | null;
}) {
  // day's samples ± one neighbour on each side for edge continuity
  const dayIdx = hours.map((h, i) => ({ h, i })).filter(({ h }) => dateOf(h.t) === date);
  const first = dayIdx[0]?.i ?? -1;
  const last = dayIdx[dayIdx.length - 1]?.i ?? -1;
  const pts: Pt[] = [];
  if (first >= 0) {
    for (let i = Math.max(0, first - 1); i <= Math.min(hours.length - 1, last + 1); i++) {
      const h = hours[i]!;
      if (h.tide === null || h.tide === undefined) continue;
      const rel = dateOf(h.t) < date ? -1440 : dateOf(h.t) > date ? 1440 : 0;
      pts.push({ min: minOf(h.t) + rel, v: h.tide });
    }
  }

  if (pts.length < 3) {
    return (
      <div class="tide-sec">
        <div class="head">
          <span class="eyebrow">Tide</span>
          <span class="note">beyond the tide-model horizon - no data yet</span>
        </div>
      </div>
    );
  }

  const vals = pts.map((p) => p.v);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const range = hi - lo;
  const span = Math.max(range, 0.2); // floor so micro-tidal days don't amplify noise
  // curve lives in the lower band; the strip above it belongs to the extreme labels
  const yOf = (v: number) => LABEL_H + ((hi - v) / span) * (H - LABEL_H - PAD);
  const xOf = (m: number) => (m / 1440) * W;
  const line = smoothPath(
    pts.map((p) => xOf(p.min)),
    pts.map((p) => yOf(p.v))
  );

  const extremes = findExtremes(pts);

  const nowX = nowT && dateOf(nowT) === date ? xOf(minOf(nowT)).toFixed(1) : null;

  const micro = range < 0.4;
  const note = micro
    ? `~${Math.max(range, 0.1).toFixed(1)} m range - barely matters here`
    : `${fmtTide(lo, metric)} to ${fmtTide(hi, metric)}`;

  return (
    <div class="tide-sec">
      <div class="head">
        <span class="eyebrow">Tide</span>
        <span class="note">{note}</span>
      </div>
      <div class="tide-chart">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
          {/* Water fades out downwards: --tide-fill at the curve, the same colour
              at zero opacity by the floor. Every instance defines the identical
              gradient, so sharing one id across them is harmless. */}
          <defs>
            <linearGradient id="tide-water" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stop-color="var(--tide-fill)" />
              <stop offset="100%" stop-color="var(--tide-fill)" stop-opacity="0" />
            </linearGradient>
          </defs>
          <path d={`${line} L${W},${H} L0,${H} Z`} fill="url(#tide-water)" stroke="none" />
          {extremes.map((e) => (
            <line
              key={e.min}
              x1={xOf(e.min).toFixed(1)}
              y1={LABEL_H}
              x2={xOf(e.min).toFixed(1)}
              y2={H}
              stroke="var(--tide-mark)"
              stroke-width="1"
            />
          ))}
          <path d={line} fill="none" stroke="var(--accent)" stroke-width="1.5" />
          {nowX && (
            <line
              x1={nowX}
              y1={LABEL_H - 4}
              x2={nowX}
              y2={H - 2}
              stroke="var(--foreground)"
              stroke-width="1"
              stroke-dasharray="2 3"
            />
          )}
        </svg>
        {/* Surfline-style: time + height pinned at each high/low (HTML overlay -
            the svg is stretch-scaled, text inside it would distort) */}
        {extremes.map((e) => (
          <span
            key={e.min}
            class="tide-ext tabular"
            style={`left:${Math.min(93, Math.max(7, (e.min / 1440) * 100)).toFixed(1)}%`}
          >
            <b>{fmtMin(e.min)}</b>
            <small>{fmtTide(e.v, metric)}</small>
          </span>
        ))}
      </div>
      {tideBest && (
        <p class="tide-best">
          Locals surf this spot best around {tideBest === "mid" ? "mid" : tideBest} tide
        </p>
      )}
    </div>
  );
}
