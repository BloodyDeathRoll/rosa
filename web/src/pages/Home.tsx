import { useEffect, useState } from "preact/hooks";
import { fetchIndex, fetchSpot } from "../api";
import { AppHeader } from "../components/AppHeader";
import { BucketWord, DaySpine, RatingChip } from "../components/parts";
import { getFavorites, toggleFavorite } from "../favorites";
import { distanceKm, getPosition, type LatLon } from "../geo";
import { cardinal, dateOf, heightRange } from "../format";
import { getRecents } from "../recents";
import type { SpotIndex, SpotPayload } from "../types";
import type { Theme } from "../theme";

type Entry = [string, SpotIndex["spots"][string]];

const DETAIL_CARDS = 3;

/** Rich card for a recently viewed spot (Surfline home style). */
function RecentCard({ data }: { data: SpotPayload }) {
  const cur = data.current;
  const today = data.hours.filter((h) => dateOf(h.t) === dateOf(data.hours[0]?.t ?? ""));
  return (
    <a class="recent-card" href={`#/spot/${data.spot.id}`}>
      <span class="recent-name">{data.spot.name}</span>
      <span class="recent-rating">
        <BucketWord bucket={cur.bucket} />
        <DaySpine hours={today} />
      </span>
      <span class="recent-numbers">
        <span class="big">
          {heightRange(cur.h)}
          <small>{data.model.split(" ")[0]}</small>
        </span>
        <span class="big">
          {Math.round(cur.wind.kph)}
          <em>kph {cardinal(cur.wind.dir)}</em>
          <small>{cur.wind.class}</small>
        </span>
      </span>
    </a>
  );
}

function SummaryRow({
  id,
  entry,
  km,
  isFav,
  onToggle,
}: {
  id: string;
  entry: SpotIndex["spots"][string];
  km?: number;
  isFav: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <li class="spot-row">
      <button
        class="star"
        aria-pressed={isFav}
        aria-label={isFav ? `Remove ${entry.name} from favorites` : `Add ${entry.name} to favorites`}
        onClick={() => onToggle(id)}
      >
        {isFav ? "★" : "☆"}
      </button>
      <a href={`#/spot/${id}`}>
        <span class="spot-name">
          {entry.name}
          {km !== undefined && <small>{Math.round(km)} km</small>}
        </span>
        <span class="spot-now">
          <b>{heightRange(entry.h)}</b>
          <RatingChip bucket={entry.bucket} />
        </span>
      </a>
    </li>
  );
}

export function Home({ theme, onToggleTheme }: { theme: Theme; onToggleTheme: () => void }) {
  const [index, setIndex] = useState<SpotIndex | null>(null);
  const [recentData, setRecentData] = useState<SpotPayload[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [favs, setFavs] = useState<string[]>(getFavorites);
  const [pos, setPos] = useState<LatLon | null>(null);

  useEffect(() => {
    fetchIndex().then(setIndex, (e: Error) => setError(e.message));
    void getPosition().then(setPos);
    const ids = getRecents().slice(0, DETAIL_CARDS);
    void Promise.allSettled(ids.map(fetchSpot)).then((results) =>
      setRecentData(
        results.filter((r): r is PromiseFulfilledResult<SpotPayload> => r.status === "fulfilled").map((r) => r.value)
      )
    );
  }, []);

  const onToggle = (id: string) => setFavs(toggleFavorite(id));

  if (error) return <main class="page"><p class="state">{error}</p></main>;
  if (!index) return <main class="page"><p class="state">Loading…</p></main>;

  const recentIds = new Set(recentData.map((d) => d.spot.id));
  const km = (e: Entry[1]) => (pos ? distanceKm(pos, { lat: e.lat, lon: e.lon }) : undefined);
  // nearby = closest first when located, else north→south
  const nearby: Entry[] = Object.entries(index.spots)
    .filter(([id]) => !recentIds.has(id))
    .sort(([, a], [, b]) =>
      pos ? (km(a) ?? 0) - (km(b) ?? 0) : b.lat - a.lat
    );

  return (
    <main class="page">
      <AppHeader theme={theme} onToggleTheme={onToggleTheme} />
      {recentData.length > 0 && (
        <>
          <h2 class="list-title">Recently viewed</h2>
          <div class="recent-cards">
            {recentData.map((d) => (
              <RecentCard key={d.spot.id} data={d} />
            ))}
          </div>
        </>
      )}
      <h2 class="list-title">{pos ? "Spots near you" : "Spots · north to south"}</h2>
      <ul class="spots">
        {nearby.map(([id, e]) => (
          <SummaryRow key={id} id={id} entry={e} km={km(e)} isFav={favs.includes(id)} onToggle={onToggle} />
        ))}
      </ul>
    </main>
  );
}
