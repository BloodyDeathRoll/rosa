/** Swim mode: the same published forecast, read for a sea swimmer instead of a surfer.

    Everything here is DERIVED in the browser from fields the pipeline already publishes
    (docs/UI.md "Swim mode"). Nothing scores on it upstream, nothing is fetched for it,
    and none of it runs while the Profile toggle is on Surf. Every weight lives in the
    constants block below so the scale can be tuned without touching the presentation. */

import { fmtClock, sunTimes } from "../sun";
import { fmtWind, windUnit, type Units } from "../units";
import type { HourEntry, SpotPayload, WaterClarity, WaterPollution } from "../types";

// ---------------------------------------------------------------------------------
// Tunable constants
// ---------------------------------------------------------------------------------

/** Breaking-wave penalty (surf range midpoint, m): none up to FREE, ramps to
    PENALTY_AT_HEAVY at HEAVY, then on to PENALTY_MAX at FLOOR and above. */
export const BREAK_FREE_M = 0.3;
export const BREAK_HEAVY_M = 1.0;
export const BREAK_FLOOR_M = 1.5;
export const BREAK_PENALTY_AT_HEAVY = 55;
export const BREAK_PENALTY_MAX = 90;

/** Chop: a wind sea (short peak period) driven by the wind. Peak periods at or above
    CHOP_PERIOD_CLEAN_S carry no chop factor; the factor is full at CHOP_PERIOD_FULL_S.
    Penalty = factor × knots × CHOP_PER_KT, capped at CHOP_MAX.
    Calibrated 2026-09-28 at Hilton Beach, Tel Aviv (docs/CALIBRATION.md): the operator in
    the water called 15:00 "choppy and windy" at 11-13 kt onshore (IMS Tel Aviv Coast, gusts
    to 16) over a 4 s wind sea, which the first weights (1.6 / kt, cap 35) scored Calm 81.
    3.5 / kt puts 12 kt on a full wind sea at 58, Choppy; the cap lets a gale reach Stay out. */
export const CHOP_PERIOD_CLEAN_S = 8;
export const CHOP_PERIOD_FULL_S = 4;
export const CHOP_PER_KT = 3.5;
export const CHOP_MAX = 70;

/** Wind pushing a swimmer out (surf-mode "offshore"): knots × PUSH_OUT_PER_KT, capped.
    Chips turn from amber to red at PUSH_OUT_RED_KT. */
export const PUSH_OUT_PER_KT = 1.4;
export const PUSH_OUT_MAX = 25;
export const PUSH_OUT_RED_KT = 12;

/** Clarity: no penalty at or above CLARITY_CLEAR_M Secchi depth, CLARITY_MAX at 0 m. */
export const CLARITY_CLEAR_M = 5;
export const CLARITY_MAX = 20;

/** The card's words. Shore break (the day's figure, m): tiny up to BREAK_FREE_M, small
    up to BREAK_SMALL_M, big below BREAK_HEAVY_M, heavy below BREAK_FLOOR_M, then
    dangerous. Clarity (Secchi depth, m): clear from CLARITY_CLEAR_M, hazy from
    CLARITY_HAZY_M, murky below. */
export const BREAK_SMALL_M = 0.6;
export const CLARITY_HAZY_M = 2.5;
/** Chop words from the hour's chop penalty (0..CHOP_MAX): flat below CHOP_LIGHT, light
    below CHOP_CHOPPY, choppy below CHOP_ROUGH, rough above. */
export const CHOP_LIGHT = 10;
export const CHOP_CHOPPY = 25;
export const CHOP_ROUGH = 45;

/** Score → word. Inverted from surf: Calm is the top. Below OUT_MIN is "Stay out";
    a pollution alert caps the score at OUT_CAP whatever the sea is doing. */
export const CALM_MIN = 80;
export const EASY_MIN = 60;
export const CHOPPY_MIN = 40;
export const ROUGH_MIN = 20;
export const OUT_CAP = ROUGH_MIN - 1;

/** Gear from water temperature (°C): at or above SKINS_C swim in skins, above WETSUIT_C
    a wetsuit, above FULL_C add cap and gloves, below that cold-water caution. */
export const GEAR_SKINS_C = 20;
export const GEAR_WETSUIT_C = 15;
export const GEAR_FULL_C = 11;

/** Rip risk (heuristic): breaking height × peak period, m·s. */
export const RIP_HIGH = 9;
export const RIP_MED = 4;

/** Surge felt at the shore: breaking height × peak period, m·s. */
export const SURGE_HIGH = 7;
export const SURGE_MED = 2.5;

