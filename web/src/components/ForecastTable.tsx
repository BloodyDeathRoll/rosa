import type { DayEntry, HourEntry } from "../types";
import { dateOf, dayLabel, heightRange, hourOf } from "../format";
import { DaySpine, RatingChip, WindCell } from "./parts";

function HourRow({ h }: { h: HourEntry }) {
  const swell = h.swells.find((s) => s.in_window) ?? h.swells[0];
  return (
    <div class="row" data-bucket={h.bucket}>
      <span class="t">{hourOf(h.t)}</span>
      <span class="h">
        <b>{heightRange(h.h)}</b>
        <small>{h.phrase}</small>
      </span>
      <span class="swell">
        {swell ? (
          <>
            <b>{swell.h} m</b>
            <small>
              {swell.period} s{!swell.in_window && <span title="out of swell window"> · off-window</span>}
            </small>
          </>
        ) : (
          <small>no swell</small>
        )}
      </span>
      <WindCell wind={h.wind} />
      <span class="r" data-bucket={h.bucket}>
        {h.rating}
      </span>
    </div>
  );
}

export function ForecastTable({ hours, days }: { hours: HourEntry[]; days: DayEntry[] }) {
  const byDate = new Map<string, HourEntry[]>();
  for (const h of hours) {
    const d = dateOf(h.t);
    byDate.set(d, [...(byDate.get(d) ?? []), h]);
  }
  const today = hours[0] ? dateOf(hours[0].t) : "";
  const dayMeta = new Map(days.map((d) => [d.date, d]));

  return (
    <section aria-label="7-day forecast">
      {[...byDate.entries()].map(([date, dayHours], i) => {
        const meta = dayMeta.get(date);
        return (
          <details class="day" key={date} open={i === 0}>
            <summary>
              <span class="day-name">{dayLabel(date, today)}</span>
              <span class="day-date">{date.slice(5).replace("-", "/")}</span>
              <DaySpine hours={dayHours} />
              {meta && (
                <span class="day-max">
                  <b>{heightRange(meta.h_max)}</b>
                  <RatingChip bucket={meta.bucket} />
                </span>
              )}
            </summary>
            <div class="rows">
              {dayHours.map((h) => (
                <HourRow key={h.t} h={h} />
              ))}
            </div>
          </details>
        );
      })}
    </section>
  );
}
