import { CamIcon } from "./icons";
import { Pill, SpotTitle, StarButton } from "./parts";
import { bestWindow, dateOf, splitName, windLabel } from "../format";
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

/** Compact spot card (Spots/Favorites list): title + rating pill on one line,
    surf range + wind on the next, favorite star pinned right (matching the map
    rows). The whole card is one anchor; the star swallows its own click. */
export function SpotCard({
  data,
  date,
  isFav,
  onToggle,
}: {
  data: SpotPayload;
  date: string;
  isFav?: boolean;
  onToggle?: () => void;
}) {
  const units = useUnits();
  const { name, region } = splitName(data.spot.name);
  const dv = dayView(data, date);
  const href = `#/spot/${data.spot.id}`;
  return (
    <a class="rank-card" href={href}>
      <div class="mid">
        <div class="card-top">
          <SpotTitle name={name} region={region} />
          <Pill bucket={dv.bucket} />
        </div>
        <div class="card-stats tabular">
          <span class="surf-range">{fmtRange(dv.range, units)}</span>
          <span class="wind-stat">{windLabel(dv.rep)}</span>
        </div>
      </div>
      <span class="card-side">
        {data.spot.cam && (
          <span class="cam-mark" title="Live cam">
            <CamIcon />
          </span>
        )}
        {onToggle && <StarButton on={!!isFav} name={name} size={18} onToggle={onToggle} />}
      </span>
    </a>
  );
}
