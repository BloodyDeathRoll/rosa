import { useCallback, useRef } from "preact/hooks";
import { ratingVar } from "../conditions";
import { dateOf, dayLabel, dayNum, splitName } from "../format";
import { fmtRange, useUnits } from "../units";
import type { Bucket, SpotPayload } from "../types";

/** Surfline-style multi-day coast grid: a shared, horizontally-draggable date
    axis with one row per spot; each day-cell shows the surf range over three
    daypart bars (morning · midday · evening). All strips (the date header and
    every spot row) scroll in lock-step across the whole forecast period. */

// Spot-local hour windows for the three dayparts.
const PERIODS: [number, number][] = [
  [5, 11], // morning
  [11, 16], // midday
  [16, 21], // evening
];

/** Representative bucket per daypart on a date (null = beyond horizon / night). */
function daypartBuckets(data: SpotPayload, date: string): (Bucket | null)[] {
  const hrs = data.hours.filter((h) => dateOf(h.t) === date);
  return PERIODS.map(([a, b]) => {
    const inP = hrs.filter((h) => {
      const H = Number(h.t.slice(11, 13));
      return H >= a && H < b;
    });
    const first = inP[0];
    if (!first) return null;
    return inP.reduce((m, h) => (h.rating > m.rating ? h : m), first).bucket;
  });
}

export function CoastGrid({
  spots,
  dates,
  today,
}: {
  spots: SpotPayload[];
  dates: string[];
  today: string;
}) {
  const units = useUnits();
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
              const day = data.days.find((d) => d.date === date);
              const buckets = daypartBuckets(data, date);
              return (
                <span key={date} class="coast-cell">
                  <span class="coast-h tabular">
                    {day ? fmtRange(day.h_max, units, false) : "—"}
                  </span>
                  <span class="coast-bars">
                    {buckets.map((b, i) => (
                      <span
                        key={i}
                        class="coast-bar"
                        style={`background:${b ? ratingVar(b) : "var(--border)"}`}
                      />
                    ))}
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
