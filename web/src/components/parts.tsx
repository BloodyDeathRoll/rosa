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

/** Sparkline of a day's surf heights (design's ranked-card proportions,
    110×26 by default; `stretch` fills the container width). */
export function Spark({
  hours,
  bucket,
  w = 110,
  h = 26,
  stretch = false,
}: {
  hours: HourEntry[];
  bucket: Bucket;
  w?: number;
  h?: number;
  stretch?: boolean;
}) {
  if (hours.length < 2) return null;
  // auto-scale to the day's own min/max so intraday shape is visible even on
  // small Med days; the range label beside it carries absolute magnitude. A
  // floor keeps near-flat days from amplifying noise into fake swings.
  const vals = hours.map((x) => x.h_mid);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = Math.max(hi - lo, 0.15);
  const pad = 3;
  const usable = h - 2 * pad;
  const pts = hours.map((x, i) => {
    const px = ((i / (hours.length - 1)) * w).toFixed(1);
    const py = (hi === lo ? h / 2 : pad + ((hi - x.h_mid) / span) * usable).toFixed(1);
    return `${px},${py}`;
  });
  return (
    <svg
      class="spark"
      width={stretch ? "100%" : w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio={stretch ? "none" : undefined}
      aria-hidden="true"
    >
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