/** Best-swim slots: score at least this (the Easy line) to be called one. */
export const BEST_SWIM_MIN = EASY_MIN;

/** Tide flow: hours at or above this share of the day's fastest |dh/dt| are shaded. */
export const FLOW_FAST_FRAC = 0.75;


// ---------------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------------

export type Mode = "surf" | "swim";
export type SwimBucket = "CALM" | "EASY" | "CHOPPY" | "ROUGH" | "OUT";
export type Level = "low" | "med" | "high";
export type Push = "out" | "in" | "drift";
export type Gear = "skins" | "wetsuit" | "full" | "caution";

export const SWIM_WORD: Record<SwimBucket, string> = {
  CALM: "Calm",
  EASY: "Easy",
  CHOPPY: "Choppy",
  ROUGH: "Rough",
  OUT: "Stay out",
};

export const GEAR_WORD: Record<Gear, string> = {
  skins: "skins",
  wetsuit: "wetsuit",
  full: "wetsuit + cap + gloves",
  caution: "cold-water caution",
};

export const PUSH_WORD: Record<Push, string> = {
  out: "pushes out",
  in: "pushes in",
  drift: "drift",
};

export interface SwimScore {
  score: number;
  bucket: SwimBucket;
  /** each penalty as applied, for the "why" bars */
  pen: { brk: number; chop: number; push: number; clarity: number };
  /** pollution forecast says likely: the score was capped */
  polluted: boolean;
  /** no pollution source for this spot - shown, never silently skipped */
  pollutionUnknown: boolean;
  /** no clarity pixel for this spot */
  clarityUnknown: boolean;
}

// ---------------------------------------------------------------------------------
// Per-hour derivations
// ---------------------------------------------------------------------------------

const clamp01 = (x: number) => Math.max(0, Math.min(1, x));

export const toKnots = (kph: number) => kph / 1.852;

/** The swell the readouts name: the in-window one, else the first published. */
export function mainSwell(h: HourEntry) {
  return h.swells.find((s) => s.in_window) ?? h.swells[0] ?? null;
}

/** Peak period of the named swell, mean period where none is published. */
export function peakPeriod(h: HourEntry): number | null {
  const s = mainSwell(h);
  return s ? (s.peak_period ?? s.period) : null;
}

/** The shortest peak period on the water - the wind sea, when there is one. */
export function windSeaPeriod(h: HourEntry): number | null {
  let best: number | null = null;
  for (const s of h.swells) {
    const p = s.peak_period ?? s.period;
    if (best === null || p < best) best = p;
  }
  return best;
}

export function breakPenalty(hMid: number): number {
  if (hMid <= BREAK_FREE_M) return 0;
  if (hMid <= BREAK_HEAVY_M)
    return (BREAK_PENALTY_AT_HEAVY * (hMid - BREAK_FREE_M)) / (BREAK_HEAVY_M - BREAK_FREE_M);
  if (hMid >= BREAK_FLOOR_M) return BREAK_PENALTY_MAX;
  return (
    BREAK_PENALTY_AT_HEAVY +
    ((BREAK_PENALTY_MAX - BREAK_PENALTY_AT_HEAVY) * (hMid - BREAK_HEAVY_M)) /
      (BREAK_FLOOR_M - BREAK_HEAVY_M)
  );
}

/** 0..1 how much of a wind sea the shortest period describes. */
export function chopFactor(windSeaTp: number | null): number {
  if (windSeaTp === null) return 0;
  return clamp01((CHOP_PERIOD_CLEAN_S - windSeaTp) / (CHOP_PERIOD_CLEAN_S - CHOP_PERIOD_FULL_S));
}

export function chopPenalty(windSeaTp: number | null, kts: number): number {
  return Math.min(CHOP_MAX, chopFactor(windSeaTp) * kts * CHOP_PER_KT);
}

export function pushOf(h: Pick<HourEntry, "wind">): Push {
  return h.wind.class === "offshore" ? "out" : h.wind.class === "onshore" ? "in" : "drift";
}

export function pushPenalty(push: Push, kts: number): number {
  return push === "out" ? Math.min(PUSH_OUT_MAX, kts * PUSH_OUT_PER_KT) : 0;
}

export function clarityPenalty(zsd: number | null): number {
  if (zsd === null) return 0;
  return clamp01((CLARITY_CLEAR_M - zsd) / CLARITY_CLEAR_M) * CLARITY_MAX;
}

export function swimBucket(score: number): SwimBucket {
  if (score >= CALM_MIN) return "CALM";
  if (score >= EASY_MIN) return "EASY";
  if (score >= CHOPPY_MIN) return "CHOPPY";
  if (score >= ROUGH_MIN) return "ROUGH";
  return "OUT";
}

