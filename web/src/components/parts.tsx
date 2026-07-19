import type { ComponentChildren } from "preact";
import type { Bucket, HourEntry } from "../types";
import { ratingVar, ratingWord } from "../conditions";
import { StarIcon } from "./icons";

/** Rating pill — bucket word on a translucent tint of the tier color. */
export function Pill({ bucket }: { bucket: Bucket }) {
  return (
    <span class="pill" data-bucket={bucket}>
      {ratingWord(bucket)}
    </span>
  );
}

/** 10px tier-colored dot for spot rows. */
export function TierDot({ bucket }: { bucket: Bucket }) {
  return <span class="tier-dot" style={`background:${ratingVar(bucket)}`} aria-hidden="true" />;
}

export function StarButton({
  on,
  name,
  size = 17,
  onToggle,
}: {
  on: boolean;
  name: string;
  size?: number;
  onToggle: () => void;
}) {
  return (
    <button
      class={`star-btn${on ? " on" : ""}`}
      aria-pressed={on}
      aria-label={on ? `Remove ${name} from favorites` : `Add ${name} to favorites`}
      onClick={onToggle}
    >
      <StarIcon size={size} />
    </button>
  );
}

/** 110×26 sparkline of a day's surf heights, per the design's ranked card. */
export function Spark({ hours, bucket }: { hours: HourEntry[]; bucket: Bucket }) {
  if (hours.length < 2) return null;
  const pts = hours.map(
    (h, i) =>
      `${((i / (hours.length - 1)) * 110).toFixed(1)},${(24 - Math.min(1, h.h_mid / 1.3) * 20).toFixed(1)}`
  );
  return (
    <svg class="spark" width="110" height="26" viewBox="0 0 110 26" aria-hidden="true">
      <path
        d={`M${pts.join(" L")}`}
        fill="none"
        stroke={ratingVar(bucket)}
        stroke-width="1.5"
        stroke-linecap="round"
      />
    </svg>
  );
}

/** Bold name + muted region, baseline-aligned. */
export function SpotTitle({ name, region }: { name: string; region: string | null }) {
  return (
    <span class="spot-title">
      <b>{name}</b>
      {region && <small>{region}</small>}
    </span>
  );
}

export function AppHeader({ right }: { right?: ComponentChildren }) {
  return (
    <header class="app-head">
      <span class="brand">
        rosa<i>.</i>
      </span>
      {right}
    </header>
  );
}
