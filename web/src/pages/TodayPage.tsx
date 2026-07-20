import { useEffect, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { DateBar } from "../components/DateBar";
import { DayCarousel } from "../components/DayCarousel";
import { SatMap } from "../components/MiniMap";
import { SearchIcon, ShirtIcon, ThermometerIcon, WavesIcon } from "../components/icons";
import { AppHeader, Pill, Spark, SpotTitle } from "../components/parts";
import { SpotCard, dayView } from "../components/SpotCard";
import { TideSection } from "../components/TideSection";
import { getFavorites, toggleFavorite } from "../favorites";
import { cardinal, splitName, windLabel } from "../format";
import { distanceKm, getPosition } from "../geo";
import { getRecents } from "../recents";
import { fmtRange, fmtTemp, useUnits } from "../units";
import type { SpotPayload } from "../types";

const LIST_COUNT = 3; // 3 spots under the extended card = 4 latest-viewed total

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
        <SatMap lat={data.spot.lat} lon={data.spot.lon} height={88} />
        <div class="dc-body">
        <span class="top">
          <SpotTitle name={name} region={region} />
          <Pill bucket={dv.bucket} />
        </span>
        <span class="range-row">
          <span class="surf-range tabular">{fmtRange(dv.range, units)}</span>
          <Spark hours={dv.hrs} bucket={dv.bucket} w={132} h={34} />
        </span>
        <span class="line tabular">
          {windLabel(dv.rep)}
          {swell ? ` · ${Math.round(swell.period)} s ${cardinal(swell.dir)}` : ""}
        </span>
        <span class="temps-row">
          <span>
            <ThermometerIcon />
            <span class="tabular">
              air {dv.rep.air !== null ? fmtTemp(dv.rep.air, units) : "—"}
            </span>
          </span>
          <span>
            <WavesIcon />
            <span class="tabular">
              water {dv.rep.sst !== null ? fmtTemp(dv.rep.sst, units) : "—"}
            </span>
          </span>
          {data.current.wetsuit && (
            <span>
              <ShirtIcon />
              <span class="suit">{data.current.wetsuit}</span>
            </span>
          )}
        </span>
        <span class="foot">
          <span class="window">
            Best window <b>{dv.bw ? `${dv.bw.start}–${dv.bw.end}` : "none"}</b>
          </span>
          <span class="accent-link">Open forecast →</span>
        </span>
        <TideSection nowT={dv.rep.t} metric={units.height === "m"} />
        </div>
      </button>
    </div>
  );
}

export function TodayPage() {
  const [detail, setDetail] = useState<SpotPayload | null>(null);
  const [cards, setCards] = useState<SpotPayload[] | null>(null);
  const [dists, setDists] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const [daySel, setDaySel] = useState(0);

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
        setDists(km);
        const byDist = [...entries].sort(([a], [b]) => (km[a] ?? 0) - (km[b] ?? 0));

        // the 4 latest-viewed spots: newest is the extended card, next 3 are the list;
        // if fewer than 4 have been viewed, fill the rest with the nearest spots
        const recents = getRecents().filter((id) => index.spots[id]);
        const detailId = recents[0] ?? byDist[0]?.[0];
        const chosen = new Set<string>(detailId ? [detailId] : []);
        const listIds: string[] = [];
        const consider = (id: string) => {
          if (listIds.length < LIST_COUNT && !chosen.has(id)) {
            listIds.push(id);
            chosen.add(id);
          }
        };
        recents.slice(1).forEach(consider);
        byDist.forEach(([id]) => consider(id));

        const orderedIds = [...(detailId ? [detailId] : []), ...listIds];
        const results = await Promise.allSettled(orderedIds.map(fetchSpot));
        if (disposed) return;
        const byId = new Map<string, SpotPayload>();
        for (const r of results) if (r.status === "fulfilled") byId.set(r.value.spot.id, r.value);
        setDetail(detailId ? (byId.get(detailId) ?? null) : null);
        setCards(listIds.map((id) => byId.get(id)).filter((d): d is SpotPayload => !!d));
      } catch (e) {
        if (!disposed) setError((e as Error).message);
      }
    })();
    return () => {
      disposed = true;
    };
  }, []);

  const search = (
    <a class="icon-btn" href="#/spots" aria-label="Search spots">
      <SearchIcon />
    </a>
  );

  // full 16-day strip from the featured spot (all spots share the date range);
  // its per-day bucket also colors the date-bar dots
  const featured = detail ?? cards?.[0];
  const days = featured?.days ?? [];
  const today = days[0]?.date ?? "";
  const sel = Math.min(daySel, Math.max(0, days.length - 1));

  if (error) {
    return (
      <main class="page">
        <AppHeader right={search} />
        <p class="state">{error}</p>
      </main>
    );
  }
  if (!cards) {
    return (
      <main class="page">
        <AppHeader right={search} />
        <p class="state">Loading…</p>
      </main>
    );
  }

  const dayStack = (dateStr: string) => (
    <div class="rank-list">
      {detail && <DetailCard data={detail} date={dateStr} />}
      {cards.map((d) => (
        <SpotCard
          key={d.spot.id}
          data={d}
          date={dateStr}
          km={dists[d.spot.id]}
          isFav={favs.includes(d.spot.id)}
          onToggle={() => setFavs(toggleFavorite(d.spot.id))}
        />
      ))}
    </div>
  );

  return (
    <main class="page">
      <AppHeader right={search} />
      <div class="home">
        <div class="greeting">
          <h2>{greeting()}</h2>
        </div>
        {days.length > 0 && (
          <DateBar
            dates={days.map((d) => d.date)}
            buckets={days.map((d) => d.bucket)}
            selected={sel}
            today={today}
            onSelect={setDaySel}
          />
        )}
        <DayCarousel
          count={days.length}
          selected={sel}
          onSelect={setDaySel}
          renderPanel={(i) => dayStack(days[i]?.date ?? today)}
        />
      </div>
    </main>
  );
}
