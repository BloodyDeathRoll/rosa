import { useCallback, useEffect, useRef } from "preact/hooks";
import { ratingVar } from "../conditions";
import { SwellDirIcon } from "./icons";
import { arrowRotation, dateOf, dayLabel, dayNum, splitName } from "../format";
import { fmtRange, useUnits } from "../units";
import type { DayEntry, SpotPayload } from "../types";

/** MSW-style multi-day forecast: same spots as the coast grid, drawn as a bar
    chart. One row per spot; each day is a column of intraday height bars (bar
    height ∝ surf size, shared scale across the whole view so spots compare),
    a prevailing-wind arrow above, and a tier-colored range pill below. All
    strips scroll in lock-step. */

const CHART_H = 42; // px - tallest bar
const BAR_MIN = 3; // px - a real but tiny day still shows a stub

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

const COL = 56; // .day-col width in px - keep in sync with styles.css

/** The spot screen's date selector: one horizontal track where each column is a
    day - its label/number/condition-dot stacked directly over that day's bars -
    so date and bars drag as one and always line up. Edge-to-edge: the day at the
    left reading edge drives the rest of the screen live (`onScrub`) and commits
    on release (`onSelect`); a tap selects directly. `live` highlights a day
    mid-scrub; bars scale to this spot's own peak. */
export function DayScrubber({
  data,
  days,
  selected,
  live,
  today,
  onSelect,
  onScrub,
}: {
  data: SpotPayload;
  days: DayEntry[];
  selected: number;
  live?: number;
  today: string;
  onSelect: (i: number) => void;
  onScrub?: (i: number) => void;
}) {
  const units = useUnits();
  const trackRef = useRef<HTMLDivElement>(null);
  // true while our own centering scroll is animating, so its scroll/scrollend
  // aren't mistaken for the user dragging.
  const programmatic = useRef(false);
  const clearTimer = useRef<number | undefined>(undefined);
  const lastScrub = useRef(selected);
  const maxH = Math.max(0.1, ...data.hours.map((h) => h.h_mid));

  // Bring the selected day to the left reading edge, but only when it isn't
  // already on screen - so a tap on a visible day doesn't yank the strip, and a
  // drag commit (which lands flush-left already) is a no-op. Off-screen jumps
  // (spot switch) scroll it into view.
  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    const col = el.children[selected] as HTMLElement | undefined;
    if (!col) return;
    const pad = 12;
    const cLeft = col.offsetLeft;
    const cRight = cLeft + col.offsetWidth;
    if (cLeft >= el.scrollLeft + pad - 1 && cRight <= el.scrollLeft + el.clientWidth) return;
    const target = Math.max(0, cLeft - pad);
    const far = Math.abs(el.scrollLeft - target) > el.clientWidth;
    programmatic.current = true;
    el.scrollTo({ left: target, behavior: far ? "auto" : "smooth" });
    clearTimeout(clearTimer.current);
    clearTimer.current = window.setTimeout(() => (programmatic.current = false), 500);
  }, [selected]);

  useEffect(() => {
    lastScrub.current = selected;
  }, [selected]);

  // Live: as the strip is dragged, report the centered column so the forecast
  // below tracks the finger instead of waiting for the drag to settle.
  useEffect(() => {
    const el = trackRef.current;
    if (!el || !onScrub) return;
    const onScroll = () => {
      if (programmatic.current) return;
      const i = Math.round(el.scrollLeft / COL);
      if (i !== lastScrub.current && i >= 0 && i < days.length) {
        lastScrub.current = i;
        onScrub(i);
      }
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => el.removeEventListener("scroll", onScroll);
  }, [days.length, onScrub]);

  // Settle: commit the centered column when the drag ends.
  useEffect(() => {
    const el = trackRef.current;
    if (!el) return;
    const onScrollEnd = () => {
      if (programmatic.current) {
        programmatic.current = false;
        return;
      }
      const i = Math.round(el.scrollLeft / COL);
      if (i !== selected && i >= 0 && i < days.length) onSelect(i);
    };
    el.addEventListener("scrollend", onScrollEnd);
    return () => el.removeEventListener("scrollend", onScrollEnd);
  }, [selected, days.length, onSelect]);

  const hi = live ?? selected;
  return (
    <div class="day-scrub">
      <div class="track" ref={trackRef}>
        {days.map((day, i) => {
          const { bars, hasAny, wind } = dayColumn(data, day.date);
          const on = i === hi;
          return (
            <button
              key={day.date}
              class={`day-col${on ? " on" : ""}`}
              aria-current={on ? "date" : undefined}
              onClick={() => onSelect(i)}
            >
              <span class="dcol-head">
                <span class="dow">{dayLabel(day.date, today)}</span>
                <span class="dnum tabular">{dayNum(day.date)}</span>
                <span
                  class="day-dot"
                  style={`background:${ratingVar(day.bucket)}`}
                  aria-hidden="true"
                />
              </span>
              <span class="dcol-bars">
                <span class="chart-wind" aria-hidden="true">
                  {wind !== null ? <SwellDirIcon size={13} rotate={arrowRotation(wind)} /> : null}
                </span>
                <span class="chart-plot" style={`height:${CHART_H}px`}>
                  {hasAny ? (
                    bars.map((b, j) => (
                      <span
                        key={j}
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
                <span class="chart-val tabular">{fmtRange(day.h_max, units, false)}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
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
                    {day ? fmtRange(day.h_max, units, false) : "-"}
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
