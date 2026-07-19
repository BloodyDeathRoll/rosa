import type { Bucket, HourEntry } from "../types";
import { arrowRotation } from "../format";
import { tierOf } from "../conditions";

/** Badge: tier background + glyph pairing on tiers 1 and 5 (never color alone). */
export function RatingChip({ bucket }: { bucket: Bucket }) {
  return (
    <span class="chip" data-bucket={bucket}>
      {bucket === "FLAT" && "×"}
      {bucket === "FIRING" && "✓"}
      {bucket}
    </span>
  );
}

/** 8px condition dot — pair with TierLabel or bucket text nearby. */
export function Dot({ bucket }: { bucket: Bucket }) {
  return <i class="dot" data-bucket={bucket} aria-hidden="true" />;
}

export function TierLabel({ bucket }: { bucket: Bucket }) {
  return <span class="tier-label">{tierOf(bucket)}/5</span>;
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

/** Sparkline strip: a day as 3-hour tier segments. */
export function DaySpine({ hours }: { hours: HourEntry[] }) {
  return (
    <span class="spine" aria-hidden="true">
      {hours.map((h) => (
        <i key={h.t} data-bucket={h.bucket} />
      ))}
    </span>
  );
}

/** Vertical day strip for the hour rail — current slot at full tier color, rest dim. */
export function HourRail({ dayHours, current }: { dayHours: HourEntry[]; current: string }) {
  return (
    <span class="rail" aria-hidden="true">
      {dayHours.map((h) => (
        <i key={h.t} data-bucket={h.bucket} class={h.t === current ? "on" : ""} />
      ))}
    </span>
  );
}
