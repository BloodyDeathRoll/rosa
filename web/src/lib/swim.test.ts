import { describe, expect, it } from "vitest";
import type { HourEntry, SpotPayload } from "../types";
import {
  BREAK_FLOOR_M,
  BREAK_FREE_M,
  BREAK_HEAVY_M,
  BREAK_PENALTY_AT_HEAVY,
  BREAK_PENALTY_MAX,
  bestSwim,
  breakPenalty,
  chopPenalty,
  daySwim,
  fastFlow,
  gearFor,
  GEAR_FULL_C,
  GEAR_SKINS_C,
  GEAR_WETSUIT_C,
  OUT_CAP,
  pushOf,
  ripLevel,
  rockyEntry,
  shoreBreak,
  slackTurns,
  surgeLevel,
  swimBucket,
  swimScore,
  tideFlow,
} from "./swim";

function hour(over: Partial<HourEntry> & { tp?: number | null; kts?: number } = {}): HourEntry {
  const { tp = 10, kts = 5, ...rest } = over;
  const h_mid = rest.h_mid ?? 0.2;
  return {
    t: rest.t ?? "2026-09-28T09:00+10:00",
    rating: 0,
    bucket: "POOR",
    h: [h_mid, h_mid],
    h_mid,
    phrase: "",
    energy_kj: 10,
    pressure: 1015,
    air: 20,
    wind: { kph: kts * 1.852, dir: 90, class: "cross-shore" },
    sst: 21,
    tide: 0,
    swells: [{ h: 0.5, period: 7, peak_period: tp, dir: 180, kind: "swell", in_window: true }],
    ...rest,
  };
}

const clearWater: SpotPayload["water"] = {
  clarity: { zsd_m: 12, date: "2026-09-26", cadence: "daily" },
  pollution: { grade: 4, label: "Good", alert: false, cadence: "daily", date: "2026-09-28", src: "nsw" },
};

describe("swim score", () => {
  it("a flat, glassy, clear hour is Calm at 100", () => {
    const s = swimScore(hour({ h_mid: 0.1, tp: 12, kts: 2 }), clearWater);
    expect(s.score).toBe(100);
    expect(s.bucket).toBe("CALM");
    expect(s.pollutionUnknown).toBe(false);
    expect(s.clarityUnknown).toBe(false);
  });

  it("break penalty: none to 0.3 m, heavy by 1 m, floor from 1.5 m", () => {
    expect(breakPenalty(BREAK_FREE_M)).toBe(0);
    expect(breakPenalty(0.65)).toBeCloseTo(BREAK_PENALTY_AT_HEAVY / 2, 5);
    expect(breakPenalty(BREAK_HEAVY_M)).toBe(BREAK_PENALTY_AT_HEAVY);
    expect(breakPenalty(BREAK_FLOOR_M)).toBe(BREAK_PENALTY_MAX);
    expect(breakPenalty(3)).toBe(BREAK_PENALTY_MAX);
    // a metre and a half of shore break is Stay out on its own
    expect(swimScore(hour({ h_mid: 1.5 }), clearWater).bucket).toBe("OUT");
  });

  it("chop: a short-period sea costs by the knot, a long-period swell costs nothing", () => {
    expect(chopPenalty(12, 20)).toBe(0);
    expect(chopPenalty(4, 10)).toBeGreaterThan(chopPenalty(6, 10));
    expect(chopPenalty(4, 10)).toBeGreaterThan(chopPenalty(4, 5));
    expect(chopPenalty(null, 20)).toBe(0);
  });

  it("wind pushing out (surf offshore) costs extra; pushing in does not", () => {
    const out = swimScore(hour({ wind: { kph: 10 * 1.852, dir: 90, class: "offshore" } }), clearWater);
    const inn = swimScore(hour({ wind: { kph: 10 * 1.852, dir: 270, class: "onshore" } }), clearWater);
    expect(out.pen.push).toBeGreaterThan(0);
    expect(inn.pen.push).toBe(0);
    expect(out.score).toBeLessThan(inn.score);
    expect(pushOf(hour({ wind: { kph: 1, dir: 0, class: "offshore" } }))).toBe("out");
    expect(pushOf(hour({ wind: { kph: 1, dir: 0, class: "onshore" } }))).toBe("in");
    expect(pushOf(hour({ wind: { kph: 1, dir: 0, class: "cross-shore" } }))).toBe("drift");
  });

  it("clarity: a penalty as Secchi depth falls below 5 m, none above, unknown when absent", () => {
    const murky = { ...clearWater!, clarity: { zsd_m: 1, date: "", cadence: "daily" as const } };
    const clear = swimScore(hour(), clearWater);
    const dim = swimScore(hour(), murky);
    expect(clear.pen.clarity).toBe(0);
    expect(dim.pen.clarity).toBeGreaterThan(0);
    const none = swimScore(hour(), { clarity: null, pollution: null });
    expect(none.pen.clarity).toBe(0);
    expect(none.clarityUnknown).toBe(true);
    expect(none.pollutionUnknown).toBe(true);
    expect(none.score).toBe(clear.score); // no data is not a penalty
  });

  it("a pollution alert caps the hour at Stay out", () => {
    const alert = { ...clearWater!, pollution: { ...clearWater!.pollution!, alert: true } };
    const s = swimScore(hour({ h_mid: 0.1, tp: 12, kts: 2 }), alert);
    expect(s.score).toBe(OUT_CAP);
    expect(s.bucket).toBe("OUT");
    expect(s.polluted).toBe(true);
  });

  it("buckets run Calm / Easy / Choppy / Rough / Stay out", () => {
    expect(swimBucket(100)).toBe("CALM");
    expect(swimBucket(80)).toBe("CALM");
    expect(swimBucket(79)).toBe("EASY");
    expect(swimBucket(60)).toBe("EASY");
    expect(swimBucket(59)).toBe("CHOPPY");
    expect(swimBucket(40)).toBe("CHOPPY");
    expect(swimBucket(39)).toBe("ROUGH");
    expect(swimBucket(20)).toBe("ROUGH");
    expect(swimBucket(19)).toBe("OUT");
    expect(swimBucket(0)).toBe("OUT");
  });
});