export function swimScore(h: HourEntry, water: SpotPayload["water"] | undefined): SwimScore {
  const kts = toKnots(h.wind.kph);
  const clarity: WaterClarity | null = water?.clarity ?? null;
  const pollution: WaterPollution | null = water?.pollution ?? null;
  const pen = {
    brk: breakPenalty(h.h_mid),
    chop: chopPenalty(windSeaPeriod(h), kts),
    push: pushPenalty(pushOf(h), kts),
    clarity: clarityPenalty(clarity ? clarity.zsd_m : null),
  };
  let score = Math.max(0, Math.round(100 - pen.brk - pen.chop - pen.push - pen.clarity));
  const polluted = pollution?.alert === true;
  if (polluted) score = Math.min(score, OUT_CAP);
  return {
    score,
    bucket: swimBucket(score),
    pen,
    polluted,
    pollutionUnknown: pollution === null,
    clarityUnknown: clarity === null,
  };
}

/** Rip risk - a heuristic from breaking height and peak period, nothing more. */
export function ripLevel(h: HourEntry): Level {
  const tp = peakPeriod(h) ?? 0;
  const x = h.h_mid * tp;
  return x >= RIP_HIGH ? "high" : x >= RIP_MED ? "med" : "low";
}

export function surgeLevel(h: HourEntry): Level {
  const tp = peakPeriod(h) ?? 0;
  const x = h.h_mid * tp;
  return x >= SURGE_HIGH ? "high" : x >= SURGE_MED ? "med" : "low";
}

export function gearFor(sstC: number | null): Gear | null {
  if (sstC === null) return null;
  if (sstC >= GEAR_SKINS_C) return "skins";
  if (sstC >= GEAR_WETSUIT_C) return "wetsuit";
  if (sstC >= GEAR_FULL_C) return "full";
  return "caution";
}

// ---------------------------------------------------------------------------------
// Day derivations
// ---------------------------------------------------------------------------------

/** Minutes-of-day (spot-local) of an hourly slot's start, e.g. "…T03:00" → 180. */
export const slotStartMin = (h: HourEntry) =>
  Number(h.t.slice(11, 13)) * 60 + Number(h.t.slice(14, 16));

/** Daylight test for one day at one spot: slots that start between first and last
    light. The same rule the surf side uses for its best-session chips and day rating. */
export function daylightOf(
  spot: { lat: number; lon: number; timezone: string },
  date: string
): (h: HourEntry) => boolean {
  const sun = sunTimes(new Date(`${date}T12:00:00Z`), spot.lat, spot.lon);
  const toMin = (d: Date) => {
    const [hh, mm] = fmtClock(d, spot.timezone).split(":");
    return Number(hh) * 60 + Number(mm);
  };
  const a = toMin(sun.firstLight);
  const b = toMin(sun.lastLight);
  return (h) => {
    const m = slotStartMin(h);
    return m >= a && m < b;
  };
}

export interface DaySwim {
  /** best daylight hour's score, the day's rating (same daylight rule as surf) */
  score: number;
  bucket: SwimBucket;
  /** the day's mean water temperature, °C - one value for the whole day */
  sst: number | null;
  /** worst daylight penalties, for the card's bars */
  worst: { chop: number; push: number; surge: number };
  polluted: boolean;
  pollutionUnknown: boolean;
}

/** The day's swim reading over the hours `daylight` admits (spot-local minutes-of-day
    of a slot's start). With no daylight hour published, every hour counts. */
export function daySwim(
  dayHours: HourEntry[],
  water: SpotPayload["water"] | undefined,
  daylight: (h: HourEntry) => boolean
): DaySwim {
  const lit = dayHours.filter(daylight);
  const pool = lit.length ? lit : dayHours;
  const scores = pool.map((h) => swimScore(h, water));
  const score = scores.length ? Math.max(...scores.map((s) => s.score)) : 0;
  const ssts = dayHours.map((h) => h.sst).filter((v): v is number => v !== null);
  const sst = ssts.length ? ssts.reduce((a, b) => a + b, 0) / ssts.length : null;
  const surge = pool.length ? Math.max(...pool.map((h) => h.h_mid * (peakPeriod(h) ?? 0))) : 0;
  const first = scores[0];
  return {
    score,
    bucket: swimBucket(score),
    sst,
    worst: {
      chop: scores.length ? Math.max(...scores.map((s) => s.pen.chop)) : 0,
      push: scores.length ? Math.max(...scores.map((s) => s.pen.push)) : 0,
      surge,
    },
    polluted: first?.polluted ?? water?.pollution?.alert === true,
    pollutionUnknown: first?.pollutionUnknown ?? !water?.pollution,
  };
}

