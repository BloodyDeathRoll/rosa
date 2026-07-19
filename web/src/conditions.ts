/** Bucket → display word + color hook, per the Rosa App design handoff.
    Scale hexes live only in styles.css (:root --rating-*); components consume
    `data-bucket` CSS hooks or ratingVar(). */

import type { Bucket } from "./types";

export const WORD: Record<Bucket, string> = {
  FLAT: "Flat",
  POOR: "Poor",
  FAIR: "Fair",
  GOOD: "Good",
  FIRING: "Epic",
};

export function ratingWord(bucket: Bucket): string {
  return WORD[bucket];
}

export function ratingVar(bucket: Bucket): string {
  return `var(--rating-${bucket.toLowerCase()})`;
}
