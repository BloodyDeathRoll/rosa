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

/** `title` is the wide-screen page heading: on a phone the wordmark stands in
    for it (the tab bar already says where you are), on desktop the bar carries
    the wordmark and this becomes the heading (styles.css DESKTOP). */
export function AppHeader({
  lead,
  right,
  title,
}: {
  lead?: ComponentChildren;
  right?: ComponentChildren;
  title?: string;
}) {
  return (
    <header class="app-head">
      <span class="brand">
        <span class="brand-mark" role="img" aria-label="Rosa" />
        {lead ? (
          <span class="brand-lead">{lead}</span>
        ) : (
          <span class="brand-word">
            rosa<span class="brand-dot" aria-hidden="true" />
          </span>
        )}
        {title && <span class="brand-title">{title}</span>}
      </span>
      {right}
    </header>
  );
}
