import { render } from "preact-render-to-string";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CoastChart, DayBars } from "../components/CoastChart";
import { SpotCard } from "../components/SpotCard";
import { MapCard } from "../pages/MapPage";
import { ResultRow } from "../pages/SearchPage";
import { Row } from "../pages/SpotsPage";
import { DetailCard } from "../pages/TodayPage";
import type { IndexEntry, SpotPayload } from "../types";
import payload from "./fixtures/bondi-beach.json";

/** Surf-mode baseline for every card outside the spot page. Written from the code as it
    stood BEFORE swim mode reached these screens (2026-09-28); swim work must reproduce it
    byte for byte with the toggle off. See surf-mode.test.tsx for the spot page itself. */

const data = payload as unknown as SpotPayload;
const TODAY = "2026-09-28";
const entry: IndexEntry = {
  name: data.spot.name,
  region: data.spot.region,
  town: data.spot.town,
  lat: data.spot.lat,
  lon: data.spot.lon,
  rating: data.days[0]!.rating_max,
  bucket: data.days[0]!.bucket,
  h: data.days[0]!.h_max,
  generated_at: data.generated_at,
};

describe("surf cards (toggle off)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-28T09:30:00+10:00"));
  });
  afterEach(() => vi.useRealTimers());

  it("today card, spots row, search row", async () => {
    const html = [
      render(<DetailCard data={data} date={TODAY} maxH={2} />),
      render(<Row id="bondi-beach" entry={entry} payload={data} onToggle={() => undefined} />),
      render(<Row id="bondi-beach" entry={entry} payload={undefined} onToggle={() => undefined} />),
      render(<ResultRow id="bondi-beach" entry={entry} isFav={false} onToggle={() => undefined} />),
    ].join("\n");
    await expect(html).toMatchFileSnapshot("./__snapshots__/surf-rows.html");
  });

  it("spot card, day bars, coast chart, map card", async () => {
    const html = [
      render(<SpotCard data={data} date={TODAY} isFav onToggle={() => undefined} />),
      render(<DayBars data={data} date={TODAY} maxH={2} />),
      render(<CoastChart spots={[data]} dates={data.days.slice(0, 5).map((d) => d.date)} today={TODAY} />),
      render(<MapCard id="bondi-beach" entry={entry} dist={3} center img={false} />),
    ].join("\n");
    await expect(html).toMatchFileSnapshot("./__snapshots__/surf-cards.html");
  });
});