describe("gear bands", () => {
  it("follow the water temperature thresholds", () => {
    expect(gearFor(GEAR_SKINS_C)).toBe("skins");
    expect(gearFor(GEAR_SKINS_C - 0.1)).toBe("wetsuit");
    expect(gearFor(GEAR_WETSUIT_C)).toBe("wetsuit");
    expect(gearFor(GEAR_WETSUIT_C - 0.1)).toBe("full");
    expect(gearFor(GEAR_FULL_C)).toBe("full");
    expect(gearFor(GEAR_FULL_C - 0.1)).toBe("caution");
    expect(gearFor(null)).toBeNull();
  });
});

describe("rip flag", () => {
  it("rises with height and period together", () => {
    expect(ripLevel(hour({ h_mid: 0.2, tp: 8 }))).toBe("low");
    expect(ripLevel(hour({ h_mid: 0.5, tp: 9 }))).toBe("med");
    expect(ripLevel(hour({ h_mid: 1.0, tp: 12 }))).toBe("high");
    // same height, longer period: more risk
    expect(ripLevel(hour({ h_mid: 0.6, tp: 6 }))).toBe("low");
    expect(ripLevel(hour({ h_mid: 0.6, tp: 16 }))).toBe("high");
  });
  it("surge word uses the same product with lower thresholds", () => {
    expect(surgeLevel(hour({ h_mid: 0.1, tp: 8 }))).toBe("low");
    expect(surgeLevel(hour({ h_mid: 0.3, tp: 10 }))).toBe("med");
    expect(surgeLevel(hour({ h_mid: 0.8, tp: 12 }))).toBe("high");
  });
});

describe("tide slack and flow", () => {
  // a semi-diurnal day sampled 3-hourly: high at 06:00, low at 12:00, high at 18:00
  const pts = [0, 3, 6, 9, 12, 15, 18, 21, 24].map((hh) => ({
    min: hh * 60,
    v: Math.cos(((hh - 6) / 6) * Math.PI),
  }));

  it("finds a slack at each turn of the tide", () => {
    expect(slackTurns(pts)).toEqual([360, 720, 1080]);
  });

  it("flow is fastest between the turns and zero at them", () => {
    const flow = tideFlow(pts);
    const at = (min: number) => flow.find((f) => f.min === min)!.rate;
    expect(at(360)).toBeCloseTo(0, 6);
    expect(at(720)).toBeCloseTo(0, 6);
    expect(at(540)).toBeGreaterThan(at(360));
    const fast = fastFlow(flow).map((f) => f.min);
    expect(fast).toContain(540);
    expect(fast).toContain(900);
    expect(fast).not.toContain(360);
    expect(fast).not.toContain(720);
    expect(fastFlow(tideFlow(pts.map((p) => ({ ...p, v: 0 }))))).toEqual([]);
  });
});

