import { useEffect, useState } from "preact/hooks";
import { gaSetPrefs, unitsTag } from "./ga";

export interface Units {
  temp: "c" | "f";
  height: "m" | "ft";
}

const KEY = "rosa.units";
const EVENT = "rosa:units";
const DEFAULTS: Units = { temp: "c", height: "m" };

export function getUnits(): Units {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Units>;
    return {
      temp: parsed.temp === "f" ? "f" : "c",
      height: parsed.height === "ft" ? "ft" : "m",
    };
  } catch {
    return DEFAULTS;
  }
}

export function setUnits(units: Units): void {
  localStorage.setItem(KEY, JSON.stringify(units));
  gaSetPrefs({ units: unitsTag(units) });
  dispatchEvent(new Event(EVENT));
}

export function useUnits(): Units {
  const [units, set] = useState<Units>(getUnits);
  useEffect(() => {
    const onChange = () => set(getUnits());
    addEventListener(EVENT, onChange);
    return () => removeEventListener(EVENT, onChange);
  }, []);
  return units;
}

const toFt = (m: number) => Math.max(1, Math.round(m * 3.28084)); // whole feet, floor 1 (design)

export function fmtH(m: number, u: Units): string {
  return u.height === "ft" ? String(toFt(m)) : (Math.round(m * 10) / 10).toFixed(1);
}

export function heightUnit(u: Units): string {
  return u.height === "ft" ? "ft" : "m";
}

export function fmtRange(h: [number, number], u: Units, withUnit = true): string {
  const [lo, hi] = h;
  if (hi === 0) return "flat";
  const a = fmtH(lo, u);
  const b = fmtH(hi, u);
  const range = a === b ? a : `${a}-${b}`;
  return withUnit ? `${range} ${heightUnit(u)}` : range;
}

/** Wind speed: km/h with metric units, knots with feet (2026-09-28 - it was knots for
    everyone). The pipeline publishes km/h; the metric/imperial switch in Profile sets both
    heights and wind, like temperature. */
export function fmtWind(kph: number, u: Units): string {
  return String(u.height === "ft" ? Math.round(kph / 1.852) : Math.round(kph));
}

export function windUnit(u: Units): string {
  return u.height === "ft" ? "kt" : "km/h";
}

export function fmtTemp(c: number, u: Units): string {
  return u.temp === "f" ? `${Math.round(c * 1.8 + 32)}°F` : `${Math.round(c)}°C`;
}
