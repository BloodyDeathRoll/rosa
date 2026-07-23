import { dateOf } from "../format";
import type { HourEntry } from "../types";

/** Real tide curve for the selected day, from the pipeline's per-hour `tide`
    series (total water level vs MSL — Open-Meteo SMOC; null beyond ~day 9).
    Replaces the session-3 mock M2 sine. Samples are 3-hourly, so the curve is
    Catmull-Rom-smoothed and high/low times are parabolically refined between
    neighbours. Med spots are micro-tidal (~0.15 m) — the header says so bluntly;
    macro-tidal spots (Costa Rica ~1.8 m) get real High/Low readouts. */

const W = 326;
const H = 70;
const PAD = 8; // vertical padding inside the viewBox

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
}: {
  /** the spot's full hourly series (neighbouring days pad the curve's edges) */
  hours: HourEntry[];
  /** the selected day (YYYY-MM-DD, spot-local) */
  date: string;
  /** spot-local "now" ISO — set only when the selected day is today */
  nowT?: string | null;
  metric: boolean;
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
          <span class="note">beyond the tide-model horizon — no data yet</span>
        </div>
      </div>
    );
  }

  const vals = pts.map((p) => p.v);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const range = hi - lo;
  const span = Math.max(range, 0.2); // floor so micro-tidal days don't amplify noise
  const yOf = (v: number) => PAD + ((hi - v) / span) * (H - 2 * PAD);
  const xOf = (m: number) => (m / 1440) * W;
  const line = smoothPath(
    pts.map((p) => xOf(p.min)),
    pts.map((p) => yOf(p.v))
  );

  const extremes = findExtremes(pts);
  const highs = extremes.filter((e) => e.kind === "high");
  const lows = extremes.filter((e) => e.kind === "low");

  const nowX = nowT && dateOf(nowT) === date ? xOf(minOf(nowT)).toFixed(1) : null;

  const micro = range < 0.4;
  const note = micro
    ? `~${Math.max(range, 0.1).toFixed(1)} m range — barely matters here`
    : `${fmtTide(lo, metric)} to ${fmtTide(hi, metric)}`;

  return (
    <div class="tide-sec">
      <div class="head">
        <span class="eyebrow">Tide</span>
        <span class="note">{note}</span>
      </div>
      <svg width="358" height="52" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <path d={`${line} L${W},${H} L0,${H} Z`} fill="rgba(217,119,86,0.10)" stroke="none" />
        <path d={line} fill="none" stroke="var(--accent)" stroke-width="1.5" />
        {nowX && (
          <line
            x1={nowX}
            y1="6"
            x2={nowX}
            y2={H - 6}
            stroke="var(--foreground)"
            stroke-width="1"
            stroke-dasharray="2 3"
          />
        )}
      </svg>
      {!micro && (highs.length > 0 || lows.length > 0) && (
        <div class="lohi tabular">
          <span class="hi">
            {highs.map((e) => `High ${fmtMin(e.min)} · ${fmtTide(e.v, metric)}`).join(" / ")}
          </span>
          <span class="lo">
            {lows.map((e) => `Low ${fmtMin(e.min)} · ${fmtTide(e.v, metric)}`).join(" / ")}
          </span>
        </div>
      )}
    </div>
  );
}
