import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { navigate } from "../router";
import { fetchIndex, fetchSpot } from "../api";
import { CoastChart, DayBars } from "../components/CoastChart";
import {
  ALL_GROUP,
  GroupChips,
  groupNameOf,
  saveGroup,
  savedGroup,
} from "../components/GroupChips";
import { SatMap } from "../components/MiniMap";
import { CamIcon, SearchIcon, ShirtIcon, ThermometerIcon, WavesIcon } from "../components/icons";
import { AppHeader, Pill, ShareButton, SpotTitle } from "../components/parts";
import { dayView } from "../components/SpotCard";
import { useFavorites } from "../favorites";
import { pendingPrompt, resolvePrompt, type FbPrompt } from "../feedback";
import { cardinal, splitName, todayIn, windLabel } from "../format";
import { distanceKm, getHome, getPosition, setHome, type LatLon } from "../geo";
import { syncPushSpots } from "../push";
import { getRecents } from "../recents";
import { signalReady } from "../splash";
import { fmtRange, fmtTemp, useUnits } from "../units";
import type { IndexEntry, SpotPayload } from "../types";

const MIN_SPOTS = 5; // a thinner Today than this isn't worth the screen

interface TodayPlan {
  /** Region chips, "All" first, the region you're in next, then A-Z. */
  regions: string[];
  /** The selected region's spots: the anchor first, then the rest. */
  ids: string[];
  /** Region you're standing in - the chart pins it above the others. */
  homeRegion: string | null;
  /** Spot nearest the real GPS fix, or null when location is unknown. */
  nearestId: string | null;
}

/** Decide what Today shows, from the index alone.
 *
 * Regions offered = where you are, plus everywhere you've recently looked at or
 * favorited - so a spot browsed in Costa Rica from Israel puts a Costa Rica chip
 * up without pretending you surf there.
 *
 * Within a region: your favorites there, and if that's under MIN_SPOTS, topped up
 * with the spots closest to the region's anchor. The anchor leads the list (it's
 * the card you land on): the last spot you viewed in that region, or - in the
 * region you're actually in - simply the closest spot to you.
 *
 * Where you are, without a GPS fix (a desktop, a denied prompt): the spot a real
 * fix ranked nearest on an earlier launch (`homeSpot`), else the region holding
 * most of your favorites, and only then the last spot you opened - a week of
 * reading about Costa Rica from Tel Aviv must not make Costa Rica home
 * (2026-09-12: it did, and Today filled with Ollie's Point's neighbours). */
