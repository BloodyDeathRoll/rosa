import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import type { Bucket } from "../types";
import { ratingVar, ratingWord } from "../conditions";
import { gaEvent } from "../ga";
import { DEFAULT_TITLE, SITE } from "../head";
import { CheckIcon, ShareIcon, StarIcon } from "./icons";

/** Share button, left of search in every header that has one (and beside the
    account avatar on desktop). Shares `path` on the canonical site: the OS share
    sheet where there is one, else it copies the link and flashes a check.
    `title` defaults to the screen's own <title>. With no `path` it shares the
    screen on show when clicked - its canonical URL, or the home page for the
    noindex (personal) screens, whose link would only open the reader's own. */
export function ShareButton({
  path,
  title,
  class: cls = "icon-btn",
}: {
  path?: string;
  title?: string;
  class?: string;
}) {
  const [copied, setCopied] = useState(false);
  const share = async () => {
    let target = path;
    let name = title;
    if (target === undefined) {
      const personal = document.head.querySelector('meta[name="robots"]') !== null;
      const canon = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
      target = personal || !canon ? "/" : new URL(canon.href).pathname;
      if (personal) name = DEFAULT_TITLE;
    }
    const url = SITE + target;
    if (navigator.share) {
      try {
        await navigator.share({ title: name ?? document.title, url });
        gaEvent("share", { method: "native", item_id: target });
      } catch {
        // dismissed the sheet - nothing to do
      }
      return;
    }
    try {
      await navigator.clipboard.writeText(url);
      gaEvent("share", { method: "copy", item_id: target });
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked - nothing to do
    }
  };
  return (
    <button class={cls} onClick={() => void share()} aria-label={copied ? "Link copied" : "Share"}>
      {copied ? <CheckIcon /> : <ShareIcon />}
    </button>
  );
}

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
