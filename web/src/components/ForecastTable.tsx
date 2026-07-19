import type { DayEntry, HourEntry } from "../types";
import { cardinal, dateOf, dayLabel, hourOf } from "../format";
import { fmtH, fmtRange, heightUnit, useUnits, type Units } from "../units";
import { BoltIcon, GaugeIcon } from "./icons";
import { DaySpine, DirArrow, HourRail, RatingChip } from "./parts";

/** Wind as one block: value / arrow+cardinal / class. */
function WindBlock({ h }: { h: HourEntry }) {
  return (
    <span class="wind-block">
      <b>{Math.round(h.wind.kph)}</b>
      <span>
        <DirArrow from={h.wind.dir} title={`wind from ${h.wind.dir}°`} />
        {cardinal(h.wind.dir)}
      </span>
      <small>{h.wind.class === "cross-shore" ? "cross" : h.wind.class}</small>
    </span>
  );
}

function HourRow({ h, dayHours, units }: { h: HourEntry; dayHours: HourEntry[]; units: Units }) {
  const swell = h.swells.find((s) => s.in_window) ?? h.swells[0];
  return (
    <div class="row" data-bucket={h.bucket}>
      <span class="t">
        <span class="tlabel">{hourOf(h.t)}</span>
        <HourRail dayHours={dayHours} current={h.t} />
      </span>
      <span class="h">
        <b>{fmtRange(h.h, units, false)}</b>
      </span>
      <span class="swell">
        {swell ? (
          <>
            <b>{fmtH(swell.h, units)}</b>
            <small>
              {swell.period} s · {Math.round(swell.dir)}°
            </small>
          </>
        ) : (
          <small>—</small>
        )}
      </span>
      <WindBlock h={h} />
      <span class="num">{h.energy}</span>
      <span class="num">{h.pressure ?? "—"}</span>
    </div>
  );
}

function HeaderRow({ units }: { units: Units }) {
  return (
    <div class="row head-row" aria-hidden="true">
      <span />
      <span>surf {heightUnit(units)}</span>
      <span>swell</span>
      <span>wind</span>
      <span class="num-h" title="wave power, kW/m">
        <BoltIcon />
      </span>
      <span class="num-h" title="pressure, mb">
        <GaugeIcon />
      </span>
    </div>
  );
}

export function ForecastTable({ hours, days }: { hours: HourEntry[]; days: DayEntry[] }) {
  const units = useUnits();
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
                  <b>{fmtRange(meta.h_max, units)}</b>
                  <RatingChip bucket={meta.bucket} />
                </span>
              )}
            </summary>
            <div class="rows">
              <HeaderRow units={units} />
              {dayHours.map((h) => (
                <HourRow key={h.t} h={h} dayHours={dayHours} units={units} />
              ))}
            </div>
          </details>
        );
      })}
    </section>
  );
}
