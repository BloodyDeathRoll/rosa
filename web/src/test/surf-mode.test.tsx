import { render } from "preact-render-to-string";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DayScrubber } from "../components/CoastChart";
import { ReportSheet } from "../components/ReportSheet";
import { SpotPanel } from "../pages/SpotPage";
import type { SpotPayload } from "../types";
import type { Units } from "../units";
import payload from "./fixtures/bondi-beach.json";

/** Surf mode must render exactly what it rendered before swim mode existed. The
    baseline file was written by this test from the pre-swim-mode code (2026-09-28,
    commit "refactor(web): SpotPanel"); every later change to the spot screen has to
    reproduce it byte for byte with the toggle off. Regenerate it only for a deliberate
    surf-mode change: delete the file and run the test once. */

const data = payload as unknown as SpotPayload;
const TODAY = "2026-09-28"; // the fixture's first day
const metric: Units = { height: "m", temp: "c" };
const imperial: Units = { height: "ft", temp: "f" };

function page(dayIndex: number, units: Units): string {
  return (
    render(
      <DayScrubber
        data={data}
        days={data.days}
        selected={dayIndex}
        today={TODAY}
        onSelect={() => undefined}
      />
    ) +
    "\n" +
    render(
      <SpotPanel
        data={data}
        dayIndex={dayIndex}
        today={TODAY}
        units={units}
        spots={[]}
        id={data.spot.id}
        onReport={() => undefined}
      />
    )
  );
}

describe("surf mode (toggle off)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    // a fixed wall clock, so the tide chart's "now" line lands at the same x every run
    vi.setSystemTime(new Date("2026-09-28T09:30:00+10:00"));
  });
  afterEach(() => vi.useRealTimers());

  it("today, metric", async () => {
    await expect(page(0, metric)).toMatchFileSnapshot("./__snapshots__/surf-today-metric.html");
  });
  it("day 3, imperial", async () => {
    await expect(page(3, imperial)).toMatchFileSnapshot("./__snapshots__/surf-day3-imperial.html");
  });
  it("report sheet", async () => {
    const html = render(
      <ReportSheet
        spot={{ id: "bondi-beach", name: "Bondi Beach", town: "Bondi", lat: -33.8913, lon: 151.2781 }}
        onClose={() => undefined}
      />
    );
    await expect(html).toMatchFileSnapshot("./__snapshots__/surf-report.html");
  });
});
