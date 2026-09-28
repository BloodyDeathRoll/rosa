import { render } from "preact-render-to-string";
import { describe, expect, it } from "vitest";
import { DayScrubber } from "../components/CoastChart";
import { ReportSheet } from "../components/ReportSheet";
import { TideSection } from "../components/TideSection";
import { SpotPanel } from "../pages/SpotPage";
import type { SpotPayload } from "../types";
import payload from "./fixtures/bondi-beach.json";

const data = payload as unknown as SpotPayload;
const TODAY = "2026-09-28";
const units = { height: "m", temp: "c" } as const;

function panel(d: SpotPayload, dayIndex = 0): string {
  return render(
    <SpotPanel
      data={d}
      dayIndex={dayIndex}
      today={TODAY}
      units={units}
      spots={[]}
      id={d.spot.id}
      onReport={() => undefined}
      mode="swim"
    />
  );
}

describe("swim mode (toggle on)", () => {
  const html = panel(data);

  it("uses the swim scale and words, never the surf ones", () => {
    expect(html).toMatch(/data-swim="(CALM|EASY|CHOPPY|ROUGH|OUT)"/);
    expect(html).not.toContain("data-bucket=");
    expect(html).toContain("--swim-");
    expect(html).not.toContain("--rating-");
    expect(html).not.toContain("Best session");
  });

  it("the surf green-for-offshore class never survives; wind reads as push", () => {
    // day 1 (2026-09-29) is the fixture's first day with an offshore hour
    const h = panel(data, 1);
    for (const x of [html, h]) expect(x).not.toMatch(/\bwc-(offshore|onshore|cross-shore)\b/);
    expect(h).toContain("push-out");
    expect(h).toContain("pushes out");
    expect(html).toContain("push-in");
    expect(html).toContain("pushes in");
    expect(html).toContain(">drift<");
  });

  it("table: shore break in cm, surge, rip + water; kJ/hPa behind the expand", () => {
    expect(html).toContain("shore break cm");
    expect(html).toContain(">surge<");
    expect(html).toContain("rip<small>water</small>");
    expect(html).toMatch(/rip-chip rip-(low|med|high)/);
    expect(html).toContain("sets · ");
    expect(html).not.toContain(" kJ · ");
    expect(html).toContain('aria-expanded="false"');
  });

  it("card: the best hour, its score, the points each factor took, and gear", () => {
    expect(html).toContain("swim-why");
    expect(html).toMatch(/best hour \d\d:\d\d · \d+\/100/);
    expect(html).toMatch(/Points lost at the best hour|Nothing took a point at the best hour/);
    expect(html).toMatch(/No penalty: /);
    // the old five-bar card and its surf-scale colours are gone
    for (const l of ["Clarity", "Chop", "Surge", "Push"]) expect(html).not.toContain(`<span>${l}</span>`);
    expect(html).not.toMatch(/\bq-(good|fair|warn|poor)\b/);
    expect(html).toMatch(/class="suit">(skins|wetsuit|wetsuit \+ cap \+ gloves|cold-water caution)</);
  });

  it("no pollution or clarity source is said out loud, once", () => {
    const noWater = { ...data, water: { clarity: null, pollution: null } };
    const h = panel(noWater);
    expect(h).toContain("pollution: no data");
    expect(h).toContain("clarity: no data");
    expect(h.match(/pollution: no data/g)!.length).toBe(1);
    const alert = { ...data, water: { ...data.water!, pollution: { ...data.water!.pollution!, alert: true } } };
    expect(panel(alert)).toContain("Pollution likely today - capped at Stay out");
  });

  it("a rock or reef shore shows the banner instead of a rating", () => {
    const rocky = { ...data, spot: { ...data.spot, shore: "reef" as const } };
    const h = panel(rocky);
    expect(h).toContain("Rocky entry - not a swimming beach");
    expect(h).not.toContain("data-swim=");
    expect(panel(data)).not.toContain("Rocky entry");
  });

  it("day strip: one bar a day in the swim colour, the shore break figure, a legend", () => {
    const strip = render(
      <DayScrubber data={data} days={data.days} selected={0} today={TODAY} onSelect={() => undefined} mode="swim" />
    );
    expect(strip).toContain("swim-col");
    const cols = strip.split('class="day-col').slice(1);
    for (const c of cols.filter((c) => c.includes("swim-bar")))
      expect(c.match(/class="chart-bar swim-bar/g)!.length).toBe(1);
    expect(strip).toMatch(/background:var\(--swim-(calm|easy|choppy|rough|out)\)/);
    expect(strip).toMatch(/chart-val tabular">\d+cm</);
    expect(strip).toContain("swim-legend");
    expect(strip).not.toContain("day-dot");
    expect(strip).not.toContain("--rating-");
  });

  it("tide: slack markers and flow shading only in swim mode", () => {
    const swim = render(<TideSection hours={data.hours} date={TODAY} metric mode="swim" />);
    const surf = render(<TideSection hours={data.hours} date={TODAY} metric />);
    expect(swim).toContain("tide-slack");
    expect(swim).toContain("tide-flow");
    expect(swim).toContain("Dots mark slack water");
    expect(surf).not.toContain("tide-slack");
    expect(surf).not.toContain("tide-flow");
  });

  it("report: the swimmer's tag set", () => {
    const h = render(
      <ReportSheet spot={{ id: "x", name: "X", lat: 0, lon: 0 }} onClose={() => undefined} mode="swim" />
    );
    for (const t of ["Jellyfish", "Stingers", "Strong current", "Murky water", "Clean water", "Calm water"])
      expect(h).toContain(t);
    expect(h).not.toContain("Forecast too high");
  });
});