export function planToday({
  index,
  pos,
  favs,
  recents,
  group,
  homeSpot = null,
}: {
  index: Record<string, IndexEntry>;
  pos: LatLon | null;
  favs: string[];
  recents: string[];
  group: string;
  homeSpot?: string | null;
}): TodayPlan {
  const known = (id: string) => index[id] !== undefined;
  const at = (id: string) => ({ lat: index[id]!.lat, lon: index[id]!.lon });
  const myRecents = recents.filter(known);
  const myFavs = favs.filter(known);

  // Somewhere to measure from: the fix; else the spot an earlier fix put you at;
  // else the north-most favorite in the region you favorite most; else the last
  // spot you opened. With none, no region is "yours" and nothing is nearest.
  const favRegionCount = new Map<string, number>();
  for (const id of myFavs) {
    const r = groupNameOf(index[id]!.region);
    favRegionCount.set(r, (favRegionCount.get(r) ?? 0) + 1);
  }
  const favRegion = [...favRegionCount.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
  const favHome = favRegion
    ? [...myFavs]
        .filter((id) => groupNameOf(index[id]!.region) === favRegion)
        .sort((a, b) => index[b]!.lat - index[a]!.lat)[0]
    : undefined;
  const from =
    pos ??
    (homeSpot && known(homeSpot) ? at(homeSpot) : null) ??
    (favHome ? at(favHome) : null) ??
    (myRecents[0] ? at(myRecents[0]) : null);
  const byDistFrom = (o: { lat: number; lon: number }, ids: string[]) =>
    [...ids].sort((a, b) => distanceKm(o, at(a)) - distanceKm(o, at(b)));
  const allIds = Object.keys(index);
  const nearestId = pos ? (byDistFrom(pos, allIds)[0] ?? null) : null;
  const homeId = from ? byDistFrom(from, allIds)[0] : undefined;
  const homeRegion = homeId ? (index[homeId]!.region?.trim() || null) : null;

  const regionOf = (id: string) => groupNameOf(index[id]!.region);
  // Only where you are, what you favorited, and the ONE spot you looked at last
  // - browsing history is not a set of places you surf, so a week of poking at
  // spots around the world must not turn into a row of chips.
  const seeds = [...(homeId ? [homeId] : []), ...myFavs, ...(myRecents[0] ? [myRecents[0]] : [])];
  const regions = [ALL_GROUP];
  for (const id of seeds) {
    const r = regionOf(id);
    if (!regions.includes(r)) regions.push(r);
  }
  // "All" and the home region lead; the rest read A-Z
  const tail = regions.slice(homeRegion ? 2 : 1).sort((a, b) => a.localeCompare(b));
  const ordered = [...regions.slice(0, homeRegion ? 2 : 1), ...tail];

  const scope = ordered.includes(group) ? group : ALL_GROUP;
  const inScope = (id: string) => scope === ALL_GROUP || regionOf(id) === scope;

  // Anchor: what you last looked at here, else the closest spot in this region.
  const anchor =
    myRecents.find(inScope) ??
    (from ? byDistFrom(from, allIds.filter(inScope))[0] : allIds.filter(inScope)[0]);

  const ids: string[] = [];
  const add = (id: string | undefined) => {
    if (id && known(id) && inScope(id) && !ids.includes(id)) ids.push(id);
  };
  // the anchor, then your favorites here (north to south), then nearest fill
  add(anchor);
  for (const id of [...myFavs].sort((a, b) => index[b]!.lat - index[a]!.lat)) add(id);
  if (ids.length < MIN_SPOTS) {
    // Top up from wherever the region is centred on you: in your own region
    // (and under "All") that's your actual position, so the fill is the cluster
    // you could drive to - not five spots around whatever you last browsed
    // abroad. In a region you're only looking at, it's the anchor.
    const origin =
      (scope === ALL_GROUP || scope === homeRegion) && from ? from : anchor ? at(anchor) : from;
    const pool = allIds.filter((id) => inScope(id) && !ids.includes(id));
    for (const id of origin ? byDistFrom(origin, pool) : pool) {
      if (ids.length >= MIN_SPOTS) break;
      ids.push(id);
    }
  }
  return { regions: ordered, ids, homeRegion, nearestId };
}

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
  const open = () => (navigate(`/spot/${data.spot.id}`));
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
  const [index, setIndex] = useState<Record<string, IndexEntry> | null>(null);
  const [pos, setPos] = useState<LatLon | null>(null);
  const [payloads, setPayloads] = useState<Record<string, SpotPayload>>({});
  const [group, setGroup] = useState<string>(savedGroup());
  const [prompt, setPrompt] = useState<FbPrompt | null>(pendingPrompt);
  const [error, setError] = useState<string | null>(null);
  // Favorites are page state, not a one-time read: the server sync (main.tsx,
  // right after the app is ready) lands AFTER this screen mounts on a fresh
  // browser, and a Today that read the empty cache once showed a signed-in user
  // none of their spots while the bar above listed them (2026-09-12).
  const [favs] = useFavorites();
  // read once: it cannot change while this screen is open
  const [recents] = useState(getRecents);
  const [homeSpot] = useState(() => getHome()?.spot ?? null);

  // Index + position first (both small); payloads follow per selected region.
  useEffect(() => {
    let disposed = false;
    (async () => {
      try {
        const [idx, at] = await Promise.all([fetchIndex(), getPosition()]);
        if (disposed) return;
        setIndex(idx.spots);
        setPos(at);
      } catch (e) {
        if (!disposed) setError((e as Error).message);
        signalReady();
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  // What Today is about: which regions you can flip between, and which spots
  // each one shows. Pure index arithmetic - no payloads needed, so the chips
  // and the ordering are settled before a single forecast has downloaded.
  const plan = useMemo(
    () => (index ? planToday({ index, pos, favs, recents, group, homeSpot }) : null),
    [index, pos, favs, recents, group, homeSpot],
  );

  // Where the user actually is: remembered for the feedback loop (which asks
  // only about your own region) and for push (which falls back to this spot).
  // A real fix only - the last spot you opened says what you were reading.
  useEffect(() => {
    if (pos === null || !plan?.nearestId || !index) return;
    setHome(plan.nearestId, index[plan.nearestId]?.region?.trim() ?? null);
    void syncPushSpots();
  }, [pos, plan?.nearestId, index]);

  // Fetch the selected region's spots (SW-cached, so flipping back is instant).
  useEffect(() => {
    if (!plan) return;
    let disposed = false;
    const missing = plan.ids.filter((id) => !payloads[id]);
    if (missing.length === 0) {
      signalReady();
      return;
    }
    (async () => {
      const results = await Promise.allSettled(missing.map(fetchSpot));
      if (disposed) return;
      const add: Record<string, SpotPayload> = {};
      for (const r of results) if (r.status === "fulfilled") add[r.value.spot.id] = r.value;
      setPayloads((prev) => ({ ...prev, ...add }));
      signalReady(); // home is populated - the splash may lift
    })();
    return () => {
      disposed = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan?.ids.join(",")]);

  const search = (
    <span class="head-actions">
      <ShareButton path="/" />
      <a class="icon-btn" href="/search" aria-label="Search spots">
        <SearchIcon />
      </a>
    </span>
  );

  // Cards in the plan's order: the anchor leads, so the card you land on is the
  // one this region is really about. Only spots already downloaded render.
  const cardsRef = useRef<HTMLDivElement>(null);
  const carousel = (plan?.ids ?? [])
    .map((id) => payloads[id])
    .filter((d): d is SpotPayload => d !== undefined);
  const homeRegion = plan?.homeRegion ?? null;
  // one scale across every card (and the chart rows below, which derive the
  // same max from the same spots) so bar heights compare spot to spot
  const chartMax = Math.max(0.1, ...carousel.flatMap((s) => s.hours.map((h) => h.h_mid)));

  // The anchor leads the list, so the carousel simply rests at its start.
  useEffect(() => {
    if (cardsRef.current) cardsRef.current.scrollLeft = 0;
  }, [plan?.ids[0]]);

  // all spots share the date range; use the featured spot's days as the axis.
  // Anchor to the spot's real current date and drop any past days, so the strip
  // never leads with a stale day from an older pipeline run.
  const featured = carousel[0];
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
  if (!plan || carousel.length === 0) {
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
        {plan.regions.length > 2 && (
          <GroupChips
            groups={plan.regions}
            selected={plan.regions.includes(group) ? group : ALL_GROUP}
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