/** Blunt day note in the app's voice, from the swim scores of the day. */
export function swimNote(dayHours: HourEntry[], water: SpotPayload["water"] | undefined): string {
  if (dayHours.length === 0) return "";
  const scored = dayHours.map((h) => ({ h, s: swimScore(h, water) }));
  if (scored.some((x) => x.s.polluted)) return "Pollution likely - stay out";
  const am = scored.filter((x) => Number(x.h.t.slice(11, 13)) < 12);
  const pm = scored.filter((x) => Number(x.h.t.slice(11, 13)) >= 12);
  const best = Math.max(...scored.map((x) => x.s.score));
  const amBest = am.length ? Math.max(...am.map((x) => x.s.score)) : best;
  const pmBest = pm.length ? Math.max(...pm.map((x) => x.s.score)) : best;
  const bucket = swimBucket(best);
  if (bucket === "OUT") return "Shore break - stay out";
  if (bucket === "ROUGH") return "Rough - experienced swimmers only";
  if (amBest >= EASY_MIN && pmBest < CHOPPY_MIN) return "Calm early, choppy by noon";
  if (pmBest >= EASY_MIN && amBest < CHOPPY_MIN) return "Settles in the afternoon";
  if (bucket === "CALM") return "Glassy - go any time";
  if (bucket === "EASY") return "Easy going";
  return "Choppy - pick your hour";
}

// ---------------------------------------------------------------------------------
// Tide flow
// ---------------------------------------------------------------------------------

export interface FlowSample {
  min: number; // minutes since day start
  rate: number; // |dh/dt|, m per hour
}

/** |dh/dt| at each sample by central difference (one-sided at the ends). */
export function tideFlow(pts: { min: number; v: number }[]): FlowSample[] {
  return pts.map((p, i) => {
    const a = pts[i - 1] ?? p;
    const b = pts[i + 1] ?? p;
    const dt = (b.min - a.min) / 60;
    return { min: p.min, rate: dt > 0 ? Math.abs(b.v - a.v) / dt : 0 };
  });
}

/** Samples running at or above FLOW_FAST_FRAC of the day's fastest flow. */
export function fastFlow(flow: FlowSample[]): FlowSample[] {
  const max = Math.max(0, ...flow.map((f) => f.rate));
  if (max <= 0) return [];
  return flow.filter((f) => f.rate >= max * FLOW_FAST_FRAC);
}

/** Slack = a turn of the tide: a local high or low of the sampled series. */
export function slackTurns(pts: { min: number; v: number }[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < pts.length - 1; i++) {
    const a = pts[i - 1]!.v;
    const b = pts[i]!.v;
    const c = pts[i + 1]!.v;
    if ((b >= a && b > c) || (b <= a && b < c)) out.push(pts[i]!.min);
  }
  return out;
}

/** |dh/dt| at an hour, from the spot's full series (m/h). 0 where tide is unpublished. */
export function flowAt(hours: HourEntry[], h: HourEntry): number {
  const i = hours.indexOf(h);
  const a = hours[i - 1] ?? h;
  const b = hours[i + 1] ?? h;
  if (a.tide === null || b.tide === null || h.tide === null) return 0;
  const dt = (Date.parse(b.t) - Date.parse(a.t)) / 3_600_000;
  return dt > 0 ? Math.abs(b.tide - a.tide) / dt : 0;
}

/** Best-swim slots: up to three daylight hours at or above BEST_SWIM_MIN, highest
    score first, a slacker tide breaking ties; returned in time order. */
export function bestSwim(
  dayHours: HourEntry[],
  allHours: HourEntry[],
  water: SpotPayload["water"] | undefined,
  daylight: (h: HourEntry) => boolean
): HourEntry[] {
  return dayHours
    .filter(daylight)
    .map((h) => ({ h, s: swimScore(h, water).score, f: flowAt(allHours, h) }))
    .filter((x) => x.s >= BEST_SWIM_MIN)
    .sort((a, b) => b.s - a.s || a.f - b.f)
    .slice(0, 3)
    .map((x) => x.h)
    .sort((a, b) => (a.t < b.t ? -1 : 1));
}

// ---------------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------------

/** How far the hour rail fills, one fifth per tier - Calm runs full. */
export const SWIM_RAIL_FILL: Record<SwimBucket, number> = {
  OUT: 20,
  ROUGH: 40,
  CHOPPY: 60,
  EASY: 80,
  CALM: 100,
};

export function swimVar(bucket: SwimBucket): string {
  return `var(--swim-${bucket.toLowerCase()})`;
}

