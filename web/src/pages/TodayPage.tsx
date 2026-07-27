import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { CoastChart, DayBars } from "../components/CoastChart";
import { sectionsOf } from "../components/GroupChips";
import { SatMap } from "../components/MiniMap";
import { SearchIcon, ShirtIcon, ThermometerIcon, WavesIcon } from "../components/icons";
import { AppHeader, Pill, SpotTitle } from "../components/parts";
import { dayView } from "../components/SpotCard";
import { getFavorites } from "../favorites";
import { pendingPrompt, resolvePrompt, type FbPrompt } from "../feedback";
import { cardinal, splitName, todayIn, windLabel } from "../format";
import { distanceKm, getPosition } from "../geo";
import { getRecents } from "../recents";
import { signalReady } from "../splash";
import { fmtRange, fmtTemp, useUnits } from "../units";
import type { SpotPayload } from "../types";

const FALLBACK_COUNT = 6; // nearest spots shown when no favorites are saved

function greeting(): string {
  const h = new Date().getHours();
  if (h < 5) return "Good night";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  if (h < 21) return "Good evening";
  return "Good night";
}

function DetailCard({ data, date }: { data: SpotPayload; date: string }) {
  const units = useUnits();
  const { name, region } = splitName(data.spot.name);
  const dv = dayView(data, date);
  const swell = dv.rep.swells.find((s) => s.in_window) ?? dv.rep.swells[0];
  const open = () => (location.hash = `#/spot/${data.spot.id}`);
  return (
    <div class="detail-card">
      <button class="open" onClick={open}>
        <SatMap lat={data.spot.lat} lon={data.spot.lon} height={141} />
        <div class="dc-body">
          <span class="top">
            <SpotTitle name={name} region={region} />
            <span class="hc-rail">
              <Pill bucket={dv.bucket} />
            </span>
          </span>
          <span class="range-row">
            <span class="surf-range tabular">{fmtRange(dv.range, units)}</span>
            <span class="hc-rail">
              <DayBars data={data} date={date} />
            </span>
          </span>
          <span class="line tabular">
            {windLabel(dv.rep)}
            {swell
              ? ` · ${Math.round(swell.peak_period ?? swell.period)} s ${cardinal(swell.dir)}`
              : ""}
          </span>
          <span class="temps-row">
            <span>
              <ThermometerIcon />
              <span class="tabular">
                air {dv.rep.air !== null ? fmtTemp(dv.rep.air, units) : "-"}
              </span>
            </span>
            <span>
              <WavesIcon />
              <span class="tabular">
                water {dv.rep.sst !== null ? fmtTemp(dv.rep.sst, units) : "-"}
              </span>
            </span>
            {data.current.wetsuit && (
              <span>
                <ShirtIcon />
                <span class="suit">{data.current.wetsuit}</span>
              </span>
            )}
          </span>
        </div>
      </button>
    </div>
  );
}

/** The retro 👍👎 row: one tap grades yesterday's call, then it's gone.
    Never asks in the moment - only about a day already surfed. */
function FeedbackRow({ p, onDone }: { p: FbPrompt; onDone: () => void }) {
  const units = useUnits();
  const { predicted } = p.view;
  const answer = (verdict: "up" | "down" | null) => {
    void resolvePrompt(p, verdict);
    onDone();
  };
  return (
    <div class="fb-row">
      <span class="fb-text">
        <b>Surfed {p.view.name} yesterday?</b>
        <small class="tabular">
          Rosa called {fmtRange(predicted.h, units)} - was it right?
        </small>
      </span>
      <span class="fb-actions">
        <button onClick={() => answer("up")} aria-label="Forecast was right">
          👍
        </button>
        <button onClick={() => answer("down")} aria-label="Forecast was off">
          👎
        </button>
        <button class="fb-x" onClick={() => answer(null)} aria-label="Dismiss">
          ✕
        </button>
      </span>
    </div>
  );
}

