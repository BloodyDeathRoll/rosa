import type { ComponentChildren } from "preact";
import type { Bucket } from "../types";
import { ratingVar, ratingWord } from "../conditions";
import { StarIcon } from "./icons";

/** Rating pill - bucket word on a translucent tint of the tier color. */
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
      onClick={(e) => {
        // when nested inside a clickable card, favoriting must never navigate
        e.preventDefault();
        e.stopPropagation();
        onToggle();
      }}
    >
      <StarIcon size={size} />
    </button>
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

export function AppHeader({ lead, right }: { lead?: ComponentChildren; right?: ComponentChildren }) {
  return (
    <header class="app-head">
      <span class="brand">
        <img class="brand-mark" src="/favicon.svg" alt="Rosa" />
        {lead ? (
          <span class="brand-lead">{lead}</span>
        ) : (
          <span class="brand-word">
            rosa<span class="brand-dot" aria-hidden="true" />
          </span>
        )}
      </span>
      {right}
    </header>
  );
}
