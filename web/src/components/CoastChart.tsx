import { useCallback, useRef } from "preact/hooks";
import { ratingVar } from "../conditions";
import { SwellDirIcon } from "./icons";
import { arrowRotation, dateOf, dayLabel, dayNum, splitName } from "../format";
import { fmtRange, useUnits } from "../units";
import type { SpotPayload } from "../types";

/** MSW-style multi-day forecast: same spots as the coast grid, drawn as a bar
    chart. One row per spot; each day is a column of intraday height bars (bar
    height ∝ surf size, shared scale across the whole view so spots compare),
    a prevailing-wind arrow above, and a tier-colored range pill below. All
    strips scroll in lock-step. */

const CHART_H = 42; // px — tallest bar
const BAR_MIN = 3; // px — a real but tiny day still shows a stub

// Spot-local daypart windows: morning · midday · evening.
const PERIODS: [number, number][] = [
  [5, 11],
  [11, 16],
  [16, 21],
];

/** Three daypart bars (height = that daypart's peak surf, color = its best-rated
    hour's condition), the prevailing daytime wind, and the day's range/bucket. */
function dayColumn(data: SpotPayload, date: string) {
  const hrs = data.hours.filter((h) => dateOf(h.t) === date);
  const bars = PERIODS.map(([a, b]) => {
    const inP = hrs.filter((h) => {
      const H = Number(h.t.slice(11, 13));
      return H >= a && H < b;
    });
    const first = inP[0];
    if (!first) return null;
    const peak = inP.reduce((m, h) => (h.h_mid > m.h_mid ? h : m), first);
    const best = inP.reduce((m, h) => (h.rating > m.rating ? h : m), first);
    return { h: peak.h_mid, color: ratingVar(best.bucket) };
  });
  // prevailing wind = the daytime hour nearest local noon (falls back to any hour)
  const noon = hrs.reduce<(typeof hrs)[number] | null>((best, h) => {
    const hour = Number(h.t.slice(11, 13));
    const d = Math.abs(hour - 12);
    return !best || d < Math.abs(Number(best.t.slice(11, 13)) - 12) ? h : best;
  }, null);
  const day = data.days.find((d) => d.date === date);
  return { bars, hasAny: hrs.length > 0, wind: noon?.wind.dir ?? null, day };
}

export function CoastChart({
  spots,
  dates,
  today,
}: {
  spots: SpotPayload[];
  dates: string[];
  today: string;
}) {
  const units = useUnits();
  // shared, comparable scale: the tallest bar across every spot + hour shown
  const maxH = Math.max(
    0.1,
    ...spots.flatMap((s) => s.hours.map((h) => h.h_mid)),
  );

  // every scrollable strip registers here so a drag on any one syncs the rest
  const strips = useRef<HTMLElement[]>([]);
  const lock = useRef(false);
  const register = useCallback((el: HTMLDivElement | null) => {
    if (el && !strips.current.includes(el)) strips.current.push(el);
  }, []);
  const onScroll = useCallback((e: Event) => {
    if (lock.current) return;
    lock.current = true;
    const src = e.currentTarget as HTMLElement;
    const x = src.scrollLeft;
    for (const s of strips.current)
      if (s.isConnected && s !== src && s.scrollLeft !== x) s.scrollLeft = x;
    requestAnimationFrame(() => (lock.current = false));
  }, []);

  return (
    <div class="coast">
      <div class="coast-head track" ref={register} onScroll={onScroll}>
        {dates.map((date) => (
          <span key={date} class="coast-day">
            <span class="dow">{dayLabel(date, today)}</span>
            <span class="dnum tabular">{dayNum(date)}</span>
          </span>
        ))}
      </div>
      {spots.map((data) => (
        <a key={data.spot.id} class="coast-row" href={`#/spot/${data.spot.id}`}>
          <span class="coast-name">{splitName(data.spot.name).name}</span>
          <div class="coast-cells track" ref={register} onScroll={onScroll}>
            {dates.map((date) => {
              const { bars, hasAny, wind, day } = dayColumn(data, date);
              return (
                <span key={date} class="chart-col">
                  <span class="chart-wind" aria-hidden="true">
                    {wind !== null ? <SwellDirIcon size={13} rotate={arrowRotation(wind)} /> : null}
                  </span>
                  <span class="chart-plot" style={`height:${CHART_H}px`}>
                    {hasAny ? (
                      bars.map((b, i) => (
                        <span
                          key={i}
                          class={`chart-bar${b === null ? " stub" : ""}`}
                          style={
                            b !== null
                              ? `height:${Math.max(BAR_MIN, (b.h / maxH) * CHART_H)}px;background:${b.color}`
                              : `height:${BAR_MIN}px`
                          }
                        />
                      ))
                    ) : (
                      <span class="chart-empty" />
                    )}
                  </span>
                  <span class="chart-val tabular">
                    {day ? fmtRange(day.h_max, units, false) : "—"}
                  </span>
                </span>
              );
            })}
          </div>
        </a>
      ))}
    </div>
  );
}