describe("day and best swim", () => {
  const T = (hh: number) => `2026-09-28T${String(hh).padStart(2, "0")}:00+10:00`;
  const daylight = (h: HourEntry) => {
    const hh = Number(h.t.slice(11, 13));
    return hh >= 6 && hh < 18;
  };

  it("day rating is the best daylight hour; a perfect 3am does not count", () => {
    const hours = [
      hour({ t: T(3), h_mid: 0.05, tp: 12, kts: 1 }), // perfect, dark
      hour({ t: T(9), h_mid: 0.9, tp: 6, kts: 15 }),
      hour({ t: T(12), h_mid: 1.0, tp: 6, kts: 18 }),
    ];
    const d = daySwim(hours, clearWater, daylight);
    expect(d.score).toBe(swimScore(hours[1]!, clearWater).score);
    expect(d.score).toBeLessThan(100);
    expect(d.sst).toBe(21);
  });

  it("best swim picks the top daylight hours, a slacker tide breaking ties", () => {
    const same = { h_mid: 0.1, tp: 12, kts: 2 };
    const hours = [
      hour({ ...same, t: T(3), tide: 0.0 }),
      hour({ ...same, t: T(6), tide: 0.5 }), // rising fast
      hour({ ...same, t: T(9), tide: 1.0 }), // high water: slack
      hour({ ...same, t: T(12), tide: 0.5 }),
      hour({ ...same, t: T(15), tide: 0.0 }), // low water: slack
      hour({ ...same, t: T(18), tide: 0.5 }),
      hour({ t: T(21), h_mid: 1.6, tide: 1.0 }),
    ];
    const best = bestSwim(hours, hours, clearWater, daylight);
    expect(best.map((h) => h.t.slice(11, 13))).toEqual(["06", "09", "15"]);
    // the two slacks rank above the fast-flowing 06:00 and 12:00
    const ranked = bestSwim(hours, hours, clearWater, daylight).map((h) => h.t.slice(11, 13));
    expect(ranked).toContain("09");
    expect(ranked).toContain("15");
    // nothing above the Easy line: no chips at all
    expect(bestSwim([hour({ t: T(9), h_mid: 1.6 })], hours, clearWater, daylight)).toEqual([]);
  });
});

describe("display helpers", () => {
  it("shore break is one figure in cm, or inches under feet", () => {
    expect(shoreBreak(0.45, false)).toEqual({ n: "45", unit: "cm" });
    expect(shoreBreak(0.5, true)).toEqual({ n: "20", unit: "in" });
  });
  it("rock and reef shores are not swimming beaches", () => {
    expect(rockyEntry("rock")).toBe(true);
    expect(rockyEntry("reef")).toBe(true);
    expect(rockyEntry("sand")).toBe(false);
    expect(rockyEntry("mixed")).toBe(false);
    expect(rockyEntry(undefined)).toBe(false);
  });
});

describe("card words", () => {
  it("shore break, clarity and push words follow their thresholds", async () => {
    const { breakWord, clarityWord, pushWord } = await import("./swim");
    expect(breakWord(0.25).word).toBe("tiny");
    expect(breakWord(0.45).word).toBe("small");
    expect(breakWord(0.8).word).toBe("big");
    expect(breakWord(1.2).word).toBe("heavy");
    expect(breakWord(1.6).word).toBe("dangerous");
    expect(clarityWord(8.8).word).toBe("clear");
    expect(clarityWord(3).word).toBe("hazy");
    expect(clarityWord(1).word).toBe("murky");
    expect(pushWord({ wind: { kph: 5 * 1.852, dir: 0, class: "offshore" } }).bucket).toBe("CHOPPY");
    expect(pushWord({ wind: { kph: 15 * 1.852, dir: 0, class: "offshore" } }).bucket).toBe("ROUGH");
    expect(pushWord({ wind: { kph: 15 * 1.852, dir: 0, class: "onshore" } }).word).toBe("pushes in");
  });
});
