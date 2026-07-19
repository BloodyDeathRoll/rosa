import type { Bucket, HourEntry, Wind } from "../types";
import { arrowRotation } from "../format";

export function RatingChip({ bucket }: { bucket: Bucket }) {
  return (
    <span class="chip" data-bucket={bucket}>
      {bucket}
    </span>
  );
}

/** Rating word as colored text (hero usage, Surfline-style). */
export function BucketWord({ bucket }: { bucket: Bucket }) {
  return (
    <span class="bucket-word" data-bucket={bucket}>
      {bucket}
    </span>
  );
}

export function DirArrow({ from, title }: { from: number; title: string }) {
  return (
    <span class="arrow" title={title} aria-label={title}>
      <svg viewBox="0 0 12 12" style={`transform: rotate(${arrowRotation(from)}deg)`}>
        <path d="M6 1l3.2 7.4L6 6.9 2.8 8.4z" fill="currentColor" />
      </svg>
    </span>
  );
}

export function WindCell({ wind }: { wind: Wind }) {
  return (
    <span class="wind" data-windclass={wind.class}>
      <DirArrow from={wind.dir} title={`wind from ${wind.dir}°`} />
      {Math.round(wind.kph)}
      <small>{wind.class === "cross-shore" ? "cross" : wind.class}</small>
    </span>
  );
}

/** The signature: a day rendered as a strip of 3-hour color segments. */
export function DaySpine({ hours }: { hours: HourEntry[] }) {
  return (
    <span class="spine" aria-hidden="true">
      {hours.map((h) => (
        <i key={h.t} data-bucket={h.bucket} />
      ))}
    </span>
  );
}

/** Vertical day strip for the hour rail — current row's slot emphasized. */
export function HourRail({ dayHours, current }: { dayHours: HourEntry[]; current: string }) {
  return (
    <span class="rail" aria-hidden="true">
      {dayHours.map((h) => (
        <i key={h.t} data-bucket={h.bucket} class={h.t === current ? "on" : ""} />
      ))}
    </span>
  );
}
