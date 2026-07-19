/** Central bucket→tier mapping per docs/rosa-conditions-color-system.md.
    Components consume `data-bucket` CSS hooks or conditionVar(); nothing else
    may know tier hexes — they live only in the two theme blocks. */

import type { Bucket } from "./types";

export type Tier = 1 | 2 | 3 | 4 | 5;

export const TIER: Record<Bucket, Tier> = {
  FLAT: 1,
  POOR: 2,
  FAIR: 3,
  GOOD: 4,
  FIRING: 5,
};

export function tierOf(bucket: Bucket): Tier {
  return TIER[bucket];
}

export function conditionVar(bucket: Bucket): string {
  return `var(--cond-${TIER[bucket]})`;
}

/** Blunt, dry, honest. Rotating variants so it never feels canned. */
const VERDICTS: Record<Tier, string[]> = {
  1: ["Go home.", "It's a lake.", "Nothing to ride.", "Flat. Check back tomorrow."],
  2: ["Junk. Desperation only.", "Barely waves.", "You'd regret the drive.", "Scraps out there."],
  3: [
    "Rideable. Manage expectations.",
    "Workable windows.",
    "Not great, not nothing.",
    "Could sneak a few.",
  ],
  4: ["Go.", "Worth the dawn alarm.", "Solid. Get out there.", "Proper waves today."],
  5: ["Drop everything.", "It's on. Go now!", "As good as it gets here.", "Call in sick."],
};

export function verdictFor(bucket: Bucket, seed: string): string {
  const list = VERDICTS[TIER[bucket]];
  let h = 0;
  for (const c of seed) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return list[h % list.length] ?? list[0]!;
}
