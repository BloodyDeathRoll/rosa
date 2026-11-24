/** Charts colour bands: a fixed, stepped scale - one flat colour per band, the
    same value every run and everywhere, so a colour can be read back to a number.
    Chosen 2026-11-24 over the smooth per-run ramp, which showed shape but not value. */

// 20 bands, cold to hot (our own values; a stepped rainbow is a convention, not an image).
export const BAND_COLORS = [
  "#1a1a8c", "#1f2fb8", "#2448dc", "#2a66f0", "#3388f5",
  "#45a8f5", "#5cc8ee", "#6edfd6", "#7fe6ae", "#96e882",
  "#bfe95e", "#e8e04a", "#f5c63c", "#f5a433", "#f07a2e",
  "#e84a2e", "#e0365e", "#e85a9a", "#f093c4", "#f8cfe6",
]; // prettier-ignore

export type BandVariable = "hs" | "per" | "energy" | "wind";

/** A chart's scale: `step` is one band's width in the unit the chart data is in
    (m, s, kW/m, kt); `shown` is the same width in the unit the legend prints.
    Bands sit on round numbers in the reader's own unit, so the legend reads
    clean. The top band also holds everything above it. */
export function bandScale(variable: BandVariable, imperial: boolean): { step: number; shown: number; unit: string } {
  if (variable === "hs") {
    return imperial ? { step: 0.3048, shown: 1, unit: "ft" } : { step: 0.25, shown: 0.25, unit: "m" }; // 0-20 ft / 0-5 m
  }
  if (variable === "wind") {
    return imperial ? { step: 2.5, shown: 2.5, unit: "kt" } : { step: 5 / 1.852, shown: 5, unit: "km/h" }; // 0-50 kt / 0-100 km/h
  }
  return variable === "per" ? { step: 1, shown: 1, unit: "s" } : { step: 10, shown: 10, unit: "kW/m" }; // 0-20 s / 0-200 kW/m
}

/** Legend numbers: the value at every second band edge, bottom to top of the scale. */
export function bandLabels(shown: number): string[] {
  const out: string[] = [];
  for (let i = 0; i <= BAND_COLORS.length; i += 2) out.push(String(Math.round(i * shown * 100) / 100));
  return out;
}

/** The band a value falls in, as the legend would say it: "1 - 1.25 m", or "5+ m" at the top. */
export function bandRange(value: number, scale: { step: number; shown: number; unit: string }): string {
  const k = bandOf(value, scale.step);
  const at = (i: number) => String(Math.round(i * scale.shown * 100) / 100);
  return k === BAND_COLORS.length - 1 ? `${at(k)}+ ${scale.unit}` : `${at(k)} - ${at(k + 1)} ${scale.unit}`;
}

/** Band index of a value, given its chart's band width. */
export function bandOf(value: number, step: number): number {
  return Math.max(0, Math.min(BAND_COLORS.length - 1, Math.floor(value / step)));
}

/** One opaque canvas pixel per band, as ImageData reads a Uint32 (little-endian: ABGR). */
export const BAND_PIXELS = Uint32Array.from(BAND_COLORS, (hex) => {
  const rgb = parseInt(hex.slice(1), 16);
  return (0xff000000 | ((rgb & 0xff) << 16) | (rgb & 0xff00) | (rgb >>> 16)) >>> 0;
});