/** Shore break as one figure: cm, or inches when the reader's heights are in feet. */
export function shoreBreak(hMid: number, feet: boolean): { n: string; unit: string } {
  return feet
    ? { n: String(Math.round(hMid * 39.3701)), unit: "in" }
    : { n: String(Math.round(hMid * 100)), unit: "cm" };
}

/** A shore that is not for swimming; the spot DB says so (`shore` in the yaml). */
export function rockyEntry(shore: string | undefined): boolean {
  return shore === "rock" || shore === "reef";
}

// ---------------------------------------------------------------------------------
// One spot, one day - what every card outside the spot page shows
// ---------------------------------------------------------------------------------

export interface SwimDayView {
  /** best daylight hour's swim score, the day's rating */
  score: number;
  bucket: SwimBucket;
  /** shore break, m: midpoint of the day's surf range (the day strip's figure) */
  brkM: number;
  /** the best daylight swim hour - the card's wind, air and water readout */
  rep: HourEntry | null;
  gear: Gear | null;
  /** the spot DB says rock / reef: not a swimming beach */
  rocky: boolean;
}

export function swimDayView(data: SpotPayload, date: string): SwimDayView {
  const hrs = data.hours.filter((h) => h.t.slice(0, 10) === date);
  const lit = daylightOf(data.spot, date);
  const d = daySwim(hrs, data.water, lit);
  const litHrs = hrs.filter(lit);
  const pool = litHrs.length ? litHrs : hrs;
  let rep: HourEntry | null = null;
  let repScore = -1;
  for (const h of pool) {
    const s = swimScore(h, data.water).score;
    if (s > repScore) {
      rep = h;
      repScore = s;
    }
  }
  const day = data.days.find((x) => x.date === date);
  const range = day?.h_max ?? data.current.h;
  return {
    score: d.score,
    bucket: d.bucket,
    brkM: (range[0] + range[1]) / 2,
    rep,
    gear: gearFor(d.sst ?? data.current.sst),
    rocky: rockyEntry(data.spot.shore),
  };
}

/** The card's one-line wind readout in swim words: "WNW 13 km/h pushes in". */
export function swimWindLabel(h: Pick<HourEntry, "wind">, u: Units): string {
  const i = Math.round((((h.wind.dir % 360) + 360) % 360) / 22.5) % 16;
  const card = CARDINALS[i] ?? "";
  return `${card} ${fmtWind(h.wind.kph, u)} ${windUnit(u)} ${PUSH_WORD[pushOf(h)]}`;
}

const CARDINALS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];

// ---------------------------------------------------------------------------------
// The swim card's words - one per factor, on the swim colours
// ---------------------------------------------------------------------------------

export interface FactorWord {
  word: string;
  bucket: SwimBucket;
}

export function breakWord(m: number): FactorWord {
  if (m <= BREAK_FREE_M) return { word: "tiny", bucket: "CALM" };
  if (m <= BREAK_SMALL_M) return { word: "small", bucket: "EASY" };
  if (m < BREAK_HEAVY_M) return { word: "big", bucket: "CHOPPY" };
  if (m < BREAK_FLOOR_M) return { word: "heavy", bucket: "ROUGH" };
  return { word: "dangerous", bucket: "OUT" };
}

export function surgeWord(level: Level): FactorWord {
  return level === "low"
    ? { word: "low", bucket: "CALM" }
    : level === "med"
      ? { word: "med", bucket: "CHOPPY" }
      : { word: "high", bucket: "ROUGH" };
}

export function pushWord(h: Pick<HourEntry, "wind">): FactorWord {
  const p = pushOf(h);
  if (p !== "out") return { word: PUSH_WORD[p], bucket: "CALM" };
  return { word: PUSH_WORD.out, bucket: toKnots(h.wind.kph) >= PUSH_OUT_RED_KT ? "ROUGH" : "CHOPPY" };
}

export function clarityWord(zsd: number): FactorWord {
  if (zsd >= CLARITY_CLEAR_M) return { word: "clear", bucket: "CALM" };
  if (zsd >= CLARITY_HAZY_M) return { word: "hazy", bucket: "CHOPPY" };
  return { word: "murky", bucket: "ROUGH" };
}

export function chopWord(penalty: number): FactorWord {
  if (penalty < CHOP_LIGHT) return { word: "flat", bucket: "CALM" };
  if (penalty < CHOP_CHOPPY) return { word: "light", bucket: "EASY" };
  if (penalty < CHOP_ROUGH) return { word: "choppy", bucket: "CHOPPY" };
  return { word: "rough", bucket: "ROUGH" };
}

