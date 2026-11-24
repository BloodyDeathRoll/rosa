import { expect, test } from "vitest";
import { BAND_COLORS, BAND_PIXELS, bandLabels, bandOf, bandRange, bandScale } from "./chartBands";

test("a value lands in its band and the top band holds everything above", () => {
  const ft = bandScale("hs", true).step;
  expect(bandOf(0, ft)).toBe(0);
  expect(bandOf(1.0, ft)).toBe(3); // 3.28 ft
  expect(bandOf(15, ft)).toBe(BAND_COLORS.length - 1);
  const m = bandScale("hs", false).step;
  expect(bandOf(1.0, m)).toBe(4); // 1.0-1.25 m
  expect(bandOf(0.99, m)).toBe(3);
  // wind data is in knots: 12 kt = 22.2 km/h -> the 20-25 km/h band
  expect(bandOf(12, bandScale("wind", false).step)).toBe(4);
  expect(bandOf(12, bandScale("wind", true).step)).toBe(4); // 10-12.5 kt
});

test("legend numbers are round in the reader's unit", () => {
  expect(bandLabels(bandScale("hs", false).shown)).toEqual(["0", "0.5", "1", "1.5", "2", "2.5", "3", "3.5", "4", "4.5", "5"]);
  expect(bandLabels(bandScale("hs", true).shown).at(-1)).toBe("20");
  expect(bandLabels(bandScale("wind", false).shown).at(-1)).toBe("100");
  expect(bandLabels(bandScale("energy", false).shown)[1]).toBe("20");
});

test("band pixels are the palette, opaque, in canvas byte order", () => {
  expect(BAND_PIXELS.length).toBe(BAND_COLORS.length);
  const bytes = new Uint8Array(BAND_PIXELS.buffer);
  // #1a1a8c -> r 0x1a, g 0x1a, b 0x8c, a 0xff
  expect([...bytes.slice(0, 4)]).toEqual([0x1a, 0x1a, 0x8c, 0xff]);
});

test("a tapped value reads as its band's range", () => {
  expect(bandRange(1.1, bandScale("hs", false))).toBe("1 - 1.25 m");
  expect(bandRange(1.1, bandScale("hs", true))).toBe("3 - 4 ft");
  expect(bandRange(9, bandScale("hs", false))).toBe("4.75+ m");
  expect(bandRange(12, bandScale("wind", false))).toBe("20 - 25 km/h"); // 12 kt
});
