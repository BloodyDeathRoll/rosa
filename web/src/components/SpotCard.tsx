import { Pill, Spark, SpotTitle, StarButton } from "./parts";
import { bestWindow, cardinal, dateOf, splitName, windLabel } from "../format";
import { fmtRange, useUnits } from "../units";
import type { DayEntry, HourEntry, SpotPayload } from "../types";

interface DayView {
  bucket: HourEntry["bucket"];
  range: [number, number];
  rep: HourEntry;
  hrs: HourEntry[];
  bw: ReturnType<typeof bestWindow>;
}

/** A spot's conditions for one calendar day: the day's peak-rating hour drives
    the wind/temp readout, the day summary drives the pill + surf range. */
export function dayView(data: SpotPayload, date: string): DayView {
  const day = data.days.find((d: DayEntry) => d.date === date);
  const hrs = data.hours.filter((h) => dateOf(h.t) === date);
  const rep = [...hrs].sort((a, b) => b.rating - a.rating || b.h_mid - a.h_mid)[0] ?? data.current;
  return {
    bucket: day?.bucket ?? rep.bucket,
    range: day?.h_max ?? data.current.h,
    rep,
    hrs,
    bw: bestWindow(hrs),
  };
}

/** Compact spot card shown on Today (under the featured card) and inside the
    map's bottom sheet. The whole card is one anchor — tapping anywhere on it
    opens the spot forecast. Star toggle sits inline and swallows the click. */
export function SpotCard({
  data,
  date,
  km,
  isFav,
  onToggle,
}: {
  data: SpotPayload;
  date: string;
  km?: number;
  isFav?: boolean;
  onToggle?: () => void;
}) {
  const units = useUnits();
  const { name, region } = splitName(data.spot.name);
  const dv = dayView(data, date);
  const swell = dv.rep.swells.find((s) => s.in_window) ?? dv.rep.swells[0];
  const href = `#/spot/${data.spot.id}`;
  return (
    <a class="rank-card" href={href}>
      <div class="mid">
        <div class="title-row">
          {onToggle && (
            <StarButton
              on={!!isFav}
              name={name}
              size={16}
              onToggle={() => {
                onToggle();
              }}
            />
          )}
          <SpotTitle name={name} region={region} />
        </div>
        <span class="range-row">
          <span class="surf-range tabular">{fmtRange(dv.range, units)}</span>
          <Spark hours={dv.hrs} bucket={dv.bucket} w={110} h={26} />
        </span>
        <span class="line tabular">
          {windLabel(dv.rep)}
          {swell ? ` · ${Math.round(swell.period)} s ${cardinal(swell.dir)}` : ""}
        </span>
      </div>
      <div class="side">
        <Pill bucket={dv.bucket} />
        {km !== undefined && <span class="rank-n tabular">{Math.round(km)} km</span>}
      </div>
    </a>
  );
}
