import { render } from "preact-render-to-string";
import { describe, expect, it } from "vitest";
import { CoastChart } from "../components/CoastChart";
import { SpotCard } from "../components/SpotCard";
import { swimDayView } from "../lib/swim";
import { MapCard } from "../pages/MapPage";
import { ResultRow } from "../pages/SearchPage";
import { Row } from "../pages/SpotsPage";
import { DetailCard } from "../pages/TodayPage";
import type { IndexEntry, SpotPayload } from "../types";
import payload from "./fixtures/bondi-beach.json";

const data = payload as unknown as SpotPayload;
const TODAY = "2026-09-28";
const entry: IndexEntry = {
  name: data.spot.name,
  lat: data.spot.lat,
  lon: data.spot.lon,
  rating: data.days[0]!.rating_max,
  bucket: data.days[0]!.bucket,
  h: data.days[0]!.h_max,
  generated_at: data.generated_at,
};
const noSurf = (html: string) => {
  expect(html).not.toContain("data-bucket=");
  expect(html).not.toContain("--rating-");
  expect(html).not.toMatch(/\b(onshore|offshore|cross)\b/);
  expect(html).not.toContain("rashguard");
};

describe("swim mode on every card", () => {
  const sv = swimDayView(data, TODAY);

  it("the Today card carries the same word as the spot page, its bars and gear", () => {
    const html = render(<DetailCard data={data} date={TODAY} maxH={2} mode="swim" />);
    expect(html).toContain(`data-swim="${sv.bucket}"`);
    expect(html).toContain("swim-ribbon"); // the strip's hour ribbon
    expect(html).toMatch(/best \d\d:\d\d/);
    expect(html).toMatch(/\d+ cm/);
    expect(html).toMatch(/pushes (in|out)|drift/);
    expect(html).toMatch(/class="suit">(skins|wetsuit|wetsuit \+ cap \+ gloves|cold-water caution)</);
    noSurf(html);
  });

  it("the Spots card and its loading row", () => {
    const card = render(<SpotCard data={data} date={TODAY} isFav onToggle={() => undefined} mode="swim" />);
    expect(card).toContain(`data-swim="${sv.bucket}"`);
    noSurf(card);
    const row = render(<Row id="b" entry={entry} payload={undefined} onToggle={() => undefined} mode="swim" />);
    expect(row).toContain("--swim-none");
    noSurf(row);
  });

  it("the coast chart rows are swim columns", () => {
    const html = render(
      <CoastChart spots={[data]} dates={data.days.slice(0, 3).map((d) => d.date)} today={TODAY} mode="swim" />
    );
    expect(html).toContain("swim-col");
    expect(html).toMatch(/chart-val tabular">\d+cm</);
    noSurf(html);
  });

  it("index-only cards stay neutral until the day reading lands", () => {
    const card = render(<MapCard id="b" entry={entry} dist={3} center img={false} />);
    // useMode reads localStorage, absent under node, so the card renders surf here;
    // the swim branch is exercised through the search row, which takes the mode as a prop
    expect(card).toContain("data-bucket=");
    const row = render(<ResultRow id="b" entry={entry} isFav={false} onToggle={() => undefined} mode="swim" />);
    expect(row).toContain("--swim-none");
    expect(row).toContain("…"); // no figure until the day reading is in
    noSurf(row);
  });

  it("the day view agrees with the spot page's day rating", () => {
    expect(sv.score).toBeGreaterThanOrEqual(0);
    expect(sv.brkM).toBeCloseTo((data.days[0]!.h_max[0] + data.days[0]!.h_max[1]) / 2, 6);
  });
});
