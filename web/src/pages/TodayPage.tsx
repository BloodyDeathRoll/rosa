import { useEffect, useRef, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { CoastChart, DayBars } from "../components/CoastChart";
import {
  ALL_GROUP,
  GroupChips,
  groupNameOf,
  saveGroup,
  savedGroup,
  sectionsOf,
} from "../components/GroupChips";
import { SatMap } from "../components/MiniMap";
import { CamIcon, SearchIcon, ShirtIcon, ThermometerIcon, WavesIcon } from "../components/icons";
import { AppHeader, Pill, SpotTitle } from "../components/parts";
import { dayView } from "../components/SpotCard";
import { getFavorites } from "../favorites";
import { pendingPrompt, resolvePrompt, type FbPrompt } from "../feedback";
import { cardinal, splitName, todayIn, windLabel } from "../format";
import { distanceKm, getPosition, setHome } from "../geo";
import { syncPushSpots } from "../push";
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

function DetailCard({ data, date, maxH }: { data: SpotPayload; date: string; maxH: number }) {
  const units = useUnits();
  const { name, region } = splitName(data.spot.name);
  const dv = dayView(data, date);
  const swell = dv.rep.swells.find((s) => s.in_window) ?? dv.rep.swells[0];
  const open = () => (location.hash = `#/spot/${data.spot.id}`);
  return (
    <div class="detail-card">
      <button class="open" onClick={open}>
        <span class="dc-cover">
          {data.spot.cam ? (
            // A spot with a cam shows what the camera sees rather than a satellite
            // view - YouTube's own still for the live stream (same as the map cards),
            // credited in full on the spot page one tap away.
            <img
              class="dc-cam"
              src={`https://i.ytimg.com/vi/${data.spot.cam.yt}/mqdefault.jpg`}
              alt=""
              loading="lazy"
              decoding="async"
            />
          ) : (
            <SatMap lat={data.spot.lat} lon={data.spot.lon} height={141} />
          )}
          {data.spot.cam && (
            <span class="cam-badge" title="Live cam">
              <CamIcon />
            </span>
          )}
        </span>
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
              <DayBars data={data} date={date} maxH={maxH} />
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

/** The retro row, asked in two steps: first whether you surfed it at all, and
    only then how the call held up - a forecast grade from someone who never
    paddled out is noise in the calibration log. "No" ends it silently (nothing
    is reported); either way the row is gone for good. */
function FeedbackRow({ p, onDone }: { p: FbPrompt; onDone: () => void }) {
  const units = useUnits();
  const [surfed, setSurfed] = useState(false);
  const { predicted } = p.view;
  const answer = (verdict: "up" | "down" | null) => {
    void resolvePrompt(p, verdict);
    onDone();
  };
  return (
    <div class="fb-row">
      <span class="fb-text">
        <b>{surfed ? "How was the forecast?" : `Surfed ${p.view.name} yesterday?`}</b>
        <small class="tabular">Rosa called {fmtRange(predicted.h, units)}</small>
      </span>
      <span class="fb-actions">
        {surfed ? (
          <>
            <button onClick={() => answer("up")} aria-label="Forecast was right">
              👍
            </button>
            <button onClick={() => answer("down")} aria-label="Forecast was off">
              👎
            </button>
          </>
        ) : (
          <>
            <button class="fb-yes" onClick={() => setSurfed(true)} aria-label="Yes, I surfed it">
              ✓
            </button>
            <button class="fb-no" onClick={() => answer(null)} aria-label="No, I didn't surf">
              ✕
            </button>
          </>
        )}
      </span>
    </div>
  );
}

export function TodayPage() {
  const [detail, setDetail] = useState<SpotPayload | null>(null);
  const [grid, setGrid] = useState<SpotPayload[] | null>(null);
  const [homeRegion, setHomeRegion] = useState<string | null>(null);
  const [group, setGroup] = useState<string>(savedGroup());
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
        // Remember where the user actually is (a real fix only - the last-opened
        // spot says what they were reading, not where they stand). The feedback
        // loop asks only about this region, and pushes fall back to this spot.
        if (pos !== null && byDist[0]) {
          setHome(byDist[0][0], nearestEntry?.region?.trim() ?? null);
          void syncPushSpots();
        }

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

  // Region filter, shared with the Spots tab (same remembered chip): a list
  // spanning countries is rarely all interesting at once. Only worth showing
  // when there is more than one region to choose between.
  const regionGroups = grid
    ? [ALL_GROUP, ...sectionsOf(grid, (s) => s.spot.region, homeRegion).map((s) => s.group)]
    : [ALL_GROUP];
  const activeGroup = regionGroups.includes(group) ? group : ALL_GROUP;
  const shown =
    grid && activeGroup !== ALL_GROUP
      ? grid.filter((s) => groupNameOf(s.spot.region) === activeGroup)
      : grid;

  // Extended-card carousel: one rich card per listed spot, swipeable, in the
  // exact order the chart below renders (home region first, then A-Z) so a swipe
  // right walks the same sequence as reading the list top to bottom.
  const cardsRef = useRef<HTMLDivElement>(null);
  const carousel = shown
    ? sectionsOf(shown, (s) => s.spot.region, homeRegion).flatMap((sec) => sec.rows)
    : [];
  // one scale across every card (and the chart rows below, which derive the
  // same max from the same spots) so bar heights compare spot to spot
  const chartMax = Math.max(0.1, ...carousel.flatMap((s) => s.hours.map((h) => h.h_mid)));

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
  // (the axis follows what's shown, so a filter can't leave the strip anchored
  // to a spot that scrolled out of the list)
  const featured = carousel.find((s) => s.spot.id === detail?.spot.id) ?? carousel[0] ?? detail;
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
        {regionGroups.length > 2 && (
          <GroupChips
            groups={regionGroups}
            selected={activeGroup}
            onSelect={(g) => {
              setGroup(g);
              saveGroup(g);
            }}
          />
        )}
        {carousel.length > 0 && (
          <div class="home-cards" ref={cardsRef}>
            {carousel.map((d) => (
              <div class="hc-slide" key={d.spot.id} data-id={d.spot.id}>
                <DetailCard data={d} date={todayIn(d.spot.timezone)} maxH={chartMax} />
              </div>
            ))}
          </div>
        )}
        <CoastChart spots={carousel} dates={dates} today={today} homeRegion={homeRegion} />
      </div>
    </main>
  );
}
