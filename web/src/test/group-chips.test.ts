import { describe, expect, it } from "vitest";
import { ALL_GROUP, chipOf, groupsOf, sectionsOf } from "../components/GroupChips";
import type { IndexEntry } from "../types";

const entry = (region: string, country?: string): IndexEntry =>
  ({ name: "x", region, ...(country ? { country } : {}), lat: 0, lon: 0, rating: 0, bucket: "FLAT", h: [0, 0], generated_at: "" }) as IndexEntry;

describe("favourites group by country (2026-10-09)", () => {
  it("puts Hokkaido and Okinawa under Japan, Hawaii under USA", () => {
    expect(chipOf(entry("Hokkaido", "Japan"))).toBe("Japan");
    expect(chipOf(entry("Hawaii", "USA"))).toBe("USA");
  });

  it("falls back to the region on an index published before countries", () => {
    expect(chipOf(entry("Hokkaido"))).toBe("Hokkaido");
    expect(chipOf(undefined)).toBe("Other");
  });

  it("offers one chip per country, regions split inside it", () => {
    const rows: [string, IndexEntry][] = [
      ["aoshima", entry("Japan", "Japan")],
      ["atsunai", entry("Hokkaido", "Japan")],
      ["popoyo", entry("Nicaragua", "Nicaragua")],
    ];
    expect(groupsOf(rows)).toEqual([ALL_GROUP, "Japan", "Nicaragua"]);
    const japan = rows.filter(([, e]) => chipOf(e) === "Japan");
    expect(sectionsOf(japan, ([, e]) => e.region).map((s) => s.group)).toEqual(["Hokkaido", "Japan"]);
  });
});
