/** Small formatting helpers. All times in payloads are already spot-local ISO strings. */

import type { HourEntry } from "./types";

export function hourOf(iso: string): string {
  return iso.slice(11, 16);
}

export function dateOf(iso: string): string {
  return iso.slice(0, 10);
}

export function dayLabel(date: string, today: string): string {
  if (date === today) return "Today";
  const names = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  return names[new Date(`${date}T12:00:00`).getDay()] ?? date;
}

/** Current calendar date (YYYY-MM-DD) in an IANA timezone - the spot's "today",
    independent of when the pipeline last ran. */
export function todayIn(tz: string): string {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: tz }).format(new Date());
  } catch {
    return new Intl.DateTimeFormat("en-CA").format(new Date());
  }
}

/** Current wall-clock minute in an IANA timezone as a spot-local ISO string
    ("YYYY-MM-DDTHH:MM") - same shape as the payload's local timestamps, but
    live, independent of when the pipeline last ran. */
export function nowIn(tz: string): string {
  try {
    const t = new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      hourCycle: "h23",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date());
    return `${todayIn(tz)}T${t}`;
  } catch {
    return new Date().toISOString().slice(0, 16);
  }
}

/** "Jul 20" style sub-label for a day pill title. */
export function dayDate(date: string): string {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const m = Number(date.slice(5, 7));
  return `${months[m - 1] ?? ""} ${Number(date.slice(8, 10))}`;
}

/** Day-of-month number without leading zero, e.g. "20", "3". */
export function dayNum(date: string): string {
  return String(Number(date.slice(8, 10)));
}

/** Compass arrow rotation: met. directions are "coming FROM", arrow shows where it goes. */
export function arrowRotation(fromDeg: number): number {
  return (fromDeg + 180) % 360;
}

const CARDINALS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];

export function cardinal(deg: number): string {
  return CARDINALS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16] ?? "";
}

/** The design speaks knots. Pipeline publishes kph. */
export function knots(kph: number): number {
  return Math.round(kph / 1.852);
}

/** "E 4 kt offshore" - cardinal, speed, wind class per the design's spot line. */
export function windLabel(h: Pick<HourEntry, "wind">): string {
  return `${cardinal(h.wind.dir)} ${knots(h.wind.kph)} kt ${windClassWord(h.wind.class)}`;
}

/** Short word for the wind class, e.g. "cross-shore" → "cross". */
export function windClassWord(cls: HourEntry["wind"]["class"]): string {
  return cls === "cross-shore" ? "cross" : cls;
}

/** Longest contiguous GOOD+ stretch of a day's (3-hourly) hours.
    `end` is the close of the last good slot, i.e. its start + 3 h. */
export interface BestWindow {
  start: string;
  end: string;
}

export function bestWindow(dayHours: HourEntry[], minRating = 50): BestWindow | null {
  let best: [number, number] | null = null;
  let cur: [number, number] | null = null;
  const keep = (c: [number, number] | null) => {
    if (c && (!best || c[1] - c[0] > best[1] - best[0])) best = c;
  };
  dayHours.forEach((h, i) => {
    if (h.rating >= minRating) {
      if (cur) cur[1] = i;
      else cur = [i, i];
    } else {
      keep(cur);
      cur = null;
    }
  });
  keep(cur);
  if (!best) return null;
  const range = best as [number, number];
  const first = dayHours[range[0]];
  const last = dayHours[range[1]];
  if (!first || !last) return null;
  const endH = (Number(last.t.slice(11, 13)) + 3) % 24;
  return { start: hourOf(first.t), end: `${String(endH).padStart(2, "0")}:00` };
}

/** Pipeline names carry the locality in parens or after a slash
    ("Zvulun (Herzliya)", "Sdot Yam / Caesarea") - split for the
    design's name + muted-region pairing. */
export function splitName(full: string): { name: string; region: string | null } {
  const paren = /^(.*?)\s*\(([^)]+)\)\s*$/.exec(full);
  if (paren?.[1] && paren[2]) return { name: paren[1], region: paren[2] };
  const slash = full.split(" / ");
  if (slash.length === 2 && slash[0] && slash[1]) return { name: slash[0], region: slash[1] };
  return { name: full, region: null };
}