export function TodayPage() {
  const [detail, setDetail] = useState<SpotPayload | null>(null);
  const [grid, setGrid] = useState<SpotPayload[] | null>(null);
  const [homeRegion, setHomeRegion] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<FbPrompt | null>(pendingPrompt);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [index, pos] = await Promise.all([fetchIndex(), getPosition()]);
        if (disposed) return;
        const entries = Object.entries(index.spots);
        const lastId = getRecents()[0];
        const lastEntry = lastId !== undefined ? index.spots[lastId] : undefined;
        const mid = (xs: number[]) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)] ?? 0;
        const at =
          pos ??
          (lastEntry
            ? { lat: lastEntry.lat, lon: lastEntry.lon }
            : { lat: mid(entries.map(([, e]) => e.lat)), lon: mid(entries.map(([, e]) => e.lon)) });
        const km: Record<string, number> = {};
        for (const [id, e] of entries) km[id] = distanceKm(at, { lat: e.lat, lon: e.lon });
        const byDist = [...entries].sort(([a], [b]) => (km[a] ?? 0) - (km[b] ?? 0));

        // Region you're in - the one the chart pins above the rest. Only claimed
        // when `at` is a real position (a GPS fix, or the last spot you opened);
        // with neither, `at` is the median of every spot on earth and the nearest
        // one to it would name a region at random, so no region leads.
        const located = pos !== null || lastEntry !== undefined;
        const nearestEntry = byDist[0]?.[1];
        setHomeRegion(located ? (nearestEntry?.region?.trim() || null) : null);

        // extended card = the last opened spot (fall back to nearest for a fresh
        // user). The grid below lists that same spot first, then every favorite
        // (north→south); with no favorites saved it falls back to nearest spots.
        const recents = getRecents().filter((id) => index.spots[id]);
        const detailId = recents[0] ?? byDist[0]?.[0];
        const favIds = getFavorites()
          .filter((fid) => index.spots[fid] && fid !== detailId)
          .sort((a, b) => (index.spots[b]?.lat ?? 0) - (index.spots[a]?.lat ?? 0));
        const listIds =
          favIds.length > 0
            ? favIds
            : byDist
                .map(([id]) => id)
                .filter((id) => id !== detailId)
                .slice(0, FALLBACK_COUNT);

        const orderedIds = [...(detailId ? [detailId] : []), ...listIds];
        const results = await Promise.allSettled(orderedIds.map(fetchSpot));
        if (disposed) return;
        const byId = new Map<string, SpotPayload>();
        for (const r of results) if (r.status === "fulfilled") byId.set(r.value.spot.id, r.value);
        setDetail(detailId ? (byId.get(detailId) ?? null) : null);
        setGrid(orderedIds.map((id) => byId.get(id)).filter((d): d is SpotPayload => !!d));
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      } finally {
        signalReady(); // home is populated (or errored) - the splash may lift
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  const search = (
    <a class="icon-btn" href="#/search" aria-label="Search spots">
      <SearchIcon />
    </a>
  );

  // Extended-card carousel: one rich card per listed spot, swipeable, in the
  // exact order the chart below renders (home region first, then A-Z) so a swipe
  // right walks the same sequence as reading the list top to bottom.
  const cardsRef = useRef<HTMLDivElement>(null);
  const carousel = grid
    ? sectionsOf(grid, (s) => s.spot.region, homeRegion).flatMap((sec) => sec.rows)
    : [];

  // Start on the last-opened spot (the old single extended card), snapped into
  // place instantly - sections may have reordered it away from index 0.
  useEffect(() => {
    const track = cardsRef.current;
    const id = detail?.spot.id;
    if (!track || !id) return;
    const slide = track.querySelector<HTMLElement>(`[data-id="${id}"]`);
    if (!slide) return;
    track.scrollLeft = slide.offsetLeft - (track.clientWidth - slide.clientWidth) / 2;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [grid]);

  // all spots share the date range; use the featured spot's days as the axis.
  // Anchor to the spot's real current date and drop any past days, so the strip
  // never leads with a stale day from an older pipeline run.
  const featured = detail ?? grid?.[0];
  const allDates = featured?.days.map((d) => d.date) ?? [];
  const today = featured ? todayIn(featured.spot.timezone) : (allDates[0] ?? "");
  const future = allDates.filter((d) => d >= today);
  const dates = future.length ? future : allDates;

  if (error) {
    return (
      <main class="page">
        <AppHeader lead={greeting()} right={search} />
        <p class="state">{error}</p>
      </main>
    );
  }
  if (!grid) {
    return (
      <main class="page">
        <AppHeader lead={greeting()} right={search} />
        <p class="state">Loading…</p>
      </main>
    );
  }

  return (
    <main class="page">
      <AppHeader lead={greeting()} right={search} />
      <div class="home">
        {prompt && <FeedbackRow p={prompt} onDone={() => setPrompt(null)} />}
        {carousel.length > 0 && (
          <div class="home-cards" ref={cardsRef}>
            {carousel.map((d) => (
              <div class="hc-slide" key={d.spot.id} data-id={d.spot.id}>
                <DetailCard data={d} date={todayIn(d.spot.timezone)} />
              </div>
            ))}
          </div>
        )}
        <CoastChart spots={grid} dates={dates} today={today} homeRegion={homeRegion} />
      </div>
    </main>
  );
}
